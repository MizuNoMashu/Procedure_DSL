"""
API endpoints for the extraction pipeline.

POST /extract      → JSON with AssemblyStep list
POST /extract-csv  → JSON with steps + saves CSV, triggers download via URL
GET  /health       → service status
GET  /download-csv/<filename> → download saved CSV
"""

import os
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request, current_app, send_file, render_template

from models.llm import language_model
from pipeline.runner import run_pipeline
from pipeline.csv_writer import steps_to_csv

api_bp = Blueprint('api', __name__)

# src/ directory, works in both Docker and local
_SRC_DIR = Path(__file__).parent.parent


def _output_dir() -> Path:
    p = _SRC_DIR / "output"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_llm_loaded():
    if language_model.model is None:
        language_model.load()


def _get_file(req) -> tuple:
    """
    Resolve the input file from the request.
    Supports:
      - multipart upload: field name 'file'
      - JSON body: {"filename": "foo.pdf"}  (must be in src/input_files/)

    Returns (file_path_str, original_filename, is_temp_file).
    Raises ValueError / FileNotFoundError on bad input.
    """
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
        # path traversal guard
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
        "llm_loaded": language_model.model is not None,
        "llm_model": language_model.model_name,
    })


@api_bp.route('/extract', methods=['POST'])
def extract():
    """Extract assembly steps from uploaded document. Returns JSON."""
    file_path = filename = None
    is_temp = False
    try:
        _ensure_llm_loaded()
        file_path, filename, is_temp = _get_file(request)
        config = current_app.config['PIPELINE_CONFIG']

        steps, stats = run_pipeline(file_path, language_model, config)

        return jsonify({
            "filename": filename,
            "stats": stats,
            "steps": [s.model_dump() for s in steps],
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if is_temp and file_path and os.path.exists(file_path):
            os.unlink(file_path)


@api_bp.route('/extract-csv', methods=['POST'])
def extract_csv():
    """Extract assembly steps, save CSV, return JSON with download URL."""
    file_path = filename = None
    is_temp = False
    try:
        _ensure_llm_loaded()
        file_path, filename, is_temp = _get_file(request)
        config = current_app.config['PIPELINE_CONFIG']

        steps, stats = run_pipeline(file_path, language_model, config)
        csv_string = steps_to_csv(steps)

        csv_filename = Path(filename).stem + "_procedure.csv"
        csv_path = _output_dir() / csv_filename
        csv_path.write_text(csv_string, encoding='utf-8')

        return jsonify({
            "filename": filename,
            "stats": stats,
            "csv_filename": csv_filename,
            "download_url": f"/download-csv/{csv_filename}",
            "steps": [s.model_dump() for s in steps],
            "csv": csv_string,
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if is_temp and file_path and os.path.exists(file_path):
            os.unlink(file_path)


@api_bp.route('/download-csv/<filename>', methods=['GET'])
def download_csv(filename):
    out = _output_dir().resolve()
    csv_path = (out / filename).resolve()
    # path traversal guard
    if not str(csv_path).startswith(str(out)):
        return jsonify({"error": "Invalid filename"}), 400
    if not csv_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(csv_path), mimetype='text/csv', as_attachment=True, download_name=filename)
