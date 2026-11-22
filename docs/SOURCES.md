# Fuentes, licencias y procedencia

## Fuentes declaradas por defecto

| Origen | URL | Forma de incorporación | Tipo |
|---|---|---|---|
| Manual de usuario | https://docs.flipper.net/zero | HTML, semillas + crawler limitado, bajo permiso de robots.txt | Manual |
| Developer Docs | https://developer.flipper.net/flipperzero/doxygen/ | HTML, secciones seleccionadas | Referencias de APIs |
| Firmware oficial | https://github.com/flipperdevices/flipperzero-firmware | Clon de rama `dev`, commit registrado | Markdown, RST, opcional C/H |
| Apps Catalog | https://github.com/flipperdevices/flipper-application-catalog | Clon de rama `main`, commit registrado | Manifiestos, documentos |
| Notas locales | `knowledge/starter/` | Ficheros propios, sin red | Markdown |

El catálogo de aplicaciones **no contiene necesariamente el código fuente de todas las apps**; normalmente referencia manifiestos, metadatos o enlaces a otros repositorios. No inferir la implementación completa de una app a partir de su ficha.

## Reglas de ingesta

- URL web: solo HTTPS de `docs.flipper.net` o `developer.flipper.net`; se verifica robots.txt, tamaño máximo 2 MB y respuesta HTML.
- Git: solo las rutas glob de `sources.json`, con límite por fichero 128 kB y máximo por repositorio (`max_files`). Se evita indexar binarios y archivos con codificación no UTF-8.
- Archivos locales: `.md`, `.txt`, `.rst`, `.c`, `.h`, `.json`; excluye por defecto carpetas distintas de las indicadas por el usuario.
- Cada documento conserva `source_id`, `title`, `url`, `category`, `revision`, `license`, hash de contenido y fecha de indexación.
- Las fuentes remotas no se distribuyen en este proyecto; si se publica o comparte la base derivada, revisar individualmente permisos, licencias y marcas.
- No añadir dumps de tarjetas, códigos de acceso, credenciales, capturas radio privadas, claves API ni información identificativa.

## Guía para ampliar

1. Editar `sources.json` con páginas oficiales válidas. URLs externas a las dos sedes permitidas requieren una revisión deliberada de `ALLOWED_DOC_HOSTS` en código y de sus condiciones de uso.
2. Cambiar categoría a una etiqueta pertinente: `nfc`, `firmware`, `gpio`, `javascript`, etc.
3. Indexar con `flipper-rag sync --web` o `--firmware`.
4. Validar `flipper-rag stats`, `flipper-rag search` y `flipper-rag eval`.
5. Regenerar embeddings si cambió el modelo: `flipper-rag reembed`.

## Fuentes oficiales adicionales (2026-11-22)

| Fuente | Enlace | Cobertura |
|---|---|---|
| uFBT | https://github.com/flipperdevices/flipperzero-ufbt | Compilación y depuración FAP |
| Flipper RPC Protobuf | https://github.com/flipperdevices/flipperzero-protobuf | Definiciones `.proto` del protocolo RPC |
| Official Good FAPs | https://github.com/flipperdevices/flipperzero-good-faps | Ejemplos C, H, JS, `application.fam` |

El catálogo es editable. La ingesta Git está deliberadamente restringida a la organización oficial `flipperdevices` y a HTTPS; revisar derechos antes de expandir a terceros.
