# src/models/llm.py
"""
Large Language Model loader and inference.
Supports both AutoTokenizer-based models (Qwen, Phi, ...)
and AutoProcessor-based models (Gemma 4 style).
"""

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, AutoModelForImageTextToText
from flask import current_app
torch.cuda.empty_cache()


class LanguageModel:
    """Wrapper per LLM"""

    def __init__(self):
        self.model = None
        self.tokenizer = None   # può essere AutoTokenizer o AutoProcessor
        self.device = None
        self.model_name = None
        self._uses_processor = False  # True per modelli Gemma 4 style

    def _supports_flash_attn(self) -> bool:
        """Check if flash attention 2 is available."""
        try:
            import flash_attn
            return True
        except ImportError:
            return False

    def load(self):
        """Carica modello da config"""
        config = current_app.config['RAG_CONFIG']

        self.model_name = config['llm']['model']
        self.device = config['device']

        print(f"📥 Loading LLM: {self.model_name}")
        print(f"   Device: {self.device}")
        print(f"   This may take a few minutes...")

        # Prova prima AutoProcessor (Gemma 4 style), fallback su AutoTokenizer
        try:
            from transformers import AutoProcessor
            self.tokenizer = AutoProcessor.from_pretrained(self.model_name)
            self._uses_processor = True
            print("   Loader: AutoProcessor")
        except Exception:
            # Fix per Gemma: extra_special_tokens deve essere un dict, non una lista
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                extra_special_tokens={}
            )
            self._uses_processor = False
            print("   Loader: AutoTokenizer")

        if self.device == "cuda":
            # Carica con bfloat16 e CPU offloading automatico se necessario
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                dtype="auto",
                device_map="auto",  # Distribuisce automaticamente tra GPU e CPU
                low_cpu_mem_usage=True,
            )
            print("   Using device_map='auto' (GPU + CPU offloading if needed)")
        else:
            dtype = torch.float16
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                dtype="auto",
                low_cpu_mem_usage=True,
            )
            self.model = self.model.to(self.device)

        print("✅ LLM loaded successfully")
        return self

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, messages: list, max_tokens: int = None, temperature: float = 0.7,
             json_schema: str = None) -> str:
        """
        Chat-style generation.
        messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
        json_schema: optional JSON Schema string for constrained decoding via lm-format-enforcer.
                     Ignored if the library is not installed or _uses_processor is True.
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        config = current_app.config['RAG_CONFIG']
        max_tokens = max_tokens or config['llm']['max_tokens']

        prompt_text = self._apply_template(messages)

        if self._uses_processor:
            return self._generate_processor(prompt_text, max_tokens, temperature)
        else:
            return self._generate_tokenizer(prompt_text, max_tokens, temperature, json_schema)

    # kept for backward compat
    def generate(self, prompt: str, max_tokens: int = None, temperature: float = 0.7) -> str:
        config = current_app.config['RAG_CONFIG']
        max_tokens = max_tokens or config['llm']['max_tokens']
        if self._uses_processor:
            return self._generate_processor(prompt, max_tokens, temperature)
        else:
            return self._generate_tokenizer(prompt, max_tokens, temperature)

    def get_info(self) -> dict:
        if self.model is None:
            return {"loaded": False}
        return {
            "loaded": True,
            "model_name": self.model_name,
            "device": self.device,
            "parameters": sum(p.numel() for p in self.model.parameters()) / 1e9,
        }

    # ------------------------------------------------------------------
    # Internal: template formatting
    # ------------------------------------------------------------------

    def _apply_template(self, messages: list) -> str:
        """Applica il chat template, gestendo modelli senza ruolo 'system'."""
        has_template = getattr(self.tokenizer, 'chat_template', None) or \
                       hasattr(self.tokenizer, 'apply_chat_template')
        if not has_template:
            return self._fallback_template(messages)

        # Prova prima con enable_thinking=False (Gemma 4 style)
        for kwargs in [
            {"tokenize": False, "add_generation_prompt": True, "enable_thinking": False},
            {"tokenize": False, "add_generation_prompt": True},
        ]:
            try:
                return self.tokenizer.apply_chat_template(messages, **kwargs)
            except TypeError:
                continue  # parametro non supportato, riprova senza
            except Exception:
                break      # errore diverso (es. ruolo non supportato), gestisci sotto

        # Fallback: merge system nel primo user (per modelli senza ruolo system)
        merged = self._merge_system_into_user(messages)
        for kwargs in [
            {"tokenize": False, "add_generation_prompt": True, "enable_thinking": False},
            {"tokenize": False, "add_generation_prompt": True},
        ]:
            try:
                return self.tokenizer.apply_chat_template(merged, **kwargs)
            except TypeError:
                continue
            except Exception:
                break

        return self._fallback_template(messages)

    def _merge_system_into_user(self, messages: list) -> list:
        merged, system_text = [], ""
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg["content"]
            elif msg.get("role") == "user" and system_text:
                merged.append({"role": "user", "content": system_text + "\n\n" + msg["content"]})
                system_text = ""
            else:
                merged.append(msg)
        return merged

    def _fallback_template(self, messages: list) -> str:
        parts = []
        for msg in messages:
            role, content = msg.get("role", "user"), msg.get("content", "")
            if role == "system":
                parts.append(f"System: {content}")
            elif role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
        parts.append("Assistant:")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal: generation backends
    # ------------------------------------------------------------------

    def _generate_processor(self, prompt_text: str, max_tokens: int, temperature: float) -> str:
        """Generazione con AutoProcessor (Gemma 4 style)."""
        inputs = self.tokenizer(text=prompt_text, return_tensors="pt").to(self.model.device)
        input_len = inputs["input_ids"].shape[-1]

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=temperature > 0,
                temperature=temperature if temperature > 0 else 1.0,
                top_p=0.95,
            )

        # Check if parse_response exists AND is callable
        has_parse = hasattr(self.tokenizer, 'parse_response') and callable(getattr(self.tokenizer, 'parse_response', None))
        response = self.tokenizer.decode(
            outputs[0][input_len:],
            skip_special_tokens=True,
        )

        if has_parse:
            try:
                return self.tokenizer.parse_response(response)
            except (AttributeError, TypeError):
                pass  # Fallback to direct response
        return response.strip()

    def _generate_tokenizer(self, prompt_text: str, max_tokens: int, temperature: float,
                             json_schema: str = None) -> str:
        """Generazione con AutoTokenizer (Qwen, Phi, ecc.).
        Se json_schema è fornito e lm-format-enforcer è installato, usa constrained decoding
        per garantire output JSON valido senza bisogno di fallback parsing.
        """
        inputs = self.tokenizer(prompt_text, return_tensors="pt").to(self.model.device)
        input_len = inputs["input_ids"].shape[-1]

        eos_id = getattr(self.tokenizer, 'eos_token_id', None)
        pad_id = getattr(self.tokenizer, 'pad_token_id', None) or eos_id

        prefix_fn = None
        if json_schema is not None:
            try:
                from lmformatenforcer import JsonSchemaParser
                from lmformatenforcer.integrations.transformers import (
                    build_transformers_prefix_allowed_tokens_fn,
                )
                prefix_fn = build_transformers_prefix_allowed_tokens_fn(
                    self.tokenizer, JsonSchemaParser(json_schema)
                )
            except ImportError:
                pass  # library not installed — fall back to normal generation

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=temperature > 0,
                temperature=temperature if temperature > 0 else 1.0,
                top_p=0.95,
                eos_token_id=eos_id,
                pad_token_id=pad_id,
                prefix_allowed_tokens_fn=prefix_fn,
            )

        new_tokens = outputs[0][input_len:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


# Global instance
language_model = LanguageModel()
