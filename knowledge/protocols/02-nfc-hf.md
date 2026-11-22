# NFC de alta frecuencia: ISO 14443, ISO 15693 y familias de tarjetas

## Capa física frente a familias comerciales
El transceptor ST25R3916 trabaja a 13,56 MHz. ISO 14443 A y B tienen mecanismos de selección diferentes; ISO 14443-4A define intercambio de bloques sobre tipo A. En los formatos `.nfc` se registran datos como UID, ATQA, SAK y ATS, cuando corresponden. ISO 15693/NFC-V es otra familia, y NFC-F/FeliCa difiere de ambas. No deduzcas el tipo completo únicamente a partir del UID ni equipares lectura con descifrado de información protegida.

## MIFARE y NTAG
MIFARE Classic organiza datos por sectores y bloques; MIFARE Ultralight y NTAG por páginas; DESFire maneja aplicaciones y archivos con distintas políticas de acceso. Los modelos de NTAG y el estado de autenticación influyen en qué datos pueden extraerse. El firmware actual puede evolucionar; consulta la documentación correspondiente al tag y release. Las operaciones con credenciales y tarjetas ajenas quedan fuera de este corpus educativo.

Referencias: https://developer.flipper.net/flipperzero/doxygen/nfc_file_format.html ; https://docs.flipper.net/zero/nfc/read ; https://docs.flipper.net/zero/development/hardware/tech-specs
