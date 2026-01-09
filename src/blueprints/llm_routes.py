# src/api/llm_routes.py
from flask import Blueprint, jsonify, request, current_app
from models.llm import language_model

llm_bp = Blueprint('llm', __name__)

def ensure_llm_loaded():
    """Assicura che LLM sia caricato"""
    if language_model.model is None:
        with current_app.app_context():
            language_model.load()

@llm_bp.route('/llm-info', methods=['GET'])
def llm_info():
    """Info sul modello LLM"""
    return jsonify(language_model.get_info())

@llm_bp.route('/generate', methods=['POST'])
def generate():
    """
    Genera testo da prompt.
    
    Body JSON:
    {
        "prompt": "your prompt here",
        "max_tokens": 512,      # optional
        "temperature": 0.7      # optional
    }
    """
    # Carica LLM se necessario
    ensure_llm_loaded()
    
    data = request.get_json()
    
    if not data or 'prompt' not in data:
        return jsonify({"error": "Missing 'prompt'"}), 400
    
    prompt = data['prompt']
    max_tokens = data.get('max_tokens')
    temperature = data.get('temperature', 0.7)
    
    try:
        response = language_model.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        return jsonify({
            "prompt": prompt,
            "response": response,
            "model": language_model.model_name
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@llm_bp.route('/chat', methods=['POST'])
def chat():
    """
    Chat-style generation.
    
    Body JSON:
    {
        "messages": [
            {"role": "user", "content": "Hello!"}
        ],
        "max_tokens": 512,
        "temperature": 0.7
    }
    """
    # Carica LLM se necessario
    ensure_llm_loaded()
    
    data = request.get_json()
    
    if not data or 'messages' not in data:
        return jsonify({"error": "Missing 'messages'"}), 400
    
    messages = data['messages']
    max_tokens = data.get('max_tokens')
    temperature = data.get('temperature', 0.7)
    
    try:
        response = language_model.chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        return jsonify({
            "messages": messages,
            "response": response,
            "model": language_model.model_name
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500