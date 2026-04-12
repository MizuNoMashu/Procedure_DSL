from sentence_transformers import SentenceTransformer
import torch
from flask import current_app

from numpy import dot
from numpy.linalg import norm

class EmbeddingModel:
    """Wrapper per modello embeddings"""
    
    def __init__(self):
        self.model = None
        self.device = None
    
    def load(self):
        """Carica modello da config"""
        config = current_app.config['RAG_CONFIG']
        
        model_name = config['embeddings']['model']
        device = config['device']
        
        print(f"📥 Loading embedding model: {model_name}")
        print(f"   Device: {device}")
        
        # Carica modello
        self.model = SentenceTransformer(model_name)
        
        # Sposta su device appropriato
        self.device = device
        self.model = self.model.to(device)
        
        print(f"✅ Embedding model loaded")
        
        return self
    
    def encode(self, texts, batch_size=32):
        """
        Crea embeddings per uno o più testi.
        
        Args:
            texts: str o List[str]
            batch_size: int
        
        Returns:
            numpy array con embeddings
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        
        # Se è una singola stringa, metti in lista
        if isinstance(texts, str):
            texts = [texts]
        
        # Genera embeddings (normalize_embeddings=True migliora BGE e cosine similarity)
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True
        )
        
        return embeddings
    
    def get_dimension(self):
        """Ritorna dimensione embeddings"""
        if self.model is None:
            return None
        return self.model.get_sentence_embedding_dimension()
    
    def similarity(self, text1, text2):
        """
        Calcola similarità tra due testi.
        
        Returns:
            float tra -1 e 1 (cosine similarity)
        """
        emb1 = self.encode(text1)
        emb2 = self.encode(text2)
        
        # Cosine similarity
        similarity = dot(emb1[0], emb2[0]) / (norm(emb1[0]) * norm(emb2[0]))
        
        return float(similarity)

# Istanza globale
embedding_model = EmbeddingModel()