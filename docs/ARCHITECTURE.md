# Arquitectura y decisiones técnicas

## Pipeline

1. `sources.json` declara URLs de manuales oficiales y orígenes Git. `sources.py` descarga páginas HTML (comprobación robots.txt, recorrido BFS opcional) o clona Git shallow; almacena los clones en `data/git-cache`.
2. `chunking.py` parte los documentos por líneas, con un solapamiento limitado y encabezados Markdown para mantener cierto contexto. Los `line_start`/`line_end` se refieren al archivo fuente, no a la UI.
3. `storage.py` persiste hash SHA-256, procedencia, categoría, revisión Git y fragmentos en SQLite. FTS5 permite recuperar incluso sin modelos.
4. `models.py` utiliza `POST /api/embed` de Ollama. Guarda los vectores como JSON en SQLite. `reembed` permite completar un corpus indexado sin embeddings.
5. `retrieval.py` consulta FTS5 y similitud coseno; combina rankings mediante RRF (k=60), limita a dos chunks por documento y devuelve URLs firmadas por commit (no enlaces dinámicos a `main`).
6. `service.py` inyecta contexto delimitado y pide citas numeradas; devuelve respuesta con objetos de procedencia y distingue explícitamente respuesta generada de solo recuperación.
7. `api.py` expone endpoints de solo lectura y panel HTML. La ingesta está reservada a CLI local.

## Contrato API

- `GET /api/health` → backend/configuración.
- `GET /api/stats` → documentos, fragmentos, cobertura de embeddings y categorías.
- `POST /api/search` con `{"query":"…","top_k":6,"category":null}` → `results`, `semantic_available`.
- `POST /api/ask` con igual cuerpo → `answer`, `sources`, `generated`, `semantic_available`.

## Próximas extensiones, no incluidas aún

- Ingestor GitHub API para issues/discusiones con políticas de atribución y límites de cuota.
- Detección de contenido duplicado entre manual web y archivos del firmware.
- Reranking cross-encoder para evitar fragmentos similares no pertinentes.
- Base vectorial ANN (Qdrant/FAISS/pgvector) para corpus muy extensos.
- Evaluación de groundedness, exactitud de citas, cobertura y regresiones de respuestas.
- Caché incremental del HTML + extracción de contenido principal más precisa.
- Roles/autenticación, limitación de consultas y aislamiento si se despliega fuera de localhost.
- Indexación PDF/multimedia, soporte multi-idioma y metadatos de compatibilidad firmware por versión.

No se deben presentar esas ampliaciones como implementadas en la versión 0.1.0.
