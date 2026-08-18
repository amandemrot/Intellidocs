import os
import shutil
import tempfile
import numpy as np
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

def get_api_key():
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        try:
            if hasattr(st, "secrets") and "GOOGLE_API_KEY" in st.secrets:
                key = st.secrets["GOOGLE_API_KEY"]
        except Exception:
            pass
    if key:
        os.environ["GOOGLE_API_KEY"] = key
        os.environ["GEMINI_API_KEY"] = key
    return key

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

# Pure Python Cosine Similarity Vector Store (0 C++ / SQLite dependencies)
class SimpleVectorStore:
    def __init__(self, embeddings):
        self.embeddings = embeddings
        self.documents = []  # list of dicts: {"text": str, "metadata": dict, "embedding": np.array}

    def add_chunks(self, chunks, doc_name):
        # Delete existing chunks for this doc_name
        self.delete_doc(doc_name)
        
        texts = [c.page_content for c in chunks]
        metadatas = []
        for c in chunks:
            m = dict(c.metadata)
            m["doc_name"] = doc_name
            metadatas.append(m)
            
        vectors = self.embeddings.embed_documents(texts)
        for text, meta, vec in zip(texts, metadatas, vectors):
            self.documents.append({
                "text": text,
                "metadata": meta,
                "embedding": np.array(vec, dtype=np.float32)
            })

    def search(self, query, doc_name=None, k=3):
        if not self.documents:
            return []
        
        candidates = self.documents
        if doc_name:
            candidates = [d for d in self.documents if d["metadata"].get("doc_name") == doc_name]
            
        if not candidates:
            return []
            
        query_vec = np.array(self.embeddings.embed_query(query), dtype=np.float32)
        scores = []
        for d in candidates:
            dot = np.dot(query_vec, d["embedding"])
            norm = np.linalg.norm(query_vec) * np.linalg.norm(d["embedding"])
            sim = dot / (norm + 1e-8)
            scores.append((sim, d))
            
        scores.sort(key=lambda x: x[0], reverse=True)
        top_k = scores[:k]
        
        class MatchDoc:
            def __init__(self, text, metadata):
                self.page_content = text
                self.metadata = metadata
                
        return [MatchDoc(d["text"], d["metadata"]) for sim, d in top_k]

    def list_docs(self):
        names = []
        for d in self.documents:
            n = d["metadata"].get("doc_name")
            if n and n not in names:
                names.append(n)
        return sorted(names)

    def delete_doc(self, doc_name):
        self.documents = [d for d in self.documents if d["metadata"].get("doc_name") != doc_name]

# Native RAG Engine Initializer
@st.cache_resource
def init_native_rag():
    key = get_api_key()
    if not key:
        return None, None, None, "GOOGLE_API_KEY missing from Streamlit Secrets. Please set GOOGLE_API_KEY in Secrets."
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
        
        embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=key)
        vstore = SimpleVectorStore(embeddings)
        llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", temperature=0, google_api_key=key)
        return vstore, embeddings, llm, None
    except Exception as e:
        return None, None, None, str(e)

def native_list_documents():
    vstore, _, _, _ = init_native_rag()
    if not vstore:
        return []
    return vstore.list_docs()

def native_process_pdf(file_bytes, filename):
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    vstore, embeddings, _, err = init_native_rag()
    if not vstore:
        raise Exception(f"Initialization Error: {err}")
    
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, filename)
    with open(file_path, "wb") as f:
        f.write(file_bytes)
        
    try:
        loader = PyPDFLoader(file_path)
        docs = loader.load()
        if not docs:
            raise Exception("No readable text found in PDF.")
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_documents(docs)
        
        vstore.add_chunks(chunks, filename)
        return f"Successfully processed '{filename}' into {len(chunks)} chunks."
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

def native_delete_document(filename):
    vstore, _, _, _ = init_native_rag()
    if vstore:
        vstore.delete_doc(filename)

def native_query_documents(question, doc_name=None):
    from langchain_core.prompts import ChatPromptTemplate
    
    vstore, _, llm, err = init_native_rag()
    if not vstore or not llm:
        raise Exception(f"AI Engine Error: {err or 'GOOGLE_API_KEY missing.'}")
        
    docs = vstore.search(question, doc_name=doc_name, k=3)
    if not docs:
        return {"answer": "I could not find anything relevant in the selected document.", "citations": []}
        
    formatted_context = "\n\n".join(doc.page_content for doc in docs)
    system_prompt = (
        "You are a helpful assistant. Answer the user's question using only the provided context below.\n"
        "If you do not know the answer or if it's not present in the context, state that you do not know.\n"
        "Context:\n{context}"
    )
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
    formatted_prompt = prompt.invoke({"context": formatted_context, "input": question})
    response = llm.invoke(formatted_prompt)
    
    raw_content = response.content
    answer = raw_content
    if isinstance(raw_content, list) and len(raw_content) > 0:
        if isinstance(raw_content[0], dict) and "text" in raw_content[0]:
            answer = raw_content[0]["text"]
        elif hasattr(raw_content[0], "text"):
            answer = raw_content[0].text
    elif isinstance(raw_content, dict) and "text" in raw_content:
        answer = raw_content["text"]
    
    citations = []
    for doc in docs:
        page = doc.metadata.get("page", 0) + 1
        source = doc.metadata.get("doc_name") or doc.metadata.get("source", "Unknown Document")
        citations.append({
            "source": os.path.basename(source),
            "page": page,
            "snippet": doc.page_content[:150] + "..."
        })
    return {"answer": response.content, "citations": citations}

# Set page config
st.set_page_config(page_title="IntelliDocs AI Assistant", layout="wide")

# Modern Obsidian, Glassmorphism & Animated Styling
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');
    
    /* Base App Styling */
    html, body, [data-testid="stAppViewContainer"] {
        background: radial-gradient(circle at 50% 50%, #0E0F16 0%, #050508 100%) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        color: #E2E8F0 !important;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: rgba(10, 11, 18, 0.95) !important;
        border-right: 1px solid rgba(255, 255, 255, 0.05) !important;
        backdrop-filter: blur(10px) !important;
    }
    
    /* Glowing title */
    .hero-title {
        font-size: 2.8rem !important;
        font-weight: 800 !important;
        background: linear-gradient(135deg, #A855F7 0%, #6366F1 50%, #3B82F6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-top: 0.5rem;
        margin-bottom: 0.2rem;
        letter-spacing: -1.5px;
    }
    
    .hero-subtitle {
        font-size: 1rem;
        color: #64748B;
        text-align: center;
        margin-bottom: 2rem;
        font-weight: 500;
        letter-spacing: 0.5px;
    }
    
    /* Style Streamlit's native bordered containers to look like Glass cards */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(255, 255, 255, 0.02) !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 16px !important;
        backdrop-filter: blur(12px) !important;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2) !important;
        padding: 1.5rem !important;
        margin-bottom: 1rem !important;
    }
    
    .metric-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 0.75rem 1rem;
        margin-bottom: 0.5rem;
    }
    .metric-label {
        font-size: 0.75rem;
        color: #94A3B8;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-value {
        font-size: 0.9rem;
        color: #A855F7;
        font-weight: 700;
    }
    .step-card {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 16px;
        padding: 1.5rem;
        text-align: center;
        height: 100%;
    }
    .step-icon {
        font-size: 2.2rem;
        margin-bottom: 0.75rem;
    }
    .step-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #F8FAFC;
        margin-bottom: 0.5rem;
    }
    .step-desc {
        font-size: 0.85rem;
        color: #94A3B8;
        line-height: 1.5;
    }
    </style>
""", unsafe_allow_html=True)

# ----------------- SIDEBAR -----------------
st.sidebar.markdown("### 📥 Document Upload")
uploaded_files = st.sidebar.file_uploader(
    "Upload PDF files to build vector space",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed"
)

@st.cache_data(ttl=5, show_spinner=False)
def fetch_documents(cache_key=0):
    try:
        r = requests.get(f"{BACKEND_URL}/documents", timeout=2)
        if r.status_code == 200:
            return r.json().get("documents", [])
    except Exception:
        pass
    return native_list_documents()

if uploaded_files:
    if st.sidebar.button("Process Document", use_container_width=True):
        for uf in uploaded_files:
            with st.sidebar.spinner(f"Processing {uf.name}..."):
                processed = False
                try:
                    files = {"file": (uf.name, uf.getvalue(), "application/pdf")}
                    response = requests.post(f"{BACKEND_URL}/upload", files=files, timeout=2)
                    if response.status_code == 200:
                        st.sidebar.success(response.json().get("message", "Success!"))
                        st.session_state["active_doc"] = response.json().get("doc_name")
                        processed = True
                except Exception:
                    pass
                
                if not processed:
                    try:
                        msg = native_process_pdf(uf.getvalue(), uf.name)
                        st.sidebar.success(msg)
                        st.session_state["active_doc"] = uf.name
                    except Exception as ne:
                        st.sidebar.error(f"{uf.name}: {ne}")
                        
                st.session_state["doc_cache_key"] = st.session_state.get("doc_cache_key", 0) + 1

# Sidebar Engine Status Metrics
st.sidebar.markdown("<br><hr style='border: 1px solid rgba(255,255,255,0.05)'>", unsafe_allow_html=True)
st.sidebar.markdown("### ⚙️ System Parameters")

metrics = [
    ("LLM Generation Engine", "Gemini 3.6 Flash"),
    ("Vector Dimension Models", "gemini-embedding-001"),
    ("Vector Database Engine", "Numpy Cosine Similarity"),
    ("Framework Core", "Streamlit + LangChain")
]

for label, val in metrics:
    st.sidebar.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{val}</div>
        </div>
    """, unsafe_allow_html=True)


# ----------------- MAIN PANEL -----------------
st.markdown('<h1 class="hero-title">INTELLIDOCS</h1>', unsafe_allow_html=True)
st.markdown('<p class="hero-subtitle">Cognitive Retrieval-Augmented Generation (RAG) System</p>', unsafe_allow_html=True)

# Mobile-friendly instructional banner
st.markdown("""
    <div style="
        background: rgba(99, 102, 241, 0.08); 
        border: 1px solid rgba(99, 102, 241, 0.2); 
        border-radius: 12px; 
        padding: 1rem; 
        margin-bottom: 2rem; 
        text-align: center;
        backdrop-filter: blur(10px);
    ">
        <span style="font-weight: 600; color: #A855F7; font-size: 0.95rem;">💡 Getting Started:</span> 
        <span style="font-size: 0.9rem; color: #94A3B8;">
            If you are on mobile, tap the arrow ( <b style="color: #6366F1;">&gt;</b> ) in the top-left corner to open the sidebar and upload your reference PDF documents first!
        </span>
    </div>
""", unsafe_allow_html=True)

# Three-column visual overview
col_step1, col_step2, col_step3 = st.columns(3)

with col_step1:
    st.markdown("""
        <div class="step-card">
            <div class="step-icon">📁</div>
            <div class="step-title">1. Chunk & Embed</div>
            <div class="step-desc">Documents are split recursively and mapped to multi-dimensional coordinate vectors.</div>
        </div>
    """, unsafe_allow_html=True)

with col_step2:
    st.markdown("""
        <div class="step-card">
            <div class="step-icon">🔍</div>
            <div class="step-title">2. Semantic Search</div>
            <div class="step-desc">Cosine similarity algorithm queries ChromaDB to retrieve relevant factual text context.</div>
        </div>
    """, unsafe_allow_html=True)

with col_step3:
    st.markdown("""
        <div class="step-card">
            <div class="step-icon">🤖</div>
            <div class="step-title">3. Grounded Synthesis</div>
            <div class="step-desc">The Gemini generation engine synthesizes context-bound outputs, preventing hallucinations.</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Question Ingestion Section
with st.container(border=True):
    st.write("### 💬 Interrogate Knowledge Base")
    st.caption("Upload your PDF documents in the sidebar to build your vector space.")

    doc_options = fetch_documents(st.session_state.get("doc_cache_key", 0))

    selected_doc = None
    if doc_options:
        default_idx = 0
        active = st.session_state.get("active_doc")
        if active in doc_options:
            default_idx = doc_options.index(active)

        pick_col, del_col = st.columns([4, 1])
        selected_doc = pick_col.selectbox(
            "Answer using this document:",
            doc_options,
            index=default_idx,
        )
        del_col.markdown("<br>", unsafe_allow_html=True)
        if del_col.button("🗑️ Remove", use_container_width=True):
            try:
                requests.delete(f"{BACKEND_URL}/documents", params={"doc_name": selected_doc}, timeout=2)
            except Exception:
                pass
            native_delete_document(selected_doc)
            st.session_state["doc_cache_key"] = st.session_state.get("doc_cache_key", 0) + 1
            st.session_state.pop("active_doc", None)
            st.rerun()

    st.caption("Try a question:")
    q_cols = st.columns(3)
    SUGGESTED = [
        ("📄 Summarize", "Summarize this document in 3 bullet points"),
        ("🔑 Key Topics", "What are the key topics covered in this document?"),
        ("⭐ Key Facts", "List the most important facts from this document"),
    ]
    for i, (label, q) in enumerate(SUGGESTED):
        if q_cols[i].button(label, key=f"suggest{i}", use_container_width=True):
            st.session_state["prefill_q"] = q

    user_question = st.text_input(
        "Ask a question based on uploaded context:", 
        value=st.session_state.get("prefill_q", ""),
        placeholder="e.g., What key findings are mentioned in this document?...",
        label_visibility="collapsed"
    )
    submit_button = st.button("Generate Answer", use_container_width=True)

# Response Processing
if submit_button:
    if not user_question.strip():
        st.warning("Please type a valid question.")
    else:
        payload = {"question": user_question}
        if selected_doc:
            payload["doc_name"] = selected_doc

        with st.spinner("Retrieving context and generating answer..."):
            data = None
            try:
                r = requests.post(f"{BACKEND_URL}/query", json=payload, timeout=2)
                if r.status_code == 200:
                    data = r.json()
            except Exception:
                pass
                
            if not data:
                try:
                    data = native_query_documents(user_question, selected_doc)
                except Exception as qe:
                    st.error(f"Error: {qe}")
                    
            if data:
                with st.container(border=True):
                    st.markdown("### 🤖 Synthesized Answer")
                    st.write(data.get("answer", ""))

                if data.get("citations"):
                    st.markdown("<br><h4>📚 Reference Sources</h4>", unsafe_allow_html=True)
                    for idx, citation in enumerate(data["citations"]):
                        with st.expander(f"Factual Fragment {idx+1} — {citation['source']} (Page {citation['page']})"):
                            st.markdown(f"*{citation['snippet']}*")