# Flipper Protocol Lab: diagnóstico estructural versus soporte real

Un archivo .sub, .nfc, .rfid, .ir o .ibtn puede tener una cabecera correcta y seguir sin ser utilizable en una versión concreta del firmware, o en un dispositivo concreto. El análisis v0.9 comprueba campos, tipos y algunas invariantes documentadas, no autentica tarjetas ni transmite señales. Una entrada en el registro de código de desarrollo no demuestra soporte en la release instalada.

Reglas: primero identificar extensión, Filetype y Version, después campos obligatorios y longitudes según formato. Registrar siempre el documento oficial utilizado. Los datos capturados se tratan como información sensible: un informe documenta exclusivamente si existen, si tienen sintaxis correcta y su longitud/contaje, no sus valores. El campo `firmware_channel=unversioned` no debe convertirse en una afirmación de compatibilidad.

Fuentes: https://developer.flipper.net/flipperzero/doxygen/file_formats.html ; https://github.com/flipperdevices/flipperzero-firmware/releases
