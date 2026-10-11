"""Estado vivo de la oficina: sesiones, su capataz, peones y ayudantes.

Entradas:
  aplicar_hook(ev)        eventos compactos que manda hook.py por UDP (tiempo real)
  aplicar_registros(...)  líneas nuevas de los transcripts (texto, tokens, títulos, respaldo)
  latigazo_oficina(...)   clic en la oficina
  tick()                  relojes: peones que se van, latigazos que no llegaron, sesiones viejas
Salida:
  snapshot()              lo que pinta la oficina (JSON)
  efectos                 animaciones puntuales (latigazos, entregas)

Sin hilos propios: el servidor serializa todo con self.lock.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque

import etiquetas
import nucleo
import transcripts

MAX_SILLAS_PEON = 6
MAX_SILLAS_AYUDANTE = 4
BITACORA_MAX = 80
HISTORIAL_AGENTE = 14
# Limpiezas para que una oficina que corre días no crezca sin fin.
OLVIDAR_AGENTE_INVISIBLE = 15 * 60   # un subagente que ya se fue
OLVIDAR_HERRAMIENTA = 30 * 60        # una herramienta "en curso" de la que nunca llegó el fin
RECORDAR_CERRADA = 10 * 60           # ids de herramientas ya terminadas (por si su inicio llega tarde)
RECORDAR_SESION_CERRADA = 2 * 3600   # para que el descubrimiento no reviva una sesión que cerraste


def _ahora():
    return time.time()


def _linea(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


class Modelo:
    def __init__(self, cfg=nucleo.config, sonar=None, reloj=_ahora, usar_bitacora_latigo=True):
        self.cfg = cfg
        self.sonar = sonar or (lambda nombre: None)
        self.reloj = reloj
        self.usar_bitacora_latigo = usar_bitacora_latigo
        self.sesiones = {}
        self.version = 0
        self.efectos = deque(maxlen=200)
        self.lock = threading.RLock()
        self.pedir_ventana = False
        self._ult_sonido = {}
        self.cerradas = {}  # sid -> cuándo se quitó de la oficina

    # ------------------------------------------------------------------ utilidades

    def _cambio(self):
        self.version += 1

    def _efecto(self, tipo, **kw):
        kw["tipo"] = tipo
        kw["t"] = self.reloj()
        self.efectos.append(kw)
        self._cambio()

    def _sonar(self, nombre, clave="", cada=0.0):
        ahora = self.reloj()
        k = nombre + ":" + clave
        if cada and ahora - self._ult_sonido.get(k, 0) < cada:
            return
        self._ult_sonido[k] = ahora
        try:
            self.sonar(nombre)
        except Exception as e:  # pragma: no cover
            nucleo.log_error("sonar", e)

    def _anotar(self, ses, ag, icono, texto, ahora=None):
        ahora = ahora or self.reloj()
        quien = ag["nombre"] if ag else ""
        ses["bitacora"].append({"t": ahora, "quien": quien, "rol": ag["rol"] if ag else "",
                                "icono": icono, "texto": _linea(texto, 160)})
        if ag is not None:
            ag["historial"].append({"t": ahora, "icono": icono, "texto": _linea(texto, 120)})

    # ------------------------------------------------------------------ sesiones y agentes

    def sesion(self, sid, cwd=None, transcript=None, crear=True):
        ses = self.sesiones.get(sid)
        ahora = self.reloj()
        if ses is None:
            if not crear:
                return None
            ses = {
                "id": sid, "cwd": cwd or "", "proyecto": os.path.basename((cwd or "").rstrip("/\\")) or "sesión",
                "titulo": None, "titulo_prio": 0, "transcript": transcript, "creada": ahora,
                "actividad": ahora, "estado": "activa", "fin": None, "modelo": None, "modo": None,
                "encargo": "", "turno_inicio": None, "agentes": {}, "bitacora": deque(maxlen=BITACORA_MAX),
                "tids_hook": set(), "tids_cerrados": {}, "agent_desc": deque(maxlen=20), "tarea_por_agente": {},
                "latigo": {"nivel": 0, "techo": 0, "latigazos": 0, "peones_activos": 0,
                           "enfriamiento_hasta": 0, "pendiente": None},
                "con_hooks": False, "demo": False,
            }
            ses["agentes"]["main"] = self._nuevo_agente(ses, "main", "capataz", "principal", ahora)
            self.sesiones[sid] = ses
            self.cerradas.pop(sid, None)
            self._cambio()
        if cwd and not ses["cwd"]:
            ses["cwd"] = cwd
            ses["proyecto"] = os.path.basename(cwd.rstrip("/\\")) or ses["proyecto"]
        if transcript and not ses["transcript"]:
            ses["transcript"] = transcript
        return ses

    def _nuevo_agente(self, ses, clave, rol, tipo, ahora):
        tipos_peon = self.cfg().get("tipos_peon", [])
        silla = None
        if rol == "peon":
            silla = self._silla_libre(ses, "peon", MAX_SILLAS_PEON)
        elif rol == "ayudante":
            silla = self._silla_libre(ses, "ayudante", MAX_SILLAS_AYUDANTE)
        if rol == "capataz":
            nombre = "Capataz"
        elif rol == "peon":
            nombre = "Peón %d" % (silla + 1) if silla is not None else "Peón"
        else:
            nombre = etiquetas.nombre_ayudante(tipo)
        return {
            "id": clave, "rol": rol, "tipo": tipo, "nombre": nombre, "silla": silla,
            "es_peon": tipo in tipos_peon, "tarea": "", "estado": "esperando" if rol == "capataz" else "arrancando",
            "desde": ahora, "actividad": ahora, "ultimo_hook": 0.0, "pend": {}, "permiso": None,
            "flash": None, "dijo": "", "dijo_t": 0.0, "pensamiento": "", "pens_t": 0.0,
            "tokens": {"salida": 0, "contexto": 0, "entrada": 0}, "_msgs": {}, "herramientas": 0,
            "errores": 0, "inicio": ahora, "fin": None, "resultado": "", "modelo": None, "rama": None,
            "visible": True, "historial": deque(maxlen=HISTORIAL_AGENTE),
        }

    def _silla_libre(self, ses, rol, maximo):
        ocupadas = {a["silla"] for a in ses["agentes"].values() if a["rol"] == rol and a["visible"]}
        for i in range(maximo):
            if i not in ocupadas:
                return i
        return None  # sin silla: se ve en el panel pero no en el escritorio

    def _agente_sub(self, ses, agent_id, agent_type, ahora, crear=True):
        clave = transcripts.normalizar_agente(agent_id)
        ag = ses["agentes"].get(clave)
        if ag is None and crear:
            tipo = agent_type or "subagente"
            rol = "peon" if tipo in self.cfg().get("tipos_peon", []) else "ayudante"
            ag = self._nuevo_agente(ses, clave, rol, tipo, ahora)
            ses["agentes"][clave] = ag
        return ag

    def _estado(self, ag, estado, ahora):
        if ag["estado"] != estado:
            ag["estado"] = estado
            ag["desde"] = ahora

    # ------------------------------------------------------------------ hooks (UDP)

    def aplicar_hook(self, ev):
        with self.lock:
            e = ev.get("e")
            sid = ev.get("s")
            if not e or not sid:
                return
            ahora = self.reloj()
            if e == "Latigo":
                return self._latigo_desde_hook(ev, ahora)
            if e == "LatigoCancelado":
                ses = self.sesiones.get(sid)
                if ses:
                    ses["latigo"]["pendiente"] = None
                    self._anotar(ses, ses["agentes"]["main"], "🫥", "Latigazo cancelado: llegó un encargo nuevo", ahora)
                    self._cambio()
                return
            if e == "SubagentStop" and not ev.get("at"):
                ses = self.sesiones.get(sid)
                if not ses or transcripts.normalizar_agente(ev.get("a")) not in ses["agentes"]:
                    return  # agentes internos (sugerencias, /btw)
            ses = self.sesion(sid, cwd=ev.get("cwd"), transcript=ev.get("tp"))
            if ev.get("tp") and ev["tp"] != ses["transcript"]:
                ses["transcript"] = ev["tp"]  # /resume o --resume desde otra carpeta: manda el hook
            if e == "SessionStart" and ev.get("cwd") and ev["cwd"] != ses["cwd"]:
                ses["cwd"] = ev["cwd"]
                ses["proyecto"] = os.path.basename(ev["cwd"].rstrip("/\\")) or ses["proyecto"]
            ses["actividad"] = ahora
            ses["con_hooks"] = True
            if ses["estado"] != "activa" and e not in ("SessionEnd",):
                ses["estado"] = "activa"
                ses["fin"] = None
            if ev.get("pm"):
                ses["modo"] = ev["pm"]
            if ev.get("a"):
                ag = self._agente_sub(ses, ev["a"], ev.get("at"), ahora)
            else:
                ag = ses["agentes"]["main"]
            ag["ultimo_hook"] = ahora
            ag["actividad"] = ahora
            manejador = getattr(self, "_h_" + e, None)
            if manejador:
                manejador(ses, ag, ev, ahora)
            self._cambio()

    def _h_SessionStart(self, ses, ag, ev, ahora):
        if ev.get("model"):
            ses["modelo"] = ev["model"]
        if ev.get("title"):
            self._titulo(ses, ev["title"], 4)
        if ev.get("src") == "compact":
            self._estado(ag, "pensando", ahora)
        elif ag["estado"] not in ("pensando",) and not ag["pend"]:
            self._estado(ag, "esperando", ahora)
        if ev.get("src") in ("startup", "clear", None):
            self._anotar(ses, ag, "🏢", "Abrió la oficina en %s" % ses["proyecto"], ahora)
        if ev.get("src") in ("startup", "resume", None):
            # Al arrancar Claude Code. "resume" es también `claude --resume/--continue`; la oficina
            # solo abre la ventana en ese caso si acaba de arrancar (ver servidor.py). Tras /clear
            # o una compactación no se reabre una caseta que cerraste a propósito.
            self.pedir_ventana = ev.get("src") or "startup"

    def _h_UserPromptSubmit(self, ses, ag, ev, ahora):
        prompt = ev.get("prompt") or ""
        if prompt.lstrip().startswith("<task-notification"):
            # Claude Code le avisa al capataz que un subagente terminó: no es un encargo nuevo.
            m = re.search(r"<summary>(.*?)</summary>", prompt, re.S)
            resumen = (m.group(1) if m else "un subagente terminó").strip()
            resumen = re.sub(r'^Agent "(.*)" (finished|completed)$', r"Terminó «\1»", resumen)
            self._estado(ag, "pensando", ahora)
            self._anotar(ses, ag, "📬", "Aviso: " + resumen, ahora)
            return
        if prompt.lstrip().startswith(("<system-reminder", "<local-command")):
            return
        ses["encargo"] = _linea(prompt, 240)
        ses["turno_inicio"] = ahora
        if ev.get("title"):
            self._titulo(ses, ev["title"], 4)
        ag["pend"].clear()
        ag["permiso"] = None
        self._estado(ag, "pensando", ahora)
        self._anotar(ses, ag, "📝", "Encargo: " + (prompt or "…"), ahora)

    def _cerrar_tid(self, ses, tid, ahora):
        if tid:
            ses["tids_cerrados"][tid] = ahora

    def _h_PreToolUse(self, ses, ag, ev, ahora):
        tid = ev.get("tid") or "t%d" % int(ahora * 1000)
        if len(ses["tids_hook"]) > 3000:
            ses["tids_hook"].clear()
        ses["tids_hook"].add(tid)
        inp = ev.get("in") or {}
        cat, icono, texto, detalle = etiquetas.etiqueta(ev.get("tool"), inp, ses["cwd"], self.cfg().get("tipos_peon", []))
        ag["herramientas"] += 1
        if tid in ses["tids_cerrados"]:
            # Los hooks async llegan por UDP en desorden: si el fin de esta herramienta llegó
            # primero, ya terminó y no se queda "en curso" para siempre.
            self._anotar(ses, ag, icono, texto, ahora)
            return
        ag["pend"][tid] = {"cat": cat, "icono": icono, "texto": texto, "detalle": detalle, "t": ahora, "tool": ev.get("tool")}
        ag["permiso"] = None
        self._estado(ag, cat, ahora)
        if ev.get("tool") in ("Agent", "Task"):
            ses["agent_desc"].append({"tid": tid, "tipo": inp.get("subagent_type") or "general-purpose",
                                      "desc": inp.get("description") or "", "t": ahora})
        self._anotar(ses, ag, icono, texto, ahora)

    def _quitar_pend(self, ses, ag, tid):
        if tid in ag["pend"]:
            ag["pend"].pop(tid, None)
            return
        for otro in ses["agentes"].values():  # por si el evento llegó con otro agente
            if tid in otro["pend"]:
                otro["pend"].pop(tid, None)
                return

    def _h_PostToolUse(self, ses, ag, ev, ahora):
        self._quitar_pend(ses, ag, ev.get("tid"))
        self._cerrar_tid(ses, ev.get("tid"), ahora)
        ag["permiso"] = None
        if ev.get("tool") in ("Agent", "Task"):
            res = ev.get("res") or {}
            aid = transcripts.normalizar_agente(res.get("agentId"))
            if aid:
                desc = res.get("description") or ""
                ses["tarea_por_agente"][aid] = desc
                sub = ses["agentes"].get(aid)
                if sub is not None:
                    if desc and not sub["tarea"]:
                        sub["tarea"] = _linea(desc, 60)
                    if res.get("worktreeBranch"):
                        sub["rama"] = res.get("worktreeBranch")
        if not ag["pend"]:
            self._estado(ag, "pensando", ahora)

    def _h_PostToolUseFailure(self, ses, ag, ev, ahora):
        self._quitar_pend(ses, ag, ev.get("tid"))
        self._cerrar_tid(ses, ev.get("tid"), ahora)
        ag["permiso"] = None
        if not ev.get("int"):
            ag["errores"] += 1
            err = ev.get("err") or "error"
            ag["flash"] = {"icono": "⚠️", "texto": "Falló: " + _linea(err, 60), "hasta": ahora + 3.5}
            self._anotar(ses, ag, "⚠️", "Falló %s: %s" % (ev.get("tool"), err), ahora)
        if not ag["pend"]:
            self._estado(ag, "pensando", ahora)

    def _h_PostToolBatch(self, ses, ag, ev, ahora):
        tids = ev.get("tids") or []
        for tid in tids:
            ag["pend"].pop(tid, None)
            self._cerrar_tid(ses, tid, ahora)
        if not tids:
            ag["pend"].clear()
        ag["permiso"] = None
        if not ag["pend"]:
            self._estado(ag, "pensando", ahora)

    def _h_PermissionRequest(self, ses, ag, ev, ahora):
        _, icono, texto, detalle = etiquetas.etiqueta(ev.get("tool"), ev.get("in") or {}, ses["cwd"])
        ag["permiso"] = {"texto": "Pide permiso: " + texto, "detalle": detalle, "t": ahora}
        self._estado(ag, "permiso", ahora)
        self._anotar(ses, ag, "🙋", "Pide permiso: " + texto, ahora)
        self._sonar("permiso", ses["id"], cada=8)

    def _h_PermissionDenied(self, ses, ag, ev, ahora):
        ag["permiso"] = None
        self._anotar(ses, ag, "🚫", "Permiso negado" + (": " + ev["razon"] if ev.get("razon") else ""), ahora)

    def _h_Notification(self, ses, ag, ev, ahora):
        nt = ev.get("nt")
        if nt == "permission_prompt":
            if not any(a["permiso"] for a in ses["agentes"].values()):
                ag["permiso"] = {"texto": _linea(ev.get("msg") or "Necesita tu permiso", 60), "detalle": "", "t": ahora}
                self._sonar("permiso", ses["id"], cada=8)
        elif nt == "idle_prompt":
            if ag["estado"] == "esperando" and not ag["pend"]:
                self._estado(ag, "durmiendo", ahora)
        elif nt in ("elicitation_dialog", "elicitation_url_dialog", "agent_needs_input"):
            ag["permiso"] = {"texto": _linea(ev.get("msg") or "Necesita tu respuesta", 60), "detalle": "", "t": ahora}

    def _h_SubagentStart(self, ses, ag, ev, ahora):
        if ag["visible"] is False or ag["estado"] in ("terminado", "saliendo"):
            # reanudado: vuelve a su escritorio
            ag["visible"] = True
            ag["fin"] = None
            if ag["rol"] in ("peon", "ayudante") and ag["silla"] is None:
                ag["silla"] = self._silla_libre(ses, ag["rol"], MAX_SILLAS_PEON if ag["rol"] == "peon" else MAX_SILLAS_AYUDANTE)
        if not ag["tarea"]:
            ag["tarea"] = _linea(ses["tarea_por_agente"].get(ag["id"]) or self._desc_para(ses, ag["tipo"], ahora), 60)
        self._estado(ag, "arrancando", ahora)
        self._anotar(ses, ag, "🚪", "Llegó %s%s" % (ag["nombre"], (": " + ag["tarea"]) if ag["tarea"] else ""), ahora)

    def _desc_para(self, ses, tipo, ahora):
        for i, d in enumerate(ses["agent_desc"]):
            if d["tipo"] == tipo and ahora - d["t"] < 120:
                del ses["agent_desc"][i]
                return d["desc"]
        return ""

    def _h_SubagentStop(self, ses, ag, ev, ahora):
        ag["pend"].clear()
        ag["permiso"] = None
        ag["fin"] = ahora
        ag["resultado"] = _linea(ev.get("last") or "", 400)
        self._estado(ag, "terminado", ahora)
        self._anotar(ses, ag, "✅", "%s terminó%s" % (ag["nombre"], (": " + _linea(ev.get("last"), 100)) if ev.get("last") else ""), ahora)
        if ag["rol"] == "peon":
            self._sonar("peon_listo", ses["id"] + ag["id"])

    def _h_Stop(self, ses, ag, ev, ahora):
        ag["pend"].clear()
        ag["permiso"] = None
        if ev.get("last"):
            ag["dijo"] = _linea(ev["last"], 400)
            ag["dijo_t"] = ahora
        if ev.get("sigue"):
            self._estado(ag, "pensando", ahora)
            return
        subs = [b for b in (ev.get("bg") or []) if b.get("type") in ("subagent", "teammate", "workflow")]
        self._estado(ag, "esperando_peones" if subs else "esperando", ahora)
        dur = ahora - (ses.get("turno_inicio") or ahora)
        if not subs:
            self._anotar(ses, ag, "🏁", "Terminó el turno (%s)" % _duracion(dur), ahora)
            if dur >= float(self.cfg().get("sonido_listo_min_segundos") or 0):
                self._sonar("listo", ses["id"], cada=5)
        else:
            self._anotar(ses, ag, "👀", "Espera a %d subagente%s" % (len(subs), "" if len(subs) == 1 else "s"), ahora)

    def _h_StopFailure(self, ses, ag, ev, ahora):
        ag["pend"].clear()
        texto = etiquetas.ERRORES_API.get(ev.get("error") or "", "Error de la API")
        ag["flash"] = {"icono": "⚠️", "texto": texto, "hasta": ahora + 30}
        self._estado(ag, "error", ahora)
        self._anotar(ses, ag, "⚠️", texto + (": " + ev["det"] if ev.get("det") else ""), ahora)
        self._sonar("error", ses["id"], cada=5)

    def _h_PreCompact(self, ses, ag, ev, ahora):
        self._estado(ag, "compactando", ahora)
        self._anotar(ses, ag, "🗜️", "Compactando la conversación", ahora)

    def _h_PostCompact(self, ses, ag, ev, ahora):
        self._estado(ag, "pensando", ahora)

    def _h_SessionEnd(self, ses, ag, ev, ahora):
        ses["estado"] = "terminada"
        ses["fin"] = ahora
        for a in ses["agentes"].values():
            a["pend"].clear()
            a["permiso"] = None
        self._estado(ses["agentes"]["main"], "esperando", ahora)
        self._anotar(ses, ses["agentes"]["main"], "🏁", "Cerró la sesión", ahora)

    # ------------------------------------------------------------------ látigo

    def _refrescar_latigo(self, ses):
        """Copia el estado del látigo de la bitácora en disco (la fuente de verdad)."""
        if not self.usar_bitacora_latigo or ses.get("demo"):
            return False
        bit = nucleo.leer_bitacora(ses["id"])
        cfg = self.cfg()
        nivel = int(bit.get("nivel") or 0)
        iny = nucleo.leer_inyeccion(ses["id"])
        nuevo = {
            "nivel": nivel,
            "techo": nucleo.techo_para(nivel, cfg),
            "latigazos": int(bit.get("latigazos") or 0),
            "peones_activos": len(bit.get("peones") or {}),
            "enfriamiento_hasta": (float(bit.get("ultimo_efectivo") or 0) + float(cfg.get("enfriamiento_segundos") or 0))
            if nivel else 0,
            "pendiente": {"creado": iny.get("creado"), "expira": iny.get("expira")} if iny else None,
        }
        if nuevo != ses["latigo"]:
            ses["latigo"] = nuevo
            return True
        return False

    def _latigo_desde_hook(self, ev, ahora):
        ses = self.sesion(ev.get("s"))
        cap = ses["agentes"]["main"]
        res = ev.get("res") or {}
        if ev.get("entregado"):
            ses["latigo"]["pendiente"] = None
            self._anotar(ses, cap, "📨", "El capataz recibió el latigazo", ahora)
            self._efecto("latigazo_entregado", sesion=ses["id"])
        else:
            self._sonar("latigazo", ses["id"], cada=0.15)
            texto = nucleo.motivo_corto(res)
            origen = {"mensaje": "por mensaje", "comando": "con /latigo", "skill": "con la skill"}.get(res.get("origen"), "")
            self._anotar(ses, cap, "🪢", ("Latigazo %s: %s" % (origen, texto)).replace("  ", " "), ahora)
            self._efecto("latigazo", sesion=ses["id"], objetivo="capataz", res=res, texto=texto)
        self._refrescar_latigo(ses)
        self._cambio()

    def latigazo_oficina(self, sid, objetivo="capataz", agente=None, sonar=True):
        with self.lock:
            ses = self.sesiones.get(sid)
            if sonar:  # suena siempre, aunque no haya obra; si la caseta ya lo tocó, no se repite
                self._sonar("latigazo", "oficina", cada=0.12)
            if ses is None:
                res = {"efectivo": False, "motivo": "sin_obra"}
                return {"ok": True, "res": res, "texto": nucleo.motivo_corto(res)}
            ahora = self.reloj()
            cap = ses["agentes"]["main"]
            if objetivo != "capataz":
                res = {"efectivo": False, "motivo": "meme"}
                ag = ses["agentes"].get(agente or "")
                texto = "¡Ay!" if ag else "¡Chas!"
                self._efecto("latigazo", sesion=sid, objetivo=objetivo, agente=agente, res=res, texto=texto)
                return {"ok": True, "res": res, "texto": texto}
            ocupado = bool(cap["pend"]) or cap["estado"] not in ("esperando", "durmiendo", "error") or \
                any(a["visible"] and a["rol"] != "capataz" and a["estado"] not in ("terminado", "saliendo")
                    for a in ses["agentes"].values())
            if ses.get("demo"):
                res = self._latigazo_demo(ses, ahora)
            elif not ocupado or ses["estado"] != "activa":
                res = {"efectivo": False, "motivo": "capataz_esperando", "origen": "oficina", "ts": ahora}
            elif nucleo.hay_inyeccion(sid):
                # El anterior todavía no le llega: otro no suma (y si el primero vence, se deshace solo).
                res = {"efectivo": False, "motivo": "en_camino", "origen": "oficina", "ts": ahora}
            else:
                res = nucleo.registrar_latigazo(sid, "oficina", ahora=ahora)
                if res.get("efectivo"):
                    nucleo.poner_inyeccion(sid, nucleo.texto_latigazo(res), res)
            texto = nucleo.motivo_corto(res)
            self._anotar(ses, cap, "🪢", "Latigazo desde la oficina: " + texto, ahora)
            self._efecto("latigazo", sesion=sid, objetivo="capataz", res=res, texto=texto)
            self._refrescar_latigo(ses)
            return {"ok": True, "res": res, "texto": texto}

    def _latigazo_demo(self, ses, ahora):
        lat = ses["latigo"]
        if lat.get("peones_activos"):
            return {"efectivo": False, "motivo": "peones_trabajando", "peones_activos": lat["peones_activos"]}
        if ahora < float(lat.get("enfriamiento_hasta") or 0):
            return {"efectivo": False, "motivo": "enfriamiento", "restante": int(lat["enfriamiento_hasta"] - ahora + 0.5)}
        lat["nivel"] = int(lat.get("nivel") or 0) + 1
        lat["techo"] = nucleo.techo_para(lat["nivel"], self.cfg())
        lat["enfriamiento_hasta"] = ahora + float(self.cfg().get("enfriamiento_segundos") or 60)
        return {"efectivo": True, "nivel": lat["nivel"], "techo": lat["techo"], "origen": "oficina", "ts": ahora}

    # ------------------------------------------------------------------ transcripts

    def _titulo(self, ses, titulo, prio):
        if titulo and prio >= ses["titulo_prio"]:
            ses["titulo"] = _linea(titulo, 60)
            ses["titulo_prio"] = prio

    def aplicar_registros(self, sid, registros, archivo_agente=None, meta=None, vivo=True):
        """Procesa registros de un transcript. archivo_agente = id si viene de subagents/."""
        if not registros:
            return
        with self.lock:
            ses = self.sesiones.get(sid)
            if ses is None:
                return
            ahora = self.reloj()
            for d in registros:
                ts, agid, lateral, hechos = transcripts.interpretar(d)
                if not hechos:
                    continue
                if archivo_agente or lateral:
                    clave = transcripts.normalizar_agente(agid or archivo_agente)
                    ag = ses["agentes"].get(clave)
                    if ag is None:
                        if not vivo or (ts and ahora - ts > 120):
                            continue  # historia vieja de un subagente que ya no está
                        tipo = (meta or {}).get("agentType") or "subagente"
                        ag = self._agente_sub(ses, clave, tipo, ahora)
                        ag["tarea"] = _linea((meta or {}).get("description") or "", 60)
                        self._estado(ag, "pensando", ahora)
                        self._anotar(ses, ag, "🚪", "Llegó %s%s" % (ag["nombre"], (": " + ag["tarea"]) if ag["tarea"] else ""), ahora)
                else:
                    ag = ses["agentes"]["main"]
                if (archivo_agente or lateral) and d.get("gitBranch") and not ag["rama"] \
                        and str(d.get("gitBranch")).startswith("worktree-"):
                    ag["rama"] = d["gitBranch"]
                for h in hechos:
                    self._hecho(ses, ag, h, ts or ahora, ahora, vivo)
            self._cambio()

    def _hecho(self, ses, ag, h, ts, ahora, vivo):
        tipo = h[0]
        sin_hooks = ahora - ag["ultimo_hook"] > 4
        reciente = vivo and ahora - ts < 90
        if tipo == "uso":
            _, mid, uso, modelo = h
            entrada = int(uso.get("input_tokens") or 0)
            cc = int(uso.get("cache_creation_input_tokens") or 0)
            cr = int(uso.get("cache_read_input_tokens") or 0)
            sal = int(uso.get("output_tokens") or 0)
            previo = ag["_msgs"].get(mid)
            if previo is None or sal > previo:
                ag["tokens"]["salida"] += sal - (previo or 0)
                ag["_msgs"][mid] = sal
                if len(ag["_msgs"]) > 4000:
                    ag["_msgs"].clear()
            ag["tokens"]["contexto"] = entrada + cc + cr
            if previo is None:
                ag["tokens"]["entrada"] += entrada + cc + cr
            if modelo and not str(modelo).startswith("<"):
                ag["modelo"] = modelo
                if ag["rol"] == "capataz":
                    ses["modelo"] = modelo
        elif tipo == "texto":
            ag["dijo"] = _linea(h[1], 400)
            ag["dijo_t"] = ts if reciente else 0.0
            if reciente:
                self._anotar(ses, ag, "💬", h[1], ahora)
        elif tipo == "pensamiento":
            if h[1]:
                ag["pensamiento"] = _linea(h[1], 300)
                ag["pens_t"] = ts if reciente else 0.0
            if reciente and sin_hooks and not ag["pend"] and ag["estado"] not in ("terminado", "saliendo"):
                self._estado(ag, "pensando", ahora)
        elif tipo == "tool_use":
            _, tid, nombre, entrada = h
            if not reciente or not tid or tid in ses["tids_hook"] or tid in ses["tids_cerrados"] or not sin_hooks:
                return
            resumen = _resumir_entrada_tr(nombre, entrada)
            cat, icono, texto, detalle = etiquetas.etiqueta(nombre, resumen, ses["cwd"], self.cfg().get("tipos_peon", []))
            ag["pend"][tid] = {"cat": cat, "icono": icono, "texto": texto, "detalle": detalle, "t": ahora,
                               "tool": nombre, "origen": "transcript"}
            ag["herramientas"] += 1
            self._estado(ag, cat, ahora)
            self._anotar(ses, ag, icono, texto, ahora)
        elif tipo == "tool_result":
            if h[1] in ag["pend"]:
                ag["pend"].pop(h[1], None)
                if not ag["pend"] and sin_hooks:
                    self._estado(ag, "pensando", ahora)
        elif tipo == "encargo":
            if ag["rol"] == "capataz":
                ses["encargo"] = _linea(h[1], 240)
                if reciente and sin_hooks:
                    ses["turno_inicio"] = ts
                    self._estado(ag, "pensando", ahora)
            elif not ag["tarea"]:
                ag["tarea"] = _linea(h[1], 60)
        elif tipo == "interrumpido":
            if reciente:
                ag["pend"].clear()
                ag["permiso"] = None
                self._estado(ag, "esperando", ahora)
                self._anotar(ses, ag, "✋", "Lo interrumpiste", ahora)
        elif tipo == "fin_turno":
            if reciente and sin_hooks and ag["rol"] == "capataz":
                ag["pend"].clear()
                self._estado(ag, "esperando", ahora)
        elif tipo == "compactado":
            if ag["estado"] == "compactando":
                self._estado(ag, "pensando", ahora)
        elif tipo == "titulo":
            self._titulo(ses, h[1], h[2])
        elif tipo == "resultado_agente":
            tur = h[1]
            sub = ses["agentes"].get(transcripts.normalizar_agente(tur.get("agentId")))
            if sub is not None and tur.get("worktreeBranch"):
                sub["rama"] = tur.get("worktreeBranch")

    def conoce(self, sid, mtime):
        """True si la sesión ya está en la oficina o la quitamos hace poco y su transcript no ha cambiado."""
        with self.lock:
            if sid in self.sesiones:
                return True
            cerrada = self.cerradas.get(sid)
            # Claude Code todavía escribe un par de líneas (título, resumen) después de cerrar.
            return cerrada is not None and mtime < cerrada + 60

    def descubrir(self, sid, transcript, cwd, mtime):
        """Sesión encontrada por su transcript (sin hooks todavía)."""
        with self.lock:
            if self.conoce(sid, mtime) and sid not in self.sesiones:
                return None
            nueva = sid not in self.sesiones
            ses = self.sesion(sid, cwd=cwd, transcript=transcript)
            if nueva:
                ses["actividad"] = mtime
                cap = ses["agentes"]["main"]
                cap["actividad"] = mtime
                self._estado(cap, "pensando" if self.reloj() - mtime < 20 else "esperando", self.reloj())
            return ses

    # ------------------------------------------------------------------ relojes

    def tick(self):
        with self.lock:
            ahora = self.reloj()
            cambio = False
            for sid in list(self.sesiones):
                ses = self.sesiones[sid]
                if self._refrescar_latigo(ses):
                    cambio = True
                pend = ses["latigo"].get("pendiente")
                if pend and ahora > float(pend.get("expira") or 0) and not ses.get("demo"):
                    if nucleo.descartar_inyeccion(sid):
                        self._anotar(ses, ses["agentes"]["main"], "🫥",
                                     "El latigazo no le llegó a tiempo al capataz: no cuenta", ahora)
                        self._efecto("latigazo_perdido", sesion=sid)
                    self._refrescar_latigo(ses)
                    ses["latigo"]["pendiente"] = None
                    cambio = True
                if self._podar_sesion(ses, ahora):
                    cambio = True
                for ag in ses["agentes"].values():
                    if ag["rol"] == "capataz":
                        if ag["estado"] in ("pensando",) and not ag["pend"] and ahora - ag["actividad"] > 20 * 60 \
                                and ahora - ses["actividad"] > 20 * 60:
                            self._estado(ag, "esperando", ahora)
                            cambio = True
                        continue
                    if ag["estado"] == "arrancando" and ahora - ag["desde"] > 2.5:
                        self._estado(ag, "pensando" if not ag["pend"] else ag["estado"], ahora)
                        cambio = True
                    if ag["estado"] == "terminado" and ag["fin"] and ahora - ag["fin"] > 10:
                        self._estado(ag, "saliendo", ahora)
                        cambio = True
                    elif ag["estado"] == "saliendo" and ag["visible"] and ahora - ag["desde"] > 6:
                        ag["visible"] = False
                        ag["silla"] = None
                        cambio = True
                    elif ag["visible"] and ag["estado"] not in ("terminado", "saliendo") and \
                            ahora - ag["actividad"] > 45 * 60:
                        ag["visible"] = False  # subagente perdido sin SubagentStop
                        ag["silla"] = None
                        cambio = True
                if (ses["estado"] == "terminada" and ses["fin"] and ahora - ses["fin"] > 180) or \
                        ahora - ses["actividad"] > 60 * 60:
                    del self.sesiones[sid]
                    self.cerradas[sid] = ahora
                    cambio = True
            for sid, t in list(self.cerradas.items()):
                if ahora - t > RECORDAR_SESION_CERRADA:
                    del self.cerradas[sid]
            for k, t in list(self._ult_sonido.items()):
                if ahora - t > 3600:
                    del self._ult_sonido[k]
            if cambio:
                self._cambio()

    def _podar_sesion(self, ses, ahora):
        """Olvida lo que ya no se ve: subagentes que se fueron, herramientas huérfanas, ids viejos."""
        cambio = False
        for clave, ag in list(ses["agentes"].items()):
            if ag["rol"] != "capataz" and not ag["visible"] and ahora - ag["desde"] > OLVIDAR_AGENTE_INVISIBLE:
                del ses["agentes"][clave]
                ses["tarea_por_agente"].pop(clave, None)
                cambio = True
                continue
            viejas = [tid for tid, p in ag["pend"].items() if ahora - p["t"] > OLVIDAR_HERRAMIENTA]
            for tid in viejas:
                ag["pend"].pop(tid, None)
                cambio = True
            if viejas and not ag["pend"] and ag["estado"] not in ("terminado", "saliendo", "esperando", "durmiendo"):
                self._estado(ag, "esperando" if ag["rol"] == "capataz" else "pensando", ahora)
        for tid, t in list(ses["tids_cerrados"].items()):
            if ahora - t > RECORDAR_CERRADA:
                del ses["tids_cerrados"][tid]
        if len(ses["tarea_por_agente"]) > 60:
            for clave in list(ses["tarea_por_agente"])[:-60]:
                del ses["tarea_por_agente"][clave]
        return cambio

    # ------------------------------------------------------------------ vista

    def _vista_agente(self, ag, ahora):
        globo = None
        if ag["permiso"]:
            cat, icono, texto, detalle = "permiso", "🙋", ag["permiso"]["texto"], ag["permiso"].get("detalle") or ""
        elif ag["pend"]:
            ult = max(ag["pend"].values(), key=lambda p: p["t"])
            cat, icono, texto, detalle = ult["cat"], ult["icono"], ult["texto"], ult["detalle"]
            if len(ag["pend"]) > 1:
                texto += "  (+%d)" % (len(ag["pend"]) - 1)
        elif ag["flash"] and ag["flash"]["hasta"] > ahora:
            cat, icono, texto, detalle = "error", ag["flash"]["icono"], ag["flash"]["texto"], ""
        else:
            cat = ag["estado"] if ag["estado"] in etiquetas.ESTADOS_BASE else "pensando"
            icono, texto = etiquetas.ESTADOS_BASE[cat]
            detalle = ""
            if cat == "terminado" and ag["resultado"]:
                detalle = ag["resultado"]
        if ag["dijo"] and ahora - ag["dijo_t"] < 9:
            globo = {"tipo": "dijo", "texto": _linea(ag["dijo"], 140)}
        elif ag["pensamiento"] and ahora - ag["pens_t"] < 9 and cat == "pensando":
            globo = {"tipo": "piensa", "texto": _linea(ag["pensamiento"], 140)}
        return {
            "id": ag["id"], "rol": ag["rol"], "tipo": ag["tipo"], "nombre": ag["nombre"], "silla": ag["silla"],
            "tarea": ag["tarea"], "cat": cat, "icono": icono, "texto": texto, "detalle": detalle,
            "desde": ag["desde"], "inicio": ag["inicio"], "fin": ag["fin"], "visible": ag["visible"],
            "tokens": dict(ag["tokens"]), "herramientas": ag["herramientas"], "errores": ag["errores"],
            "modelo": ag["modelo"], "rama": ag["rama"], "resultado": ag["resultado"], "globo": globo,
            "historial": list(ag["historial"]), "paralelas": len(ag["pend"]),
        }

    def snapshot(self):
        with self.lock:
            ahora = self.reloj()
            cfg = self.cfg()
            sesiones = []
            for ses in sorted(self.sesiones.values(), key=lambda s: -s["actividad"]):
                agentes = [self._vista_agente(a, ahora) for a in ses["agentes"].values()]
                orden = {"capataz": 0, "peon": 1, "ayudante": 2}
                agentes.sort(key=lambda a: (orden.get(a["rol"], 3), a["silla"] if a["silla"] is not None else 99, a["inicio"]))
                salida = sum(a["tokens"]["salida"] for a in agentes)
                sesiones.append({
                    "id": ses["id"], "proyecto": ses["proyecto"], "titulo": ses["titulo"], "cwd": ses["cwd"],
                    "estado": ses["estado"], "actividad": ses["actividad"], "creada": ses["creada"],
                    "modelo": ses["modelo"], "modo": ses["modo"], "encargo": ses["encargo"],
                    "turno_inicio": ses["turno_inicio"], "demo": ses["demo"], "con_hooks": ses["con_hooks"],
                    "latigo": dict(ses["latigo"]), "agentes": agentes, "bitacora": list(ses["bitacora"])[-50:],
                    "tokens_salida": salida,
                })
            return {
                "v": self.version, "ahora": ahora, "version": nucleo.VERSION,
                "config": {
                    "sonidos": cfg.get("sonidos"), "tope_peones": cfg.get("tope_peones"),
                    "techo_por_nivel": cfg.get("techo_por_nivel"),
                    "enfriamiento_segundos": cfg.get("enfriamiento_segundos"),
                    "abrir_oficina_al_iniciar": cfg.get("abrir_oficina_al_iniciar"),
                    "silencio": bool(cfg.get("silencio")), "volumen": cfg.get("volumen"),
                },
                "sesiones": sesiones,
            }


def _duracion(seg):
    seg = int(max(0, seg))
    if seg < 60:
        return "%d s" % seg
    if seg < 3600:
        return "%d min %02d s" % (seg // 60, seg % 60)
    return "%d h %02d min" % (seg // 3600, (seg % 3600) // 60)


def _resumir_entrada_tr(nombre, entrada):
    """Mismo resumen que hace hook.py, para herramientas vistas solo en el transcript."""
    try:
        import hook  # mismo directorio

        return hook.resumir_entrada(nombre or "", entrada if isinstance(entrada, dict) else {})
    except Exception:
        return entrada if isinstance(entrada, dict) else {}
