from flask import Flask
from flask_cors import CORS
import yaml
from pathlib import Path

app = Flask(__name__)
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
app.config['RAG_CONFIG'] = config


from blueprints.api import api_bp
app.register_blueprint(api_bp)


if __name__ == "__main__":
    print("=" * 50)
    print("LLM Extraction Service — port 8001")
    if config:
        print(f"   Device : {config.get('device', 'cpu')}")
        print(f"   LLM    : {config.get('llm', {}).get('model', 'unknown')}")
    print("⚠️  Model loads on first /extract-csv request")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8001, debug=False)
