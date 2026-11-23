# Diagnóstico estático de FAM y esquemas protobuf

El archivo `application.fam` declara módulos Flipper con `App(appid=..., apptype=FlipperAppType.EXTERNAL, ...)`. Aunque su sintaxis es Python, el Protocol Lab solo lo analiza con AST y nunca ejecuta código ni el sistema de compilación. Si el manifiesto incluye `fap_extbuild`, se advierte expresamente que existen comandos de compilación externos sin intentar ejecutarlos. Para verificar una aplicación real, usar uFBT y la versión SDK correspondiente.

Los ficheros `.proto` definen mensajes, servicios y enums de RPC. La prueba documental v0.9 comprueba existencia de sintaxis y equilibrio de llaves; no resuelve imports, números de campo de forma exhaustiva ni compilación. La validación semántica corresponde a protoc.

Fuentes: https://developer.flipper.net/flipperzero/doxygen/app_manifests.html ; https://protobuf.dev/programming-guides/proto3/ ; https://developer.flipper.net/flipperzero/doxygen/expansion_protocol.html
