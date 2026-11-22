# iButton: Dallas 1-Wire, Cyfral y Metakom

La familia iButton utiliza contactos físicos; Dallas 1-Wire define un bus y diversos dispositivos DS199x, mientras que Cyfral y Metakom son familias de llaves con formatos distintos. El archivo `.ibtn` puede contener `Rom Data`, `Sram Data`, `Eeprom Data` o `Data` según el protocolo. `DSGeneric` permite representar una ROM de dispositivos Dallas desconocidos sin verificar todos sus datos; no es lo mismo que soporte completo.

No confundir iButton 1-Wire con RFID de 125 kHz aunque ambos puedan usarse como identificadores de acceso. Distinguir lectura, emulación, soporte de memoria y escritura según dispositivo.

Referencias: https://docs.flipper.net/zero/ibutton ; https://developer.flipper.net/flipperzero/doxygen/ibutton_file_format.html
