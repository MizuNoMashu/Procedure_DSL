from flask import Blueprint, jsonify, current_app, request
from models.embeddings import embedding_model

test_bp = Blueprint('test', __name__)

@test_bp.route('/test')
def test():
    config = current_app.config.get('RAG_CONFIG')
    
    return jsonify({
        'message': 'Test blueprint working', 
        'status': 'success', 
        'config_loaded': config is not None
    })

@test_bp.route('/config')
def get_config():
    config = current_app.config.get('RAG_CONFIG')
    return jsonify({
        "device": config['device'],
        "embedding_model": config['embeddings']['model'],
        "embedding_dimension": embedding_model.get_dimension(),
        "model_loaded": embedding_model.model is not None
    })

@test_bp.route('/embed', methods=['POST'])
def embed():
    """
    Crea embedding per un testo.
    
    Body JSON:
    {
        "text": "your text here"
    }
    """
    data = request.get_json()
    
    if not data or 'text' not in data:
        return jsonify({"error": "Missing 'text' in request"}), 400
    
    text = data['text']
    
    # Genera embedding
    embedding = embedding_model.encode(text)
    
    return jsonify({
        "text": text,
        "embedding": embedding[0].tolist(),  # Converti numpy a list
        "dimension": len(embedding[0])
    })

@test_bp.route('/similarity', methods=['POST'])
def similarity():
    """
    Calcola similarità tra due testi.
    
    Body JSON:
    {
        "text1": "first text",
        "text2": "second text"
    }
    """
    data = request.get_json()
    
    if not data or 'text1' not in data or 'text2' not in data:
        return jsonify({"error": "Missing 'text1' or 'text2'"}), 400
    
    text1 = data['text1']
    text2 = data['text2']
    
    # Calcola similarità
    score = embedding_model.similarity(text1, text2)
    
    return jsonify({
        "text1": text1,
        "text2": text2,
        "similarity": score,
        "interpretation": get_similarity_interpretation(score)
    })

def get_similarity_interpretation(score):
    """Interpreta score di similarità"""
    if score > 0.8:
        return "Very similar"
    elif score > 0.6:
        return "Similar"
    elif score > 0.4:
        return "Somewhat similar"
    elif score > 0.2:
        return "Somewhat different"
    else:
        return "Very different"