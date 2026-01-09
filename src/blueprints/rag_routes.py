# src/api/rag_routes.py
from flask import Blueprint, jsonify, request, current_app
from rag.pipeline import rag_pipeline
from models.llm import language_model

rag_bp = Blueprint('rag', __name__)

def ensure_llm_loaded():
    """Ensure LLM is loaded"""
    if language_model.model is None:
        with current_app.app_context():
            language_model.load()

@rag_bp.route('/rag-query', methods=['POST'])
def rag_query():
    """
    RAG query - retrieve and generate answer.
    
    Body JSON:
    {
        "question": "your question here",
        "top_k": 5,              # optional
        "max_tokens": 512,       # optional
        "temperature": 0.7,      # optional
        "include_sources": true  # optional
    }
    """
    ensure_llm_loaded()
    
    data = request.get_json()
    
    if not data or 'question' not in data:
        return jsonify({"error": "Missing 'question'"}), 400
    
    question = data['question']
    top_k = data.get('top_k') if data.get('top_k') else current_app.config['RAG_CONFIG']['retrieval']['top_k']
    max_tokens = data.get('max_tokens') if data.get('max_tokens') else current_app.config['RAG_CONFIG']['llm']['max_tokens']
    temperature = data.get('temperature', 0.7)
    include_sources = data.get('include_sources', True)
    
    try:
        # Execute RAG pipeline
        result = rag_pipeline.query(
            question=question,
            top_k=top_k,
            max_tokens=max_tokens,
            temperature=temperature,
            include_sources=include_sources
        )
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@rag_bp.route('/rag-chat', methods=['POST'])
def rag_chat():
    """
    RAG chat - conversational with context.
    
    Body JSON:
    {
        "messages": [
            {"role": "user", "content": "What is Python?"}
        ],
        "top_k": 5,
        "max_tokens": 512,
        "temperature": 0.7
    }
    """
    ensure_llm_loaded()
    
    data = request.get_json()
    
    if not data or 'messages' not in data:
        return jsonify({"error": "Missing 'messages'"}), 400
    
    messages = data['messages']
    top_k = data.get('top_k') if data.get('top_k') else current_app.config['RAG_CONFIG']['retrieval']['top_k']
    max_tokens = data.get('max_tokens') if data.get('max_tokens') else current_app.config['RAG_CONFIG']['llm']['max_tokens']
    temperature = data.get('temperature', 0.7)
    
    try:
        result = rag_pipeline.chat_with_context(
            messages=messages,
            top_k=top_k,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@rag_bp.route('/rag-status', methods=['GET'])
def rag_status():
    """Check RAG system status"""
    from vectorstore.chroma_store import vector_store
    
    return jsonify({
        "llm_loaded": language_model.model is not None,
        "llm_model": language_model.model_name if language_model.model else None,
        "vectorstore_docs": vector_store.collection.count() if vector_store.collection else 0,
        "ready": language_model.model is not None and vector_store.collection is not None
    })