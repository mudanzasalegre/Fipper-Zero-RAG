# Diagnóstico seguro de formatos NFC, LF RFID e iButton

Los `.nfc` guardan información de identificación y campos específicos según el tipo de dispositivo; por ejemplo, ISO14443-3A documenta UID de 4/7 bytes, ATQA de 2 y SAK de 1 byte. Un UID no es prueba de autenticidad y una coincidencia de longitud no demuestra lectura completa ni emulación autorizada.

Los `.rfid` usan una cabecera y un campo `Key type`, seguido de `Data` en hexadecimal. Su valor es un identificador sensible y debe omitirse de informes técnicos. Los `.ibtn` modernos usan versión 2 y `Protocol`; Dallas usa ROM, mientras determinados modelos admiten SRAM/EEPROM, y Cyfral/Metakom guardan datos en `Data`. El formato v1 está obsoleto. No se validan secret keys ni protocolos criptográficos.

Fuentes: https://developer.flipper.net/flipperzero/doxygen/nfc_file_format.html ; https://developer.flipper.net/flipperzero/doxygen/lfrfid_file_format.html ; https://developer.flipper.net/flipperzero/doxygen/ibutton_file_format.html
