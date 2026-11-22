# Recuperación, evaluación y calidad

## Pipeline

1. Fuentes explícitamente permitidas (`sources.json`) y documentos locales seleccionados.
2. Extracción de texto, saneamiento de rutas y exclusión de volcados o binarios sensibles.
3. Chunking con líneas, título, categoría, revisión SHA y nivel de confianza.
4. Hash de contenido: reindexación incremental de documentos nuevos o modificados.
5. SQLite FTS5 (BM25) y embeddings opcionales (Ollama o API OpenAI compatible).
6. Reciprocal Rank Fusion (RRF), deduplicación limitada por documento y filtros `category`/`trust`.
7. El LLM recibe evidencia con referencias numeradas. Si no hay evidencia o el modelo falla, lo comunica.

## Calidad de búsqueda

El benchmark `benchmarks/questions.jsonl` contiene `question` y `must_contain_url`. La evaluación calcula Recall@K y MRR. Ejecuta la sincronización antes de evaluar (el benchmark de fuentes oficiales no puede medirse con solo las notas locales):

```bash
flipper-rag sync --web --crawl --max-pages 350 --depth 3
flipper-rag eval --file benchmarks/questions.jsonl --top-k 6 --min-recall 0.7
```

Los resultados dependen de páginas disponibles, versión y proveedor de embeddings, no hay un Recall@K prometido. No confundir Recall@K con exactitud factual de las respuestas generadas.

## Pruebas

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m compileall -q src
```

## Escalabilidad

SQLite FTS5 es eficiente para recuperación textual. En esta versión la similitud semántica examina vectores del índice SQLite (coste lineal): adecuado para decenas de miles de fragmentos, pero para corpus de cientos de miles considera Qdrant, FAISS o sqlite-vec. No afirmamos que haya una vector DB ANN en esta versión.

## Seguridad

La recuperación documental no autoriza acciones sobre hardware real; no hay herramientas de ejecución autónoma ni control del Flipper conectado. El corpus es input no confiable; el prompt de sistema contiene mitigación de prompt injection, pero no ofrece garantías formales contra todas las manipulaciones.
