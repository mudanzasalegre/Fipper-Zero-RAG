# v0.8 — Development Assistant: Furi, FAP, mJS y compilaciones de prueba

**Estado:** implementación local (sin dispositivo) y automatización opcional de compilación real con uFBT. El proyecto no controla ni flashea dispositivos; esta funcionalidad no es un sandbox para código desconocido.

## Fuentes primarias examinadas — 22 noviembre 2026

| Tema | Referencia oficial | Hecho verificable |
|---|---|---|
| Furi, aplicaciones y arquitectura | https://developer.flipper.net/flipperzero/doxygen/app_dev_furi_api.html | Furi ofrece servicios, hilos, objetos y primitivas de memoria; usar versiones SDK compatibles |
| GUI en C | https://developer.flipper.net/flipperzero/doxygen/app_dev_gui.html | Dialogs / ViewPort y ciclo de vida con servicios registrados |
| Manifest FAM | https://developer.flipper.net/flipperzero/doxygen/app_manifests.html | `application.fam` declara `App(appid=..., apptype=FlipperAppType.EXTERNAL, entry_point=...)` |
| FAP | https://developer.flipper.net/flipperzero/doxygen/apps_on_sd_card.html | Los FAP son ejecutables ELF con metadata/API del SDK; compilar no demuestra funcionamiento en el dispositivo |
| uFBT oficial | https://github.com/flipperdevices/flipperzero-ufbt/blob/dev/README.md | `python -m pip install ufbt`, `ufbt` compila en proyecto y genera `.fap` bajo `dist/`, SDK `release` por defecto |
| JavaScript nativo | https://developer.flipper.net/flipperzero/doxygen/js_about_js_engine.html | Runtime mJS con limitaciones: **no es Node.js ni navegador** |
| EventLoop | https://developer.flipper.net/flipperzero/doxygen/js_event_loop.html | Temporizadores y `subscribe`: callback recibe valores de estado extra; no asumir closures JS estándar |
| GPIO JS | https://developer.flipper.net/flipperzero/doxygen/js_gpio.html | `event_loop` se carga antes de `gpio`; `Pin.read()` requiere entrada digital |
| Notificaciones JS | https://developer.flipper.net/flipperzero/doxygen/js_notification.html | `require("notification")`, `.success()` |
| TypeScript SDK | https://developer.flipper.net/flipperzero/doxygen/js_developing_apps_using_js_sdk.html | `npx @flipperdevices/create-fz-app@latest`: editor TypeScript + transpilador; no subir `.ts` al motor mJS como `.js` |
| Símbolos exportados | https://github.com/flipperdevices/flipperzero-firmware/blob/dev/targets/f7/api_symbols.csv | `+` denota exportación de símbolo para FAP en el snapshot: no implica compatibilidad en otros firmware |

No se copian implementaciones de terceros; los ejemplos son síntesis educativas y remiten a sus fuentes. El repositorio no distribuye el SDK ni los ejecutables del firmware.

## Componentes implementados

- `src/flipper_rag/data/development_catalog.json`: catálogo original de **7 plantillas** y **7 guías**, enlaces oficiales validados al cargar.
- `src/flipper_rag/data/dev_templates/`: **3 aplicaciones FAP C** (Dialogs, ViewPort/Input, FuriString/Log) y **4 scripts mJS** (Hello, EventLoop timer, Notification, GPIO read-only).
- `src/flipper_rag/development.py`: generador seguro de proyectos, validación estática FAM con `ast.parse/ast.literal_eval`, comprobaciones C, mJS, y build opt-in.
- `src/flipper_rag/development_cli.py`: `flipper-rag dev`.
- `src/flipper_rag/development_api.py`: endpoints **de consulta y validación**; no compilan, descargan SDK, ni ejecutan scripts.
- `/development`: panel web con biblioteca de código, guías y validador inline; renderizado con `textContent` (sin HTML de usuario).
- `dev index`: añade las síntesis originales al recuperador híbrido existente con `trust=local`, `firmware_channel=unversioned`.
- `.github/workflows/development-build.yml`: smoke build **manual (`workflow_dispatch`)** con uFBT real, tres FAP, comprobación del artifact `.fap` y upload de artefactos 7 días.

## Inicio rápido (Windows PowerShell)

```powershell
py -m pip install -e ".[dev]"
flipper-rag dev templates
flipper-rag dev guides
flipper-rag dev scaffold --template furi-dialog --appid demo_dialog --output ./demo_dialog
flipper-rag dev validate --project ./demo_dialog
flipper-rag dev build --project ./demo_dialog        # SOLO PLAN; no ejecuta
py -m pip install ufbt
flipper-rag dev build --project ./demo_dialog --execute
```

En Linux/macOS sustituye `py` por `python3`. La compilación real requiere acceso a los paquetes SDK correspondientes si no están en caché. Para determinar el canal del SDK, usa `ufbt update --channel=release`; para actualizar una rama/tag, consulta la documentación oficial, no adivines la disponibilidad de una release.

Scripts nativos mJS (no necesitan compilación C):

```bash
flipper-rag dev scaffold --template js-timer --appid demo_timer --output ./demo_timer
flipper-rag dev validate --project ./demo_timer
# Copia manualmente ./demo_timer/main.js al dispositivo en /ext/apps/Scripts/
```

Si buscas **TypeScript con autocompletado y empaquetado oficial**, sigue el tutorial del SDK y crea un proyecto con `npx @flipperdevices/create-fz-app@latest`. Se trata de una herramienta distinta al script mJS directo.

## Compilaciones reproducibles de prueba

```bash
mkdir -p data/fap-smoke
flipper-rag dev smoke --output data/fap-smoke                 # dry-run, crea ejemplos y valida
# Para compilación real usa un directorio vacío distinto:
mkdir -p data/fap-smoke-real
flipper-rag dev smoke --output data/fap-smoke-real --execute
```

El comando de compilación **solo** invoca el ejecutable uFBT con `argv=[path_del_ejecutable]`, directorio actual del proyecto y timeout 30–900 segundos. No usa `shell=True`, `launch`, `flash_usb` ni otras acciones de dispositivo. Valida el manifiesto antes. Los resultados incluyen return code, duración, rutas/tamaños/SHA-256 de `.fap` encontrados en `dist`, y salidas truncadas/saneadas. La repetición de una compilación puede generar el mismo hash y continuar siendo correcta; el campo `content_changed` lo registra.

Un resultado `passed` acredita que el proceso uFBT ha salido con código 0 y existe al menos un `.fap` en `dist`. **No** acredita pruebas en el dispositivo real, autenticidad del SDK descargado, compatibilidad con una release diferente ni seguridad de código externo.

### GitHub Actions

En **Actions → Development assistant - real FAP smoke build → Run workflow** puedes lanzar el workflow de compilación real sobre `main`. El CI estándar valida `pytest` y sintaxis, **no descarga el SDK**: esa es la razón de mantener el smoke build real como flujo separado, explícito. El workflow requiere acceso de GitHub Actions a los distribuidores oficiales; si falla por red o por una API modificada, hay que examinar el log y los errores de compilador.

## API para integrar en el RAG o clientes locales

- `GET /development`: interfaz web.
- `GET /api/development/templates` y `/{id}`: inventario y código de ejemplo.
- `GET /api/development/guides` y `/{id}`: síntesis con enlaces oficiales.
- `POST /api/development/validate`: JSON `{ "kind":"mjs", "files":{"main.js":"print('test');"} }`; también FAP con `application.fam` y fuentes `.c`. Máximo 24 archivos y 64 KiB por solicitud; no guarda ni ejecuta el proyecto permanentemente.
- **No existe `POST /api/development/build`**. La ejecución se restringe a CLI local por decisión explícita del usuario.

## Límites de validación

El parser FAM solo admite **un `App()` literal** con argumentos estáticos. Rechaza imports, expresiones ejecutables, plantillas de build con hooks y librerías privadas en el runner. El proyecto original podría compilar con uFBT normal con un manifiesto más elaborado, pero se excluye voluntariamente del modo automatizado de pruebas.

La validación C comprueba `appid`, `FlipperAppType.EXTERNAL`, `entry_point`, glob de fuentes, tamaño de stack, algunos patrones de limpieza y nombres de símbolos exportados del snapshot v0.7 opcional. **No usa compilador/AST real de C**. Cuando se solicita `--firmware-ref` y faltan símbolos exportados, devuelve «no verificado» en vez de afirmar que el código será incompatible.

La validación mJS es heurística: balance de delimitadores, lista de módulos reconocidos, orden de `event_loop`/`gpio` y detección de algunas APIs de navegador/Node. **No ejecuta mJS ni transpila TS**. Una validación correcta no garantiza que el script arranque en un firmware concreto. La comprobación final exige pruebas en un Flipper propio y SDK compatible.

**Seguridad:** la compilación local no es un sandbox; el SDK y archivos de build de terceros podrían ejecutar procesos y descargar dependencias. Solo usar `--execute` con proyectos y herramientas en los que confíes. No introducir credenciales ni señales privadas en la API; el navegador trabaja únicamente contra el servidor local por defecto.

## Evaluación realizada

`tests/test_development_v08.py` cubre las siete plantillas, prevención de ejecución del FAM durante validación, rutas y symlinks, C/Furi, mJS, comprobación de exports, endpoints locales, CLI, indexación RAG, dry-run y ejecución de un **uFBT simulado** en subprocess. El binario real de uFBT y la compilación cruzada quedan pendientes hasta ejecutar el workflow manual o un build local con toolchain oficial.
