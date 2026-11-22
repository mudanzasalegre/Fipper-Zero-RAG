# Seguridad y uso responsable

## Superficie de ataque

- La UI expone consultas y respuestas, **sin endpoints de ingesta, ejecución, comandos shell ni acceso al dispositivo**.
- No hay inicio de sesión. Mantén la API en `127.0.0.1` o detrás de un proxy TLS con autenticación y rate limiting.
- Los documentos indexados se tratan como datos no confiables. La separación entre contexto y prompt reduce riesgos pero no garantiza inmunidad a prompt injection.
- Los enlaces se construyen desde orígenes permitidos para web/Git. Las notas locales son de confianza del usuario. La UI presenta texto usando `textContent`, y enlaces con `noopener noreferrer`.
- No almacenes secretos en archivos indexados; `data/` y `.env` se excluyen de Git, pero esto no reemplaza las prácticas de gestión de secretos.
- Los resultados pueden contener errores, enlaces obsoletos o instrucciones técnicas incorrectas. Verifica comandos y características antes de usarlos en hardware real.
- Radio, NFC, RFID, iButton y otras funciones deben usarse únicamente en equipos propios o autorizados y dentro de las bandas/limitaciones regionales aplicables.

## Checklist antes de publicar en GitHub

- `git status` y `git diff --cached` para descartar secretos.
- No incluir `data/`, clones de terceros, bases indexadas o `.env`.
- No habilitar exposición de `ollama:11434` ni `uvicorn:8000` fuera de localhost sin controles adecuados.
- Revisar dependencias con una herramienta de análisis de vulnerabilidades.
- Mantener repositorios de terceros y sus licencias separados del software propio.
