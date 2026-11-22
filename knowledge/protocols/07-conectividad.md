# Interfaces digitales: GPIO, UART, I2C, SPI y expansión

La cabecera GPIO permite conectar equipos periféricos con niveles eléctricos compatibles (la lógica general es 3,3 V). UART transmite bytes asíncronos y requiere velocidad compatible y referencia de masa; SPI e I2C son buses diferentes con su propia temporización y cableado. Hay que verificar alimentación y pinout antes de conectar hardware.

El protocolo de módulos de expansión define mecanismos de detección, negociación de baudrate, intercambio de tramas con checksum y transporte de mensajes RPC. RPC utiliza mensajes Protobuf en el ecosistema Flipper, mientras que UART es un medio físico de transferencia: no son sinónimos. Bluetooth LE y USB tienen perfiles y modos distintos, cuyo soporte efectivo requiere comprobar firmware.

Referencias: https://docs.flipper.net/zero/gpio-and-modules ; https://developer.flipper.net/flipperzero/doxygen/expansion_protocol.html ; https://docs.flipper.net/zero/development/hardware/tech-specs
