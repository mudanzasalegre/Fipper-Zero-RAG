# Método de comprobación de un protocolo en Flipper Zero

1. Identifica la **familia y la capa**: NFC vs LF RFID vs radio Sub-GHz vs IR vs iButton vs interfaz cableada.
2. Busca la ficha curada y abre su enlace oficial. El registro del RAG es una ayuda de localización, nunca una lista de capacidades garantizadas.
3. Comprueba el código fuente o la documentación de la **release** exacta, no solo `dev`. Las modificaciones comunitarias se muestran separadas.
4. Distingue lectura/identificación, decodificación, guardado, emulación, transmisión y escritura: una operación no demuestra las demás.
5. Para transmisión radio, revisa banda, región, potencia y permisos. Para credenciales, usa únicamente sistemas propios o autorizados.
6. Anota resultado verificable, versión, fuente y fecha. Si falta evidencia, responde «no verificado».

Los archivos de datos del Flipper usan formatos `.sub`, `.nfc`, `.rfid`, `.ir` e `.ibtn` con campos y formatos de versión específicos. Una extensión de archivo no determina por sí sola autenticidad ni seguridad.

Referencias: https://developer.flipper.net/flipperzero/doxygen/file_formats.html ; https://docs.flipper.net/zero/development/hardware/tech-specs
