# Flipper Knowledge Platform — evaluación y evidencia

La evaluación de fuentes oficiales se ejecuta **después de descargar las páginas reales**. El corpus no incluye documentos descargados en GitHub; el equipo que ejecuta la prueba los obtiene bajo sus propias condiciones de red y respetando robots.txt.

El banco de preguntas manual `benchmarks/real_official_v1.json` registra URLs oficiales y grados de relevancia, no sus contenidos. La evaluación calcula Recall@K, MRR, nDCG@K, precisión, abstención de preguntas negativas, cobertura de páginas y metadatos de cita. Una cobertura insuficiente produce un informe `incomplete`, nunca una puntuación inventada.

El score mide recuperación, **no** exactitud factual de un modelo generativo, seguridad de transmisiones ni compatibilidad de un firmware determinado. Los cambios en documentación, chunking, idiomas y modelos deben registrarse por fecha y hash del dataset. El workflow de GitHub Actions se ejecuta sin modelos externos ni credenciales; realiza búsquedas lexicales sobre contenido descargado durante esa ejecución.

Fuentes oficiales: https://developer.flipper.net/flipperzero/doxygen/index.html y https://docs.flipper.net/zero/development.
