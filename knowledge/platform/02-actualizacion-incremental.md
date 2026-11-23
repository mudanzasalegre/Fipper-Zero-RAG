# Actualizaciones incrementales y procedencia

`flipper-rag platform sync --web --local` consulta únicamente dominios oficiales permitidos, comprueba robots.txt y utiliza cabeceras ETag/Last-Modified. Una respuesta HTTP 304 aprovecha la copia textual local; una respuesta HTTP 200 verifica el hash del contenido antes de sustituir fragmentos. Se conservan referencias, procedencia, confianza y revisiones de Git. Las consultas web no ejecutan scripts descargados ni controlan el dispositivo.

El trabajo con repositorios Git (`--git`) usa el colector oficial de Git del proyecto y conserva la ingesta por hashes. Los fallos de red no borran la documentación existente. Los datos descargados permanecen en `data/`, ignorado por Git. Si un fichero Git mantiene el mismo cuerpo y título pero cambia de revisión, se actualiza su URL con SHA sin regenerar los vectores; solo se reconstruye el índice cuando cambia su contenido. Las fichas internas de Protocol Intelligence y Development Assistant se incorporan con `platform sync --internal`, conservando la etiqueta `local` de sus resúmenes editoriales. No se debe activar community sin autorización expresa ni sincronizar capturas sensibles.

La actualización en GitHub Actions produce informes temporales de recuperación real. Como su runner es efímero, no representa una caché incremental persistente entre ejecuciones; para actualizaciones recurrentes con caché se recomienda instalar el proyecto en un equipo/servidor local persistente.

Los resultados de `/api/platform/status` y `/api/platform/audit` sirven para detectar fuentes anticuadas, fallos e índices incompletos. `GET /platform` nunca inicia descargas; ejecutar `platform sync` desde la CLI es una acción deliberada.
