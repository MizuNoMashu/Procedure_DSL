# src/models/llm.py
"""
Large Language Model loader and inference.
"""

from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
import torch
from flask import current_app

class LanguageModel:
    """Wrapper per LLM"""
    
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.pipeline = None
        self.device = None
        self.model_name = None
    
    def load(self):
        """Carica modello da config"""
        config = current_app.config['RAG_CONFIG']
        
        self.model_name = config['llm']['model']
        self.device = config['device']
        
        print(f"📥 Loading LLM: {self.model_name}")
        print(f"   Device: {self.device}")
        print(f"   This may take a few minutes...")
        
        # Carica tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            cache_dir="/app/models/cache"
        )
        
        # Carica modello
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            cache_dir="/app/models/cache",
            dtype=torch.float16 if self.device != "cpu" else torch.float32,
            device_map="auto" if self.device != "cpu" else None,
            low_cpu_mem_usage=True
        )
        
        # Se CPU, metti modello su CPU esplicitamente
        if self.device == "cpu":
            self.model = self.model.to("cpu")
        
        # Crea pipeline per generazione
        self.pipeline = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            device=0 if self.device == "cuda" else -1  # 0 per GPU, -1 per CPU
        )
        
        print(f"✅ LLM loaded successfully")
        
        return self
    
    def generate(self, prompt: str, max_tokens: int = None, temperature: float = 0.7) -> str:
        """
        Genera testo da prompt.
        
        Args:
            prompt: Input prompt
            max_tokens: Max tokens da generare (None = usa config)
            temperature: Temperature (0-1, più alto = più creativo)
        
        Returns:
            Generated text
        """
        if self.pipeline is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        
        config = current_app.config['RAG_CONFIG']
        max_tokens = max_tokens or config['llm']['max_tokens']
        
        # Genera
        result = self.pipeline(
            prompt,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=True,
            top_p=0.95,
            num_return_sequences=1,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.pad_token_id
        )
        
        # Estrai testo generato
        generated_text = result[0]['generated_text']
        
        # Rimuovi il prompt dall'output (vogliamo solo la risposta)
        if generated_text.startswith(prompt):
            generated_text = generated_text[len(prompt):].strip()
        
        return generated_text
    
    def chat(self, messages: list, max_tokens: int = None, temperature: float = 0.7) -> str:
        """
        Chat-style generation.
        
        Args:
            messages: List of dicts [{"role": "user", "content": "..."}]
            max_tokens: Max tokens
            temperature: Temperature
        
        Returns:
            Generated response
        """
        # Formatta messages in prompt
        prompt = self._format_chat_prompt(messages)
        
        return self.generate(prompt, max_tokens, temperature)
    
    def _format_chat_prompt(self, messages: list) -> str:
        """
        Formatta messaggi chat in prompt.
        
        Formato semplice:
        User: [message]
        Assistant: [response]
        """
        prompt_parts = []
        
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            
            if role == 'user':
                prompt_parts.append(f"User: {content}")
            elif role == 'assistant':
                prompt_parts.append(f"Assistant: {content}")
            elif role == 'system':
                prompt_parts.append(f"System: {content}")
        
        # Aggiungi "Assistant:" alla fine per far iniziare la generazione
        prompt_parts.append("Assistant:")
        
        return "\n".join(prompt_parts)
    
    def get_info(self) -> dict:
        """Info sul modello"""
        if self.model is None:
            return {"loaded": False}
        
        return {
            "loaded": True,
            "model_name": self.model_name,
            "device": self.device,
            "parameters": sum(p.numel() for p in self.model.parameters()) / 1e9  # in billions
        }

# Global instance
language_model = LanguageModel()