# Procedure DSL

Estrazione automatica di step di assemblaggio da documenti tecnici (PDF, DOCX, TXT) tramite LLM locale, editing manuale, e generazione di DSL interno/esterno.

---

## Struttura

```
Procedure_DSL/
├── ui_dsl/                  # Interfaccia web + parser DSL (qualsiasi OS)
│   ├── src/
│   │   ├── main.py
│   │   ├── blueprints/api_ui.py
│   │   ├── templates/       # editor.html, index.html, cobot.html
│   │   ├── parser_dsl/      # modelli DSL, generatori interno/esterno
│   │   ├── pipeline/        # csv_writer, dsl_runner, schema
│   │   └── output/          # CSV e DSL generati
│   ├── Dockerfile
│   └── requirements.txt
│
├── extractor_pipeline/      # Pipeline LLM (richiede NVIDIA GPU)
│   ├── src/
│   │   ├── main.py
│   │   ├── blueprints/api.py
│   │   ├── models/llm.py    # wrapper LLM (Qwen, Gemma, ...)
│   │   ├── pipeline/        # extractor, runner, validator, refiner
│   │   ├── document_processor/
│   │   ├── examples/        # few-shot examples per il prompt
│   │   ├── config/          # config.yaml (modello, device, ecc.)
│   │   └── input_files/     # documenti da estrarre (opzionale)
│   ├── Dockerfile
│   └── requirements.txt
│
├── cobot/                   # Cobot API server (Franka) — non tracciato da git
│   ├── app/routes/          # robot.py, gripper.py
│   ├── Dockerfile
│   └── docker-compose.yml   # per uso standalone con network_mode: host (FCI)
│
└── docker-compose.yml
```

---

## Avvio

| Servizio    | Porta | Descrizione                              |
|-------------|-------|------------------------------------------|
| `ui`        | 8000  | Editor, generazione DSL, pagina Cobot    |
| `extractor` | 8001  | Estrazione LLM (richiede NVIDIA GPU)     |
| `cobot`     | 5001  | API robot Franka (richiede `./cobot/`)   |

### Configurazioni disponibili

```bash
# Tutto (default): UI + Extractor + Cobot
docker compose up --build

# UI + Extractor (senza cobot)
docker compose up ui extractor --build

# Solo UI (no GPU — per editing CSV e DSL già estratti)
docker compose up ui --no-deps --build

# Solo UI + Cobot (no GPU)
docker compose up ui cobot --no-deps --build
```

> **Nota cobot:** la cartella `./cobot/` non è tracciata da git e va copiata manualmente.
> Per uso con il robot Franka reale via FCI, avviare il cobot standalone:
> ```bash
> cd cobot && docker compose up --build
> ```

---

## Flusso

```
Documento (PDF/DOCX/TXT)
        │
        ▼
  [extractor:8001]  ←── LLM locale (GPU)
  /extract-csv
        │  restituisce CSV come stringa JSON
        ▼
   [ui:8000]        ←── salva CSV in output/
  /editor
        │  editing manuale degli step
        ▼
  /generate-dsl     ←── parser_dsl (puro Python, no GPU)
        │
        ▼
  output/*.yml      ← External DSL (YAML)
  output/*.txt      ← Internal DSL
```

---

## Formato CSV

Ogni step di assemblaggio ha i campi:

| Campo            | Formato                                      |
|------------------|----------------------------------------------|
| COMPONENT        | Nome parte (es. `Screw 1`)                   |
| COMPONENT DETAIL | `Key = Value; Key = Value;`                  |
| ACTION           | `Place` / `Insert` / `Screw in` / `Connect` / `Solder` / `Apply` / `Remove` |
| APPLIED TO       | `Componente;` o `Componente.Caratteristica;` |
| ORIENTATION      | `ParteCorrente = AltroComponente;` o `ParteCorrente = AltroComponente.Dettaglio;` |
| TOOL             | Nome utensile                                |
| TOOL DETAIL      | `Key = Value; Key = Value;`                  |
| ASSEMBLY DETAIL  | Note, avvertenze, istruzioni aggiuntive      |

---

## Configurazione LLM

Modifica `extractor_pipeline/src/config/config.yaml`:

```yaml
device: cuda
llm:
  model: google/gemma-4-E4B-it   # qualsiasi modello HuggingFace
  max_tokens: 4096
```

La cache dei modelli HuggingFace è persistita in `extractor_pipeline/src/models/cache/`.
