# src/api/vectorstore_routes.py
from flask import Blueprint, jsonify, request, current_app
from vectorstore.chroma_store import vector_store
from document_processor.loader import DocumentLoader
from document_processor.chunker import TextChunker
from pathlib import Path

vs_bp = Blueprint('vectorstore', __name__)

@vs_bp.route('/stats', methods=['GET'])
def stats():
    """Get vector store statistics"""
    return jsonify(vector_store.get_stats())

@vs_bp.route('/add-text', methods=['POST'])
def add_text():
    """
    Add text directly to vector store.
    
    Body JSON:
    {
        "text": "your text here",
        "metadata": {"optional": "metadata"}
    }
    """
    data = request.get_json()
    
    if not data or 'text' not in data:
        return jsonify({"error": "Missing 'text'"}), 400
    
    text = data['text']
    metadata = data.get('metadata', {})
    
    # Chunk text
    config = current_app.config['RAG_CONFIG']
    chunker = TextChunker()
    chunks = chunker.split(text, metadata=metadata)
    
    # Add to vector store
    texts = [chunk.text for chunk in chunks]
    metadatas = [chunk.metadata for chunk in chunks]
    
    ids = vector_store.add_texts(texts, metadatas=metadatas)
    
    return jsonify({
        "message": "Text added to vector store",
        "num_chunks": len(chunks),
        "ids": ids
    })

@vs_bp.route('/index-document', methods=['POST'])
def index_document():
    """
    Index an uploaded document.
    
    Body JSON:
    {
        "filename": "document.txt"
    }
    """
    data = request.get_json()
    
    if not data or 'filename' not in data:
        return jsonify({"error": "Missing 'filename'"}), 400
    
    filename = data['filename']
    file_path = Path("/app/src/input_files") / filename
    
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    
    try:
        # Load document
        doc = DocumentLoader.load(str(file_path))
        
        # Chunk document
        chunker = TextChunker()
        chunks = chunker.split(doc.content, metadata=doc.metadata)
        
        # Add to vector store
        texts = [chunk.text for chunk in chunks]
        metadatas = [chunk.metadata for chunk in chunks]
        
        ids = vector_store.add_texts(texts, metadatas=metadatas)
        
        return jsonify({
            "message": f"Document '{filename}' indexed",
            "filename": filename,
            "num_chunks": len(chunks),
            "ids": ids[:5]  # First 5 IDs
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@vs_bp.route('/search', methods=['POST'])
def search():
    """
    Search vector store.
    
    Body JSON:
    {
        "query": "your search query",
        "top_k": 5  # optional
    }
    """
    data = request.get_json()
    
    if not data or 'query' not in data:
        return jsonify({"error": "Missing 'query'"}), 400
    
    query = data['query']
    config = current_app.config['RAG_CONFIG']
    top_k = data.get('top_k', config['retrieval']['top_k'])
    
    # Search
    results = vector_store.search(query, top_k=top_k)
    
    return jsonify(results)

@vs_bp.route('/clear', methods=['POST'])
def clear():
    """Clear all documents from vector store"""
    vector_store.clear()
    
    return jsonify({
        "message": "Vector store cleared",
        "stats": vector_store.get_stats()
    })