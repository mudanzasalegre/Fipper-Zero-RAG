# Hardware, almacenamiento y arquitectura

El Flipper Zero integra microcontrolador y periféricos para RF Sub-GHz, NFC, RFID de baja frecuencia, infrarrojos, iButton y pines GPIO. Cada subsistema tiene capacidades y restricciones independientes; no asumir que leer un formato implica poder emular todos sus mecanismos criptográficos. La tarjeta microSD almacena recursos, bases de datos y archivos de usuario. Comprobar siempre la versión de firmware, tarjeta y aplicación que interviene.

El firmware oficial proporciona abstracciones HAL y Furi Core para tareas, eventos, memoria y servicios. No confundir el hardware del Flipper Zero con accesorios externos como la Wi-Fi Development Board: un componente opcional no equivale a una radio Wi-Fi integrada en el dispositivo.

Referencias: https://docs.flipper.net/zero/development/hardware/tech-specs ; https://developer.flipper.net/flipperzero/doxygen/app_dev_furi_api.html ; https://github.com/flipperdevices/flipperzero-firmware
