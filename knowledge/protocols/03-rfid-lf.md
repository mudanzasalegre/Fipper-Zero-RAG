# RFID LF 125 kHz: familias, codificación y formatos

RFID de baja frecuencia opera en torno a 125 kHz y no debe confundirse con NFC a 13,56 MHz. Los transpondedores LF pueden tener esquemas de identificación diferentes: EM4100, HID H10301, Indala 26, AWID, FDX-A y FDX-B son ejemplos de familias listadas oficialmente. Los datos de una tarjeta se interpretan según el tipo de protocolo. El archivo `.rfid` describe un `Key type` y datos hexadecimales, no demuestra interoperabilidad de un sistema completo.

## Modulación vs protocolo
ASK/OOK y PSK describen codificación o modulación, no identifican por sí solos el formato de credencial. La documentación de depuración describe la lectura RAW de señales LF; una grabación RAW no tiene por qué ser una lectura decodificada correcta. La simple presencia en la lista de lecturas no certifica que pueda escribirse en cualquier etiqueta.

Referencias: https://docs.flipper.net/zero/rfid/read ; https://developer.flipper.net/flipperzero/doxygen/lfrfid_file_format.html ; https://developer.flipper.net/flipperzero/doxygen/lfrfid_raw.html
