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
├── moveit_api/               # MoveIt 2 planner for the Franka arm (planning only, see below)
│   ├── moveit_client/        # srdf.py (SRDF discovery), interface.py (rclpy client)
│   ├── routes.py              # /moveit/* blueprint
│   ├── app.py
│   └── Dockerfile
│
└── docker-compose.yml
```

---

## Services

| Service     | Port | Description                                  |
|-------------|------|----------------------------------------------|
| `ui`        | 8000 | Editor, DSL generation, Cobot page           |
| `extractor` | 8001 | LLM extraction (requires NVIDIA GPU)         |
| `cobot`     | 5001 | Franka robot API — actuates the arm (requires `./cobot/`) |
| `moveit`    | 5002 | MoveIt 2 motion **planner** for the Franka arm (plans only, never actuates) |

### Available configurations

```bash
# Everything (default): UI + Extractor + Cobot + MoveIt
docker compose up --build

# UI + Extractor (without cobot/moveit)
docker compose up ui extractor --build

# UI only (no GPU — for editing already-extracted CSV and DSL)
docker compose up ui --no-deps --build

# UI + Cobot only (no GPU)
docker compose up ui cobot --no-deps --build

# Just the MoveIt planner
docker compose up moveit --no-deps --build

# UI + cobot + MoveIt
docker compose up ui cobot moveit --no-deps --build
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

## MoveIt Integration (planner) + Cobot (actuator)

`moveit_api` and `cobot` split planning and actuation into two separate services:

- **`cobot`** is the only service that actually moves the robot. It holds the
  live FCI connection (`pylibfranka`) — connect/disconnect and current state
  are managed exactly as before, via the UI.
- **`moveit_api`** only *plans*: given a joint/named/pose goal, it asks
  MoveIt 2's `move_group` (collision checking + IK + OMPL) for a
  collision-free trajectory and returns it as JSON. It never sends anything
  to the robot, real or simulated — see [moveit_api/README.md](moveit_api/README.md)
  for the full API and why (`moveit_py` was ruled out because
  `franka_fr3_moveit_config` builds its MoveIt config by hand, not via
  `MoveItConfigsBuilder`).

Typical flow to move the arm using a MoveIt-planned, collision-free path:

```
1. GET  cobot:5001/api/robot/state              → real current joint positions
2. POST moveit:5002/moveit/plan-pose (or plan-joint/plan-named)
       body includes "start_joint_positions" = state from step 1
       → returns trajectory.points (collision-free waypoints)
3. POST cobot:5001/api/motion/execute-trajectory
       body: {"waypoints": [p.positions for p in trajectory.points]}
       → cobot executes each waypoint in sequence via pylibfranka
```

`moveit_api`'s own `move_group` runs against a **simulated** robot state when
`USE_FAKE_HARDWARE=true` (the default), so it has no idea where the real arm
actually is unless step 1's state is passed in as `start_joint_positions`.

This flow is wired into the UI: the **Cobot page** (`/cobot`) has a "MoveIt
Plan → Execute (cartesian pose)" panel — enter X/Y/Z and roll/pitch/yaw
(sliders), hit **Plan** (proxies to `moveit_api` via `ui_dsl`'s
`/moveit-proxy/*`, mirroring the existing `/cobot-proxy/*`), inspect the
result, then **Execute on Cobot** to actually run it (with a confirm dialog,
since this really moves the robot). The panel assumes joint order
`fr3_joint1..7`, same as everywhere else this repo talks to the Franka arm.

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
