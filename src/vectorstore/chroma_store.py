# src/vectorstore/chroma_store.py
"""
ChromaDB vector store for embeddings.
"""

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any
from flask import current_app
from models.embeddings import embedding_model

class VectorStore:
    """Wrapper for ChromaDB vector store"""
    
    def __init__(self):
        self.client = None
        self.collection = None
        self.collection_name = "documents"
    
    def initialize(self, persist_directory: str = "/app/src/vectorstore"):
        """
        Initialize ChromaDB client and collection.
        
        Args:
            persist_directory: Where to save the database
        """
        print(f"📦 Initializing vector store at {persist_directory}")
        
        # Create ChromaDB client (API v1.x)
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False)
        )

        # Get or create collection with cosine similarity
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={
                "description": "RAG document embeddings",
                "hnsw:space": "cosine"
            }
        )
        
        print(f"✅ Vector store initialized")
        print(f"   Collection: {self.collection_name}")
        print(f"   Documents: {self.collection.count()}")
        
        return self
    
    def add_texts(self, texts: List[str], metadatas: List[Dict] = None, ids: List[str] = None):
        """
        Add texts to vector store.
        
        Args:
            texts: List of text chunks
            metadatas: Optional list of metadata dicts
            ids: Optional list of IDs (auto-generated if None)
        
        Returns:
            List of IDs
        """
        if self.collection is None:
            raise RuntimeError("Vector store not initialized")
        
        # Generate IDs if not provided
        if ids is None:
            existing_count = self.collection.count()
            ids = [f"doc_{existing_count + i}" for i in range(len(texts))]
        
        # Generate embeddings
        print(f"🔢 Generating embeddings for {len(texts)} texts...")
        embeddings = embedding_model.encode(texts)
        embeddings_list = embeddings.tolist()
        
        # Add to collection
        self.collection.add(
            embeddings=embeddings_list,
            documents=texts,
            metadatas=metadatas or [{} for _ in texts],
            ids=ids
        )
        
        print(f"✅ Added {len(texts)} documents to vector store")
        
        return ids
    
    def search(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """
        Search for similar documents.
        
        Args:
            query: Search query
            top_k: Number of results to return
        
        Returns:
            Dict with results
        """
        if self.collection is None:
            raise RuntimeError("Vector store not initialized")
        
        # Generate query embedding
        query_embedding = embedding_model.encode([query])
        
        # Search
        results = self.collection.query(
            query_embeddings=query_embedding.tolist(),
            n_results=top_k
        )
        
        # Format results
        formatted_results = []
        
        if results['ids'] and len(results['ids'][0]) > 0:
            for i in range(len(results['ids'][0])):
                formatted_results.append({
                    'id': results['ids'][0][i],
                    'text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i] if 'distances' in results else None
                })
        
        return {
            'query': query,
            'results': formatted_results,
            'count': len(formatted_results)
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics"""
        if self.collection is None:
            return {"initialized": False}
        
        return {
            "initialized": True,
            "collection_name": self.collection_name,
            "total_documents": self.collection.count(),
            "embedding_dimension": embedding_model.get_dimension()
        }
    
    def clear(self):
        """Clear all documents from vector store"""
        if self.collection is None:
            raise RuntimeError("Vector store not initialized")
        
        # Delete collection and recreate
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "RAG document embeddings"}
        )
        
        print(f"🗑️  Vector store cleared")

# Global instance
vector_store = VectorStore()