# Sub-GHz: radio, modulaciones, protocolo y restricciones

El transceptor CC1101 integrado puede trabajar en bandas de frecuencia indicadas por el fabricante, pero las **frecuencias habilitadas para transmitir dependen de la región**. El menú de información regional debe cotejarse con la normativa aplicable y con las condiciones de uso del dispositivo.

## Señal RAW y datos interpretados
ASK/OOK y FSK describen modulaciones de radio. Un archivo `.sub` incluye metadatos de frecuencia y preset, seguidos de datos de protocolo o una secuencia de tiempos `RAW_Data`. Un registro de tiempos no identifica necesariamente un protocolo ni permite repetir exitosamente un comando. Algunos sistemas utilizan códigos cambiantes, sincronización o autenticación; no son equivalentes a un mando de código fijo.

## Registro del firmware
El archivo `lib/subghz/protocols/protocol_items.c` de la rama `dev` enumera diversos protocolos como Princeton, KeeLoq y otras familias comerciales. Esta lista es **del código de desarrollo** y por sí sola no certifica el soporte de una release concreta, capacidad de transmisión o un derecho de uso. No almacenar capturas, llaves de fabricante o datos confidenciales en el repositorio.

Referencias: https://docs.flipper.net/zero/sub-ghz ; https://docs.flipper.net/zero/sub-ghz/frequencies ; https://developer.flipper.net/flipperzero/doxygen/subghz_file_format.html ; https://github.com/flipperdevices/flipperzero-firmware/blob/dev/lib/subghz/protocols/protocol_items.c
