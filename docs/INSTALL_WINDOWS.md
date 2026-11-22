# Instalación detallada en Windows 11 (PowerShell)

## Requisitos

- Python 3.10 o superior, Git y espacio para el corpus de firmware.
- [Ollama](https://ollama.com/) si quieres generación de respuestas o embeddings. Para búsqueda lexical funciona sin IA.

```powershell
git clone https://github.com/mudanzasalegre/Fipper-Zero-RAG.git
cd Fipper-Zero-RAG
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Si PowerShell bloquea la activación por su política de ejecución, no cambies la política global: ejecuta directamente `.venv\Scripts\python.exe -m pip install -e ".[dev]"` y `.venv\Scripts\flipper-rag.exe ...`.

## Índice inicial sin Ollama

```powershell
$env:RAG_EMBED_PROVIDER = "none"
$env:RAG_CHAT_PROVIDER = "none"
flipper-rag doctor
flipper-rag ingest --path knowledge/starter
flipper-rag search "Cómo se compila una app FAP" --mode lexical
uvicorn flipper_rag.api:app --host 127.0.0.1 --port 8000
```

Abre http://127.0.0.1:8000.

## Habilitar IA local

Con Ollama ya instalado y funcionando:

```powershell
ollama pull nomic-embed-text
ollama pull qwen2.5:7b
$env:RAG_EMBED_PROVIDER = "ollama"
$env:RAG_CHAT_PROVIDER = "ollama"
flipper-rag reembed
flipper-rag ask "Qué diferencia hay entre Furi y uFBT"
```

Puedes sustituir el modelo por otro compatible. Un servidor de llama.cpp/LM Studio con API OpenAI-compatible se configura con `RAG_CHAT_PROVIDER=openai`, `RAG_OPENAI_BASE_URL`, `RAG_OPENAI_MODEL` y (si ofrece embeddings) `RAG_EMBED_PROVIDER=openai`.

## Sincronización real

```powershell
flipper-rag sync --web --crawl --max-pages 350 --depth 3
flipper-rag sync --firmware --with-code
flipper-rag sync --apps
flipper-rag sync --tools
flipper-rag reembed
flipper-rag stats
```

La descarga puede ser grande y algunas URLs pueden responder con errores o estar limitadas por `robots.txt`. La ingesta continúa cuando falla una página y conserva los documentos previamente indexados. **No basta con clonar este repo para tener el corpus remoto ya indexado.**
