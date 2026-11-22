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
