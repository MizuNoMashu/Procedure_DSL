from flask import Blueprint, jsonify, request, current_app
from pathlib import Path

from document_processor.loader import DocumentLoader
from document_processor.chunker import TextChunker

doc_bp = Blueprint('documents', __name__)

def _get_input_dir() -> Path:
    """Ritorna la dir degli input_files sia in Docker che in locale."""
    docker_path = Path("/app/src/input_files")
    if docker_path.parent.parent.exists() and (docker_path.parent.parent / "src").exists():
        return docker_path
    # In locale: cartella src/input_files relativa a questo file
    return Path(__file__).parent.parent / "input_files"

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

    upload_dir = _get_input_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / file.filename
    file.save(str(file_path))

    try:
        doc = DocumentLoader.load(str(file_path))
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
                for chunk in chunks[:3]
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
        "chunk_size": 500,
        "overlap": 50
    }
    """
    data = request.get_json()

    if not data or 'text' not in data:
        return jsonify({"error": "Missing 'text' in request"}), 400

    text = data['text']
    chunk_size = data.get('chunk_size')
    overlap = data.get('overlap')

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
    upload_dir = _get_input_dir()

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

    # Prevenzione path traversal
    upload_dir = _get_input_dir().resolve()
    requested = (upload_dir / data['file_path']).resolve()
    if not str(requested).startswith(str(upload_dir)):
        return jsonify({"error": "Invalid file path"}), 400

    loaded_document = DocumentLoader.load(str(requested))

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
            for chunk in chunks[:3]
        ]
    })
