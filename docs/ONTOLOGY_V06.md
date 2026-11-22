# Flipper Zero RAG v0.6 — Protocol Intelligence

Actualización: **22 de noviembre de 2026**. Esta especificación documenta el módulo de consulta **sin ejecución de acciones en el dispositivo**.

## Objetivo y resultados

La v0.5 contenía 118 entradas en `data/protocols.json`, clasificadas por familias con una referencia oficial. Aquellas entradas son un **índice de nombres y fuentes**, no una matriz de funciones de firmware. La v0.6 añade el módulo `protocol_intelligence.py`, su API, la consola `/ontology`, el dataset `data/ontology_v06.json` y un benchmark de regresión. No reemplaza el índice v0.5, lo **enriquece por superposición**.

- **118 protocolos** en el registro base (si el registro v0.5 está completo).
- **9 familias** con evidencias sobre medios físicos, bandas o extensiones.
- **35 perfiles** con características, notas y capacidades cuando existe documentación individualizada.
- **27 relaciones curatoriales** entre protocolos, con URL y semántica explícita.
- **4 reglas de enriquecimiento** limitadas a su ámbito original.
- **11 operaciones** modeladas con cuatro estados de evidencia.
- Gráfico con nodos de protocolos, familias y formatos, y aristas justificadas; exportación JSON o JSON-LD.

Estos recuentos **no equivalen** a protocolos probados en hardware ni capacidades de emulación verificadas. Los perfiles sin prueba permanecen como `unknown`.

## Diferenciar las capas

| Clase de evidencia | Qué acredita | Qué no acredita |
|---|---|---|
| `official-reader-list` | El manual enumera un protocolo RFID para lectura | Escritura, emulación ilimitada o firmware concreto |
| `file-format-listed` | El identificador se acepta en el formato `.ir` o `.ibtn` | Captura de cualquier señal o emulación universal |
| `file-format-or-tech-spec` | Campos de un archivo o soporte técnico indicado | Acceso a datos protegidos o compatibilidad de cualquier variante |
| `dev-source-registry` | Nombre presente en un commit de `dev` fijado | Que el protocolo pueda transmitirse, decodificarse o emularse en la release instalada |
| `firmware-source-snapshot` | Existencia de código en un commit determinado | Comportamiento de una release distinta |

**Regla fundamental:** ninguna propiedad de familia (`frequency_hz`, `medium`, `.sub`) se transforma automáticamente en una capacidad de cada protocolo. La frecuencia del ejemplo Princeton **no** se asigna a todos los protocolos Sub-GHz. El catálogo no incluye claves, credenciales ni grabaciones de terceros.

## Ontología

### Nodos y relaciones

`protocol:{id}` → `family:{name}` (`member_of`) → `format:.nfc` (`documents_with`). Una relación de protocolo a protocolo requiere **referencia y nota editorial**, y usa uno de:

- `layered_over`: una representación depende de una capa inferior; p. ej., MIFARE DESFire y el encabezado ISO 14443-4A.
- `variant_of`: variante nominal de familia, p. ej. RC5X respecto de RC5.
- `related_to`: comparten conceptos o tratamiento documental sin ser equivalentes.
- `contrasts_with`: las fuentes diferencian los conceptos; p. ej., NFC-V y NFC-A.

El validador prohíbe IDs desconocidos, referencias ajenas a Flipper Devices, relaciones duplicadas, bucles y ciclos en las dos relaciones dirigidas. Una búsqueda de vecinos puede navegar tanto hacia arriba como hacia abajo, conservando la dirección real de la relación.

### Matriz de capacidades

Operaciones admitidas: `read`, `save`, `decode`, `parse_file`, `emulate_uid`, `emulate_data`, `write`, `receive`, `transmit`, `operate_interface`, `source_identified`. `source_identified` indica **presencia en el código fuente**, no una operación física.

| Estado | Interpretación |
|---|---|
| `documented` | Una referencia oficial dice que la operación existe para el ámbito descrito |
| `limited` | Existe solo bajo condiciones específicas reflejadas en `evidence.note` |
| `not_supported` | La fuente oficial niega la operación; no se deduce de una ausencia |
| `unknown` | No hay evidencia suficiente; **no significa incompatible** |

La evidencia de una operación incluye URL, ámbito (`protocol`, `family`, `file-format`, `variant` o `dev-snapshot`), explicación y, cuando exista, versión del firmware. Si se consulta la compatibilidad con una **release específica**, toda afirmación sin versión coincidente pasa a `status=unknown` para esa consulta y conserva su `documentation_status` general. Por tanto, la interfaz no presenta documentación genérica o `dev` como prueba de esa release.

### Ejemplos contrastados

- **MIFARE DESFire:** lectura de aplicaciones no protegidas; únicamente emulación del UID, no de archivos de aplicación. [Manual oficial de lectura NFC](https://docs.flipper.net/zero/nfc/read).
- **MIFARE Classic:** lectura y emulación de sectores según claves o sectores desbloqueados; no se presupone memoria completa. [Manual oficial](https://docs.flipper.net/zero/nfc/read).
- **NTAG 213/215/216:** se documenta la lectura/emulación de páginas accesibles y ciertas condiciones de escritura. [Manual oficial](https://docs.flipper.net/zero/nfc/read).
- **ISO 15693:** se relaciona con NFC-V; la capacidad de ICODE SLIX no se generaliza a toda la norma. [Manual NFC](https://docs.flipper.net/zero/nfc/read).
- **IR NEC/RC5/RC6:** los nombres aparecen en el formato `parsed`, lo cual **no** certifica cualquier control remoto. [Formato IR](https://developer.flipper.net/flipperzero/doxygen/infrared_file_format.html).
- **Sub-GHz Princeton/RAW/BinRAW:** se documentan como ejemplos de archivos, mientras que la presencia de un decodificador en `dev` no acredita emisión en una región. [Formato .sub](https://developer.flipper.net/flipperzero/doxygen/subghz_file_format.html), [menú Sub-GHz](https://docs.flipper.net/zero/sub-ghz).

## CLI — sin modelos externos

```bash
flipper-rag ontology validate
flipper-rag ontology stats
flipper-rag ontology search --family nfc --feature page-memory
flipper-rag ontology search --capability emulate_data --status limited
flipper-rag ontology search --family lf-rfid --frequency-hz 125000
flipper-rag ontology search --family sub-ghz --capability transmit --status documented
flipper-rag ontology show mifare-desfire
flipper-rag ontology show mifare-classic --firmware-version 1.5.1
flipper-rag ontology compare mifare-classic mifare-desfire iso-15693
flipper-rag ontology related iso-14443-3a --depth 2
flipper-rag ontology graph --format jsonld
flipper-rag ontology eval --file benchmarks/ontology_v06.jsonl
flipper-rag ontology index
```

`ontology index` crea fichas curadas con `trust=local` en SQLite para que el RAG híbrido pueda citarlas como **resúmenes editoriales**, nunca como páginas oficiales. Las URLs de las afirmaciones son enlaces a las fuentes originales. Para utilizarlas junto al corpus oficial, sincroniza e indexa las fuentes con los comandos de la v0.5 y consulta según la revisión Git del firmware.

## API y panel

| Ruta | Acción |
|---|---|
| `GET /ontology` | Interfaz de exploración y comparación |
| `GET /api/ontology/stats` | Cobertura y estado de afirmaciones |
| `GET /api/ontology/search` | Búsqueda por texto, familia, formato, característica, capacidad, estado y frecuencia **de familia** |
| `GET /api/ontology/protocols/{id}` | Ficha enriquecida, evidencia y advertencia de versión |
| `GET /api/ontology/protocols/{id}/relations` | Vecinos del grafo hasta tres saltos |
| `POST /api/ontology/compare` | Comparación estructurada de 2 a 8 IDs |
| `GET /api/ontology/graph?format=jsonld` | Grafo completo con procedencia |

Las rutas se mantienen de consulta documental; el único cambio persistente es la indexación voluntaria mediante CLI. La API no lee tarjetas, no interactúa con radiofrecuencias y no ejecuta comandos del sistema.

## Benchmark, pruebas y límites

El archivo `benchmarks/ontology_v06.jsonl` contiene 18 escenarios de recuperación y abstención. Calcula cobertura de IDs esperados, exclusión de falsos positivos y acierto de búsquedas negativas. La batería `tests/test_v06.py` cubre integridad del esquema, dependencias cíclicas, referencias, filtros, relaciones, comparación, versiones y exportación. `tests/test_v06_integration.py` prueba el catálogo real de v0.5 y las rutas API en CI. No se deben extrapolar estos indicadores a exactitud generativa, interoperabilidad física ni disponibilidad de TX por país.

## Fuentes oficiales principales (22-11-2026)

- [Especificaciones físicas](https://docs.flipper.net/zero/development/hardware/tech-specs)
- [Lectura NFC y límites de emulación](https://docs.flipper.net/zero/nfc/read)
- [NFC `.nfc`](https://developer.flipper.net/flipperzero/doxygen/nfc_file_format.html)
- [Lectura LF RFID](https://docs.flipper.net/zero/rfid/read)
- [LF RFID `.rfid`](https://developer.flipper.net/flipperzero/doxygen/lfrfid_file_format.html)
- [Formato de infrarrojos](https://developer.flipper.net/flipperzero/doxygen/infrared_file_format.html)
- [Formato iButton](https://developer.flipper.net/flipperzero/doxygen/ibutton_file_format.html)
- [Formato Sub-GHz](https://developer.flipper.net/flipperzero/doxygen/subghz_file_format.html)
- [Protocolo de expansión](https://developer.flipper.net/flipperzero/doxygen/expansion_protocol.html)

**Revisión pendiente para una futura versión:** establecer matrices físicas validadas por release y región, ampliar los perfiles a los 118 identificadores, extraer automáticamente pruebas de funcionalidades por test de firmware y medir relevancia/latencia con un corpus real. Este proyecto no certifica compatibilidad de hardware o funciones de acceso.
