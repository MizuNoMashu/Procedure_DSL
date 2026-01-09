# src/rag/pipeline.py
"""
Complete RAG (Retrieval-Augmented Generation) pipeline.
"""

from typing import Dict, Any, List
from flask import current_app

from vectorstore.chroma_store import vector_store
from models.llm import language_model

class RAGPipeline:
    """Complete RAG pipeline"""
    
    def __init__(self):
        self.vector_store = vector_store
        self.llm = language_model
    
    def query(
        self, 
        question: str, 
        top_k: int = None,
        max_tokens: int = None,
        temperature: float = 0.7,
        include_sources: bool = True
    ) -> Dict[str, Any]:
        """
        Execute RAG query.
        
        Args:
            question: User question
            top_k: Number of documents to retrieve (None = use config)
            max_tokens: Max tokens to generate (None = use config)
            temperature: Generation temperature
            include_sources: Include source documents in response
        
        Returns:
            Dict with answer and metadata
        """
        config = current_app.config['RAG_CONFIG']
        top_k = top_k or config['retrieval']['top_k']
        
        # Step 1: Retrieve relevant documents
        print(f"🔍 Searching for: {question}")
        search_results = self.vector_store.search(question, top_k=top_k)
        
        retrieved_docs = search_results['results']
        print(f"📄 Retrieved {len(retrieved_docs)} documents")
        
        # Step 2: Build context from retrieved documents
        context = self._build_context(retrieved_docs)
        
        # Step 3: Build prompt with context
        prompt = self._build_prompt(question, context)
        
        # Step 4: Generate answer
        print(f"🤖 Generating answer...")
        answer = self.llm.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        # Step 5: Build response
        response = {
            "question": question,
            "answer": answer,
            "model": self.llm.model_name,
            "num_sources": len(retrieved_docs)
        }
        
        if include_sources:
            response["sources"] = [
                {
                    "text": doc['text'],
                    "metadata": doc['metadata'],
                    "relevance_score": 1 - doc['distance'] if doc['distance'] else None
                }
                for doc in retrieved_docs
            ]
        
        return response
    
    def _build_context(self, documents: List[Dict]) -> str:
        """
        Build context string from retrieved documents.
        
        Args:
            documents: List of retrieved document dicts
        
        Returns:
            Formatted context string
        """
        if not documents:
            return "No relevant documents found."
        
        context_parts = []
        
        for i, doc in enumerate(documents, 1):
            context_parts.append(f"[Document {i}]")
            context_parts.append(doc['text'])
            context_parts.append("")  # Empty line between docs
        
        return "\n".join(context_parts)
    
    def _build_prompt(self, question: str, context: str) -> str:
        """Build prompt for LLM with context"""
        
        prompt = f"""You are a precise assistant. Answer the question using ONLY the information from the context below.

        CONTEXT:
        {context}

        QUESTION: {question}

        INSTRUCTIONS:
        - Answer based ONLY on the context above
        - If the context doesn't contain the answer, say "I don't have enough information to answer this question."
        - Be concise and accurate
        - Quote relevant parts from context when possible

        ANSWER:"""
        
        return prompt
    
    def chat_with_context(
        self,
        messages: List[Dict],
        top_k: int = None,
        max_tokens: int = None,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Chat with RAG context.
        
        Args:
            messages: Chat messages (last one should be user question)
            top_k: Documents to retrieve
            max_tokens: Max tokens
            temperature: Temperature
        
        Returns:
            Response dict
        """
        config = current_app.config['RAG_CONFIG']
        top_k = top_k or config['retrieval']['top_k']
        
        # Extract last user message as query
        last_user_message = None
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                last_user_message = msg.get('content')
                break
        
        if not last_user_message:
            return {"error": "No user message found"}
        
        # Retrieve context
        search_results = self.vector_store.search(last_user_message, top_k=top_k)
        retrieved_docs = search_results['results']
        context = self._build_context(retrieved_docs)
        
        # Add context to system message
        enhanced_messages = [
            {
                "role": "system",
                "content": f"You are a helpful assistant. Use the following context to answer questions:\n\n{context}"
            }
        ] + messages
        
        # Generate response
        answer = self.llm.chat(
            messages=enhanced_messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        return {
            "messages": messages,
            "answer": answer,
            "num_sources": len(retrieved_docs),
            "sources": [doc['text'][:100] + "..." for doc in retrieved_docs[:3]]
        }

# Global instance
rag_pipeline = RAGPipeline()