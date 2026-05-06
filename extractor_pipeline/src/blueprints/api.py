"""
LLM extraction service endpoints.

Handles document ingestion and step extraction (requires GPU/LLM).
Returns CSV as string in JSON — the UI service saves it to disk.
"""

import os
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request, current_app

from models.llm import language_model
from pipeline.runner import run_pipeline
from pipeline.csv_writer import steps_to_csv_with_confidence

api_bp = Blueprint('api', __name__)

_SRC_DIR = Path(__file__).parent.parent


def _ensure_llm_loaded():
    if language_model.model is None:
        language_model.load()


def _get_file(req) -> tuple:
    if 'file' in req.files:
        f = req.files['file']
        if not f.filename:
            raise ValueError("Empty filename in upload")
        suffix = Path(f.filename).suffix.lower()
        if suffix not in ('.pdf', '.docx', '.txt'):
            raise ValueError(f"Unsupported file type: {suffix}")
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        f.save(tmp.name)
        tmp.close()
        return tmp.name, f.filename, True

    data = req.get_json(silent=True) or {}
    if 'filename' in data:
        filename = data['filename']
        input_dir = _SRC_DIR / "input_files"
        file_path = (input_dir / filename).resolve()
        if not str(file_path).startswith(str(input_dir.resolve())):
            raise ValueError("Invalid filename")
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filename}")
        return str(file_path), filename, False

    raise ValueError("Provide 'file' (multipart) or JSON body with 'filename'")


@api_bp.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "extractor",
        "llm_loaded": language_model.model is not None,
        "llm_model": language_model.model_name,
    })


@api_bp.route('/extract-csv', methods=['POST'])
def extract_csv():
    """Extract steps from document, return CSV as string."""
    file_path = filename = None
    is_temp = False

    # --- model loading (separated so errors give 500, not 400) ---
    try:
        _ensure_llm_loaded()
    except Exception as e:
        import traceback
        print(f"❌ LLM loading failed: {e}", flush=True)
        traceback.print_exc()
        return jsonify({"error": f"LLM loading failed: {e}"}), 500

    try:
        file_path, filename, is_temp = _get_file(request)
        config = current_app.config['PIPELINE_CONFIG']

        steps, stats = run_pipeline(file_path, language_model, config)
        csv_string = steps_to_csv_with_confidence(steps)
        csv_filename = Path(filename).stem + "_procedure.csv"

        return jsonify({
            "filename": filename,
            "stats": stats,
            "csv_filename": csv_filename,
            "steps": [s.model_dump() for s in steps],
            "csv": csv_string,
        })

    except ValueError as e:
        print(f"❌ extract_csv ValueError: {e}", flush=True)
        return jsonify({"error": str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if is_temp and file_path and os.path.exists(file_path):
            os.unlink(file_path)
