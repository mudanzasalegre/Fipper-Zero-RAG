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
