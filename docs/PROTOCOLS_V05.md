# Flipper Zero RAG v0.5 — catálogo verificable de protocolos

## Objetivo

Ampliar la cobertura de **protocolos** sin confundir la existencia de un identificador, un soporte físico, una rutina de decodificación, la emulación y la autorización legal para transmitir. Esta es una base de conocimiento de consulta, no un controlador del Flipper.

## Estructura

- `src/flipper_rag/data/protocols.json`: **118 identificadores** con nombre canónico, familia, capa, sinónimos, nivel de evidencia, resumen editorial y URL oficial.
- `src/flipper_rag/protocols.py`: validador estricto de referencias oficiales, búsqueda y producción de documentos listos para RAG.
- `knowledge/protocols/`: ocho guías explicativas originales por dominios y criterios de validación, con fuentes explícitas.
- `sources.json`: **68 semillas web oficiales**, incluidas referencias detalladas sobre NFC/RFID/IR y Sub-GHz.
- CLI: `flipper-rag protocols list|validate|index`, `sync --protocols`, `search --protocol ID`, `ask --protocol ID`.
- API: `GET /api/protocols`, `GET /api/protocols/{id}` y argumento opcional `protocol` en `POST /api/search`/`POST /api/ask`.
- UI: selector para protocolos individuales.
- Tests de API/CLI/catálogo/retrieval con un benchmark offline dedicado, incorporado en CI.

## Precisión de los alcances

| Alcance (`evidence_scope`) | Qué permite afirmar | Qué NO permite afirmar |
| --- | --- | --- |
| `file-format-or-tech-spec` | Citado en documentación HF NFC o formato | Emulación o lectura de contenido protegido en todos los casos |
| `official-reader-list` | Enumerado entre protocolos LF para lectura | Escritura/emulación universal |
| `file-format-listed` | Identificador admitido en formato IR o iButton | Compatibilidad con todos los dispositivos finales |
| `dev-source-registry` | Nombre presente en registro Sub-GHz de rama `dev` | Soporte en release instalada, licencia TX, replay exitoso |
| `official-hardware-or-protocol-doc` | Bus/perfil especificado por proveedor | Disponibilidad con cualquier hardware/firmware |

El registro usa `trust=local` al indexar las explicaciones editoriales. Las fuentes originales tienen URL oficial, pero los resúmenes **no se reetiquetan como documentación oficial**. Se registra `firmware_channel=unversioned` y la búsqueda `--firmware-version ... --version-policy strict` los excluye. De este modo no se atribuye compatibilidad a revisiones futuras o antiguas.

Los 118 registros **no son 118 capacidades verificadas de emulación**. Un gran número de registros Sub-GHz procede de un inventario de la rama `dev` y debe validarse contra una release de interés.

## Procedimiento de instalación y evaluación

```bash
python -m pip install -e '.[dev]'
export RAG_EMBED_PROVIDER=none RAG_CHAT_PROVIDER=none
flipper-rag protocols validate
flipper-rag protocols list --family nfc
flipper-rag protocols index
flipper-rag ingest --path knowledge/protocols --source-id guias-protocolos
flipper-rag search 'diferencias de ISO14443-4A' --protocol iso-14443-4a --mode lexical
flipper-rag eval --file benchmarks/protocols_offline.jsonl --mode lexical --top-k 6
```

Para obtener datos actualizados del firmware real: `flipper-rag sync --web --crawl`, `flipper-rag sync --firmware-ref <VERSION> --with-code`; usa la revisión publicada exacta del dispositivo y filtra por versión en la consulta. Las fichas editoriales no acreditan compatibilidad de una release.

## Referencias primarias revisadas — 22 nov. 2026

- [Hardware y familias HF/LF/IR/iButton](https://docs.flipper.net/zero/development/hardware/tech-specs)
- [NFC `.nfc` y diferencias ISO14443/MIFARE](https://developer.flipper.net/flipperzero/doxygen/nfc_file_format.html)
- [RFID LF — lista oficial de lectura](https://docs.flipper.net/zero/rfid/read)
- [Formato `.rfid`](https://developer.flipper.net/flipperzero/doxygen/lfrfid_file_format.html)
- [Infrared parsed/RAW `.ir`](https://developer.flipper.net/flipperzero/doxygen/infrared_file_format.html)
- [iButton `.ibtn`](https://developer.flipper.net/flipperzero/doxygen/ibutton_file_format.html)
- [Sub-GHz `.sub` y RAW](https://developer.flipper.net/flipperzero/doxygen/subghz_file_format.html)
- [Lista Sub-GHz en firmware `dev` (no matriz de soporte release)](https://github.com/flipperdevices/flipperzero-firmware/blob/dev/lib/subghz/protocols/protocol_items.c)
- [Protocolo de módulos de expansión](https://developer.flipper.net/flipperzero/doxygen/expansion_protocol.html)
- [Frecuencias regionales](https://docs.flipper.net/zero/sub-ghz/frequencies)

**Límites:** sin auditoría de compatibilidad sobre el hardware real, sin benchmarks semánticos CrossEncoder en el corpus global, sin descargar documentos protegidos de terceros; la evaluación offline mide recuperación, no precisión factual de generación.
