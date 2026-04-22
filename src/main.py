from flask import Flask, jsonify, render_template
from flask_cors import CORS
import yaml
from pathlib import Path

app = Flask(__name__, template_folder='templates')
CORS(app)


def load_config():
    for config_path in [
        Path("/app/src/config/config.yaml"),
        Path(__file__).parent / "config" / "config.yaml",
    ]:
        if config_path.exists():
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
    print("⚠️  Configuration file not found, using defaults")
    return {}


config = load_config()
app.config['PIPELINE_CONFIG'] = config
app.config['RAG_CONFIG'] = config   # kept for llm.py / chunker.py compatibility


def print_startup_banner():
    print("=" * 60)
    print("Procedure Extraction Pipeline")
    print("=" * 60)
    if config:
        print("✅ Configuration loaded")
        print(f"   Device : {config.get('device', 'cpu')}")
        print(f"   LLM    : {config.get('llm', {}).get('model', 'unknown')}")
    print("\nEndpoints:")
    print("   GET  /               Web UI")
    print("   GET  /health         Health check")
    print("   POST /extract        Extract steps → JSON")
    print("   POST /extract-csv    Extract steps → CSV")
    print("\n⚠️  LLM loads on first request (may take several minutes)")
    print("Server: http://0.0.0.0:8000")
    print("=" * 60)


from blueprints.api import api_bp
app.register_blueprint(api_bp)


@app.route('/')
def index():
    return render_template('index.html')


if __name__ == "__main__":
    print_startup_banner()
    app.run(host="0.0.0.0", port=8000, debug=True, use_reloader=True)
