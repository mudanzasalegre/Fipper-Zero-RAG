# Arquitectura y decisiones técnicas

## Pipeline

1. `sources.json` declara URLs de manuales oficiales y orígenes Git. `sources.py` descarga páginas HTML (comprobación robots.txt, recorrido BFS opcional) o clona Git shallow; almacena los clones en `data/git-cache`.
2. `chunking.py` parte los documentos por líneas, con un solapamiento limitado y encabezados Markdown para mantener cierto contexto. Los `line_start`/`line_end` se refieren al archivo fuente, no a la UI.
3. `storage.py` persiste hash SHA-256, procedencia, categoría, revisión Git y fragmentos en SQLite. FTS5 permite recuperar incluso sin modelos.
4. `models.py` utiliza `POST /api/embed` de Ollama. Guarda los vectores como JSON en SQLite. `reembed` permite completar un corpus indexado sin embeddings.
5. `ann.py` guarda un índice HNSW USearch opcional: un contador de cambios SQLite invalida caches antiguos, reconstruibles por CLI. Filtrados estrictos se verifican en SQLite con fallback exacto si escasean candidatos.
6. `versioning.py` normaliza etiquetas release/RC, conserva snapshots separadas del firmware y marca las fuentes sin revisión como no verificadas.
7. `retrieval.py` consulta FTS5 y similitud coseno exacta o ANN, combina rankings con RRF (k=60), aplica un CrossEncoder local opcional vía `reranking.py` sobre una shortlist, limita a dos chunks por documento y devuelve URLs firmadas por commit (no enlaces dinámicos a `main`).
8. `service.py` inyecta contexto delimitado y pide citas numeradas; devuelve respuesta con objetos de procedencia y distingue explícitamente respuesta generada de solo recuperación.
9. `api.py` expone endpoints de solo lectura y panel HTML. La ingesta está reservada a CLI local.

## Contrato API

- `GET /api/health` → backend/configuración.
- `GET /api/stats` → documentos, fragmentos, cobertura de embeddings y categorías.
- `POST /api/search` con `{"query":"…","top_k":6,"category":null}` → `results`, `semantic_available`.
- `POST /api/ask` con igual cuerpo → `answer`, `sources`, `generated`, `semantic_available`.

## Cambios v0.4

- ANN persistente (HNSW) en `ann.py`, opcional mediante `.[ann]`; SQLite sigue siendo la fuente de verdad.
- Reranker local configurable en `reranking.py`, opcional mediante `.[rerank]`.
- Versionado conservador en `versioning.py`, con migración SQLite y políticas de compatibilidad.
- CLI/API/panel pueden recibir `firmware_version`, `version_policy` y `rerank`.

## Próximas extensiones, no incluidas aún

- Ingestor GitHub API para issues/discusiones con políticas de atribución y límites de cuota.
- Detección de contenido duplicado entre manual web y archivos del firmware.
- Evaluación de groundedness, exactitud de citas, cobertura y regresiones de respuestas.
- Caché incremental del HTML + extracción de contenido principal más precisa.
- Roles/autenticación, limitación de consultas y aislamiento si se despliega fuera de localhost.
- Indexación multimodal (OCR e imágenes) y análisis de cambios en APIs entre versiones del firmware.

Las funcionalidades no verificadas sobre firmware real no deben presentarse como certificadas.
