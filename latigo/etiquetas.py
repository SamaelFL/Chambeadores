"""Qué está haciendo un agente, en español corto, a partir de la herramienta que usa.

Devuelve (categoria, icono, texto, detalle). La categoría decide la animación en la
oficina; el texto va en el globo; el detalle aparece al pasar el mouse y en el panel.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

CATEGORIAS = (
    "pensando", "leyendo", "escribiendo", "terminal", "buscando", "web", "delegando",
    "permiso", "hablando", "esperando", "esperando_peones", "durmiendo", "compactando",
    "error", "terminado", "pendientes", "skill", "mcp", "pregunta", "plan", "herramienta",
    "arrancando", "saliendo",
)

NOMBRES_AYUDANTE = {
    "Explore": "Explorador",
    "Plan": "Planeador",
    "general-purpose": "Ayudante",
    "claude": "Ayudante",
    "claude-code-guide": "Guía",
    "statusline-setup": "Técnico",
    "fork": "Gemelo",
}


def _medio(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    mitad = (n - 1) // 2
    return s[:mitad] + "…" + s[-(n - 1 - mitad):]


def ruta_corta(path: str, cwd: str = None, n: int = 42) -> str:
    if not path:
        return ""
    p = str(path)
    try:
        if cwd:
            rel = os.path.relpath(p, cwd)
            if not rel.startswith(".."):
                p = rel
            else:
                p = os.path.join(os.path.basename(os.path.dirname(p)), os.path.basename(p))
    except ValueError:  # Windows: distinta unidad
        p = os.path.basename(p)
    return _medio(p.replace("\\", "/"), n)


def _linea(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _diff(inp: dict) -> str:
    d = inp.get("diff")
    if isinstance(d, list) and len(d) == 2 and (d[0] or d[1]):
        return " (+%s −%s)" % (d[0], d[1])
    return ""


def etiqueta(tool: str, inp: dict, cwd: str = None, tipos_peon=("peon", "peon-libre")):
    """(categoria, icono, texto, detalle) para una herramienta y su entrada resumida."""
    inp = inp if isinstance(inp, dict) else {}
    t = tool or ""
    archivo = inp.get("file_path") or inp.get("notebook_path") or ""
    if t == "Read":
        return "leyendo", "📖", "Leyendo " + ruta_corta(archivo, cwd), archivo
    if t == "Grep":
        donde = inp.get("glob") or ruta_corta(inp.get("path") or "", cwd, 24)
        txt = "Buscando «%s»" % _linea(inp.get("pattern"), 28)
        return "buscando", "🔎", txt + (" en " + donde if donde else ""), inp.get("pattern") or ""
    if t == "Glob":
        return "buscando", "🗂️", "Buscando archivos " + _linea(inp.get("pattern"), 30), inp.get("pattern") or ""
    if t == "LS":
        return "leyendo", "🗂️", "Revisando " + ruta_corta(inp.get("path") or "", cwd), inp.get("path") or ""
    if t in ("Edit", "MultiEdit"):
        return "escribiendo", "✏️", "Editando " + ruta_corta(archivo, cwd) + _diff(inp), archivo
    if t == "Write":
        d = inp.get("diff")
        lineas = " (%s líneas)" % d[0] if isinstance(d, list) and d and d[0] else ""
        return "escribiendo", "📝", "Escribiendo " + ruta_corta(archivo, cwd) + lineas, archivo
    if t == "NotebookEdit":
        return "escribiendo", "📓", "Editando notebook " + ruta_corta(archivo, cwd), archivo
    if t in ("Bash", "PowerShell"):
        cmd = inp.get("command") or ""
        prefijo = "PS> " if t == "PowerShell" else "$ "
        if inp.get("description"):
            return "terminal", "💻", _linea(inp["description"], 48), prefijo + cmd
        return "terminal", "💻", prefijo + _linea(cmd, 44), prefijo + cmd
    if t in ("BashOutput", "KillShell", "KillBash", "Monitor", "TaskStop"):
        return "terminal", "📟", "Revisando un proceso", ""
    if t == "WebFetch":
        url = inp.get("url") or ""
        try:
            dominio = urlparse(url).netloc or url
        except ValueError:
            dominio = url
        return "web", "🌐", "Leyendo " + _linea(dominio, 36), url
    if t == "WebSearch":
        return "web", "🌐", "Buscando en web «%s»" % _linea(inp.get("query"), 30), inp.get("query") or ""
    if t in ("Agent", "Task"):
        tipo = inp.get("subagent_type") or "general-purpose"
        desc = _linea(inp.get("description") or "", 40)
        if tipo in tipos_peon:
            return "delegando", "👷", "Mandando peón: " + desc, inp.get("prompt") or desc
        quien = NOMBRES_AYUDANTE.get(tipo, tipo)
        return "delegando", "📨", "Delegando a %s: %s" % (quien, desc), inp.get("prompt") or desc
    if t == "TodoWrite":
        extra = (": " + _linea(inp.get("activo"), 36)) if inp.get("activo") else ""
        return "pendientes", "📋", "Actualizando pendientes" + extra, ""
    if t == "TaskCreate":
        return "pendientes", "📋", "Anotando: " + _linea(inp.get("subject"), 36), inp.get("subject") or ""
    if t in ("TaskUpdate", "TaskGet", "TaskList"):
        tid = inp.get("taskId")
        return "pendientes", "📋", ("Tarea #%s" % tid) if tid else "Revisando tareas", ""
    if t == "Skill":
        return "skill", "🧰", "Usando la skill " + _linea(inp.get("skill"), 30), inp.get("args") or ""
    if t == "ToolSearch":
        return "herramienta", "🧰", "Buscando herramientas", inp.get("query") or ""
    if t == "AskUserQuestion":
        return "pregunta", "❓", "Te está preguntando algo", ""
    if t == "ExitPlanMode":
        return "plan", "🗺️", "Esperando que apruebes el plan", ""
    if t == "EnterPlanMode":
        return "plan", "🗺️", "Entrando a modo plan", ""
    if t == "SendMessage":
        return "hablando", "📨", "Mensaje para " + _linea(inp.get("to"), 24), ""
    if t == "SubagentHandback":
        return "hablando", "📤", "Entregando su reporte", ""
    if t in ("EnterWorktree", "ExitWorktree"):
        return "herramienta", "🌳", "Cambiando de worktree", ""
    if t == "LSP":
        return "leyendo", "🧭", "Consultando el LSP", ""
    if t == "Artifact":
        return "escribiendo", "🖼️", "Publicando una página", ""
    if t.startswith("mcp__"):
        partes = t.split("__")
        servidor = partes[1] if len(partes) > 1 else "MCP"
        herramienta = partes[2] if len(partes) > 2 else ""
        return "mcp", "🔌", _linea("%s: %s" % (servidor, herramienta), 44), t
    return "herramienta", "🛠️", "Usando " + _linea(t, 36), ""


ESTADOS_BASE = {
    "pensando": ("🧠", "Pensando…"),
    "esperando": ("☕", "Esperando tus instrucciones"),
    "esperando_peones": ("👀", "Vigilando a los peones"),
    "durmiendo": ("😴", "Zzz… te está esperando"),
    "compactando": ("🗜️", "Compactando la conversación"),
    "arrancando": ("🚪", "Llegando a su escritorio"),
    "terminado": ("✅", "¡Terminé!"),
    "saliendo": ("👋", "Ya se va"),
    "error": ("⚠️", "Algo falló"),
}

ERRORES_API = {
    "rate_limit": "Llegó al límite de uso",
    "overloaded": "Servidores saturados",
    "authentication_failed": "Falló la autenticación",
    "billing_error": "Problema de facturación",
    "server_error": "Error del servidor",
    "max_output_tokens": "Se pasó del máximo de salida",
    "invalid_request": "Petición inválida",
    "model_not_found": "Modelo no encontrado",
}


def nombre_ayudante(tipo: str) -> str:
    if not tipo:
        return "Ayudante"
    return NOMBRES_AYUDANTE.get(tipo, tipo.replace("-", " ").replace("_", " ").strip().capitalize()[:18])
