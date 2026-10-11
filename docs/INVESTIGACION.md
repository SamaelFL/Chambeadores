# Investigación: qué se puede ver y controlar de Claude Code en vivo

Fecha: 1 de octubre de 2026. Versión de referencia: Claude Code 2.1.286.
Confianza: **Confirmado** (fuente primaria leída o probado aquí), **Probable** (una fuente, sin contradicción), **Hueco** (lo busqué y no está).

## Respuesta corta

- **Se puede ver casi todo en vivo, sin gastar tokens.** Hay hooks para cada herramienta, permiso, subagente, compactación y fin de turno; los de subagentes traen `agent_id`. Los transcripts JSONL completan con el texto de las respuestas, los tokens y el título de la sesión.
- **Lo único que no se ve es el texto del razonamiento.** Llega vacío y solo trae firma. La animación de "pensando" se infiere del hueco entre herramientas.
- **El latigazo a media tarea entra por un hook.** Un `PostToolBatch` o `Stop` inyecta el aviso como contexto. `/latigo` no sirve a media tarea porque Claude Code guarda los comandos hasta el fin del turno; un mensaje normal ("latigazo") sí llega.
- **Para repartir conviene usar subagentes con `isolation: worktree`, no Agent Teams.** Los subagentes son estables y más baratos. Agent Teams sigue experimental, y su ventaja (que los agentes hablen entre ellos) no hace falta para partir y repartir.
- **Todo esto se probó con Claude Code real**, incluidos 3 peones en paralelo, el merge y las pruebas en verde. Ver "Lo que probé".

## 1. Señales disponibles

| Qué quiero ver | De dónde sale | Confianza |
|---|---|---|
| Qué herramienta corre y con qué (archivo, comando, búsqueda) | `PreToolUse`/`PostToolUse`/`PostToolUseFailure` (`tool_name`, `tool_input`, `tool_use_id`, `duration_ms`) | Confirmado |
| Quién la corre (capataz o qué subagente) | `agent_id` y `agent_type` en eventos de herramientas dentro de subagentes (desde 2.1.69) | Confirmado (probado aquí) |
| Pide permiso | `PermissionRequest` (inmediato) y `Notification` `permission_prompt` (llega hasta ~6 s después) | Confirmado |
| Llega o termina un subagente | `SubagentStart` / `SubagentStop` (con `last_assistant_message`) | Confirmado |
| Etiqueta de la tarea de cada peón | `tool_input.description` del `Agent` y el `.meta.json` junto a su transcript | Confirmado |
| Terminó el turno, o sigue esperando subagentes | `Stop` con `background_tasks` | Confirmado |
| Error de API (límite, saturación) | `StopFailure` (`error`) | Confirmado |
| Compactando | `PreCompact` / `PostCompact` | Confirmado |
| Lo que contesta (texto) | Bloques `text` del transcript; `last_assistant_message` en `Stop` | Confirmado |
| Tokens por agente | `usage` en el transcript (deduplicar por `message.id`; las líneas de un mismo mensaje lo repiten) | Confirmado |
| Título de la sesión | Registros `ai-title` / `custom-title` del transcript | Confirmado (probado aquí) |
| Rama del worktree de un peón | Campo `gitBranch` en las líneas de su transcript | Confirmado (probado aquí) |
| "Pensando" | No hay evento. Se infiere entre `PostToolBatch` o `UserPromptSubmit` y la siguiente herramienta | Probable |
| Texto del razonamiento | Redactado: llega vacío con firma; con `showThinkingSummaries: true` llega un resumen | Confirmado |

Detalles que importan:

- El transcript se escribe **asíncrono y con retraso**. Los hooks mandan en tiempo real y el transcript completa.
- `SubagentStop` también dispara para agentes internos (sugerencias, `/btw`) con `agent_type` vacío; hay que ignorarlos.
- `UserPromptSubmit` también dispara con los avisos de que un subagente terminó (`<task-notification>…`); no son encargos del usuario. Lo vi en las pruebas.

## 2. Cómo meterle el latigazo a Claude a media tarea

| Canal | ¿Sirve? | Por qué |
|---|---|---|
| Escribir `/latigo` en la terminal | Solo al final del turno | La doc de modo interactivo dice que los comandos se guardan hasta que termina el turno |
| Escribir "latigazo" como mensaje | **Sí** | Los mensajes que se encolan se entregan en el mismo turno, en cuanto terminan las herramientas en curso |
| `additionalContext` en `PostToolBatch` | **Sí (el principal)** | Se inyecta una vez antes de la siguiente llamada al modelo |
| `additionalContext` en `Stop` | **Sí (respaldo)** | Si el turno termina antes, Claude continúa con el aviso; con protección anti-bucle (`stop_hook_active` y tope de 8) |
| Hooks HTTP | No conviene | Si la oficina está apagada, cada evento marca "hook error" en el transcript |
| `asyncRewake` | No se usó | Despierta a Claude aunque esté esperándote, y eso es justo lo que no queremos |

**Redacción del aviso:** la documentación pide escribir `additionalContext` como hechos, no como órdenes de sistema, porque si no puede activar las defensas contra prompt injection. El aviso dice que lo configuró el usuario y qué espera él ("cargar la skill latigo y seguirla"). Con esa redacción Sonnet sí reaccionó. Con una versión más neutra, Haiku lo leyó y lo ignoró.

## 3. Repartir: subagentes contra Agent Teams contra "oficinas"

- **Subagentes con `isolation: worktree`:** son estables. Cada uno tiene su copia del repo y su rama `worktree-agent-<id>`. Corren en segundo plano por defecto desde 2.1.198 y sus permisos se piden en la sesión principal. Por eso el látigo pide 2.1.198 como mínimo (la forma exec de los hooks llegó en 2.1.139).
- **Agent Teams:** sigue experimental (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`). Los compañeros se mandan mensajes entre ellos. Gasta alrededor de 7 veces los tokens con un equipo de 3 (dato de la doc de costos que citan varias guías). Tiene fallas conocidas: después de `/resume`, el líder le escribe a compañeros que ya no existen, y solo puede haber un equipo por sesión. No encontré ningún benchmark público serio de que acelere el trabajo de código en proporción a lo que cuesta. Queda para una v2.
- **Oficinas pixel art existentes** (Pixel Agents, claude-office, Agent Office, Pixel Agent Desk, Agents in the Office): son visuales que observan transcripts o hooks; no reparten trabajo. claude-office usa tu token para generar nombres y resúmenes, y eso sí gasta. La caseta no.

## 4. Worktrees de los peones

- Por defecto salen de la rama por defecto del remoto (`"fresh"`). Con `worktree.baseRef: "head"` salen de tu HEAD local; no se puede indicar una rama específica. **Lo que no esté commiteado no lo ven**: de ahí sale el commit de checkpoint.
- Los archivos ignorados (`.env`) no se copian; para eso está `.worktreeinclude`. `node_modules` tampoco: la ficha dice cómo enlazarlo.
- Un worktree con cambios se queda en disco hasta la limpieza periódica (`cleanupPeriodDays`). Por eso el protocolo limpia al integrar y `init` agrega `.claude/worktrees/` a `.git/info/exclude`.

## 5. Permisos de los peones

La documentación de permisos fija cómo se arman las reglas de `init --permisos`:

- `*` cubre cualquier texto. `Bash(git add *)` exige el espacio (no cubre `git addx`) y también cubre `git add` a secas.
- Una regla angosta falla con flags que el modelo agrega: en la prueba real, `Bash(git commit -m *)` negó `git commit -q -m …`. Por eso la regla es `Bash(git commit *)`.
- Y al revés: el `*` final también deja pasar flags peligrosos al final (`git worktree remove … --force`, `git branch -d x otra -D`). Las reglas `ask` le ganan a las `allow`, así que `init` agrega reglas `ask` para `--force`, `-f`, `-D` y `--amend`: esas variantes siempre preguntan.
- La ficha puede venir del repo, escrita por otra persona. `init --permisos` solo pre-autoriza comandos de verificación con un programa conocido (npm, mvn, python3…) y sin caracteres de shell, y avisa si la ficha está commiteada sin cambios tuyos.
- Los comandos de solo lectura (`ls`, `cat`, `grep` y las formas de solo lectura de `git`, como `status`, `diff` y `log`) ya corren sin preguntar: no llevan regla.
- Con "runners" como `npx`, `devbox run` o `docker exec`, un comodín después del runner permite ejecutar cualquier cosa. Por eso la verificación va con el comando exacto (`Bash(npx ng build)`), sin `*`.
- En un comando compuesto (`&&`, `;`, `|`) cada parte se revisa por separado. Un `for` con variables (`$b`) o un `cd` seguido de `git` piden permiso aunque cada parte tenga regla. La skill y los peones lo evitan: un comando por rama, desde la raíz.
- En Windows, con la herramienta PowerShell activa, las reglas tienen la misma forma (`PowerShell(git commit -m *)`); `init` agrega las dos.

## 6. Costo

- **La caseta:** cero tokens. Corre en Python local y lee hooks y archivos.
- **Hooks:** los de telemetría son `async` y no hacen esperar a Claude. Los de control tardan unos 22 ms (medido).
- **El latigazo:** cerca de 100 tokens el aviso y unos 1,500 la skill la primera vez.
- **Los peones:** cada uno es otra sesión de Sonnet (alias `sonnet` en el agente: el Sonnet más nuevo), con su propio contexto. Gastas más en total y terminas antes. Por eso hay techo, calma y bloqueo con peones trabajando.

## Lo que probé aquí con Claude Code 2.1.286 real (modo `-p`)

1. **Hooks:** Claude Code aceptó los 19 hooks en forma exec (`command` + `args`), incluidos los `async`. El `SessionStart` arrancó la oficina sola.
2. **Telemetría:** sesión con Haiku que leyó un archivo y escribió otro. La bitácora mostró el encargo, la lectura, la escritura, el fin de turno y el cierre, con tokens del transcript.
3. **Latigazo desde la oficina (Haiku):** `PostToolBatch` entregó el aviso (`provided additionalContext (345 chars)`) y quedó en el transcript como `hook_additional_context`. Haiku no reaccionó, y eso llevó a cambiar la redacción del aviso.
4. **Latigazo desde la oficina (Sonnet), punta a punta:**
   - El capataz recibió el aviso, cargó la skill `latigo`, revisó la ficha (no existía) y lanzó 3 peones en un solo mensaje. Cada encargo traía objetivo, archivos permitidos, verificación y commit.
   - Cada peón trabajó en su worktree, corrió su prueba e hizo commit.
   - El capataz esperó los tres avisos y mergeó con `--no-ff`. Las 3 pruebas quedaron en verde y el nivel volvió a 0 al cerrar.
5. **Peones sin permisos de Bash:** sin permiso para Bash (modo headless, sin a quién preguntarle), los peones no pudieron hacer commit. El capataz copió sus archivos, verificó (18 pruebas en verde) y limpió los worktrees. De ahí salió `init --permisos`.
6. **Con `init --permisos` y sin permisos amplios en la línea de comandos (Sonnet, `-p`):** primer intento, la regla `git commit -m *` les negó a los peones `git commit -q -m …`, y uno concluyó que todo Bash estaba negado. Con la regla corregida y las instrucciones nuevas (Edit/Write para escribir, git sin `cd`, un comando por rama), segundo intento: latigazo desde la oficina, 3 peones en paralelo con verificación y commit propios, 3 merges `--no-ff`, 19 pruebas en verde, worktrees y ramas borrados y nivel de vuelta a 0. Todo en 73 s. De 17 comandos Bash, solo se negaron 2 (dos `for` del capataz, que luego partió en comandos sueltos).
7. **Tercera corrida, con la configuración final (incluidas las reglas `ask`):** 52 s, mismo resultado (3 commits de peones, 3 merges, 19 pruebas en verde, limpieza completa). Los peones intentaron correr solo sus pruebas (`python3 -m unittest pruebas.test_x`), que no estaban en la ficha, y Claude Code se los negó; la verificación del capataz al final sí corrió. De ahí que el peón corra la verificación tal cual viene en la ficha y que la ficha de Python incluya las pruebas también para el peón.

## Riesgos y contra-evidencia

- **Hooks dentro de subagentes:** hay issues cerrados sin fix confirmado de hooks que no disparaban dentro de subagentes (#34692, #43612, #69260). Aquí sí dispararon, pero la oficina tiene respaldo: lee los transcripts de `subagents/`.
- **El modelo puede no hacer caso:** un modelo más chico puede ignorar el aviso (pasó con Haiku). Con Opus o Sonnet funcionó.
- **Permisos de los peones:** los permisos de peones en segundo plano interrumpen tu sesión principal. La mitigación es opcional y explícita (`--permisos`, reglas exactas).
- **Windows:** no se pudo probar aquí. El código usa forma exec, rutas con `os.path`, procesos desacoplados con `DETACHED_PROCESS` y sonido con `winsound`. El primer uso real en Windows es la prueba que falta.

## Huecos

- **Comandos encolados:** no está documentado si `UserPromptSubmit` dispara para mensajes encolados a media tarea. Por eso también se detecta el latigazo cuando Claude carga la skill (`PreToolUse` de `Skill`).
- **Respuesta a un permiso:** no hay un evento de "permiso concedido o negado por el usuario". La oficina limpia el estado con el siguiente evento de ese agente.
- **Latencia:** no hay cifras oficiales de latencia por hook. Las de aquí son mediciones propias en Linux.

## Fuentes

- Hooks (referencia y guía): https://code.claude.com/docs/en/hooks · https://code.claude.com/docs/en/hooks-guide
- Subagentes: https://code.claude.com/docs/en/sub-agents
- Permisos (reglas y comodines): https://code.claude.com/docs/en/permissions
- Worktrees: https://code.claude.com/docs/en/worktrees
- Skills y comandos: https://code.claude.com/docs/en/skills
- Modo interactivo (mensajes encolados): https://code.claude.com/docs/en/interactive-mode
- Changelog: https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
- Agent Teams, costo y fallas: https://claudemarket.ai/blog/claude-code-agent-teams · https://bestagent.dev/claude-code-agent-teams-worth-it-2026 · https://blog.laozhang.ai/en/posts/claude-code-agent-teams
- Formato de transcripts (código y datos de prueba reales): https://github.com/daaain/claude-code-log · https://github.com/ryoppippi/ccusage
- Oficinas existentes: https://github.com/pablodelucca/pixel-agents · https://github.com/paulrobello/claude-office · https://github.com/Pixel-Process-UG/agent-office · https://github.com/Mgpixelart/pixel-agent-desk · https://github.com/gukosowa/agents-in-the-office
- Látigo original: https://github.com/fffonion/badclaude
