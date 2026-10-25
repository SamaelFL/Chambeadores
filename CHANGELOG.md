# Cambios

## 0.1.0 · 2026-10-25

Primera versión pública.

- La caseta: oficina isométrica en vivo que muestra qué hace cada agente (piensa, lee, edita, corre comandos, pide permiso) sin gastar tokens.
- El látigo: un latigazo reparte el trabajo largo entre peones (subagentes en su propio worktree), con techo de 3 y luego 5, y 60 s de calma entre latigazos.
- `/latigo init`: ficha del proyecto con stack, comandos de verificación y permisos acotados para los peones.
- Instalador que valida y respalda tu `settings.json`, conserva tus hooks y se desinstala limpio.
- Demo en el navegador, sin instalar nada.
- El servidor abre el puerto sin búsqueda DNS inversa, que en algunas redes retrasaba varios segundos el arranque.
- 65 pruebas en Linux, macOS y Windows, que corren en cada push.
