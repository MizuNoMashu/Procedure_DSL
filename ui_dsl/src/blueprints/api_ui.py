"""
UI service API endpoints.

Handles: editor interface, CSV management, DSL generation.
Proxies: /extract-csv → LLM service (LLM_SERVICE_URL, default http://llm:8001)
"""

import csv as _csv_mod
import io as _io
import os
from pathlib import Path

import requests as _requests
from flask import Blueprint, jsonify, request, send_file, render_template

from pipeline.csv_writer import CSV_COLUMNS
from pipeline.dsl_runner import run_dsl_from_csv
from pipeline.output_paths import output_root, csv_folder, resolve_in, find_in_any_folder

api_ui_bp = Blueprint('api_ui', __name__)

_SRC_DIR = Path(__file__).parent.parent
_LLM_URL = os.environ.get('LLM_SERVICE_URL', 'http://llm:8001')
_COBOT_URL = os.environ.get('COBOT_SERVICE_URL', 'http://cobot:5000')


@api_ui_bp.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "ui"})


@api_ui_bp.route('/extract-csv', methods=['POST'])
def extract_csv():
    """Proxy to LLM service. Saves the returned CSV into its own output folder."""
    try:
        if 'file' in request.files:
            f = request.files['file']
            f.stream.seek(0)  # Flask legge lo stream durante il parsing; rewind prima di forwardare
            resp = _requests.post(
                f'{_LLM_URL}/extract-csv',
                files={'file': (f.filename, f.stream, f.content_type)},
                timeout=3600,
            )
        else:
            resp = _requests.post(
                f'{_LLM_URL}/extract-csv',
                json=request.get_json(silent=True) or {},
                timeout=3600,
            )
    except _requests.exceptions.ConnectionError:
        return jsonify({"error": f"LLM service unreachable at {_LLM_URL}"}), 503
    except _requests.exceptions.Timeout:
        return jsonify({"error": "LLM service timed out"}), 504

    data = resp.json()
    if resp.ok and 'csv' in data and 'csv_filename' in data:
        folder = csv_folder(_SRC_DIR, data['csv_filename'], create=True)
        (folder / data['csv_filename']).write_text(data['csv'], encoding='utf-8')
        data['download_url'] = f"/download-csv/{data['csv_filename']}"

    return jsonify(data), resp.status_code


@api_ui_bp.route('/editor', methods=['GET'])
def editor():
    return render_template('editor.html')


@api_ui_bp.route('/list-csv', methods=['GET'])
def list_csv_files():
    files = sorted(f.name for f in output_root(_SRC_DIR).glob('*/*.csv'))
    return jsonify({"files": files})


@api_ui_bp.route('/load-csv-json/<filename>', methods=['GET'])
def load_csv_json(filename):
    try:
        path = resolve_in(csv_folder(_SRC_DIR, filename), filename)
    except ValueError:
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    rows = []
    with open(str(path), encoding='utf-8', newline='') as f:
        reader = _csv_mod.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return jsonify({"filename": filename, "rows": rows})


@api_ui_bp.route('/save-csv', methods=['POST'])
def save_csv_edit():
    """Save (or create) a CSV. Each filename gets its own output folder, so
    both hand-created CSVs and extractor output live under a consistent layout."""
    data = request.get_json(silent=True) or {}
    filename = data.get('filename', '').strip()
    rows = data.get('rows', [])
    if not filename or '/' in filename or '\\' in filename or not filename.endswith('.csv'):
        return jsonify({"error": "Invalid filename — must be a .csv name without path separators"}), 400
    try:
        folder = csv_folder(_SRC_DIR, filename, create=True)
    except ValueError:
        return jsonify({"error": "Invalid filename"}), 400
    buf = _io.StringIO()
    writer = _csv_mod.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, '') for col in CSV_COLUMNS})
    (folder / filename).write_text(buf.getvalue(), encoding='utf-8')
    return jsonify({"ok": True, "filename": filename, "download_url": f"/download-csv/{filename}"})


@api_ui_bp.route('/download-csv/<filename>', methods=['GET'])
def download_csv(filename):
    try:
        path = resolve_in(csv_folder(_SRC_DIR, filename), filename)
    except ValueError:
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(path), mimetype='text/csv', as_attachment=True, download_name=filename)


@api_ui_bp.route('/generate-dsl', methods=['POST'])
def generate_dsl():
    data = request.get_json(silent=True) or {}
    csv_filename = data.get('csv_filename', '').strip()
    project_name = data.get('project_name', '').strip()
    if not csv_filename or not project_name:
        return jsonify({"error": "csv_filename and project_name are required"}), 400
    if '/' in csv_filename or '\\' in csv_filename:
        return jsonify({"error": "Invalid csv_filename"}), 400
    try:
        folder = csv_folder(_SRC_DIR, csv_filename)
        csv_path = resolve_in(folder, csv_filename)
    except ValueError:
        return jsonify({"error": "Invalid csv_filename"}), 400
    if not csv_path.exists():
        return jsonify({"error": f"CSV not found: {csv_filename}"}), 404
    try:
        # DSL files are derived from this CSV, so they're written into the
        # same per-CSV folder rather than a shared flat directory.
        external_path, internal_path = run_dsl_from_csv(str(csv_path), project_name, folder)
        return jsonify({
            "ok": True,
            "external_url": f"/download-dsl/{external_path.name}",
            "internal_url": f"/download-dsl/{internal_path.name}",
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_ui_bp.route('/download-dsl/<filename>', methods=['GET'])
def download_dsl(filename):
    path = find_in_any_folder(_SRC_DIR, filename)
    if path is None or not path.exists():
        return jsonify({"error": "File not found"}), 404
    mime = 'application/yaml' if filename.endswith('.yml') else 'text/plain'
    return send_file(str(path), mimetype=mime, as_attachment=True, download_name=filename)


# ── Cobot page & proxy ────────────────────────────────────────────────────────

@api_ui_bp.route('/cobot', methods=['GET'])
def cobot_page():
    return render_template('cobot.html')


_LONG_TIMEOUT_PATHS = {'api/desk/prepare-and-connect', 'api/desk/prepare-fci'}

@api_ui_bp.route('/cobot-proxy/<path:path>', methods=['GET', 'POST', 'DELETE'])
def cobot_proxy(path):
    """Transparent proxy to the cobot API service."""
    url = f'{_COBOT_URL}/{path}'
    timeout = 120 if path in _LONG_TIMEOUT_PATHS else 30
    try:
        resp = _requests.request(
            method=request.method,
            url=url,
            json=request.get_json(silent=True) if request.method in ('POST',) else None,
            params=request.args,
            timeout=timeout,
        )
        return resp.content, resp.status_code, {'Content-Type': resp.headers.get('Content-Type', 'application/json')}
    except _requests.exceptions.ConnectionError:
        return jsonify({"error": f"Cobot service unreachable at {_COBOT_URL}"}), 503
    except _requests.exceptions.Timeout:
        return jsonify({"error": "Cobot service timed out"}), 504
    except Exception as e:
        print(f"[PROXY ERROR] {request.method} /{path}: {type(e).__name__}: {e}")
        return jsonify({"error": f"Proxy error: {str(e)}"}), 502
