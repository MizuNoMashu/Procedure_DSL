from flask import Flask, jsonify
from flask_cors import CORS
import yaml
from pathlib import Path

app = Flask(__name__)
CORS(app)

def load_config():
    # Funziona sia in Docker (/app/src/...) che in locale (src/...)
    for config_path in [
        Path("/app/src/config/config.yaml"),
        Path(__file__).parent / "config" / "config.yaml"
    ]:
        if config_path.exists():
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
    print("⚠️  Configuration file not found")
    return None

app.config['RAG_CONFIG'] = load_config()

def print_startup_banner():
    print("=" * 60)
    print("RAG System Starting...")
    print("=" * 60)
    if app.config['RAG_CONFIG']:
        print("✅ Configuration loaded successfully")
        print(f"   Device: {app.config['RAG_CONFIG'].get('device', 'cpu')}")
        print(f"   Embeddings model: {app.config['RAG_CONFIG'].get('embeddings', {}).get('model', 'unknown')}")
        print(f"   LLM model: {app.config['RAG_CONFIG'].get('llm', {}).get('model', 'unknown')}")
    else:
        print("⚠️  No configuration file found")
    print("\nRAG Pipeline ready!")
    print("   1. Upload documents with /upload")
    print("   2. Index them with /index-document")
    print("   3. Ask questions with /rag-query")
    print("   4. Extract procedure CSV with /extract-csv (POST)")
    print("\n⚠️  Note: LLM loads on first query (may take time)")
    print("Server: http://0.0.0.0:8000")
    print("=" * 60)

from blueprints.test import test_bp
app.register_blueprint(test_bp)

from blueprints.document_routes import doc_bp
app.register_blueprint(doc_bp)

from blueprints.vectorstore_routes import vs_bp
app.register_blueprint(vs_bp)

from blueprints.llm_routes import llm_bp
app.register_blueprint(llm_bp)

from blueprints.rag_routes import rag_bp
app.register_blueprint(rag_bp)

from blueprints.extraction_routes import extraction_bp
app.register_blueprint(extraction_bp)

@app.before_request
def load_models():
    from models.embeddings import embedding_model
    if embedding_model.model is None:
        embedding_model.load()

    from vectorstore.chroma_store import vector_store
    if vector_store.collection is None:
        vector_store.initialize()


@app.route('/')
def root():
    return jsonify({
        "status": "running",
        "message": "RAG System",
        "endpoints": {
            "embeddings": {
                "info": "/info",
                "embed": "/embed (POST)",
                "similarity": "/similarity (POST)"
            },
            "documents": {
                "upload": "/upload (POST)",
                "chunk": "/chunk-text (POST)",
                "list": "/list"
            },
            "vectorstore": {
                "stats": "/stats",
                "add-text": "/add-text (POST)",
                "index-document": "/index-document (POST)",
                "search": "/search (POST)",
                "clear": "/clear (POST)"
            },
            "llm": {
                "info": "/llm-info",
                "generate": "/generate (POST)",
                "chat": "/chat (POST)"
            },
            "rag": {
                "query": "/rag-query (POST)",
                "chat": "/rag-chat (POST)",
                "status": "/rag-status"
            },
            "extraction": {
                "extract-csv": "/extract-csv (POST)",
                "download-csv": "/download-csv/<filename> (GET)"
            }
        }
    })

if __name__ == "__main__":
    print_startup_banner()
    app.run(
        host="0.0.0.0",
        port=8000,
        debug=True,
        use_reloader=True
    )
