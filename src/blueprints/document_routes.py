# src/api/document_routes.py
from document_processor import chunker
from flask import Blueprint, jsonify, request, current_app
from pathlib import Path
import os

from document_processor.loader import DocumentLoader
from document_processor.chunker import TextChunker

doc_bp = Blueprint('documents', __name__)

@doc_bp.route('/upload', methods=['POST'])
def upload_document():
    """
    Upload and process a document.
    
    Expects multipart/form-data with 'file' field.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400
    
    # Save file temporarily
    upload_dir = Path("/app/src/input_files")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / file.filename
    file.save(str(file_path))
    
    try:
        # Load document
        doc = DocumentLoader.load(str(file_path))
        
        # Create chunks
        chunker = TextChunker()
        chunks = chunker.split(doc.content, metadata=doc.metadata)
        
        return jsonify({
            "filename": file.filename,
            "type": doc.metadata.get('type'),
            "content_length": len(doc.content),
            "num_chunks": len(chunks),
            "chunks_preview": [
                {
                    "index": chunk.index,
                    "text": chunk.text[:100] + "..." if len(chunk.text) > 100 else chunk.text,
                    "length": len(chunk.text)
                }
                for chunk in chunks[:3]  # First 3 chunks
            ]
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@doc_bp.route('/chunk-text', methods=['POST'])
def chunk_text():
    """
    Chunk raw text.
    
    Body JSON:
    {
        "text": "your long text here",
        "chunk_size": 500,  # optional
        "overlap": 50       # optional
    }
    """
    data = request.get_json()
    
    if not data or 'text' not in data:
        return jsonify({"error": "Missing 'text' in request"}), 400
    
    text = data['text']
    chunk_size = data.get('chunk_size')
    overlap = data.get('overlap')
    
    # Create chunker
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=overlap)
    chunks = chunker.split(text)
    
    return jsonify({
        "text_length": len(text),
        "chunk_size": chunker.chunk_size,
        "overlap": chunker.chunk_overlap,
        "num_chunks": len(chunks),
        "chunks": [
            {
                "index": chunk.index,
                "text": chunk.text,
                "length": len(chunk.text)
            }
            for chunk in chunks
        ]
    })

@doc_bp.route('/list', methods=['GET'])
def list_documents():
    """List uploaded documents"""
    upload_dir = Path("/app/src/input_files")
    
    if not upload_dir.exists():
        return jsonify({"documents": []})
    
    documents = []
    for file_path in upload_dir.iterdir():
        if file_path.is_file():
            documents.append({
                "filename": file_path.name,
                "size": file_path.stat().st_size,
                "extension": file_path.suffix
            })
    
    return jsonify({"documents": documents})

@doc_bp.route("/load_local", methods=["POST"])
def load_local_document():
    data = request.get_json()
    
    if not data or 'file_path' not in data:
        return jsonify({"error": "Missing 'file_path' in request"}), 400
    
    file_path = data['file_path']

    loaded_document = DocumentLoader.load("/app/src/input_files/" +file_path)
    
    chunker = TextChunker()
    chunks = chunker.split(loaded_document.content, metadata=loaded_document.metadata)

    return jsonify({
            "filename": data['file_path'],
            "type": loaded_document.metadata.get('type'),
            "content_length": len(loaded_document.content),
            "num_chunks": len(chunks),
            "chunks_preview": [
                {
                    "index": chunk.index,
                    "text": chunk.text[:100] + "..." if len(chunk.text) > 100 else chunk.text,
                    "length": len(chunk.text)
                }
                for chunk in chunks[:3]  # First 3 chunks
            ]
        })