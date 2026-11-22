# Desarrollo oficial de aplicaciones

## C y FAP

Flipper Zero permite desarrollar aplicaciones externas en C/C++. El archivo `application.fam` describe metadatos de la aplicación, mientras que FAP es el paquete ejecutable cargado desde la tarjeta microSD. Para crear, compilar, depurar y publicar aplicaciones, utiliza la guía oficial: https://developer.flipper.net/flipperzero/doxygen/applications.html.

La herramienta uFBT simplifica la construcción de aplicaciones y descarga las dependencias de compilación correspondientes al firmware. Un cambio en la API de firmware puede requerir recompilar la aplicación: verifica su compatibilidad con la versión instalada.

## JavaScript

El firmware incluye un motor JavaScript orientado a microcontroladores, distinto del JavaScript de los navegadores. Puede trabajar con ciertos módulos proporcionados por el firmware (almacenamiento, GPIO, interfaz gráfica, UART). Documentación: https://developer.flipper.net/flipperzero/doxygen/js.html.

## Herramientas de diagnóstico

La CLI oficial permite consultar registros y diagnosticar el dispositivo a través de una conexión compatible. La documentación está en https://docs.flipper.net/zero/development/cli. Ante un problema, anota versión de firmware, modelo, pasos de reproducción y mensajes de error.
