# Investigación de fuentes y alcance (22-11-2026)

Esta matriz describe **fuentes verificadas** de documentación y sus límites. Un RAG fiable no es una colección indiscriminada de dumps: importa la calidad, versión, licencia, procedencia y actualidad.

| Fuente | Cobertura | Autoridad / rama | Cómo se incorpora |
|---|---|---|---|
| [Manual de Flipper Zero](https://docs.flipper.net/zero) | Hardware, actualización, aplicaciones, Sub-GHz, NFC, RFID, IR, iButton, GPIO, U2F | Oficial, web viva | HTML, crawler acotado que respeta `robots.txt` |
| [Flipper Developer Docs](https://developer.flipper.net/flipperzero/doxygen/) | Furi/HAL, FBT, FAP, JS, formatos | Oficial, web viva | HTML, crawler acotado |
| [flipperzero-firmware](https://github.com/flipperdevices/flipperzero-firmware) | Código C, Furi, apps, controladores, documentos | Oficial, `dev` | Git, trazabilidad por SHA |
| [flipper-application-catalog](https://github.com/flipperdevices/flipper-application-catalog) | Manifiestos y metadatos de apps, no todo el código | Oficial, `main` | Git (YAML/JSON/Markdown) |
| [flipperzero-ufbt](https://github.com/flipperdevices/flipperzero-ufbt) | Compilación y prueba de apps FAP, toolchain | Oficial, `dev` | Git |
| [flipperzero-protobuf](https://github.com/flipperdevices/flipperzero-protobuf) | Esquemas RPC/Protobuf | Oficial, `dev` | Git |
| [qFlipper](https://github.com/flipperdevices/qFlipper) | Cliente de escritorio, interacción con dispositivo | Oficial, `dev` | Git |
| [flipperzero-good-faps](https://github.com/flipperdevices/flipperzero-good-faps) | Ejemplos de apps y SDK | Oficial, `dev` | Git |
| [awesome-flipperzero](https://github.com/djsime1/awesome-flipperzero) | Índice de recursos y comunidad | Comunidad, `main` | Solo Markdown, opt-in |
| [Unleashed Firmware](https://github.com/DarkFlippers/unleashed-firmware) | Diferencias documentales de firmware alternativo | Comunidad, `dev` | Solo Markdown, opt-in |
| [Momentum Firmware](https://github.com/Next-Flip/Momentum-Firmware) | Diferencias documentales de firmware alternativo | Comunidad, `dev` | Solo Markdown, opt-in |

## Hallazgos que afectan la calidad del RAG

1. El **Apps Catalog es principalmente de manifiestos**, no constituye una réplica del código de cada aplicación. Por eso se indexa como metadatos y hay que acudir a los repositorios concretos para investigar implementaciones.
2. **uFBT** permite construir aplicaciones sin compilar el firmware completo; FBT está asociado al árbol del firmware. Ambos se documentan por separado.
3. **Furi API** es la capa de servicios usada por el firmware. Es preferible consultar el archivo/commit exacto para que una respuesta de API no mezcle versiones.
4. Sub-GHz tiene **restricciones legales y técnicas regionales** para transmitir. No confundir capacidades de recepción con emisiones permitidas o emulación efectiva de cualquier sistema.
5. NFC y RFID de baja frecuencia son tecnologías diferentes. Disponer de una lectura no equivale a capacidad criptográfica o autorización para reproducir credenciales.
6. Los proyectos comunitarios pueden modificar funciones, límites y dependencias; no se deben citar como prueba de capacidades oficiales.
7. Las fuentes pueden cambiar después de esta investigación. Este proyecto conserva un `revision` Git cuando está disponible y exige ejecutar sincronización local para consultar cambios.

## Lo que deliberadamente NO se incorpora

Dumps de llaves, tarjetas, señales o mandos reales; repositorios masivos de capturas Sub-GHz, BadUSB malicioso, volcados privados y secretos. No se descargan automáticamente páginas externas a los dos dominios oficiales. Las fuentes comunitarias requieren una opción explícita.

## Propiedad intelectual

El código de esta aplicación tiene licencia MIT. **Esa licencia no se extiende a las fuentes externas.** Los documentos, ejemplos, firmware, esquemas y marcas de terceros pertenecen a sus autores y licencias. Su texto se recupera localmente, no se redistribuye en este repo ni en la base SQLite de Git. Antes de publicar corpus o pesos, revisar derechos de cada fuente.

## Limitaciones explícitas

- Una página indexada puede dejar de reflejar la versión de firmware que tengas. Comprueba las revisiones.
- La ingesta web depende de `robots.txt`, disponibilidad de red y estructura HTML. Puede haber páginas no accesibles sin JavaScript.
- La búsqueda vectorial por defecto realiza similitud de embeddings desde SQLite: ideal para corpus local mediano; índices enormes pueden requerir vector DB especializada.
- El resultado de un modelo generativo **puede ser incorrecto** incluso con citas. Verifica el texto original para cambios de firmware o tareas críticas.
