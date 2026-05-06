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
│   │   ├── templates/       # editor.html, index.html
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
└── docker-compose.yml
```

---

## Avvio

```bash
# Entrambi i servizi
docker compose up --build

# Solo UI (senza GPU, per editare CSV già estratti)
docker compose up ui --no-deps --build
```

| Servizio   | Porta | Descrizione                        |
|------------|-------|------------------------------------|
| ui         | 8000  | Editor, generazione DSL            |
| extractor  | 8001  | Estrazione LLM (interno alla rete) |

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
