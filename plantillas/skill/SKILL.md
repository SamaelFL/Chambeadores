---
name: latigo
description: Látigo del usuario para tareas largas. Úsala solo cuando el usuario escriba "latigazo" o "látigo", use /latigo, o un aviso del látigo diga que azotó el látigo desde la oficina. Reparte lo que falta de la tarea entre subagentes "peon" en paralelo, hasta el techo que diga el aviso. Nunca por iniciativa propia.
argument-hint: "[nota] | init"
---

# Latigazo: repartir lo que falta entre peones

Un hook del látigo ya registró este latigazo y dejó un aviso con el número de latigazo, el **techo de peones** y si cuenta o no. Si no ves ningún aviso, trátalo como el latigazo 1 con techo de 3 peones.

Si el argumento es `init`, ve directo a "Ficha del proyecto", al final.

## 0. ¿Cuenta?

Si el aviso dice que el latigazo **no cuenta** (enfriamiento o peones trabajando), no lances peones: contesta en una línea ("Ya hay N peones chambeando" o "Calma, faltan N s") y sigue exactamente como ibas.

## 1. ¿Se puede repartir?

1. Haz la lista de lo que falta para terminar la tarea actual.
2. Agrúpalo en **piezas independientes**: cada pieza toca un conjunto de archivos que ninguna otra toca. Parte por archivo o módulo, nunca por "idea" ni por capas que crucen archivos compartidos.
3. No repartas si es una cadena (cada paso necesita el anterior), un solo bug con una sola causa, si quedan menos de 2 piezas o si casi todo depende del mismo archivo. Di en una línea "Esto no se paraleliza: <razón>" y sigue tú.

## 2. Ficha del proyecto

Lee `.claude/latigo.md` en la raíz del repo si existe: stack, comandos de verificación, qué no se toca y si se permite el commit de checkpoint. A los peones les llega sola al arrancar. Si no existe, deduce el stack con un vistazo rápido (package.json, angular.json, pom.xml…) y al final sugiere `/latigo init`.

## 3. Base para los peones

- **Repo git:** usa subagentes `peon`; cada uno trabaja en su propio worktree, que sale de tu **último commit**, así que lo que no esté commiteado no lo ven.
  - Si hay cambios sin commitear que las piezas necesitan y la ficha no dice `checkpoint: no`, haz antes un commit `latigo: checkpoint antes de repartir`, sin trailers de coautoría.
  - Si la ficha dice `checkpoint: no`, reparte solo piezas que no dependan de esos cambios.
- **Sin git:** usa `peon-libre` (trabajan en esta misma carpeta), con archivos estrictamente separados y sin comandos que reescriban archivos ajenos (formateadores globales, instalaciones).

## 4. Lanza N peones

- N = el mínimo entre las piezas independientes y el techo del aviso. Nunca más que el techo.
- Lánzalos **en un solo mensaje** (varias llamadas Agent en paralelo), con `subagent_type: "peon"` (o `"peon-libre"`) y sin parámetro `name`.
- `description`: de 3 a 5 palabras con la pieza; es lo que se ve en la oficina.
- El `prompt` de cada peón lleva: el objetivo de la pieza, los archivos que sí puede tocar, los que no, el criterio de terminado, el comando de verificación (de la ficha) y que haga commit en su rama al terminar.

## 5. Mientras chambean

No repitas su trabajo. Avanza solo en lo que no repartiste o espera sus resultados.

## 6. Integra

Trabaja desde la raíz del repo, con un comando por peón: nada de `cd` ni `git -C` hacia sus worktrees, ni `for` con variables `$…`. Claude Code pide permiso para git después de un `cd` y para cualquier expansión, aunque haya reglas, y eso te frena.

1. Mergea cada rama de peón, una por una, en tu rama: `git merge --no-ff worktree-agent-…`. Los conflictos los resuelves tú.
   - Si un peón no pudo hacer commit, trae sus archivos al checkout principal con Read y Write (o `cp .claude/worktrees/agent-…/<archivo> <archivo>`) y haz tú el commit.
2. Corre la verificación final tal como viene en la ficha (puedes agregarle `2>&1 | tail -n 30`). Si algo falla, arréglalo o vuelve a encargar solo esa pieza.
3. Limpia: por cada peón ya integrado, `git worktree remove .claude/worktrees/agent-…` (ruta relativa) y `git branch -d worktree-agent-…`.
4. Cierra con un resumen corto: qué hizo cada peón, qué verificaste y qué falta.

## Ficha del proyecto (`/latigo init`)

Corre en la raíz del proyecto:

```
"{{PY}}" "{{DIR}}/latigo.py" init
```

Si la herramienta de shell es PowerShell, antepón `&` (sin él, PowerShell toma la ruta entre comillas como texto y no la ejecuta):

```
& "{{PY}}" "{{DIR}}/latigo.py" init
```

El comando detecta el stack y escribe `.claude/latigo.md`. Léela y corrige lo que esté mal: los comandos reales de build y pruebas del proyecto, las carpetas que no se tocan y, en `skills:`, las skills disponibles que sí apliquen a este proyecto (las sugeridas son solo una pista). Al final enséñale al usuario la ficha en 5 líneas.

El comando imprime al final las reglas que agregaría con `--permisos`: las que permite (`git add/commit`, los comandos exactos de verificación de la ficha y la limpieza de las ramas de los peones) y las que siempre preguntan (`--force`, `-D`, `--amend`). Si la ficha venía del repo o trae comandos que no pre-autoriza, también lo dice.

Enséñale esas reglas al usuario y pregúntale si quiere que los peones las usen sin pedirle permiso cada vez. Solo si dice que sí, corre el mismo comando con `--permisos` (escribe en `.claude/settings.local.json` del proyecto, que es local y no se sube al repo).
