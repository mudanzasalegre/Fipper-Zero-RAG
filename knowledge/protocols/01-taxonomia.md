# Taxonomía de protocolos Flipper Zero

## Separar tecnología, protocolos, datos y funciones
NFC 13,56 MHz, RFID LF 125 kHz, Sub-GHz, infrarrojos, iButton y buses GPIO son familias tecnológicas diferentes. Una **capa física** (frecuencia, modulación, antena, cable) no es el **formato lógico** del mensaje; ambos son distintos de las capacidades de la aplicación (leer, identificar, decodificar, guardar, emular, escribir o transmitir). Un archivo `.nfc`, `.rfid`, `.sub`, `.ir` o `.ibtn` codifica información en un formato propio de Flipper, no constituye por sí solo un protocolo universal.

## Evidencia y compatibilidad
El catálogo local de protocolos es una guía de navegación hacia fuentes oficiales. Un nombre en una cabecera o en un registro de `dev` no prueba que la versión de firmware del usuario pueda utilizar todas sus funciones. Para confirmar comportamiento, combina documentación de hardware, código en **tag** de firmware exacto, pruebas de laboratorio y requisitos legales. No extrapoles funciones entre forks ni entre releases.

Referencias: https://docs.flipper.net/zero/development/hardware/tech-specs ; https://developer.flipper.net/flipperzero/doxygen/file_formats.html
