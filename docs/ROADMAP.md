# Roadmap

## 0.2 — primer repositorio público

- Fuentes oficiales ampliadas, herramientas de desarrollo y comunidad opt-in.
- Trazabilidad por commit y niveles de confianza de origen.
- Búsqueda híbrida configurable, API, interfaz, pruebas y guías.
- Diagnóstico, evaluaciones Recall@K/MRR y corpus local inicial.

## 0.3 — calidad de recuperación y gestión del corpus

- 61 semillas oficiales verificadas, incluidos módulos JS, formato de archivos y Devboard.
- Filtros fuente/categoría/confianza en SQL, expansión ES/EN y umbral léxico para evitar coincidencias triviales.
- Estado de sincronizaciones, limpieza incremental opt-in con protecciones y referencias a PDF local por página.
- Benchmark offline reproducible (12 preguntas técnicas + control negativo) en CI.

## Próximas mejoras sugeridas

- Conector ANN opcional (Qdrant/sqlite-vec) para índices grandes.
- Reranking local (cross-encoder) y evaluación de exactitud de citas.
- Detección de versiones compatibles entre firmware y FAP.
- Mejor extracción de documentación Doxygen, diagramas y tablas.
- Exportación de fuentes en formato interoperable, sin secretos.
- Actualizaciones programadas del índice bajo control del usuario.
- Monitoreo de cambios de hashes y métricas de obsolescencia.

**No está implementado** el control del dispositivo, transmisión RF, lectura de tarjetas ni ninguna acción sobre sistemas externos. Este proyecto es un asistente documental.

### Realizado en v0.4

- Índice ANN persistente USearch HNSW con invalidación y fallback exacto.
- CrossEncoder opcional local para reranking de shortlist.
- Snapshots Git etiquetados por versión y restricciones conservadoras de compatibilidad.

### Pendiente tras v0.4

- Benchmark de corpus oficial real (Recall/nDCG/latencia) con juicios manuales de relevancia.
- Recalibración y optimización de reranker multilingüe sobre preguntas de firmware.
- Políticas de versiones más avanzadas: comparación de cambios de símbolos/API entre tags, diffs por release.
- Cache ANN transaccional compartida entre múltiples procesos/hosts con bloqueo coordinado.


### Realizado en v0.6 — Protocol Intelligence

- Ontología no invasiva de 118 identificadores, 9 familias, 35 perfiles y 27 relaciones curatoriales.
- Matriz de capacidades con estados verificables (`documented`, `limited`, `not_supported`, `unknown`), enlace y ámbito de prueba por afirmación.
- Búsqueda por características, comparador de 2–8 protocolos, navegación del grafo y exportación JSON-LD.
- API de lectura y consola `/ontology`, indexación editorial opcional y benchmark offline con controles negativos.
- Conservación de incertidumbre: no inferir compatibilidad de release a partir de documentación sin versión o del registro `dev`.

### Posterior a v0.6

- Extraer pruebas automatizadas de cambios en símbolos C por versión (v0.7).
- Verificar compatibilidad real de dispositivos y firmware en entornos autorizados; el RAG no certifica hardware.
- Ampliar evidencias individualizadas para los protocolos cuyo único origen es un registro fuente.


## 0.7 — Firmware Knowledge Graph (implementado)

- Escaneo local de snapshots Git inmutables del firmware oficial (tags o SHA), con metadatos de integridad, referencias a líneas y estado de completitud.
- Extracción estructurada conservadora de declaraciones/definiciones C, macros, tipos, includes y manifiestos `.fam` sin ejecución.
- Grafo de referencias con resolución de símbolos y ambigüedades explícitas, búsqueda por firma/nombre, navegación y visualizador `/firmware`.
- Comparador entre snapshots: símbolos añadidos/eliminados/movidos/modificados y comparación separada de exportaciones FAP desde `targets/f7/api_symbols.csv`.
- CLI/API de solo lectura, sin acciones sobre hardware, tests temporales con releases simuladas.

Ver [documentación de la v0.7](FIRMWARE_GRAPH_V07.md). No se ha ejecutado un benchmark de precisión semántica sobre el firmware oficial completo; la resolución de C/C++ no equivale a la de un compilador.

## v0.8 — Development Assistant

- 7 ejemplos originales Furi/C y JavaScript mJS, 7 guías con referencias oficiales.
- Scaffold, validación estática FAM sin ejecución, y comprobación opcional de exports a partir de v0.7.
- CLI `dev`, interfaz `/development`, API de consulta/validación y fuentes indexables en RAG.
- Compilación local de pruebas con uFBT bajo `--execute`, reportes SHA-256 y workflow manual de compilación real.
- Pendiente: compilar los ejemplos con la SDK oficial en GitHub Actions / PC y probar en un Flipper propio; la CI estándar no es prueba de dispositivo.

## v0.9 — Protocol Lab (realizado)

- Analizadores offline y acotados de Sub-GHz, NFC, LF RFID, IR, iButton, FAM, Proto y BadUSB estático opt-in.
- Diagnósticos estructurales con fuente, gravedad y línea; informes JSON, Markdown y HTML.
- CLI `lab` con análisis individual, lote, comparación y resumen redactado opcional para RAG.
- API de texto local y panel web `/lab`, sin acceso a sistemas externos ni ejecución de archivos.
- Pruebas automatizadas con entradas sintéticas y controles de privacidad. No realiza pruebas de hardware/firmware real.

Ver [especificación de Protocol Lab](PROTOCOL_LAB_V09.md). El siguiente paso es ampliar la validación documental de formatos específicos de releases oficiales, sin inferir capacidades a partir de ejemplos.

## v1.0 — Flipper Knowledge Platform (2026-11-23)

- Panel `/platform`, búsqueda federada RAG/ontología/firmware/desarrollo/laboratorio y estado de fuentes.
- Indexación incremental de documentación oficial con HTTP ETag/Last-Modified (304) y SHA-256; metadatos Git sin re-embeddings cuando el texto es idéntico.
- Banco de 13 URLs oficiales y 22 preguntas con juicios graduados, Recall@K, MRR, nDCG@K, abstención y cobertura de citas; resultados reales solo tras descargar fuentes.
- CLI y workflow manual, programado y en push relevante para evaluar fuentes reales; sin controles de hardware.

Ver [diseño v1.0](KNOWLEDGE_PLATFORM_V10.md). Las métricas no equivalen a validar comportamiento físico ni veracidad generativa.
