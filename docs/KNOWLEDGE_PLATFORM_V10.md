# Flipper Zero RAG v1.0 — Knowledge Platform

## Objetivo y alcance

La v1.0 integra el RAG con Protocol Intelligence (v0.6), Firmware Knowledge Graph (v0.7), Development Assistant (v0.8) y Protocol Lab (v0.9). Añade un panel unificado **de solo lectura**, métricas de salud y procedencia, sincronización incremental de documentación oficial y evaluación medible sobre un corpus de fuentes reales.

## Arquitectura

- `platform.py`: persistencia de metadatos HTTP (ETag, Last-Modified, fecha, SHA-256, texto extraído), contador de cambios y fallos, historial de evaluaciones, integridad FTS y estado por fuente.
- `platform_eval.py`: benchmark con juicios manuales por URL y grado, cobertura, Recall@K, MRR, nDCG@K, precisión@K, abstención, porcentaje de metadatos de cita y latencia. No utiliza LLM para puntuar.
- `platform_cli.py`: CLI con `status`, `audit`, `sync`, `evaluate` y `report`.
- `platform_api.py`: API GET exclusivamente; no ejecuta descargas ni comandos.
- `platform_discovery.py`: consulta federada, con procedencia, de RAG, protocolos, símbolos de firmware indexado, plantillas y formatos. No infiere capacidades a partir de etiquetas sin evidencia.
- `web/platform.html`: panel responsivo de los módulos, evolución, salud de las fuentes, cobertura, resultados y comandos seguros.
- `benchmarks/real_official_v1.json`: 13 URLs oficiales, 20 preguntas con relevancia graduada y 2 negativos. El fichero contiene preguntas y referencias, **no** reproduce páginas de terceros.
- `.github/workflows/official-retrieval-eval.yml`: workflow semanal, manual y en push relevante que descarga páginas reales y exporta informes; deja constancia explícita si una evaluación quedó incompleta. No requiere Ollama ni hardware.

## Comandos

```bash
python -m pip install -e '.[dev]'
flipper-rag platform status
flipper-rag platform sync --local
flipper-rag platform sync --web --max-pages 100 --delay 0.5
flipper-rag platform sync --internal  # fichas editoriales del catálogo y desarrollo
flipper-rag platform sync --git --git-cache data/upstream
flipper-rag platform evaluate --file benchmarks/real_official_v1.json --fetch --json-output data/eval-v10.json
flipper-rag platform audit
flipper-rag platform report --format markdown --output data/health.md
uvicorn flipper_rag.api:app --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000/platform`. La búsqueda federada también está disponible mediante `GET /api/platform/discover?q=api_symbols.csv` y admite `firmware_ref` si ya existe un snapshot v0.7 indexado. Si falta un módulo o snapshot, se comunica como limitación sin ocultar otros resultados. Para GitHub Actions: *Official documentation retrieval benchmark* → *Run workflow*. Si hay políticas `robots.txt`, falta de red o documentos no disponibles, el benchmark no inventa una métrica positiva: registra una ejecución incompleta. Los informes se publican como artefactos de Actions durante 30 días.

## Interpretación de resultados

- **Recall@K**: porcentaje de preguntas con algún documento relevante entre los K primeros.
- **MRR@K**: media de la inversa de la posición del primer relevante.
- **nDCG@K**: calidad del orden teniendo en cuenta juicios graduados; 1 es óptimo.
- **Abstención**: porcentaje de preguntas negativas sin resultados entre los primeros K.
- **Cobertura**: URLs del benchmark realmente indexadas desde la documentación oficial.
- **Metadatos de cita**: proporción de fragmentos recuperados con URL oficial y líneas; no prueba que el LLM cite correctamente.

Estos indicadores son **solo de recuperación**. La plataforma no promete que el contenido indexado cubra todas las releases, que el hardware funcione en casos no probados, o que el modelo genere siempre respuestas correctas. Para evaluar generación hay que añadir juicios humanos y casos de prueba específicos, distintos del benchmark documental.

## Actualizaciones incrementales

- HTTP: el cliente acepta únicamente URLs canónicas HTTPS en dominios oficiales permitidos, lee robots.txt, bloquea cambios de host en redirecciones y limita el tamaño. Al enviar validadores HTTP (ETag/Last-Modified) puede recibir 304. La respuesta 304 actualiza la fecha de comprobación, pero no marca contenido como modificado.
- Indexación: SHA-256 del texto extraído y metadatos de procedencia deciden si sustituir los fragmentos; documentos idénticos no recalculan vectores.
- Git: ingesta por repositorio oficial permitido y versión Git, mediante el colector existente.
- Fallos: una fuente inaccesible se contabiliza, pero no se eliminan documentos ni se oculta el estado parcial. No se publica corpus descargado en Git.
- API: de solo lectura; las acciones de red solo pueden lanzarse desde CLI explícita.

## Seguridad y limitaciones

Sin acceso a radiofrecuencia, NFC/RFID, flash, ejecución de firmware ni scripts externos en esta iteración. No publica capturas, llaves o volcados. El rastreador no sigue enlaces arbitrarios. No reemplaza una auditoría de hardware real, una evaluación de veracidad de generación o una revisión legal de uso.

Fuentes: [Developer Docs](https://developer.flipper.net/flipperzero/doxygen/index.html), [App Development](https://developer.flipper.net/flipperzero/doxygen/applications.html), [FAP y versiones de API](https://developer.flipper.net/flipperzero/doxygen/apps_on_sd_card.html), [Manual](https://docs.flipper.net/zero/development).
