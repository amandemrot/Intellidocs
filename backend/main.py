import os
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# LangChain Imports
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI

# Modern LangChain Expression Language (LCEL) Imports
from langchain_core.runnables import RunnableParallel, RunnablePassthrough
from langchain_core.prompts import ChatPromptTemplate

# Load environment variables (API keys)
load_dotenv()

app = FastAPI(title="IntelliDocs Gemini Backend")

# Enable CORS so our Streamlit frontend can communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup paths
UPLOAD_DIR = "temp_uploads"
DB_DIR = "backend/document_store"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Initialize Embeddings and Vector Store
try:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    vector_store = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
except Exception as e:
    print(f"Embedding initialization error: {e}. Ensure GOOGLE_API_KEY is set.")
    embeddings = None
    vector_store = None

llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)

@app.get("/health")
def health():
    return {"ok": True}

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample_docs", "sample.pdf")

def clear_vector_store():
    """Delete all chunks so only one document lives in the store at a time."""
    try:
        existing = vector_store._collection.get()
        if existing and existing.get("ids"):
            vector_store._collection.delete(ids=existing["ids"])
            print(f"--- DIAGNOSTIC --- Cleared {len(existing['ids'])} old chunks.")
    except Exception as ce:
        print(f"--- DIAGNOSTIC --- Clear failed: {ce}")

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
        vector_store.add_documents(chunks)
        vector_store.persist()
        print(f"--- STARTUP --- Preloaded sample.pdf into {len(chunks)} chunks.")
    except Exception as e:
        print(f"--- STARTUP --- Preload failed: {e}")

class QueryRequest(BaseModel):
    question: str

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Receives a PDF, wipes the previous knowledge base, parses and chunks
    the new PDF, and stores it as the ONLY document in the Chroma DB.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are currently supported.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    try:
        # Save uploaded file locally
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 1. Document Parsing (Load PDF)
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        
        # Diagnostic Log
        print(f"--- DIAGNOSTIC --- Loaded {len(documents)} pages from the PDF.")

        if not documents or len(documents) == 0:
            raise HTTPException(
                status_code=400, 
                detail="The PDF file appears to be empty or corrupted."
            )

        # 2. Text Chunking
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = text_splitter.split_documents(documents)
        
        # Diagnostic Log
        print(f"--- DIAGNOSTIC --- Split document into {len(chunks)} chunks.")

        # Safety Check: If chunking returned nothing, do not pass to Chroma
        if not chunks or len(chunks) == 0:
            raise HTTPException(
                status_code=400, 
                detail=(
                    "No selectable text was found in this PDF. It might be an image-only scanned document. "
                    "Please try uploading a digital PDF with selectable text."
                )
            )

        # 3. Wipe previous documents, then store ONLY this one
        global vector_store
        if vector_store is None:
            vector_store = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
        
        clear_vector_store()
        vector_store.add_documents(chunks)
        vector_store.persist()

        return {"message": f"Successfully processed '{file.filename}' into {len(chunks)} chunks. Answers will now come only from this document."}

    except HTTPException as he:
        # Re-raise HTTP exceptions so FastAPI handles them properly
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")
    
    finally:
        # Clean up temporary file
        if os.path.exists(file_path):
            os.remove(file_path)

@app.post("/query")
async def query_documents(request: QueryRequest):
    """
    Retrieves relevant document chunks and uses Gemini to generate an answer.
    """
    global vector_store
    if vector_store is None:
        raise HTTPException(status_code=500, detail="Vector store not initialized. Upload documents first.")

    try:
        # Diagnostic Log
        print(f"\n--- DIAGNOSTIC --- Received Query: '{request.question}'")

        # 1. Retrieve the top 3 relevant chunks directly from the database
        retriever = vector_store.as_retriever(search_kwargs={"k": 3})
        docs = retriever.invoke(request.question)
        print(f"--- DIAGNOSTIC --- Successfully retrieved {len(docs)} chunks from Chroma.")

        # 2. Format the text context for the prompt
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

        # 3. Generate the prompt and invoke Gemini
        formatted_prompt = prompt.invoke({"context": formatted_context, "input": request.question})
        print("--- DIAGNOSTIC --- Sending prompt to Gemini...")
        response = llm.invoke(formatted_prompt)
        print("--- DIAGNOSTIC --- Gemini response received.")

        # --- Safe and Robust Content Extraction ---
        raw_content = response.content
        answer = raw_content

        # Handle Scenario A: Content is returned as a direct Python list of dicts (Gemini block structure)
        if isinstance(raw_content, list):
            if len(raw_content) > 0 and isinstance(raw_content[0], dict) and "text" in raw_content[0]:
                answer = raw_content[0]["text"]
        
        # Handle Scenario B: Content is returned as a JSON-encoded string representation of a list
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
                pass  # Fallback to raw string if parsing fails

        # 4. Extract citations (sources) from the retrieved documents
        citations = []
        for doc in docs:
            page = doc.metadata.get("page", 0) + 1
            source = doc.metadata.get("source", "Unknown Document")
            snippet = doc.page_content[:150] + "..."
            citations.append({
                "source": os.path.basename(source), 
                "page": page, 
                "snippet": snippet
            })

        return {
            "answer": answer,
            "citations": citations
        }

    except Exception as e:
        print(f"--- DIAGNOSTIC ERROR --- Query failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")