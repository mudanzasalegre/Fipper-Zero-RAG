# Análisis de ficheros de señales Sub-GHz e infrarrojos

En archivos `.sub`, `Filetype`, `Version`, `Frequency`, `Preset` y `Protocol` documentan la estructura. `Protocol: RAW` emplea campos RAW_Data repetibles de intervalos en microsegundos. `Protocol: BinRAW` organiza pares Bit_RAW y Data_RAW. El analizador verifica su estructura sin guardar ni difundir el contenido de capturas. No infiere legalidad de transmisión por la frecuencia ni validez de sistemas con rolling code.

En archivos `.ir`, cada bloque representa un botón: `type: parsed` usa `protocol`, `address`, `command`; `type: raw` usa frecuencia, duty_cycle y tiempos. El documento oficial limita a 1024 las duraciones de una señal raw en el formato de mando. Los archivos `.irtest` tienen matrices `parsed_array` para pruebas. Una señal interpretada no acredita que el mando físico responda.

Fuentes: https://developer.flipper.net/flipperzero/doxygen/subghz_file_format.html ; https://developer.flipper.net/flipperzero/doxygen/infrared_file_format.html
