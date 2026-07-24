import os
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

# LangChain Imports
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI

from langchain_core.prompts import ChatPromptTemplate

load_dotenv()

app = FastAPI(title="IntelliDocs Gemini Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "temp_uploads"
DB_DIR = "backend/document_store"
os.makedirs(UPLOAD_DIR, exist_ok=True)

try:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    vector_store = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
except Exception as e:
    print(f"Embedding initialization error: {e}. Ensure GOOGLE_API_KEY is set.")
    embeddings = None
    vector_store = None

llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample_docs", "sample.pdf")
MAX_CHUNKS = 60


@app.get("/health")
def health():
    return {"ok": True}


def remove_document(doc_name: str):
    """Delete all chunks belonging to one document (used when re-uploading the same file)."""
    try:
        existing = vector_store._collection.get(where={"doc_name": doc_name})
        if existing and existing.get("ids"):
            vector_store._collection.delete(ids=existing["ids"])
            print(f"--- DIAGNOSTIC --- Removed {len(existing['ids'])} old chunks for '{doc_name}'.")
    except Exception as ce:
        print(f"--- DIAGNOSTIC --- Remove failed: {ce}")


def embed_and_store(chunks, doc_name):
    """Embed chunks in batches and store them tagged with doc_name."""
    texts = [c.page_content for c in chunks]
    metadatas = []
    for c in chunks:
        m = dict(c.metadata)
        m["doc_name"] = doc_name
        metadatas.append(m)

    all_vectors = []
    BATCH = 100
    for i in range(0, len(texts), BATCH):
        all_vectors.extend(embeddings.embed_documents(texts[i:i + BATCH], batch_size=BATCH))
    calls = max(1, (len(texts) + BATCH - 1) // BATCH)
    print(f"--- DIAGNOSTIC --- Embedded {len(texts)} chunks in {calls} batched API call(s).")

    # IDs must be unique per document or chunks from different PDFs overwrite each other
    ids = [f"{doc_name}-chunk-{i}" for i in range(len(texts))]
    vector_store._collection.add(ids=ids, embeddings=all_vectors, documents=texts, metadatas=metadatas)
    vector_store.persist()


@app.on_event("startup")
def preload_sample():
    """Rebuild the demo knowledge base after every restart (Render disk is ephemeral)."""
    global vector_store
    try:
        if vector_store is None or embeddings is None:
            return
        existing = vector_store._collection.count()
        if existing > 0:
            print(f"--- STARTUP --- Vector store already has {existing} chunks, skipping preload.")
            return
        if not os.path.exists(SAMPLE_PATH):
            print("--- STARTUP --- No sample.pdf found, skipping preload.")
            return
        loader = PyPDFLoader(SAMPLE_PATH)
        documents = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_documents(documents)
        embed_and_store(chunks, "sample.pdf")
        print(f"--- STARTUP --- Preloaded sample.pdf into {len(chunks)} chunks.")
    except Exception as e:
        print(f"--- STARTUP --- Preload failed: {e}")


class QueryRequest(BaseModel):
    question: str
    doc_name: Optional[str] = None


@app.get("/documents")
def list_documents():
    """Return the list of documents currently in the vector store."""
    try:
        data = vector_store._collection.get(include=["metadatas"])
        names = []
        for m in (data.get("metadatas") or []):
            n = (m or {}).get("doc_name")
            if n and n not in names:
                names.append(n)
        return {"documents": sorted(names)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not list documents: {str(e)}")


@app.delete("/documents")
def delete_document(doc_name: str):
    """Remove one document and all its chunks from the vector store."""
    try:
        before = vector_store._collection.get(where={"doc_name": doc_name})
        count = len(before.get("ids") or [])
        if count == 0:
            raise HTTPException(status_code=404, detail=f"No document named '{doc_name}' in the store.")
        remove_document(doc_name)
        return {"message": f"Removed '{doc_name}' ({count} chunks).", "removed": count}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Adds a PDF to the knowledge base, tagged so it can be queried on its own."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are currently supported.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        loader = PyPDFLoader(file_path)
        documents = loader.load()
        print(f"--- DIAGNOSTIC --- Loaded {len(documents)} pages from the PDF.")

        if not documents or len(documents) == 0:
            raise HTTPException(status_code=400, detail="The PDF file appears to be empty or corrupted.")

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = text_splitter.split_documents(documents)
        print(f"--- DIAGNOSTIC --- Split document into {len(chunks)} chunks.")

        if not chunks or len(chunks) == 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No selectable text was found in this PDF. It might be an image-only scanned document. "
                    "Please try uploading a digital PDF with selectable text."
                )
            )

        # Guard: free-tier Gemini quota is ~100 embedded chunks/day, so cap document size
        if len(chunks) > MAX_CHUNKS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This PDF is too large ({len(chunks)} sections). "
                    f"Please upload a smaller document (up to roughly {MAX_CHUNKS} sections, about 15-20 pages of text). "
                    "This keeps the free AI quota available for answering your questions."
                )
            )

        global vector_store
        if vector_store is None:
            vector_store = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)

        doc_name = file.filename
        remove_document(doc_name)   # re-uploading the same file replaces its old chunks
        embed_and_store(chunks, doc_name)

        return {
            "message": f"Successfully processed '{doc_name}' into {len(chunks)} chunks. Select it above to ask questions about it.",
            "doc_name": doc_name
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.post("/query")
async def query_documents(request: QueryRequest):
    """Retrieves relevant chunks (optionally from one document only) and answers with Gemini."""
    global vector_store
    if vector_store is None:
        raise HTTPException(status_code=500, detail="Vector store not initialized. Upload documents first.")

    try:
        print(f"\n--- DIAGNOSTIC --- Received Query: '{request.question}' | doc: {request.doc_name}")

        search_kwargs = {"k": 3}
        if request.doc_name:
            search_kwargs["filter"] = {"doc_name": request.doc_name}

        retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
        docs = retriever.invoke(request.question)
        print(f"--- DIAGNOSTIC --- Retrieved {len(docs)} chunks from Chroma.")

        if not docs:
            return {
                "answer": "I could not find anything relevant in the selected document.",
                "citations": []
            }

        formatted_context = "\n\n".join(doc.page_content for doc in docs)

        system_prompt = (
            "You are a helpful assistant. Answer the user's question using only the provided context below.\n"
            "If you do not know the answer or if it's not present in the context, state that you do not know.\n"
            "Do not make up information.\nBe concise: answer in at most 3-4 sentences, or 3 short bullet points, unless the user explicitly asks for more detail.\n\n"
            "Context:\n{context}"
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])

        formatted_prompt = prompt.invoke({"context": formatted_context, "input": request.question})
        print("--- DIAGNOSTIC --- Sending prompt to Gemini...")
        response = llm.invoke(formatted_prompt)
        print("--- DIAGNOSTIC --- Gemini response received.")

        raw_content = response.content
        answer = raw_content

        if isinstance(raw_content, list):
            if len(raw_content) > 0 and isinstance(raw_content[0], dict) and "text" in raw_content[0]:
                answer = raw_content[0]["text"]
        elif isinstance(raw_content, str) and raw_content.strip().startswith("["):
            import json
            try:
                parsed = json.loads(raw_content)
                if isinstance(parsed, list) and len(parsed) > 0:
                    if isinstance(parsed[0], dict) and "text" in parsed[0]:
                        answer = parsed[0]["text"]
                    elif isinstance(parsed[0], str):
                        answer = parsed[0]
            except Exception:
                pass

        citations = []
        for doc in docs:
            page = doc.metadata.get("page", 0) + 1
            source = doc.metadata.get("doc_name") or doc.metadata.get("source", "Unknown Document")
            snippet = doc.page_content[:150] + "..."
            citations.append({
                "source": os.path.basename(source),
                "page": page,
                "snippet": snippet
            })

        return {"answer": answer, "citations": citations}

    except Exception as e:
        print(f"--- DIAGNOSTIC ERROR --- Query failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
@app.post("/query_stream")
async def query_stream(request: QueryRequest):
    """Same as /query but streams the answer token-by-token, then sends citations."""
    import json

    global vector_store
    if vector_store is None:
        raise HTTPException(status_code=500, detail="Vector store not initialized.")

    search_kwargs = {"k": 3}
    if request.doc_name:
        search_kwargs["filter"] = {"doc_name": request.doc_name}

    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
    docs = retriever.invoke(request.question)
    print(f"--- DIAGNOSTIC --- [stream] Retrieved {len(docs)} chunks | doc: {request.doc_name}")

    citations = []
    for doc in docs:
        page = doc.metadata.get("page", 0) + 1
        source = doc.metadata.get("doc_name") or doc.metadata.get("source", "Unknown Document")
        citations.append({
            "source": os.path.basename(source),
            "page": page,
            "snippet": doc.page_content[:150] + "..."
        })

    formatted_context = "\n\n".join(doc.page_content for doc in docs)

    system_prompt = (
        "You are a helpful assistant. Answer the user's question using only the provided context below.\n"
        "If you do not know the answer or if it's not present in the context, state that you do not know.\n"
        "Do not make up information.\n\n"
        "Context:\n{context}"
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])
    formatted_prompt = prompt.invoke({"context": formatted_context, "input": request.question})

    def generate():
        if not docs:
            yield "I could not find anything relevant in the selected document."
        else:
            try:
                for chunk in llm.stream(formatted_prompt):
                    piece = chunk.content
                    if isinstance(piece, list):
                        piece = "".join(
                            p.get("text", "") for p in piece if isinstance(p, dict)
                        )
                    if piece:
                        yield piece
            except Exception as e:
                yield f"\n\n[Generation error: {e}]"
        # Citations can't stream alongside text, so send them last behind a marker
        yield "<<<CITATIONS>>>" + json.dumps(citations)

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )