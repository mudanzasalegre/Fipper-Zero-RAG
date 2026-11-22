"""Read-only, localhost-first FastAPI API. Never expose publicly without auth."""
from __future__ import annotations
from importlib.resources import files
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Literal
from .config import Settings
from .storage import Store
from .models import Embedder, ChatModel
from .retrieval import Retriever
from .service import RAGService

settings = Settings()
store = Store(settings.db_path)
retriever = Retriever(store, Embedder(settings))
service = RAGService(retriever, ChatModel(settings), settings)
app = FastAPI(title="Flipper Zero RAG", version="0.4.0", docs_url="/api/docs")


class Query(BaseModel):
    query: str = Field(min_length=2, max_length=3000)
    top_k: int = Field(default=6, ge=1, le=20)
    category: str | None = Field(default=None, max_length=80)
    mode: Literal["hybrid", "lexical", "semantic"] = "hybrid"
    trust: Literal["official", "community", "local"] | None = None
    source_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    expand: bool = True
    firmware_version: str | None = Field(default=None, max_length=32,
                                         pattern=r"^v?[0-9]+\.[0-9]+(\.[0-9]+)?(-rc(\.[0-9]+)?)?$")
    version_policy: Literal["strict", "include-unversioned"] = "include-unversioned"
    rerank: bool = False


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                                  "style-src 'self' 'unsafe-inline'; "
                                                  "connect-src 'self'; img-src 'self' data:; "
                                                  "object-src 'none'; base-uri 'none'; form-action 'self'")
    return response


@app.get("/", response_class=HTMLResponse)
def home():
    return files("flipper_rag").joinpath("web/index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"status": "ok", "chat_provider": settings.chat_provider,
            "embedding_provider": settings.embed_provider,
            "reranker_provider": settings.rerank_provider,
            "ann": retriever.ann.status(settings.embed_model).as_dict() if retriever.ann else {"state": "disabled"}}


@app.get("/api/stats")
def stats():
    return store.stats()


@app.get("/api/runs")
def runs(limit: int = 30):
    return {"runs": store.source_runs(limit)}


@app.post("/api/search")
def search(req: Query):
    return retriever.search(req.query, req.top_k, req.category, req.mode, req.trust,
                            source_id=req.source_id, expand=req.expand,
                            firmware_version=req.firmware_version,
                            version_policy=req.version_policy, rerank=req.rerank)


@app.post("/api/ask")
def ask(req: Query):
    return service.ask(req.query, req.category, req.top_k, req.mode, req.trust,
                       source_id=req.source_id, expand=req.expand,
                       firmware_version=req.firmware_version,
                       version_policy=req.version_policy, rerank=req.rerank)
