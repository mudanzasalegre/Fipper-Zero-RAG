# Investigación técnica y fuentes — 2026-11-22

## Criterio de selección

1. Documentación de Flipper Devices (`docs.flipper.net`, `developer.flipper.net`) como fuente normativa del comportamiento oficial.
2. Firmware oficial (`flipperdevices/flipperzero-firmware`, rama dev) para APIs, formatos y algoritmos; atribuir SIEMPRE el commit.
3. Herramientas oficiales: uFBT (build de apps), protobuf (esquema RPC) y good-faps (ejemplos reales).
4. Catálogo oficial: metadatos y manifiestos; NO presuponer que contiene el código de todas las aplicaciones.
5. Firmware comunitario y repositorios de terceros: **no se indexan de forma automática** porque podrían diferir del dispositivo oficial o tener licencias específicas. Añadir de forma separada tras verificar procedencia y permisos.

## Cobertura

- Interfaces: NFC, RFID LF, Sub-GHz, IR, iButton, GPIO, BLE, USB, microSD.
- Software: Furi, FBT, uFBT, FAP, FAM, JavaScript, RPC/protobuf, Apps Catalog, configuración y actualizaciones.
- Firmware: controladores y bibliotecas según extensiones y límites de `sources.json`.
- Ámbitos sujetos a autorizaciones legales: la documentación se usa solo en entornos propios, educativos o expresamente autorizados.

## Referencias base

- https://docs.flipper.net/zero
- https://developer.flipper.net/flipperzero/doxygen/
- https://developer.flipper.net/flipperzero/doxygen/applications.html
- https://developer.flipper.net/flipperzero/doxygen/app_manifests.html
- https://developer.flipper.net/flipperzero/doxygen/fbt.html
- https://github.com/flipperdevices/flipperzero-firmware
- https://github.com/flipperdevices/flipper-application-catalog
- https://github.com/flipperdevices/flipperzero-ufbt
- https://github.com/flipperdevices/flipperzero-protobuf
- https://github.com/flipperdevices/flipperzero-good-faps

## Limitaciones y validación

No se redistribuyen aquí repositorios de terceros ni el índice derivado. La cobertura real depende de ejecución `sync` con internet y acceso a Git; cada origen informa el número de archivos procesados. Un RAG indexado sobre la rama `dev` no representa necesariamente el firmware `release` instalado. Reejecutar el benchmark tras cada actualización y contrastar citas con las fuentes originales.
