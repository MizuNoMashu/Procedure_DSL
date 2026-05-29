# Procedure DSL

Automatic extraction of assembly steps from technical documents (PDF, DOCX, TXT) via a local LLM, manual editing, and generation of an internal/external DSL.

---

## Structure

```
Procedure_DSL/
├── ui_dsl/                  # Web interface + DSL parser (any OS)
│   ├── src/
│   │   ├── main.py
│   │   ├── blueprints/api_ui.py
│   │   ├── templates/       # editor.html, index.html, cobot.html
│   │   ├── parser_dsl/      # DSL models, internal/external generators
│   │   ├── pipeline/        # csv_writer, dsl_runner, schema
│   │   └── output/          # Generated CSV and DSL files
│   ├── Dockerfile
│   └── requirements.txt
│
├── extractor_pipeline/      # LLM pipeline (requires NVIDIA GPU)
│   ├── src/
│   │   ├── main.py
│   │   ├── blueprints/api.py
│   │   ├── models/llm.py    # LLM wrapper (Qwen, Gemma, ...)
│   │   ├── pipeline/        # extractor, runner, validator, refiner
│   │   ├── document_processor/
│   │   ├── examples/        # few-shot examples for the prompt
│   │   ├── config/          # config.yaml (model, device, etc.)
│   │   └── input_files/     # documents to extract (optional)
│   ├── Dockerfile
│   └── requirements.txt
│
├── cobot/                   # Cobot API server (Franka) — not tracked by git
│   ├── app/routes/          # robot.py, gripper.py
│   ├── Dockerfile
│   └── docker-compose.yml   # for standalone use with network_mode: host (FCI)
│
└── docker-compose.yml
```

---

## Services

| Service     | Port | Description                                  |
|-------------|------|----------------------------------------------|
| `ui`        | 8000 | Editor, DSL generation, Cobot page           |
| `extractor` | 8001 | LLM extraction (requires NVIDIA GPU)         |
| `cobot`     | 5001 | Franka robot API (requires `./cobot/`)       |

### Available configurations

```bash
# Everything (default): UI + Extractor + Cobot
docker compose up --build

# UI + Extractor (without cobot)
docker compose up ui extractor --build

# UI only (no GPU — for editing already-extracted CSV and DSL)
docker compose up ui --no-deps --build

# UI + Cobot only (no GPU)
docker compose up ui cobot --no-deps --build
```

> **Cobot note:** the `./cobot/` folder is not tracked by git. From the root of `Procedure_DSL/`, run:
> ```bash
> git clone --filter=blob:none --sparse https://github.com/MizuNoMashu/cobot-assembly-components
> cd cobot-assembly-components && git sparse-checkout set cobot
> mv cobot ../cobot && cd .. && rm -rf cobot-assembly-components
> ```
> If the cobot Docker build fails during the `cmake --build` steps (OOM or compiler crash), edit `cobot/Dockerfile` and change `-j$(nproc)` to `-j1` on the failing step.
>
> For use with the real Franka robot via FCI, start the cobot standalone:
> ```bash
> cd cobot && docker compose up --build
> ```

---

## Cobot Integration

The cobot component exposes a REST API to control the Franka robot arm during assembly procedures. For installation, configuration, and API reference, see the [cobot-assembly-components](https://github.com/MizuNoMashu/cobot-assembly-components) repository.

---

## Pipeline

```
Document (PDF/DOCX/TXT)
        │
        ▼
  [extractor:8001]  ←── local LLM (GPU)
  /extract-csv
        │  returns CSV as JSON string
        ▼
   [ui:8000]        ←── saves CSV to output/
  /editor
        │  manual step editing
        ▼
  /generate-dsl     ←── parser_dsl (pure Python, no GPU)
        │
        ▼
  output/*.yml      ← External DSL (YAML)
  output/*.txt      ← Internal DSL
```

---

## CSV Format

Each assembly step has the following fields:

| Field            | Format                                       |
|------------------|----------------------------------------------|
| COMPONENT        | Part name (e.g. `Screw 1`)                   |
| COMPONENT DETAIL | `Key = Value; Key = Value;`                  |
| ACTION           | `Place` / `Insert` / `Screw in` / `Connect` / `Solder` / `Apply` / `Remove` |
| APPLIED TO       | `Component;` or `Component.Feature;`         |
| ORIENTATION      | `CurrentPart = OtherComponent;` or `CurrentPart = OtherComponent.Detail;` |
| TOOL             | Tool name                                    |
| TOOL DETAIL      | `Key = Value; Key = Value;`                  |
| ASSEMBLY DETAIL  | Notes, warnings, additional instructions     |

---

## LLM Configuration

Edit `extractor_pipeline/src/config/config.yaml`:

```yaml
device: cuda
llm:
  model: google/gemma-4-E4B-it   # any HuggingFace model
  max_tokens: 4096
```

The HuggingFace model cache is persisted in `extractor_pipeline/src/models/cache/`.
