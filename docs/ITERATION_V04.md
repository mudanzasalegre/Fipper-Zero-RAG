# v0.4 — ANN, reranking y compatibilidad por versión

**Fecha:** 22 de noviembre de 2026. Código listo para sincronizar e indexar fuentes en el equipo del usuario. No se distribuye un corpus oficial descargado, modelos neuronales ni índices de terceros.

## Diseño y referencias

**USearch/HNSW:** índice ANN persistente, similitud coseno y llaves enteras estables ([SDK oficial](https://unum-cloud.github.io/USearch/python/index.html)). Se instala como dependencia opcional `.[ann]`; en ausencia de dependencia, caché o versión válida se usa búsqueda exacta.

**CrossEncoder:** reranking local sobre los candidatos de FTS5 y vectores, antes de diversificar resultados ([Sentence Transformers](https://www.sbert.net/docs/cross_encoder/usage/usage.html)). Modelo multilingüe sugerido: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`. No se carga al iniciar la API, requiere activación; `trust_remote_code=False`.

**Versiones:** los canales [Dev, RC y Release](https://docs.flipper.net/zero/basics/firmware-update) no son intercambiables. Una etiqueta release explícita conserva su SHA y su snapshot. Las guías sin versión son **no verificadas**, nunca se les presupone compatibilidad.

## Flujo

```text
Git/web/PDF → SQLite: fuente de verdad (documentos, SHA, versión, canal)
              ├→ FTS5 + BM25 + expansión ES/EN
              └→ Ollama embeddings → USearch HNSW opcional
           → RRF → filtros de procedencia y compatibilidad (SQLite)
           → CrossEncoder local opcional (solo shortlist)
           → diversidad por documento → citas → respuesta fundamentada
```

### Índice ANN

`flipper-rag ann build` indexa los vectores SQLite e informa del modelo, número de entradas y dimensiones. Los archivos `.usearch` y `.usearch.json` son cachés ignorados por Git. Se publican mediante reemplazo atómico, con manifiesto al final y contador `vector_epoch` SQLite. Cualquier alta, actualización, eliminación o revectorización invalida ANN. Hasta reconstruir se usa escaneo exacto. La pareja fichero/manifiesto no constituye una transacción distribuida: si aparece un fallo o carrera se descarta la caché.

Filtros de procedencia, categoría y versión se comprueban en SQLite, no se confía en la caché ANN para autorizaciones. Cuando el ANN deja pocos candidatos después de filtrar, se ejecuta un escaneo exacto filtrado. No se garantiza aceleración con corpus pequeños o filtros estrictos; compara con `RAG_ANN_ENABLED=false`.

### Reranker

`RAG_RERANK_PROVIDER=none` por defecto. Con `.[rerank]`, `RAG_RERANK_PROVIDER=cross-encoder` y `--rerank`, el motor evalúa los pares pregunta/fragmento de una shortlist (máximo ~80) y ordena los resultados por score del CrossEncoder. Si falla la carga o inferencia, mantiene el orden RRF. El modelo puede requerir una descarga inicial de pesos y CPU/RAM adicional. La clasificación no implica veracidad.

### Versiones

`flipper-rag sync --firmware-ref 1.5.1 --with-code` indexa una etiqueta del firmware oficial con origen `firmware-oficial-v1_5_1`, independiente de `dev`. Solo admite etiquetas de release/RC normalizadas, no refs Git arbitrarias. `--firmware-version 1.5.1 --version-policy strict` busca únicamente documentos marcados para esa versión. `include-unversioned` también admite guías sin versión como **unverified** pero excluye releases diferentes y `dev`. `exact_snapshot` significa coincidencia del código recuperado, no verificación física de compatibilidad.

## Ejemplo

```bash
python -m pip install -e '.[dev,ann,rerank]'
ollama pull nomic-embed-text
flipper-rag ingest --path knowledge/starter
flipper-rag reembed --build-ann
flipper-rag ann status
flipper-rag sync --firmware-ref 1.5.1 --with-code
flipper-rag reembed --build-ann
export RAG_RERANK_PROVIDER=cross-encoder
flipper-rag search 'API de NFC' --firmware-version 1.5.1 --version-policy strict --rerank
```

PowerShell: `$env:RAG_RERANK_PROVIDER='cross-encoder'`.

## Pruebas y límites

- Tests offline cubren migración de SQLite, procedencia, invalidación, búsquedas filtradas, fallback, USearch simulado y reranking simulado.
- GitHub CI dispone de un trabajo separado que instala y prueba USearch **real** sobre Python 3.12. Sin conexión, esa prueba se omite localmente.
- La inferencia real de un modelo CrossEncoder no se prueba en CI para evitar descargas grandes; tampoco se verifican características del dispositivo mediante hardware.
- El benchmark offline de las 15 guías introductoras **no mide** acierto sobre toda la documentación de Flipper Zero.
- El panel es localhost-first, no ofrece autenticación para exposición pública, y no transmite RF ni ejecuta comandos sobre dispositivos.
