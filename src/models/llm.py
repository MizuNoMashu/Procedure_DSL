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
        
        # Carica tokenizer (usa HF_HOME come cache, allineato al volume Docker)
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name
        )

        # Carica modello in float16
        # device_map="auto" funziona solo con CUDA, non con MPS o CPU
        if self.device == "cuda":
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                dtype=torch.float16,
                device_map="auto",
                low_cpu_mem_usage=True
            )
        else:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                dtype=torch.float16,
                low_cpu_mem_usage=True
            )
            self.model = self.model.to(self.device)

        # Crea pipeline per generazione
        pipeline_device = {"cuda": 0, "mps": "mps", "cpu": -1}.get(self.device, -1)
        self.pipeline = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            device=pipeline_device
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
            pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id
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
        Formatta messaggi usando il chat template del tokenizer se disponibile
        (es. Qwen2.5, TinyLlama, ecc.), altrimenti fallback semplice.
        """
        if getattr(self.tokenizer, 'chat_template', None):
            return self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )

        # Fallback generico
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