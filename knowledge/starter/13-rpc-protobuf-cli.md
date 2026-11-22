# CLI, RPC y Protobuf

Flipper dispone de consola y mecanismos de RPC para herramientas de desarrollo y aplicaciones compañeras. Los mensajes RPC y esquemas Protobuf son contratos de interfaz: deben contrastarse con los archivos `.proto` del commit exacto. Para depurar problemas, comprobar conectividad USB, permisos del puerto y estado de la aplicación en el equipo.

Las operaciones que modifican archivos del equipo o interactúan con hardware real deben gestionarse desde herramientas explícitas, no desde una respuesta generada por el RAG. El asistente de este proyecto solo busca, cita y explica documentos.

Referencias: https://docs.flipper.net/zero/development/cli ; https://github.com/flipperdevices/flipperzero-protobuf
