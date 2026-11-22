"""Dependency-light Ollama embedding and chat; OpenAI-compatible chat optional."""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from .config import Settings

class ModelUnavailable(RuntimeError):
    pass


def _post(url: str, payload: dict, headers: dict | None = None, timeout: int = 90) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        raise ModelUnavailable(f"Error al conectar con {url}: {exc}") from exc

class Embedder:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def active(self) -> bool:
        return self.settings.embed_provider in {"ollama", "openai"}

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.settings.embed_provider == "none":
            return []
        if self.settings.embed_provider == "ollama":
            out = _post(self.settings.ollama_url + "/api/embed",
                        {"model": self.settings.embed_model, "input": texts}, timeout=180)
            vectors = out.get("embeddings", [])
        elif self.settings.embed_provider == "openai":
            out = _post(self.settings.openai_base_url + "/embeddings",
                        {"model": self.settings.embed_model, "input": texts},
                        {"Authorization": "Bearer " + self.settings.openai_api_key}, timeout=180)
            entries = sorted(out.get("data", []), key=lambda entry: entry.get("index", 0))
            vectors = [entry.get("embedding", []) for entry in entries]
        else:
            raise ValueError("RAG_EMBED_PROVIDER must be ollama, openai, or none")
        if len(vectors) != len(texts) or not all(isinstance(v, list) and v for v in vectors):
            raise ModelUnavailable("Ollama did not return one embedding per input")
        return vectors

class ChatModel:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, system: str, prompt: str) -> str:
        provider = self.settings.chat_provider
        if provider == "none":
            raise ModelUnavailable("RAG_CHAT_PROVIDER=none")
        if provider == "ollama":
            result = _post(self.settings.ollama_url + "/api/chat",
                           {"model": self.settings.chat_model,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": prompt}],
                            "stream": False, "options": {"temperature": 0.1}}, timeout=240)
            return (result.get("message") or {}).get("content", "").strip()
        if provider == "openai":
            result = _post(self.settings.openai_base_url + "/chat/completions",
                           {"model": self.settings.openai_model,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": prompt}],
                            "temperature": 0.1},
                           {"Authorization": "Bearer " + self.settings.openai_api_key}, timeout=240)
            choices = result.get("choices") or []
            return (choices[0].get("message", {}).get("content") or "").strip() if choices else ""
        raise ValueError("RAG_CHAT_PROVIDER must be ollama, openai, or none")
