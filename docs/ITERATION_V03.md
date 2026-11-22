# Iteración v0.3 — revisión integral de Flipper Zero RAG

Fecha: 22 de noviembre de 2026. Esta versión **no incorpora una base de datos oficial ya descargada**: el índice y los embeddings deben construirse en la máquina del usuario.

## Investigación y procedencia

Revisadas fuentes documentales de Flipper Devices:

- Índice oficial de documentación: https://developer.flipper.net/flipperzero/doxygen/pages.html
- FAP y FAM: https://developer.flipper.net/flipperzero/doxygen/apps_on_sd_card.html y https://developer.flipper.net/flipperzero/doxygen/app_manifests.html
- Furi API y FuriHalBus: https://developer.flipper.net/flipperzero/doxygen/app_dev_furi_api.html y https://developer.flipper.net/flipperzero/doxygen/furi_hal_bus.html
- Protocolo de expansión para módulos UART/RPC: https://developer.flipper.net/flipperzero/doxygen/expansion_protocol.html
- Motor y SDK JavaScript: https://developer.flipper.net/flipperzero/doxygen/js_about_js_engine.html y https://developer.flipper.net/flipperzero/doxygen/js_developing_apps_using_js_sdk.html
- Referencias de formatos NFC/Sub-GHz/RFID/IR y módulos JS: https://developer.flipper.net/flipperzero/doxygen/file_formats.html y https://developer.flipper.net/flipperzero/doxygen/js.html
- Wi-Fi Devboard y debugging: https://developer.flipper.net/flipperzero/doxygen/dev_board_reading_logs.html
- Manifiestos de Apps Catalog (no contienen necesariamente fuentes de apps): https://github.com/flipperdevices/flipper-application-catalog

Se amplió el listado a **61 semillas web HTTPS**, manteniendo 6 repositorios oficiales y 3 comunitarios opcionales. La selección de fuentes Git está sujeta a allowlist y no redistribuye automáticamente código ni índices.

## Cambios técnicos implementados

1. **Recuperación**: FTS5/BM25 y vectores filtrados por categoría, confianza y fuente **antes** del límite top-N; reduce falsos negativos por filtros post-hoc.
2. **Precisión**: eliminación de stopwords ES/EN, rechazo de coincidencias triviales en preguntas con múltiples conceptos, expansión técnica ES/EN de peso inferior, y señales de recuperación por fragmento. No sustituye a un reranker neuronal.
3. **Crawler**: parser HTML con correcto manejo de etiquetas `void` y bloques anidados excluidos; preformateado preservado; redirección externa bloqueada; conteo de errores y páginas omitidas por límite.
4. **Ciclo de vida**: ingesta incremental con `--prune` explícito y guardas contra fallos, límites de archivos y corpus vacío; registro en SQLite de últimas sincronizaciones con estado y métricas; `flipper-rag runs` y `/api/runs`.
5. **Documentos propios**: PDF por página con `--pdf` opcional y `pypdf`, soporte de extensiones adicionales; no OCR ni documentos cifrados.
6. **Calidad**: benchmark offline versionado, Recall@k, MRR y exactitud de abstención; CI en tres versiones de Python y pruebas de regresión.
7. **Interfaz**: filtros interactivos de categoría y `source_id`, cobertura de embeddings y resumen del último estado de sincronización.

## Verificación y límites

- Las pruebas automatizadas se ejecutan sin red y sin conectar Flipper Zero.
- El resultado del benchmark sobre notas locales **no es** una estimación de acierto sobre todo el firmware o versiones instaladas.
- Los filtros mejoran precisión operativa, pero una respuesta del LLM puede contener errores incluso con citas. Contrasta afirmaciones técnicas y licencias en origen.
- La búsqueda vectorial sigue siendo **exacta lineal**; no se incorpora ANN, OCR ni reranker neuronal en v0.3.
- Los servidores de IA y API se mantienen locales por defecto; no se debe exponer el panel sin autenticación y TLS.
- Las funciones de la herramienta son documentales: no transmiten RF ni ejecutan comandos en dispositivos.
