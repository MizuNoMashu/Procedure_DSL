"""
Endpoint per l'estrazione strutturata di procedure da documenti tecnici
in formato CSV compatibile con Montaggio Cubesat.csv.

Colonne target:
ID, COMPONENT, COMPONENT DETAIL, ORIENTATION, ACTION, APPLIED TO,
TOOL, TOOL DETAIL, ASSEMBLY DETAIL
"""

from flask import Blueprint, jsonify, request, current_app, send_file
from pathlib import Path
import csv
import io
import json

from document_processor.loader import DocumentLoader
from document_processor.chunker import TextChunker
from vectorstore.chroma_store import vector_store
from models.llm import language_model

extraction_bp = Blueprint('extraction', __name__)

CSV_COLUMNS = [
    "ID", "COMPONENT", "COMPONENT DETAIL", "ORIENTATION",
    "ACTION", "APPLIED TO", "TOOL", "TOOL DETAIL", "ASSEMBLY DETAIL"
]

SYSTEM_PROMPT = (
    "You are a precise technical procedure extractor. "
    "Extract assembly steps from the text and return ONLY a JSON array. "
    "No explanations, no markdown, no code fences, just the JSON array."
)

# Few-shot examples derivati da Montaggio Cubesat.csv
FEW_SHOT_EXAMPLES = """[
  {"COMPONENT": "Frame 1", "COMPONENT DETAIL": "Type = Lower;", "ORIENTATION": "", "ACTION": "Place", "APPLIED TO": "Frame 1;", "TOOL": "", "TOOL DETAIL": "", "ASSEMBLY DETAIL": "Place Frame 1 on the Workstation"},
  {"COMPONENT": "Screw 1", "COMPONENT DETAIL": "Head = Hexagonal; Diameter = 3mm; Length = 11mm;", "ORIENTATION": "", "ACTION": "Insert", "APPLIED TO": "Frame 1.Hole 1;", "TOOL": "Screwdriver", "TOOL DETAIL": "Tip = CR-V 2.0mm;", "ASSEMBLY DETAIL": ""},
  {"COMPONENT": "Spacer 1", "COMPONENT DETAIL": "Body = Hexagonal; Threaded = True; Diameter = 3mm; Length = 10mm;", "ORIENTATION": "", "ACTION": "Screw in", "APPLIED TO": "Screw 1;", "TOOL": "Wrench", "TOOL DETAIL": "Diameter = 3mm;", "ASSEMBLY DETAIL": ""},
  {"COMPONENT": "Frame 2", "COMPONENT DETAIL": "Type = Upper;", "ORIENTATION": "Hole 1 = Spacer 29; Hole 2 = Spacer 30; Hole 3 = Spacer 31; Hole 4 = Spacer 32;", "ACTION": "Place", "APPLIED TO": "Spacer 29; Spacer 30; Spacer 31; Spacer 32;", "TOOL": "", "TOOL DETAIL": "", "ASSEMBLY DETAIL": ""}
]"""

USER_PROMPT_TEMPLATE = """Extract all assembly/procedure steps from the technical text below.
Return a JSON array where each object has these exact keys:
"COMPONENT", "COMPONENT DETAIL", "ORIENTATION", "ACTION", "APPLIED TO", "TOOL", "TOOL DETAIL", "ASSEMBLY DETAIL"

Rules:
- COMPONENT: name of the part being acted on (e.g. "Screw 1", "Motor A")
- COMPONENT DETAIL: technical specs (e.g. "Diameter = 3mm; Length = 11mm;")
- ORIENTATION: positioning info if mentioned, else ""
- ACTION: the operation (e.g. "Insert", "Screw in", "Place", "Connect", "Tighten")
- APPLIED TO: what the action targets (e.g. "Frame 1.Hole 1;")
- TOOL: tool used if any, else ""
- TOOL DETAIL: tool specs if any, else ""
- ASSEMBLY DETAIL: extra notes if any, else ""
- If no procedure steps are present in the text, return []

Example output format:
{examples}

Now extract from this text:
{text}

Output ONLY the JSON array:"""


def _build_messages(chunk_text: str) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
            examples=FEW_SHOT_EXAMPLES,
            text=chunk_text
        )}
    ]


def _parse_llm_json(raw: str) -> list:
    """Estrae il JSON array dalla risposta dell'LLM con più tentativi."""
    if not raw:
        return []

    start = raw.find('[')
    end = raw.rfind(']')
    if start == -1 or end == -1 or end <= start:
        return []

    candidate = raw[start:end + 1]
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: cerca oggetti singoli
    steps = []
    depth = 0
    obj_start = None
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(raw[obj_start:i + 1])
                    steps.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None

    return steps


def _dedup_steps(steps: list) -> list:
    """Rimuove step duplicati basandosi su ACTION + COMPONENT + APPLIED TO."""
    seen = set()
    unique = []
    for step in steps:
        key = (
            step.get("ACTION", "").strip().lower(),
            step.get("COMPONENT", "").strip().lower(),
            step.get("APPLIED TO", "").strip().lower(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(step)
    return unique


def _steps_to_csv_string(steps: list) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=CSV_COLUMNS,
        extrasaction='ignore',
        lineterminator='\n'
    )
    writer.writeheader()
    for i, step in enumerate(steps, 1):
        row = {col: "" for col in CSV_COLUMNS}
        row["ID"] = i
        row.update({k: v for k, v in step.items() if k in CSV_COLUMNS})
        writer.writerow(row)
    return output.getvalue()


@extraction_bp.route('/extract-csv', methods=['POST'])
def extract_csv():
    """
    Estrae step procedurali da un documento e restituisce CSV.

    Body JSON:
    {
        "filename": "EdgeFlyte_user_manual.pdf",
        "max_tokens": 1024,     # optional
        "use_rag": false,       # false = processa TUTTI i chunk (consigliato)
                                # true  = usa solo i top_k chunk più rilevanti
        "top_k": 10,            # usato solo se use_rag=true
        "debug": false          # include raw LLM output per debugging
    }
    """
    if language_model.model is None:
        language_model.load()

    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({"error": "Missing 'filename'"}), 400

    filename = data['filename']
    config = current_app.config['RAG_CONFIG']
    max_tokens = data.get('max_tokens', config['llm']['max_tokens'])
    # default use_rag=False: processa tutto il documento
    use_rag = data.get('use_rag', False)
    top_k = data.get('top_k', config['retrieval']['top_k'])
    debug = data.get('debug', False)

    file_path = Path("/app/src/input_files") / filename
    if not file_path.exists():
        return jsonify({"error": f"File not found: {filename}"}), 404

    try:
        doc = DocumentLoader.load(str(file_path))
        chunker = TextChunker()
        chunks = chunker.split(doc.content, metadata=doc.metadata)

        if use_rag:
            # Usa il vectorstore già indicizzato (non ri-indicizza qui)
            # Se non ci sono documenti indicizzati, avvisa
            if vector_store.collection is None or vector_store.collection.count() == 0:
                return jsonify({
                    "error": "Vectorstore vuoto. Prima indicizza il documento con POST /index-document"
                }), 400

            search_results = vector_store.search(
                "assembly procedure steps components actions tools installation",
                top_k=top_k
            )
            work_chunks = [r['text'] for r in search_results['results']]
        else:
            # Processa tutti i chunk del documento
            work_chunks = [c.text for c in chunks]

        all_steps = []
        raw_outputs = []

        print(f"Processing {len(work_chunks)} chunks...")

        for i, chunk_text in enumerate(work_chunks):
            if not chunk_text.strip():
                continue

            print(f"  Chunk {i+1}/{len(work_chunks)}...")
            messages = _build_messages(chunk_text)
            raw = language_model.chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.1
            )

            if debug:
                raw_outputs.append({"chunk": i, "text": chunk_text[:100], "raw": raw})

            steps = _parse_llm_json(raw)
            all_steps.extend(steps)

        # Deduplica
        all_steps = _dedup_steps(all_steps)

        csv_string = _steps_to_csv_string(all_steps)

        output_dir = Path("/app/src/output")
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_filename = file_path.stem + "_procedure.csv"
        csv_path = output_dir / csv_filename
        csv_path.write_text(csv_string, encoding='utf-8')

        response = {
            "filename": filename,
            "num_chunks_processed": len(work_chunks),
            "num_steps": len(all_steps),
            "csv_filename": csv_filename,
            "download_url": f"/download-csv/{csv_filename}",
            "steps": all_steps,
            "csv": csv_string
        }

        if debug:
            response["raw_llm_outputs"] = raw_outputs

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@extraction_bp.route('/download-csv/<filename>', methods=['GET'])
def download_csv(filename):
    output_dir = Path("/app/src/output").resolve()
    csv_path = (output_dir / filename).resolve()
    if not str(csv_path).startswith(str(output_dir)):
        return jsonify({"error": "Invalid filename"}), 400
    if not csv_path.exists():
        return jsonify({"error": "File not found"}), 404

    return send_file(
        str(csv_path),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


@extraction_bp.route('/extract-status', methods=['GET'])
def extract_status():
    output_dir = Path("/app/src/output")
    csv_files = []
    if output_dir.exists():
        csv_files = [f.name for f in output_dir.glob("*.csv")]

    return jsonify({
        "llm_loaded": language_model.model is not None,
        "llm_model": language_model.model_name,
        "generated_csv_files": csv_files
    })
