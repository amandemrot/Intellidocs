# IntelliDocs - RAG-Based AI Knowledge Assistant

IntelliDocs is a cognitive Retrieval-Augmented Generation (RAG) system designed to perform intelligent document analysis. It allows users to upload unstructured PDF documents and interrogate them using Google's Gemini models for context-grounded, cited answers.

## 🚀 Live Demo
[Access IntelliDocs App](https://intellidocs-kzprstjnrsevlyfmwjzo9.streamlit.app/)

> **Note:** This app is hosted on a free-tier cloud service. If the server is inactive, the backend may take ~60 seconds to "wake up" upon the initial request. Thank you for your patience!

## 🛠 Tech Stack
- **AI/ML:** Google Gemini 3.5 Flash, Gemini Embedding-001, LangChain
- **Backend:** FastAPI
- **Database:** ChromaDB (Vector Store)
- **Frontend:** Streamlit (Custom Obsidian-themed UI)
- **Deployment:** Render & Streamlit Cloud

## 💡 Key Features
- **Semantic Context Search:** Utilizes vector embeddings to execute precise queries over complex PDF documents.
- **Grounded Synthesis:** Prevents hallucinations by synthesizing answers directly from the provided source material.
- **Dynamic Citations:** Automatically extracts and maps metadata to provide cited references for all answers.
- **Custom UI:** A polished, obsidian-themed interface for a distraction-free user experience.

## 🏗 Architecture
1. **Chunk & Embed:** Documents are split recursively and mapped to high-dimensional coordinate vectors.
2. **Semantic Search:** Cosine similarity algorithms query ChromaDB to retrieve relevant factual text context.
3. **Grounded Synthesis:** The Gemini generation engine produces accurate, context-bound outputs.

---
*Built by Aman Demrot*
