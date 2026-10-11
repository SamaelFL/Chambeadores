"""Lectura incremental de los transcripts JSONL de Claude Code.

Los hooks dicen en tiempo real qué herramienta corre; el transcript completa lo que los
hooks no dan: lo que Claude contesta (texto), los tokens por mensaje, el título de la
sesión y, como respaldo, las herramientas de subagentes cuyos hooks no llegaron.

Formato (verificado contra transcripts reales de v2.1.x):
- una línea por bloque de contenido; varias líneas comparten message.id y repiten usage
- en subagentes: isSidechain=true y agentId; archivo <sesion>/subagents/agent-<id>.jsonl
  con un <id>.meta.json al lado (agentType, description, worktreePath)
- el razonamiento llega vacío (solo firma) salvo que showThinkingSummaries esté activo
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

LECTURA_INICIAL_MAX = 8 * 1024 * 1024
LECTURA_MAX = 16 * 1024 * 1024

_ETIQUETAS = re.compile(r"<[^>]{1,80}>")


class LectorJSONL:
    """Lee solo lo nuevo de un archivo que crece. Tolera truncados y líneas a medias."""

    def __init__(self, path: str, desde_final: bool = False):
        self.path = path
        self.pos = 0
        self.iniciado = False
        self.desde_final = desde_final
        self.mtime = 0.0

    def leer_nuevas(self) -> list:
        try:
            st = os.stat(self.path)
        except OSError:
            return []
        self.mtime = st.st_mtime
        tam = st.st_size
        saltar_primera = False
        if not self.iniciado:
            self.iniciado = True
            if self.desde_final:
                self.pos = tam
                return []
            if tam > LECTURA_INICIAL_MAX:
                self.pos = tam - LECTURA_INICIAL_MAX
                saltar_primera = True
        if tam < self.pos:  # el archivo se reescribió o truncó
            self.pos = 0
        if tam == self.pos:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                datos = f.read(min(tam - self.pos, LECTURA_MAX))
        except OSError:
            return []
        corte = datos.rfind(b"\n")
        if corte < 0:
            return []  # línea a medio escribir: esperar
        self.pos += corte + 1
        lineas = datos[: corte + 1].split(b"\n")
        if saltar_primera and lineas:
            lineas = lineas[1:]
        registros = []
        for linea in lineas:
            linea = linea.strip()
            if not linea:
                continue
            try:
                d = json.loads(linea.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(d, dict):
                registros.append(d)
        return registros


def ts_iso(s) -> float:
    if not isinstance(s, str) or not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def limpiar_texto_usuario(c) -> str:
    """Texto de un mensaje del usuario sin envolturas de comandos ni recordatorios."""
    if isinstance(c, list):
        partes = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        c = "\n".join(partes)
    if not isinstance(c, str):
        return ""
    if "<command-name>" in c:
        m = re.search(r"<command-name>\s*([^<]+?)\s*</command-name>", c)
        a = re.search(r"<command-args>\s*([^<]*?)\s*</command-args>", c)
        if m:
            return (m.group(1) + (" " + a.group(1) if a and a.group(1) else "")).strip()
    if c.lstrip().startswith(("<local-command", "<system-reminder", "<task-notification", "Caveat:")):
        return ""
    return " ".join(_ETIQUETAS.sub(" ", c).split())


def interpretar(d: dict):
    """Convierte un registro en hechos simples. Devuelve (ts, agentId|None, lateral, hechos)."""
    t = d.get("type")
    ts = ts_iso(d.get("timestamp"))
    agente = d.get("agentId")
    lateral = bool(d.get("isSidechain"))
    hechos = []
    if t == "assistant":
        m = d.get("message") if isinstance(d.get("message"), dict) else {}
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt in ("thinking", "redacted_thinking"):
                hechos.append(("pensamiento", (b.get("thinking") or "").strip()))
            elif bt == "text":
                txt = (b.get("text") or "").strip()
                if txt:
                    hechos.append(("texto", txt))
            elif bt == "tool_use":
                hechos.append(("tool_use", b.get("id"), b.get("name"), b.get("input")))
        uso = m.get("usage")
        if isinstance(uso, dict) and m.get("id"):
            hechos.append(("uso", m.get("id"), uso, m.get("model")))
    elif t == "user":
        m = d.get("message") if isinstance(d.get("message"), dict) else {}
        c = m.get("content")
        resultados = [b for b in c if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(c, list) else []
        for b in resultados:
            hechos.append(("tool_result", b.get("tool_use_id"), bool(b.get("is_error"))))
        if not resultados and not d.get("isMeta"):
            texto = limpiar_texto_usuario(c)
            if texto:
                if "[Request interrupted by user" in texto:
                    hechos.append(("interrumpido",))
                else:
                    hechos.append(("encargo", texto))
        tur = d.get("toolUseResult")
        if isinstance(tur, dict) and tur.get("agentId"):
            hechos.append(("resultado_agente", tur))
    elif t == "system":
        st = d.get("subtype")
        if st == "turn_duration":
            hechos.append(("fin_turno", d.get("durationMs")))
        elif st == "compact_boundary":
            hechos.append(("compactado",))
    elif t == "custom-title" and d.get("customTitle"):
        hechos.append(("titulo", d["customTitle"], 3))
    elif t == "ai-title" and d.get("aiTitle"):
        hechos.append(("titulo", d["aiTitle"], 2))
    elif t == "summary" and d.get("summary"):
        hechos.append(("titulo", d["summary"], 1))
    return ts, agente, lateral, hechos


def dir_subagentes(transcript_path: str) -> str:
    base = transcript_path[:-6] if transcript_path.endswith(".jsonl") else transcript_path
    return os.path.join(base, "subagents")


def leer_meta(path_jsonl: str) -> dict:
    meta = path_jsonl[:-6] + ".meta.json" if path_jsonl.endswith(".jsonl") else path_jsonl + ".meta.json"
    try:
        with open(meta, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def id_de_archivo(path_jsonl: str) -> str:
    nombre = os.path.basename(path_jsonl)
    if nombre.endswith(".jsonl"):
        nombre = nombre[:-6]
    return nombre[6:] if nombre.startswith("agent-") else nombre


def normalizar_agente(agent_id) -> str:
    s = str(agent_id or "")
    return s[6:] if s.startswith("agent-") else s


def leer_cabecera(path: str, max_lineas: int = 60) -> dict:
    """cwd y sessionId de las primeras líneas (para sesiones descubiertas sin hooks)."""
    out = {}
    try:
        with open(path, "rb") as f:
            for _ in range(max_lineas):
                linea = f.readline()
                if not linea:
                    break
                try:
                    d = json.loads(linea.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                if d.get("cwd") and "cwd" not in out:
                    out["cwd"] = d["cwd"]
                if d.get("sessionId") and "sesion" not in out:
                    out["sesion"] = d["sessionId"]
                if "cwd" in out and "sesion" in out:
                    break
    except OSError:
        pass
    return out
