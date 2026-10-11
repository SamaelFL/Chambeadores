"""Hook del látigo. Claude Code lo ejecuta en cada evento (lo registra instalar.py).

Modos (primer argumento):
  telemetria  async: solo avisa a la oficina qué está pasando. No imprime nada.
  inicio      async: SessionStart; además arranca la oficina si no está corriendo.
  control     sync: puede devolver contexto a Claude:
                - UserPromptSubmit / UserPromptExpansion / Skill(latigo): registra el latigazo
                  y le dice a Claude el nivel, el techo y si cuenta o no.
                - PostToolBatch / Stop: entrega un latigazo pendiente que se dio en la oficina.
                - SubagentStart (peones): le pasa al peón la ficha del proyecto.

Reglas de oro: nunca imprimir texto suelto (en algunos eventos se iría al contexto y
costaría tokens), nunca salir con error (Claude Code mostraría "hook error") y no tardar.
"""
import json
import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

# Eventos de control que no tienen un manejador de telemetría aparte en settings.json.
CONTROL_CON_TELEMETRIA = {"UserPromptSubmit", "PostToolBatch", "Stop"}
COMANDOS_SIN_LATIGAZO = {"init", "estado", "ayuda", "help"}


# ---------------------------------------------------------------------------
# Resumen compacto del evento para la oficina (UDP)
# ---------------------------------------------------------------------------

def _corta(v, n):
    if v is None:
        return None
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def _lineas(s):
    if not isinstance(s, str) or not s:
        return 0
    return s.count("\n") + 1


def resumir_entrada(tool, ti):
    if not isinstance(ti, dict):
        return {}
    out = {}
    claves = {
        "file_path": 300, "notebook_path": 300, "path": 300, "pattern": 160, "glob": 80,
        "command": 240, "description": 160, "url": 240, "query": 160, "subagent_type": 60,
        "skill": 80, "args": 120, "subject": 120, "to": 60, "taskId": 20, "status": 30,
        "output_mode": 30, "name": 60, "isolation": 20, "run_in_background": 6, "model": 40,
    }
    for k, n in claves.items():
        if k in ti and ti[k] not in (None, ""):
            v = ti[k]
            out[k] = v if isinstance(v, bool) else _corta(v, n)
    if tool == "Agent" or tool == "Task":
        out["prompt"] = _corta(ti.get("prompt"), 300)
    elif tool == "Edit":
        out["diff"] = [_lineas(ti.get("new_string")), _lineas(ti.get("old_string"))]
    elif tool == "MultiEdit":
        eds = ti.get("edits") or []
        out["diff"] = [sum(_lineas(e.get("new_string")) for e in eds if isinstance(e, dict)),
                       sum(_lineas(e.get("old_string")) for e in eds if isinstance(e, dict))]
    elif tool == "Write":
        out["diff"] = [_lineas(ti.get("content")), 0]
    elif tool == "TodoWrite":
        todos = ti.get("todos") or []
        out["todos"] = len(todos)
        activo = [t.get("activeForm") or t.get("content") for t in todos
                  if isinstance(t, dict) and t.get("status") == "in_progress"]
        if activo:
            out["activo"] = _corta(activo[0], 120)
    elif tool.startswith("mcp__"):
        extra = [(k, v) for k, v in ti.items() if isinstance(v, (str, int, float)) and k not in out][:2]
        for k, v in extra:
            out[k] = _corta(v, 80)
    return out


def resumir(ev):
    e = ev.get("hook_event_name") or ""
    out = {"v": 1, "e": e, "t": round(time.time(), 3), "s": ev.get("session_id")}
    for fuente, k in (("agent_id", "a"), ("agent_type", "at"), ("cwd", "cwd"),
                      ("permission_mode", "pm"), ("prompt_id", "prid")):
        if ev.get(fuente):
            out[k] = ev[fuente]
    if ev.get("transcript_path"):
        out["tp"] = ev["transcript_path"]
    tool = ev.get("tool_name")
    if tool:
        out["tool"] = tool
        if ev.get("tool_use_id"):
            out["tid"] = ev["tool_use_id"]
        out["in"] = resumir_entrada(tool, ev.get("tool_input"))
        if isinstance(ev.get("mcp_server"), dict):
            out["mcp"] = ev["mcp_server"].get("name")
    if "duration_ms" in ev:
        out["ms"] = ev.get("duration_ms")
    if e == "PostToolUse" and tool in ("Agent", "Task"):
        tr = ev.get("tool_response") if isinstance(ev.get("tool_response"), dict) else {}
        out["res"] = {k: _corta(tr.get(k), 300) for k in
                      ("agentId", "status", "description", "agentType", "worktreeBranch", "worktreePath",
                       "totalTokens", "totalDurationMs", "resolvedModel") if tr.get(k) is not None}
    elif e == "PostToolUse" and tool == "Bash":
        tr = ev.get("tool_response") if isinstance(ev.get("tool_response"), dict) else {}
        if tr.get("interrupted"):
            out["int"] = True
    if e == "PostToolUseFailure":
        err = ev.get("error") or ""
        out["err"] = _corta(err.strip().splitlines()[0] if err.strip() else "", 200)
        if ev.get("is_interrupt"):
            out["int"] = True
    if e == "PostToolBatch":
        calls = ev.get("tool_calls") or []
        out["n"] = len(calls)
        out["tids"] = [c.get("tool_use_id") for c in calls if isinstance(c, dict)][:30]
    if e == "Notification":
        out["nt"] = ev.get("notification_type")
        out["msg"] = _corta(ev.get("message"), 200)
    if e in ("Stop", "SubagentStop"):
        out["last"] = _corta(ev.get("last_assistant_message"), 400)
        bg = ev.get("background_tasks") or []
        out["bg"] = [{"type": t.get("type"), "at": t.get("agent_type"), "d": _corta(t.get("description"), 80)}
                     for t in bg if isinstance(t, dict)][:12]
        if ev.get("stop_hook_active"):
            out["sha"] = True
    if e == "SubagentStop" and ev.get("agent_transcript_path"):
        out["atp"] = ev["agent_transcript_path"]
    if e == "SessionStart":
        out["src"] = ev.get("source")
        if ev.get("model"):
            out["model"] = ev.get("model")
    if e in ("SessionStart", "UserPromptSubmit") and ev.get("session_title"):
        out["title"] = _corta(ev.get("session_title"), 120)
    if e == "UserPromptSubmit":
        out["prompt"] = _corta(ev.get("prompt"), 300)
    if e == "SessionEnd":
        out["reason"] = ev.get("reason")
    if e == "StopFailure":
        out["error"] = ev.get("error")
        out["det"] = _corta(ev.get("error_details"), 200)
    if e in ("PreCompact", "PostCompact"):
        out["trigger"] = ev.get("trigger")
    if e == "PermissionDenied":
        out["razon"] = _corta(ev.get("reason"), 160)
    return out


# ---------------------------------------------------------------------------
# Detección del latigazo escrito como mensaje
# ---------------------------------------------------------------------------

def es_aviso_interno(prompt):
    """Mensajes que Claude Code inyecta como si fueran del usuario (avisos de subagentes, etc.)."""
    return isinstance(prompt, str) and prompt.lstrip().startswith(("<task-notification", "<system-reminder", "<local-command"))


def es_latigazo(prompt):
    """Devuelve True si el mensaje del usuario es un latigazo.

    Cuenta: la palabra sola ("latigo", "látigo", "latigazo", "¡latigazo!"), "latigazo" con
    una nota separada por dos puntos, coma o guion ("latigazo: apúrate con los tests"),
    "¡latigazo! <nota>", "/latigo" y "/latigo <nota>". No cuenta: frases que mencionan el
    látigo ("latigazos no funcionan, revisa el hook"), preguntas ("latigazo, ¿por qué no
    suena?"), ni "/latigo init|estado|ayuda".
    """
    if not isinstance(prompt, str):
        return False
    p = prompt.strip()
    if not p or len(p) > 400:
        return False
    import re

    m = re.match(r"^/l[aá]tigo(?:\s+(.*))?$", p, re.I | re.S)
    if m:
        primera = ((m.group(1) or "").split() or [""])[0].lower()
        return primera not in COMANDOS_SIN_LATIGAZO
    if re.match(r"^[¡!]*\s*(?:l[aá]tigo|latigazos?)\s*[!¡.…]*$", p, re.I):
        return True
    if "?" in p:
        return False  # "latigazo, ¿por qué no suena?" es una pregunta sobre el látigo, no un latigazo
    return bool(re.match(r"^(?:¡\s*latigazos?\s*!+|[¡!]*\s*latigazos?\s*!*\s*[:,\-–—])\s*\S", p, re.I))


# ---------------------------------------------------------------------------
# Control (sync)
# ---------------------------------------------------------------------------

def _contexto(evento, texto):
    return {"hookSpecificOutput": {"hookEventName": evento, "additionalContext": texto}}


def _anunciar(nucleo, ev, res, entregado=False):
    """Avisa a la oficina (animación + sonido). Si la oficina no corre, suena aquí."""
    aviso = {"v": 1, "e": "Latigo", "t": round(time.time(), 3), "s": ev.get("session_id"),
             "res": res, "entregado": entregado}
    enviado = nucleo.enviar_telemetria(aviso) and nucleo.servidor_vivo()
    if not enviado and not entregado:
        nucleo.reproducir("latigazo", desde_hook=True)


def _latigazo_desde_terminal(nucleo, ev, origen):
    sid = ev.get("session_id") or ""
    iny = nucleo.tomar_inyeccion(sid)
    if iny:
        # Había un latigazo de la oficina sin entregar: se entrega ahora y no se cuenta doble,
        # ni aquí ni en el evento gemelo del mismo prompt.
        datos = dict(iny.get("datos") or {})
        nucleo.anotar_entrega(sid, ev.get("prompt_id"), datos)
        _anunciar(nucleo, ev, datos, entregado=True)
        return iny["texto"]
    res = nucleo.registrar_latigazo(sid, origen, prompt_id=ev.get("prompt_id"))
    if res.get("duplicado"):
        return None
    _anunciar(nucleo, ev, res)
    return nucleo.texto_latigazo(res)


def control(nucleo, ev):
    e = ev.get("hook_event_name") or ""
    sid = ev.get("session_id") or ""
    en_subagente = bool(ev.get("agent_id"))

    if e == "UserPromptSubmit":
        if en_subagente or es_aviso_interno(ev.get("prompt")):
            return None  # p. ej. <task-notification>: un peón terminó; no es un encargo del usuario
        if es_latigazo(ev.get("prompt")):
            texto = _latigazo_desde_terminal(nucleo, ev, "comando" if ev.get("prompt", "").lstrip().startswith("/") else "mensaje")
            return _contexto(e, texto) if texto else None
        # Encargo nuevo: un latigazo de la oficina que no alcanzó a entregarse ya no aplica.
        if nucleo.descartar_inyeccion(sid, mas_vieja_que=15):
            nucleo.enviar_telemetria({"v": 1, "e": "LatigoCancelado", "t": time.time(), "s": sid})
        return None

    if e == "UserPromptExpansion":
        if (ev.get("command_name") or "").split(":")[-1] != "latigo" or en_subagente:
            return None
        primera = ((ev.get("command_args") or "").split() or [""])[0].lower()
        if primera in COMANDOS_SIN_LATIGAZO:
            return None
        texto = _latigazo_desde_terminal(nucleo, ev, "comando")
        return _contexto(e, texto) if texto else None

    if e == "PreToolUse":
        ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
        skill = str(ti.get("skill") or ti.get("name") or "").split(":")[-1].strip("/")
        if ev.get("tool_name") != "Skill" or skill != "latigo" or en_subagente:
            return None
        primera = (str(ti.get("args") or "").split() or [""])[0].lower()
        if primera in COMANDOS_SIN_LATIGAZO:
            return None
        if nucleo.tomar_pendiente_skill(sid):
            return None  # el aviso ya le llegó con el mensaje o con la oficina
        texto = _latigazo_desde_terminal(nucleo, ev, "skill")
        return _contexto(e, texto) if texto else None

    if e == "PostToolBatch":
        if en_subagente or not nucleo.hay_inyeccion(sid):
            return None
        iny = nucleo.tomar_inyeccion(sid)
        if not iny:
            return None
        _anunciar(nucleo, ev, dict(iny.get("datos") or {}), entregado=True)
        return _contexto(e, iny["texto"])

    if e == "Stop":
        if en_subagente:
            return None
        if nucleo.hay_inyeccion(sid) and not ev.get("stop_hook_active"):
            iny = nucleo.tomar_inyeccion(sid)
            if iny:
                _anunciar(nucleo, ev, dict(iny.get("datos") or {}), entregado=True)
                return _contexto(e, iny["texto"])
        bg = [t for t in (ev.get("background_tasks") or []) if isinstance(t, dict)]
        quedan = any(t.get("type") in ("subagent", "teammate", "workflow") for t in bg)
        nucleo.fin_de_tarea(sid, quedan_subagentes=quedan)
        return None

    if e == "SubagentStart":
        if (ev.get("agent_type") or "") not in nucleo.config().get("tipos_peon", []):
            return None
        ruta, contenido = nucleo.buscar_ficha(ev.get("cwd"))
        if contenido:
            texto = ("Contexto del látigo: este subagente es un peón que recibió una pieza de una tarea "
                     "repartida por el capataz. Ficha del proyecto (%s):\n\n%s"
                     % (ruta, contenido[:8000]))
        else:
            texto = ("Contexto del látigo: este subagente es un peón que recibió una pieza de una tarea "
                     "repartida por el capataz. El proyecto no tiene ficha (.claude/latigo.md), así que el "
                     "stack y los comandos de verificación se deducen del repositorio.")
        return _contexto(e, texto)

    return None


# ---------------------------------------------------------------------------
# Telemetría y efectos secundarios (bitácora de peones)
# ---------------------------------------------------------------------------

def efectos(nucleo, ev, modo):
    e = ev.get("hook_event_name") or ""
    sid = ev.get("session_id") or ""
    tipos = nucleo.config().get("tipos_peon", [])
    if modo == "telemetria" and e == "SubagentStart" and ev.get("agent_type") in tipos:
        nucleo.peon_inicio(sid, ev.get("agent_id") or "", ev.get("agent_type"))
    elif modo == "telemetria" and e == "SubagentStop" and ev.get("agent_type") in tipos:
        nucleo.peon_fin(sid, ev.get("agent_id") or "")
    elif modo == "telemetria" and e == "SessionEnd":
        nucleo.descartar_inyeccion(sid)
    elif modo == "inicio" and ev.get("source") in ("startup", "clear"):
        nucleo.reiniciar_sesion(sid)


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else "telemetria"
    try:
        crudo = sys.stdin.buffer.read()
        ev = json.loads(crudo.decode("utf-8", "replace") or "{}")
    except Exception:
        return
    if not isinstance(ev, dict):
        return
    import nucleo

    salida = None
    try:
        if modo == "control":
            salida = control(nucleo, ev)
    except Exception as err:
        nucleo.log_error("control %s" % ev.get("hook_event_name"), err)
        salida = None

    if salida:
        # ASCII puro: en Windows la consola del hook puede no ser UTF-8.
        sys.stdout.write(json.dumps(salida, ensure_ascii=True))
        sys.stdout.flush()

    try:
        efectos(nucleo, ev, modo)
        if modo != "control" or ev.get("hook_event_name") in CONTROL_CON_TELEMETRIA:
            if modo == "inicio" and nucleo.config().get("autoiniciar_servidor", True) and not nucleo.servidor_vivo():
                nucleo.arrancar_servidor(esperar=3.0)
            resumen = resumir(ev)
            if salida and ev.get("hook_event_name") == "Stop":
                resumen["sigue"] = True  # el hook le entregó un latigazo: Claude sigue trabajando
            nucleo.enviar_telemetria(resumen)
    except Exception as err:
        nucleo.log_error("telemetria %s" % ev.get("hook_event_name"), err)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
