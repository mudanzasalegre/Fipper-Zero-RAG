# v0.7 — Firmware Knowledge Graph: fuente de verdad, índices y límites

**Ámbito:** indexar firmware desde un repositorio Git local; no interactuar con Flipper Zero ni ejecutar código de los repositorios analizados. La finalidad es encontrar implementaciones, declaraciones, dependencias y cambios de API entre revisiones verificables por hash Git.

## Investigación: arquitectura del firmware oficial

El firmware oficial distribuye código en `applications/`, `applications_user/`, `furi/`, `lib/`, `targets/`, además de `assets/` y `documentation/`. Furi define primitivas de RTOS y servicios comunes; Furi HAL abstrae dispositivos. Los archivos `application.fam` son manifiestos Python con invocaciones `App(...)`; por seguridad este proyecto **analiza su AST sin ejecutarlos**. Las aplicaciones externas FAP no tienen acceso automáticamente a toda función presente en firmware: la lista de API exportada está en **`targets/f7/api_symbols.csv`**; el archivo marca cada símbolo con `+`, `-` o `?`, e incluye una versión mayor/menor de API. Las variaciones de API mayor pueden afectar la compatibilidad de las FAP. Este índice no compila ni verifica el firmware físicamente.

Referencias primarias:

- [Árbol de módulos del firmware](https://github.com/flipperdevices/flipperzero-firmware#project-structure)
- [Arquitectura Furi](https://developer.flipper.net/flipperzero/doxygen/app_dev_furi_api.html)
- [Manifiestos FAM](https://developer.flipper.net/flipperzero/doxygen/app_manifests.html)
- [FAP: versiones y tabla de símbolos](https://developer.flipper.net/flipperzero/doxygen/apps_on_sd_card.html)
- [Símbolos de la API FAP en el repositorio oficial](https://github.com/flipperdevices/flipperzero-firmware/blob/dev/targets/f7/api_symbols.csv)
- [Releases verificables](https://github.com/flipperdevices/flipperzero-firmware/releases)

## Modelo del grafo

Persistencia: tablas `fw_snapshots`, `fw_snapshot_refs`, `fw_files`, `fw_symbols`, `fw_references` y `fw_api_exports` en el mismo SQLite que el RAG (pero en tablas independientes). Cada snapshot se identifica por un **SHA de commit completo**. Los nombres de releases son aliases que apuntan a ese SHA; una actualización de `dev` da lugar a otro snapshot y **no sobrescribe** una release antigua. `fw_files` incluye SHA-256 del contenido; los resultados llevan ruta, línea, scope y URL a `blob/<commit>/...#L...` cuando el origen local declara el remoto oficial.

Nodos de símbolos: `function`, `declaration`, `macro`, `typedef`, `struct`, `enum`, `union`, `app`; entradas para ficheros. Aristas `calls`, `includes`, `requires_app`, `provides_app`, `conflicts_with`. Cada arista tiene `resolution` (`resolved`, `ambiguous`, `unresolved`, `declaration_only`), posición y tipo de evidencia. Se prefiere enlazar llamadas con una definición en el mismo fichero; después con una **única** definición global; nunca se resuelve automáticamente una función estática de otro fichero. Los includes ambiguos no se adjudican a un fichero arbitrario.

### Diferencias con un AST semántico compilado

La extracción C/C++ integrada es conservadora y no ejecuta preprocesador ni compilador. Detecta declaraciones/definiciones de funciones de sintaxis habitual, macros, tipos e invocaciones con nombre. **No** demuestra ruta de ejecución, ABI real, resolución de sobrecargas C++, funciones indirectas, configuración de `#if`, macros expandidas ni símbolos enlazados; el enlace de llamadas es heurístico. Los manifiestos FAM se procesan con `ast.parse` y `ast.literal_eval` solamente, evitando importar o ejecutar código ajeno. Una ampliación futura puede añadir Tree-sitter/clangd opcional, conservando el backend seguro actual.

La columna `status='+'` de `fw_api_exports` es evidencia explícita de exportación en el CSV de ese snapshot. Las entradas `-` o `?` **no** se consideran exportadas. La comparación mantiene **dos informes separados**: modificaciones en el código y cambios en símbolos exportados; si falta `api_symbols.csv` en cualquiera de los dos snapshots, el estado de comparación API es `unavailable-missing-api-symbols`.

## Instalación y uso local

```bash
# Clona tu repositorio RAG y prepara el entorno
python -m pip install -e '.[dev]'

# Obtén el firmware oficial sin incluirlo en tu propio GitHub
# Se necesita conexión a GitHub en tu PC.
git clone --filter=blob:none https://github.com/flipperdevices/flipperzero-firmware.git data/firmware-upstream
cd data/firmware-upstream
git fetch --tags origin
cd ../..

# Indexa dos etiquetas existentes (comprueba los nombres con git tag --list)
flipper-rag firmware index --repo data/firmware-upstream --ref 1.5.0
flipper-rag firmware index --repo data/firmware-upstream --ref 1.5.1
flipper-rag firmware snapshots
flipper-rag firmware symbols --ref 1.5.1 --query furi_thread --kind function
flipper-rag firmware symbols --ref 1.5.1 --query furi_ --exported-only
flipper-rag firmware refs --ref 1.5.1 --name furi_record_open
flipper-rag firmware graph --ref 1.5.1 --name furi_record_open --depth 2
flipper-rag firmware exports --ref 1.5.1 --query furi
flipper-rag firmware compare --before 1.5.0 --after 1.5.1

# Opción: crear documentos breves de funciones para el recuperador existente
flipper-rag firmware rag-index --ref 1.5.1 --limit 1500
flipper-rag reembed
uvicorn flipper_rag.api:app --host 127.0.0.1 --port 8000
```

Abre `/firmware` para navegar por símbolos, referencias y diferencias; `/api/docs` muestra los endpoints de consulta. Este servicio no expone un endpoint de indexación remota ni instala firmware.

**Atención a clones superficiales:** el comando antiguo `sync` puede usar clones `--depth 1` que no tengan tags históricas; para comparar releases usa un clon con las dos etiquetas disponibles y objetos completos. `git fetch --tags` puede requerir ampliar el historial antes de acceder a determinadas versiones.

### CLI de firmware

| Subcomando | Función |
| --- | --- |
| `firmware index --repo ... --ref <tag>` | Ingiere un snapshot inmutable, límites por archivos y tamaño. Puede usar `--index-rag`. |
| `firmware snapshots` | Enumera commits, aliases Git, cobertura y versión SDK. |
| `firmware symbols` | Filtro por nombre, tipo, ruta y exportación FAP. |
| `firmware symbol --id ...` | Ficha de símbolo por ID, enlaces de entrada/salida y coincidencias API. |
| `firmware refs` | Referencias a un nombre, incluidas candidatas sin resolver. |
| `firmware graph` | Vecindario de referencias resueltas, profundidad acotada. |
| `firmware exports` | API FAP en `api_symbols.csv` para una revisión exacta. |
| `firmware compare` | Modificaciones de código y diferencias API; requiere snapshots completos. |
| `firmware rag-index` | Resume símbolos hacia el RAG híbrido existente, sin copiar el firmware íntegro. |

### Endpoints

- `GET /api/firmware/snapshots`
- `GET /api/firmware/symbols?ref=...&query=...&kind=...&exported_only=true`
- `GET /api/firmware/symbols/{symbol_id}?ref=...`
- `GET /api/firmware/references?ref=...&name=...`
- `GET /api/firmware/graph?ref=...&name=...&depth=...`
- `GET /api/firmware/exports?ref=...&status=%2B`
- `GET /api/firmware/compare?before=...&after=...`

**Seguridad:** los refs Git solo permiten etiquetas de versión, `dev` o SHAs de 40 caracteres y se usan con argumentos de subprocess, sin shell. Se aplican límites a la cantidad/tamaño de archivos y se ignoran rutas fuera de las raíces del firmware. No se extraen blobs, volcados de señales, keys o binarios en GitHub. Las salidas se generan desde información de origen local; un remoto Git declarado como oficial no es una prueba criptográfica de autenticidad de un clon modificado. Para auditoría, contrasta la URL a SHA con GitHub oficial.

## Cómo evaluar

- `tests/test_firmware_v07.py`: commits reales creados en un repositorio temporal, tags, API exports, dependencias FAM, referencias ambiguas, seguridad del parser, comparación de firmas, endpoints.
- `python -m pytest -q`: suite completa v0.1–v0.7 sin red y sin dispositivos.
- `python -m compileall -q src`: carga y sintaxis.
- El benchmark usa fixtures pequeños; **no** garantiza exactitud de llamadas C del firmware completo ni compatibilidad del dispositivo.

## Limitaciones conocidas

1. C/C++: reglas heurísticas; un analizador semántico basado en compilación aumentaría precisión en macros y C++.
2. La disponibilidad de exports no demuestra que una FAP binaria particular arranque en el firmware del usuario. La compatibilidad depende de su versión API y otros requisitos de la app.
3. El RAG recupera documentos de síntesis solo cuando ejecutas `firmware rag-index` o `firmware index --index-rag`; el código fuente íntegro se consulta en GitHub por SHA y no se redistribuye.
4. Los datos se construyen en local cuando se indexa el firmware: los índices SQLite y los clones de firmware quedan fuera del repositorio Git por `.gitignore`.
5. El snapshot `complete=0` implica que se excluyeron archivos sobredimensionados o binarios; la comparación de snapshots incompletos falla salvo autorización explícita `--allow-partial`.
