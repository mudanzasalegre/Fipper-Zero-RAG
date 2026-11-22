from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    db_path: Path = Path(os.getenv("RAG_DB_PATH", "./data/flipper_rag.sqlite3"))
    ollama_url: str = os.getenv("RAG_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    chat_model: str = os.getenv("RAG_CHAT_MODEL", "qwen2.5:7b")
    embed_model: str = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
    embed_provider: str = os.getenv("RAG_EMBED_PROVIDER", "ollama").lower()
    chat_provider: str = os.getenv("RAG_CHAT_PROVIDER", "ollama").lower()
    top_k: int = int(os.getenv("RAG_TOP_K", "6"))
    max_context_chars: int = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "12000"))
    openai_base_url: str = os.getenv("RAG_OPENAI_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
    openai_model: str = os.getenv("RAG_OPENAI_MODEL", "local-model")
    openai_api_key: str = os.getenv("RAG_OPENAI_API_KEY", "local")
