"""
API endpoints for the extraction pipeline.

POST /extract              → JSON with AssemblyStep list
POST /extract-csv          → JSON with steps + saves CSV, triggers download via URL
POST /generate-dsl         → generate External + Internal DSL from a saved CSV
GET  /health               → service status
GET  /download-csv/<f>     → download saved CSV
GET  /download-dsl/<f>     → download generated DSL file (.yml or .txt)
"""

import csv as _csv_mod
import io as _io
import os
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request, current_app, send_file, render_template

from models.llm import language_model
from pipeline.runner import run_pipeline
from pipeline.csv_writer import steps_to_csv, steps_to_csv_with_confidence, CSV_COLUMNS
from pipeline.dsl_runner import run_dsl_from_csv

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
        csv_string = steps_to_csv_with_confidence(steps)  # includes CONFIDENCE col for editor; stripped on save

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


# ── Editor endpoints ──────────────────────────────────────────────────────────

@api_bp.route('/editor', methods=['GET'])
def editor():
    return render_template('editor.html')


@api_bp.route('/list-csv', methods=['GET'])
def list_csv_files():
    """Return list of .csv files available in the output directory."""
    files = sorted([f.name for f in _output_dir().glob('*.csv')])
    return jsonify({"files": files})


@api_bp.route('/load-csv-json/<filename>', methods=['GET'])
def load_csv_json(filename):
    """Load a saved CSV and return its rows as JSON."""
    out = _output_dir().resolve()
    path = (out / filename).resolve()
    if not str(path).startswith(str(out)):
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    rows = []
    with open(str(path), encoding='utf-8', newline='') as f:
        reader = _csv_mod.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return jsonify({"filename": filename, "rows": rows})


@api_bp.route('/save-csv', methods=['POST'])
def save_csv_edit():
    """Save edited rows (JSON) back to a CSV file in the output directory."""
    data = request.get_json(silent=True) or {}
    filename = data.get('filename', '').strip()
    rows = data.get('rows', [])

    if not filename or '/' in filename or '\\' in filename or not filename.endswith('.csv'):
        return jsonify({"error": "Invalid filename — must be a .csv name without path separators"}), 400

    buf = _io.StringIO()
    writer = _csv_mod.DictWriter(
        buf, fieldnames=CSV_COLUMNS, extrasaction='ignore', lineterminator='\n'
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, '') for col in CSV_COLUMNS})

    csv_path = _output_dir() / filename
    csv_path.write_text(buf.getvalue(), encoding='utf-8')
    return jsonify({"ok": True, "filename": filename, "download_url": f"/download-csv/{filename}"})


# ── DSL generation endpoints ──────────────────────────────────────────────────

@api_bp.route('/generate-dsl', methods=['POST'])
def generate_dsl():
    """
    Generate External DSL (.yml) and Internal DSL (.txt) from a saved CSV.
    Body: { "csv_filename": "foo_procedure.csv", "project_name": "MyProject" }
    Returns: { "ok": true, "external_url": "...", "internal_url": "..." }
    """
    data = request.get_json(silent=True) or {}
    csv_filename = data.get('csv_filename', '').strip()
    project_name = data.get('project_name', '').strip()

    if not csv_filename or not project_name:
        return jsonify({"error": "csv_filename and project_name are required"}), 400
    if '/' in csv_filename or '\\' in csv_filename:
        return jsonify({"error": "Invalid csv_filename"}), 400

    out = _output_dir()
    csv_path = (out / csv_filename).resolve()
    if not str(csv_path).startswith(str(out.resolve())):
        return jsonify({"error": "Invalid filename"}), 400
    if not csv_path.exists():
        return jsonify({"error": f"CSV not found: {csv_filename}"}), 404

    try:
        external_path, internal_path = run_dsl_from_csv(str(csv_path), project_name, out)
        return jsonify({
            "ok": True,
            "external_url": f"/download-dsl/{external_path.name}",
            "internal_url": f"/download-dsl/{internal_path.name}",
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/download-dsl/<filename>', methods=['GET'])
def download_dsl(filename):
    """Serve a generated DSL file from the output directory."""
    out = _output_dir().resolve()
    path = (out / filename).resolve()
    if not str(path).startswith(str(out)):
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    mime = 'application/yaml' if filename.endswith('.yml') else 'text/plain'
    return send_file(str(path), mimetype=mime, as_attachment=True, download_name=filename)
