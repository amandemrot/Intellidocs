import streamlit as st
import requests

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
    
    /* Style inputs */
    div[data-baseweb="input"] {
        background-color: rgba(255, 255, 255, 0.01) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 10px !important;
        color: #FFFFFF !important;
        transition: all 0.3s ease;
    }
    
    div[data-baseweb="input"]:focus-within {
        border-color: #6366F1 !important;
        box-shadow: 0 0 10px rgba(99, 102, 241, 0.15) !important;
    }
    
    /* Cinematic primary button style */
    .stButton>button {
        background: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%) !important;
        color: white !important;
        border: none !important;
        padding: 0.6rem 1.8rem !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 15px rgba(99, 102, 241, 0.2) !important;
    }
    
    .stButton>button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 18px rgba(99, 102, 241, 0.4) !important;
        background: linear-gradient(135deg, #818CF8 0%, #6366F1 100%) !important;
    }
    
    /* Sidebar info metric cards */
    .metric-card {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 8px;
        padding: 0.8rem;
        margin-bottom: 0.6rem;
    }
    
    .metric-label {
        font-size: 0.75rem;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    .metric-value {
        font-size: 0.9rem;
        font-weight: 600;
        color: #F1F5F9;
    }
    
    /* Step pipeline layout with cinematic zoom & press feedback */
    .step-card {
        text-align: center;
        background: rgba(255, 255, 255, 0.01) !important;
        border: 1px solid rgba(255, 255, 255, 0.03) !important;
        border-radius: 12px !important;
        padding: 1.2rem !important;
        cursor: pointer !important;
        user-select: none !important;
        
        /* Smooth, modern cubic-bezier curve for high-end feel */
        transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), 
                    box-shadow 0.4s cubic-bezier(0.16, 1, 0.3, 1), 
                    border-color 0.4s cubic-bezier(0.16, 1, 0.3, 1), 
                    background-color 0.4s ease !important;
    }
    
    /* Elegant Hover Zoom, Elevation and Violet Glow */
    .step-card:hover {
        transform: scale(1.05) translateY(-5px) !important;
        background-color: rgba(255, 255, 255, 0.03) !important;
        border-color: rgba(168, 85, 247, 0.3) !important;
        
        /* Two-layer glowing shadow */
        box-shadow: 0 15px 35px rgba(168, 85, 247, 0.12), 
                    0 5px 15px rgba(0, 0, 0, 0.2) !important;
    }
    
    /* Satisfying tactile press feedback when clicked */
    .step-card:active {
        transform: scale(0.97) translateY(-1px) !important;
        border-color: rgba(99, 102, 241, 0.5) !important;
        transition: transform 0.08s ease !important; /* Fast response on release */
    }
    
    .step-icon {
        font-size: 1.5rem;
        margin-bottom: 0.3rem;
    }
    
    .step-title {
        font-weight: 600;
        color: #A855F7;
        font-size: 0.9rem;
    }
    
    .step-desc {
        font-size: 0.75rem;
        color: #64748B;
    }
    </style>
""", unsafe_allow_html=True)

# ----------------- SIDEBAR -----------------
st.sidebar.markdown("### 📥 Document Upload")
uploaded_file = st.sidebar.file_uploader("Upload PDF files to build vector space", type=["pdf"], label_visibility="collapsed")

import os
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

if uploaded_file is not None:
    if st.sidebar.button("Process Document", use_container_width=True):
        with st.sidebar.spinner("Parsing text and calculating embeddings..."):
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
            try:
                response = requests.post(f"{BACKEND_URL}/upload", files=files)
                if response.status_code == 200:
                    st.sidebar.success(response.json().get("message", "Success!"))
                else:
                    st.sidebar.error(f"Error: {response.json().get('detail')}")
            except Exception as e:
                st.sidebar.error(f"Backend offline: {e}")

# Sidebar Engine Status Metrics
st.sidebar.markdown("<br><hr style='border: 1px solid rgba(255,255,255,0.05)'>", unsafe_allow_html=True)
st.sidebar.markdown("### ⚙️ System Parameters")

metrics = [
    ("LLM Generation Engine", "Gemini 3.5 Flash"),
    ("Vector Dimension Models", "gemini-embedding-001"),
    ("Vector Database Engine", "ChromaDB (Local Store)"),
    ("API Framework Core", "FastAPI (Python)")
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

# Mobile-friendly instructional banner to guide users to the sidebar
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
    user_question = st.text_input(
        "Ask a question based on uploaded context:", 
        placeholder="e.g., Which college or university is mentioned in this resume template?...",
        label_visibility="collapsed"
    )
    submit_button = st.button("Generate Answer", use_container_width=True)

# Response Processing
if submit_button:
    if not user_question.strip():
        st.warning("Please type a valid question.")
    else:
        with st.spinner("Retrieving data and generating grounded response..."):
            try:
                response = requests.post(f"{BACKEND_URL}/query", json={"question": user_question})
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Display Answer Card
                    with st.container(border=True):
                        st.markdown("### 🤖 Synthesized Answer")
                        st.write(data["answer"])
                    
                    # Display Citation Cards
                    if data.get("citations"):
                        st.markdown("<br><h4>📚 Reference Sources</h4>", unsafe_allow_html=True)
                        for idx, citation in enumerate(data["citations"]):
                            with st.expander(f"Factual Fragment {idx+1} — {citation['source']} (Page {citation['page']})"):
                                st.markdown(f"*{citation['snippet']}*")
                else:
                    st.error(f"Failing Backend response: {response.json().get('detail', 'Unknown error')}")
                    
            except Exception as e:
                st.error(f"Error connecting to FastAPI engine: {e}")