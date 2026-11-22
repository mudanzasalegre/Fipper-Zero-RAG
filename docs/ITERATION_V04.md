# v0.4 — ANN, reranking y compatibilidad por versión

**Fecha:** 22 de noviembre de 2026. Código listo para sincronizar e indexar las fuentes por el usuario. El repositorio NO distribuye un corpus oficial descargado, un índice de terceros, un modelo neuronal ni archivos del dispositivo.

## Decisiones verificadas

- **USearch / HNSW**: índice ANN persistente con métrica coseno y llaves enteras estables. [SDK oficial](https://unum-cloud.github.io/USearch/python/index.html). Instalación opcional `pip install -e ".[ann]"` para Windows, Linux y macOS. No se utiliza si falta, está obsoleto o el modelo/dimensión no coincide.
- **CrossEncoder**: reranking local de los candidatos recuperados por FTS5 y/o vector, antes de aplicar diversidad por documento. [Referencia de Sentence Transformers](https://www.sbert.net/docs/cross_encoder/usage/usage.html). Modelo multilingüe sugerido: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`. Se descarga de Hugging Face únicamente después de activarlo; no es necesario para búsqueda léxica/semántica normal. Al cargar, `trust_remote_code=False`.
- **Versiones de firmware**: los canales [Dev, RC y Release](https://docs.flipper.net/zero/basics/firmware-update) NO son equivalentes. El código de una etiqueta release explícita se indexa con su versión y SHA. La documentación sin versión se presenta como **no verificada**. No se infiere compatibilidad por presencia de palabras o por proximidad entre versiones.

## Arquitectura

```text
Datos locales o upstream (git/web/PDF)
       ↓ documentos: origen, revisión SHA, versión y canal
 SQLite / FTS5 (fuente de verdad)
       ↓ vectores Ollama o endpoint embeddings
 USearch HNSW (caché opcional con epoch de invalidación)
       ↓ unión con FTS5 + expansión terminológica ES/EN → RRF
       ↓ filtro de versionado y procedencia; fallback exacto si faltan candidatos
       ↓ CrossEncoder local opcional (solo shortlist)
       ↓ diversificación por documento y citas
       ↓ respuesta fundamentada o abstención
```

### Durabilidad de la caché ANN

`flipper-rag ann build` lee vectores de SQLite, ignora dimensiones inconsistentes y publica un fichero `.usearch` junto a un manifiesto JSON con modelo, dimensión, contador de cambios y correspondencia de IDs. Se guarda con reemplazos atómicos, publicando el manifiesto al final. Todo el directorio `data/` está ignorado por Git. Si se indexa, borra o re-vectoriza contenido, el contador cambia y se deja de usar el índice antiguo. El motor consulta SQLite de forma exacta hasta reconstruir ANN. No es una transacción distribuida de ambos ficheros; una corrupción o carrera puede provocar fallback y reconstrucción.

Los filtros por fuente, tema, confianza o versión se verifican siempre contra SQLite. Si la búsqueda aproximada deja pocos candidatos tras filtrar, se realiza un escaneo exacto filtrado. **No se promete aceleración ANN en todos los casos**, ni resultados idénticos a la búsqueda exhaustiva sin filtros; el usuario puede elegir `RAG_ANN_ENABLED=false` para comparar.

### Reranking

`RAG_RERANK_PROVIDER=none` por defecto. Para ejecutar un modelo local real, instalar `[rerank]`, configurar el proveedor a `cross-encoder` y añadir `--rerank` a la consulta o marcar la opción del panel. El modelo solo evalúa la shortlist (hasta un máximo aproximado de 80 fragmentos), no todos los documentos. El score del reranker se muestra separado de RRF. Ante un error de carga o inferencia el orden de RRF se conserva. **El reranker no convierte una respuesta en verdadera** y es recomendable evaluar el modelo bilingüe con preguntas reales antes de activar el modo de producción.

### Versiones

`flipper-rag sync --firmware-ref 1.5.1 --with-code` clona una etiqueta Git permitida y la registra como `firmware-oficial-v1_5_1`. No pisa los documentos de la rama `dev`. Esta etiqueta se etiqueta como release; `-rc` como candidato. No se aceptan opciones arbitrarias como refs Git, flags de shell ni rangos.

`--firmware-version 1.5.1 --version-policy strict` devuelve **solo** documentos etiquetados exactamente `1.5.1`. `include-unversioned` (por defecto) agrega fuentes sin versión con aviso, pero excluye expresamente otra versión de release y la rama móvil dev. La documentación web general no tiene etiqueta firmware y no se presenta como certificación de compatibilidad. Para el usuario, **exact_snapshot** significa revisión de código recuperada para la etiqueta, no compatibilidad comprobada en hardware.

## Instalación y ejemplo

```bash
python -m pip install -e '.[dev,ann,rerank]'
ollama pull nomic-embed-text
flipper-rag ingest --path knowledge/starter
flipper-rag reembed --build-ann
flipper-rag ann status
# Firmware en snapshot distinto al canal dev; requiere Internet para git clone
flipper-rag sync --firmware-ref 1.5.1 --with-code
flipper-rag reembed --build-ann
# Modelo de reranking previamente descargado/instalado en entorno confiable
export RAG_RERANK_PROVIDER=cross-encoder
flipper-rag search 'API de NFC' --firmware-version 1.5.1 --version-policy strict --rerank
```

*En PowerShell*: `$env:RAG_RERANK_PROVIDER='cross-encoder'` en lugar de `export`.

## Verificación y límites

- Tests unitarios y de integración offline: versiones, migraciones, invalidación, backend USearch simulado, filtros estrictos, fallback y reranking simulado.
- CI instala y prueba el backend USearch **real** en Python 3.12, además de la matriz base 3.10/3.12/3.13 sin extras.
- No se ejecuta inferencia de CrossEncoder real en CI, porque exigiría descargar pesos grandes. Tampoco se prueban respuestas generadas por un modelo específico ni se mide exactitud de compatibilidad sobre dispositivos físicos.
- La comparación ANN vs exacto es una **opción**, no una garantía de ventaja de latencia: depende del tamaño del corpus, el porcentaje filtrado y las dimensiones de embeddings.
- El benchmark offline basado en 15 guías introductorias no representa la documentación completa; realiza una evaluación propia tras sincronizar fuentes reales.
- El asistente no transmite señales, no opera sistemas ajenos ni descarga contenido no autorizado. Ejecuta interfaz local, sin autenticación por defecto: nunca publiques el servidor sin protecciones adicionales.
