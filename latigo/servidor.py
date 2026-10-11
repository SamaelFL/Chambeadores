#!/usr/bin/env python3
"""Servidor de la oficina del látigo.

- Escucha los eventos de hook.py por UDP en 127.0.0.1 (mismo número de puerto que el HTTP).
- Lee los transcripts de las sesiones activas (texto, tokens, títulos, subagentes).
- Sirve la oficina (HTML/JS) y empuja el estado por SSE.
- Recibe los latigazos que das con el mouse y los deja listos para el siguiente hook.
- Toca los sonidos.

Solo escucha en 127.0.0.1 y exige un Host local (defensa contra DNS rebinding). La API
(estado, eventos y todo lo que cambia algo) exige además el token de la instalación, que
vive en estado/token (0600). El token nunca va en una URL ni en una línea de comandos: la
ventana se abre con un boleto de un solo uso (#p=…, vence en 2 minutos) que la página canjea
por el token. Los POST exigen también un Origin local, si viene (CSRF).
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Full, Queue
from urllib.parse import parse_qs, urlparse

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

import modelo as modelo_mod  # noqa: E402
import nucleo  # noqa: E402
import transcripts  # noqa: E402

WEB = os.path.join(AQUI, "web")
ESTATICOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/estilos.css": ("estilos.css", "text/css; charset=utf-8"),
    "/iso.js": ("iso.js", "text/javascript; charset=utf-8"),
    "/figuras.js": ("figuras.js", "text/javascript; charset=utf-8"),
    "/escena.js": ("escena.js", "text/javascript; charset=utf-8"),
    "/panel.js": ("panel.js", "text/javascript; charset=utf-8"),
    "/demo.js": ("demo.js", "text/javascript; charset=utf-8"),
    "/icono.svg": ("icono.svg", "image/svg+xml"),
}
for _f in ("archivo-expanded-800", "archivo-semiexpanded-600", "geist-400", "geist-500", "geist-mono-400", "geist-mono-500"):
    ESTATICOS["/fuentes/%s.woff2" % _f] = ("fuentes/%s.woff2" % _f, "font/woff2")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def log(msg: str) -> None:
    try:
        p = os.path.join(nucleo.dir_estado(), "servidor.log")
        if os.path.exists(p) and os.path.getsize(p) > 1_000_000:
            os.replace(p, p + ".1")
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


class Cliente:
    def __init__(self):
        self.cola = Queue(maxsize=60)

    def poner(self, tipo, datos):
        try:
            self.cola.put_nowait((tipo, datos))
        except Full:
            if tipo == "estado":  # el estado es completo: se tira lo viejo y queda el nuevo
                try:
                    while True:
                        self.cola.get_nowait()
                except Empty:
                    pass
                try:
                    self.cola.put_nowait((tipo, datos))
                except Full:
                    pass


class Oficina:
    def __init__(self, puerto: int, demo: bool = False):
        self.puerto = puerto
        # El mismo token entre reinicios: una caseta abierta sigue funcionando. Si no se pudo
        # leer ni crear, uno al azar solo para esta ejecución (nunca vacío).
        self.token = nucleo.token_oficina() or secrets.token_hex(16)
        self.boletos = {}  # boleto de un solo uso -> vence
        self.boletos_lock = threading.Lock()
        self.inicio = time.time()
        self.corriendo = True
        self.sonidos = Queue(maxsize=20)
        self.modelo = modelo_mod.Modelo(sonar=self._encolar_sonido)
        self.clientes = set()
        self.clientes_lock = threading.Lock()
        self.ultima_conexion = time.time()
        self.ultima_ventana = 0.0
        self.lectores = {}
        self.metas = {}
        self.ultimo_barrido_sub = {}
        self.subs_por_sesion = {}
        self.hosts = {"127.0.0.1:%d" % puerto, "localhost:%d" % puerto}
        self.origenes = {"http://127.0.0.1:%d" % puerto, "http://localhost:%d" % puerto}
        self.url = "http://127.0.0.1:%d/" % puerto
        self.demo = demo
        self._snap_cache = (None, b"")

    # ------------------------------------------------------------------ boletos para abrir la caseta

    def boleto(self) -> str:
        """Boleto de un solo uso para la URL de la ventana. Si alguien lo lee de la línea de
        comandos del navegador, ya está gastado o vencido."""
        ahora = time.time()
        b = secrets.token_urlsafe(18)
        with self.boletos_lock:
            for k in [k for k, v in self.boletos.items() if v < ahora]:
                del self.boletos[k]
            if len(self.boletos) > 50:
                self.boletos.clear()
            self.boletos[b] = ahora + 120
        return b

    def canjear(self, b) -> bool:
        if not isinstance(b, str) or not b:
            return False
        with self.boletos_lock:
            vence = self.boletos.pop(b, None)
        return vence is not None and vence > time.time()

    def url_caseta(self, demo=False) -> str:
        return self.url + ("?demo" if demo else "") + "#p=" + self.boleto()

    # ------------------------------------------------------------------ clientes SSE

    def registrar(self, c):
        with self.clientes_lock:
            self.clientes.add(c)
            self.ultima_conexion = time.time()

    def quitar(self, c):
        with self.clientes_lock:
            self.clientes.discard(c)
            self.ultima_conexion = time.time()

    def num_clientes(self):
        with self.clientes_lock:
            return len(self.clientes)

    def snapshot_json(self) -> bytes:
        v = self.modelo.version
        if self._snap_cache[0] == v:
            return self._snap_cache[1]
        datos = json.dumps(self.modelo.snapshot(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._snap_cache = (v, datos)
        return datos

    def difundir(self, tipo, datos: bytes):
        with self.clientes_lock:
            clientes = list(self.clientes)
        for c in clientes:
            c.poner(tipo, datos)

    # ------------------------------------------------------------------ sonidos

    def _encolar_sonido(self, nombre):
        try:
            self.sonidos.put_nowait(nombre)
        except Full:
            pass

    def bucle_sonidos(self):
        ultimo = 0.0
        while self.corriendo:
            try:
                nombre = self.sonidos.get(timeout=0.5)
            except Empty:
                continue
            espera = 0.12 - (time.time() - ultimo)
            if espera > 0:
                time.sleep(espera)
            nucleo.reproducir(nombre)
            ultimo = time.time()

    # ------------------------------------------------------------------ UDP

    def bucle_udp(self, sock):
        sock.settimeout(0.5)
        while self.corriendo:
            try:
                datos, origen = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if not self.corriendo:
                    break
                time.sleep(0.2)
                continue
            if origen[0] not in ("127.0.0.1", "::1"):
                continue
            try:
                ev = json.loads(datos.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("v") == 1:
                try:
                    self.modelo.aplicar_hook(ev)
                except Exception as e:
                    nucleo.log_error("aplicar_hook %s" % ev.get("e"), e)

    # ------------------------------------------------------------------ transcripts

    def _lector(self, path):
        lec = self.lectores.get(path)
        if lec is None:
            lec = transcripts.LectorJSONL(path)
            self.lectores[path] = lec
        return lec

    def bucle_transcripts(self):
        while self.corriendo:
            try:
                self._leer_transcripts()
            except Exception as e:
                nucleo.log_error("transcripts", e)
            time.sleep(0.35)

    def _podar_lectores(self, vivos):
        """Suelta lectores y metadatos de transcripts de sesiones que ya no están en la oficina."""
        for path in list(self.subs_por_sesion):
            if path not in vivos:
                for p in self.subs_por_sesion.pop(path, []):
                    self.lectores.pop(p, None)
                    self.metas.pop(p, None)
                self.ultimo_barrido_sub.pop(path, None)
        de_subs = {p for lista in self.subs_por_sesion.values() for p in lista}
        for path in list(self.lectores):
            if path not in vivos and path not in de_subs:
                self.lectores.pop(path, None)
                self.metas.pop(path, None)
        for path in list(self.ultimo_barrido_sub):
            if path not in vivos:
                self.ultimo_barrido_sub.pop(path, None)

    def _leer_transcripts(self):
        with self.modelo.lock:
            pares = [(s["id"], s["transcript"]) for s in self.modelo.sesiones.values()
                     if s["transcript"] and not s["demo"]]
        ahora = time.time()
        if ahora - getattr(self, "_ultima_poda", 0) > 30:
            self._ultima_poda = ahora
            self._podar_lectores({p for _, p in pares})
        for sid, path in pares:
            regs = self._lector(path).leer_nuevas()
            if regs:
                self.modelo.aplicar_registros(sid, regs)
            if ahora - self.ultimo_barrido_sub.get(path, 0) > 1.2:
                self.ultimo_barrido_sub[path] = ahora
                d = transcripts.dir_subagentes(path)
                try:
                    nombres = sorted(n for n in os.listdir(d) if n.endswith(".jsonl"))
                except OSError:
                    nombres = []
                lista = []
                for n in nombres:
                    p = os.path.join(d, n)
                    lista.append(p)
                    if p not in self.lectores:
                        try:
                            viejo = ahora - os.path.getmtime(p) > 600
                        except OSError:
                            continue
                        # Un subagente que terminó hace rato no se vuelve a sentar en la oficina.
                        self.lectores[p] = transcripts.LectorJSONL(p, desde_final=viejo)
                self.subs_por_sesion[path] = lista
            for p in self.subs_por_sesion.get(path, []):
                lec = self.lectores.get(p)
                if lec is None:
                    continue
                regs = lec.leer_nuevas()
                if regs:
                    if not self.metas.get(p):
                        self.metas[p] = transcripts.leer_meta(p)
                    self.modelo.aplicar_registros(sid, regs, archivo_agente=transcripts.id_de_archivo(p),
                                                  meta=self.metas[p])

    def bucle_descubrimiento(self):
        while self.corriendo:
            try:
                self._descubrir()
            except Exception as e:
                nucleo.log_error("descubrir", e)
            for _ in range(12):
                if not self.corriendo:
                    return
                time.sleep(0.5)

    def _descubrir(self):
        base = os.path.join(nucleo.dir_claude(), "projects")
        limite = time.time() - 15 * 60
        candidatos = []
        try:
            proyectos = list(os.scandir(base))
        except OSError:
            return
        for proy in proyectos:
            if not proy.is_dir():
                continue
            try:
                for f in os.scandir(proy.path):
                    if f.name.endswith(".jsonl") and not f.name.startswith("agent-") and f.is_file():
                        m = f.stat().st_mtime
                        if m > limite:
                            candidatos.append((m, f.path))
            except OSError:
                continue
        candidatos.sort(reverse=True)
        for mtime, path in candidatos[:12]:
            sid = os.path.basename(path)[:-6]
            if self.modelo.conoce(sid, mtime):
                continue  # ya está, o la cerraste hace poco y no ha cambiado
            cab = transcripts.leer_cabecera(path)
            self.modelo.descubrir(sid, path, cab.get("cwd"), mtime)

    # ------------------------------------------------------------------ latido y difusión

    def escribir_info(self):
        info = {"pid": os.getpid(), "puerto": self.puerto, "token": self.token, "inicio": self.inicio,
                "latido": time.time(), "version": nucleo.VERSION, "url": self.url}
        estado = nucleo.dir_estado()
        nucleo.escribir_json(os.path.join(estado, "servidor.json"), info, modo=0o600)
        # El archivo `puerto` es lo que leen los hooks para mandar la telemetría: se repara solo
        # si alguien lo borró (por ejemplo, otra oficina que se cerró).
        p = os.path.join(estado, "puerto")
        if nucleo.puerto_servidor() != self.puerto:
            tmp = "%s.%d" % (p, os.getpid())
            with open(tmp, "w", encoding="ascii") as f:
                f.write(str(self.puerto))
            nucleo.reemplazar(tmp, p)
        if not getattr(self, "_arranque_suelto", False):
            self._arranque_suelto = True
            try:
                os.remove(nucleo.ruta_arranque())  # ya estamos vivos: otro hook ya puede intentarlo
            except OSError:
                pass

    def _cedo_ante(self, info):
        """True si otra oficina viva tiene preferencia: gana la que arrancó primero."""
        otro = info.get("pid")
        if otro in (None, os.getpid()):
            return False
        try:
            if time.time() - float(info.get("latido") or 0) >= 4:
                return False
            return (float(info.get("inicio") or 0), int(otro)) < (self.inicio, os.getpid())
        except (TypeError, ValueError):
            return False

    def _limpiar_bitacoras(self):
        """Borra bitácoras e inyecciones de sesiones de hace más de una semana."""
        limite = time.time() - 7 * 86400
        try:
            d = nucleo.dir_latigos()
            for f in os.scandir(d):
                try:
                    if f.is_file() and f.stat().st_mtime < limite:
                        os.remove(f.path)
                except OSError:
                    continue
        except OSError:
            pass

    def bucle_latido(self):
        ultimo_tick = 0.0
        ultima_limpieza = 0.0
        while self.corriendo:
            ahora = time.time()
            if ahora - ultimo_tick >= 1.0:
                ultimo_tick = ahora
                try:
                    self.modelo.tick()
                except Exception as e:
                    nucleo.log_error("tick", e)
                info = nucleo.info_servidor()
                if self._cedo_ante(info):
                    log("otra oficina (pid %s) arrancó antes que yo; salgo" % info.get("pid"))
                    self.detener()
                    return
                try:
                    self.escribir_info()
                except OSError as e:
                    nucleo.log_error("escribir_info", e)
                if ahora - ultima_limpieza > 3600:
                    ultima_limpieza = ahora
                    self._limpiar_bitacoras()
                minutos = float(nucleo.config().get("apagar_tras_inactividad_min") or 180)
                if not self.modelo.sesiones and self.num_clientes() == 0 and \
                        ahora - max(self.ultima_conexion, self.inicio) > minutos * 60:
                    log("sin sesiones ni ventanas por %d min; me apago" % minutos)
                    self.detener()
                    return
            pedido = self.modelo.pedir_ventana
            # Después de 2.5 s: si arrancaron dos oficinas a la vez, ya se decidió cuál se queda.
            if pedido and ahora - self.inicio > 2.5:
                self.modelo.pedir_ventana = False
                # `claude --resume` también llega como "resume": solo abre si esta oficina acaba de
                # arrancar con esa sesión (no tras un /resume con la caseta cerrada a propósito).
                if pedido != "resume" or ahora - self.inicio < 30:
                    self.quizas_abrir_ventana()
            time.sleep(0.25)

    def bucle_difusion(self):
        ultima_v = -1
        while self.corriendo:
            try:
                efectos = []
                while self.modelo.efectos:
                    efectos.append(self.modelo.efectos.popleft())
                for ef in efectos:
                    self.difundir("efecto", json.dumps(ef, ensure_ascii=False).encode("utf-8"))
                if self.modelo.version != ultima_v and self.num_clientes():
                    ultima_v = self.modelo.version
                    self.difundir("estado", self.snapshot_json())
            except Exception as e:
                nucleo.log_error("difusion", e)
            time.sleep(0.08)

    def quizas_abrir_ventana(self, forzar=False):
        if not forzar:
            if not nucleo.config().get("abrir_oficina_al_iniciar", True):
                return
            if self.num_clientes() > 0 or time.time() - self.ultima_ventana < 90:
                return
        self.ultima_ventana = time.time()
        try:
            import ventana

            ventana.abrir(self.url_caseta())
        except Exception as e:
            nucleo.log_error("abrir ventana", e)

    def detener(self):
        self.corriendo = False
        try:
            info = nucleo.info_servidor()
            if info.get("pid") == os.getpid():
                info["latido"] = 0
                nucleo.escribir_json(os.path.join(nucleo.dir_estado(), "servidor.json"), info, modo=0o600)
                os.remove(os.path.join(nucleo.dir_estado(), "puerto"))
        except OSError:
            pass
        httpd = getattr(self, "httpd", None)
        if httpd is not None:
            threading.Thread(target=httpd.shutdown, daemon=True).start()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Manejador(BaseHTTPRequestHandler):
    server_version = "Latigo/" + nucleo.VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"

    @property
    def of(self) -> Oficina:
        return self.server.oficina  # type: ignore[attr-defined]

    def log_message(self, *args):
        pass

    def _cabeceras_seguridad(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def _responder(self, codigo, cuerpo: bytes, tipo="application/json; charset=utf-8", cache=False):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "max-age=60" if cache else "no-store")
        if getattr(self, "close_connection", False):
            self.send_header("Connection", "close")
        self._cabeceras_seguridad()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _json(self, codigo, obj):
        self._responder(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _host_ok(self):
        if self.headers.get("Host", "") not in self.of.hosts:
            self._rechazar(403, "host")
            return False
        return True

    def _rechazar(self, codigo, motivo):
        # Sin leer el cuerpo, la conexión keep-alive quedaría con basura: se cierra.
        self.close_connection = True
        self._json(codigo, {"error": motivo})

    def _token_ok(self, query=None):
        dado = self.headers.get("X-Latigo-Token") or ""
        if not dado and query is not None:
            dado = (parse_qs(query).get("t") or [""])[0]
        return bool(dado) and secrets.compare_digest(dado.encode(), self.of.token.encode())

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return
        url = urlparse(self.path)
        ruta = url.path
        if ruta in ("/api/eventos", "/api/estado"):
            if not self._token_ok(url.query):
                return self._rechazar(403, "token")
            if ruta == "/api/eventos":
                return self._sse()
            return self._responder(200, self.of.snapshot_json())
        if ruta.startswith("/sonidos/") and ruta.endswith(".wav") and ruta[9:-4] in nucleo.SONIDOS:
            p = nucleo.ruta_sonido(ruta[9:-4])  # la demostración toca el mismo latigazo que la oficina
            if p:
                with open(p, "rb") as f:
                    return self._responder(200, f.read(), "audio/wav", cache=True)
            return self._json(404, {"error": "no existe"})
        if ruta == "/api/salud":
            return self._json(200, {"ok": True, "version": nucleo.VERSION})
        if ruta in ESTATICOS:
            nombre, tipo = ESTATICOS[ruta]
            try:
                with open(os.path.join(WEB, nombre), "rb") as f:
                    cuerpo = f.read()
            except OSError:
                return self._json(404, {"error": "no existe"})
            if nombre == "index.html":
                cuerpo = cuerpo.replace(b"{{VERSION}}", nucleo.VERSION.encode())
            return self._responder(200, cuerpo, tipo, cache=False)
        self._json(404, {"error": "no existe"})

    def do_POST(self):
        if not self._host_ok():
            return
        origen = self.headers.get("Origin")
        if origen and origen not in self.of.origenes:
            return self._rechazar(403, "origen")
        ruta = urlparse(self.path).path
        canje = ruta == "/api/canjear"  # lo único que no pide token: lo da a cambio del boleto
        if not canje and not self._token_ok():
            return self._rechazar(403, "token")
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._rechazar(400, "largo")
        if largo < 0 or largo > (2_000 if canje else 20_000):
            return self._rechazar(413, "muy grande")
        try:
            datos = json.loads(self.rfile.read(largo).decode("utf-8") or "{}") if largo else {}
        except (ValueError, UnicodeDecodeError):
            return self._rechazar(400, "json")
        if not isinstance(datos, dict):
            return self._json(400, {"error": "json"})
        if canje:
            if self.of.canjear(datos.get("boleto")):
                return self._json(200, {"token": self.of.token})
            return self._rechazar(403, "boleto")
        if ruta == "/api/boleto":
            return self._json(200, {"url": self.of.url_caseta(demo=bool(datos.get("demo")))})
        if ruta == "/api/latigo":
            objetivo = datos.get("objetivo") if datos.get("objetivo") in ("capataz", "peon", "ayudante", "aire") else "aire"
            res = self.of.modelo.latigazo_oficina(str(datos.get("sesion") or ""), objetivo, str(datos.get("agente") or ""),
                                                  sonar=not datos.get("sonado"))
            return self._json(200, res)
        if ruta == "/api/config":
            cambios = {}
            if isinstance(datos.get("sonidos"), dict):
                cambios["sonidos"] = {k: bool(v) for k, v in datos["sonidos"].items() if k in nucleo.SONIDOS}
            if isinstance(datos.get("volumen"), (int, float)):
                cambios["volumen"] = max(0.0, min(1.0, float(datos["volumen"])))
            if isinstance(datos.get("abrir_oficina_al_iniciar"), bool):
                cambios["abrir_oficina_al_iniciar"] = datos["abrir_oficina_al_iniciar"]
            if isinstance(datos.get("silencio"), bool):
                cambios["silencio"] = datos["silencio"]
            if cambios:
                nucleo.guardar_config(cambios)
                if "volumen" in cambios:
                    nucleo.generar_sonidos()
                with self.of.modelo.lock:
                    self.of.modelo._cambio()
            return self._json(200, {"ok": True})
        if ruta == "/api/sonar":
            nombre = datos.get("nombre")
            if nombre in nucleo.SONIDOS:
                threading.Thread(target=nucleo.reproducir, args=(nombre,), kwargs={"forzar": True}, daemon=True).start()
            return self._json(200, {"ok": True})
        if ruta == "/api/abrir":
            self.of.quizas_abrir_ventana(forzar=True)
            return self._json(200, {"ok": True})
        if ruta == "/api/parar":
            self._json(200, {"ok": True})
            self.of.detener()
            return
        self._json(404, {"error": "no existe"})

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._cabeceras_seguridad()
        self.end_headers()
        cliente = Cliente()
        self.of.registrar(cliente)
        try:
            self._evento("estado", self.of.snapshot_json())
            while self.of.corriendo:
                try:
                    tipo, datos = cliente.cola.get(timeout=12)
                except Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._evento(tipo, datos)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.of.quitar(cliente)
            self.close_connection = True

    def _evento(self, tipo, datos: bytes):
        self.wfile.write(b"event: " + tipo.encode() + b"\ndata: " + datos + b"\n\n")
        self.wfile.flush()


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    # En macOS/Linux permite reabrir el puerto al reiniciar (TIME_WAIT). En Windows SO_REUSEADDR
    # dejaría que dos procesos escuchen el mismo puerto, así que ahí no.
    allow_reuse_address = os.name != "nt"


def crear(puerto_pedido: int = None, demo: bool = False):
    """Abre HTTP y UDP en el primer puerto libre a partir del configurado."""
    base = int(puerto_pedido or nucleo.config().get("puerto") or 47821)
    for puerto in range(base, base + 10):
        try:
            httpd = Servidor(("127.0.0.1", puerto), Manejador)
        except OSError:
            continue
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.bind(("127.0.0.1", puerto))
        except OSError:
            httpd.server_close()
            udp.close()
            continue
        of = Oficina(puerto, demo=demo)
        httpd.oficina = of  # type: ignore[attr-defined]
        of.httpd = httpd
        of.udp = udp
        return of
    raise OSError("no hay puerto libre entre %d y %d" % (base, base + 9))


def correr(abrir: bool = False, puerto: int = None, demo: bool = False):
    if nucleo.servidor_vivo() and nucleo.info_servidor().get("pid") != os.getpid():
        info = nucleo.info_servidor()
        print("La oficina ya está abierta en %s" % info.get("url"))
        return 0
    if os.name != "nt":
        try:
            os.chmod(nucleo.dir_estado(), 0o700)  # también si la carpeta venía de una versión anterior
        except OSError:
            pass
    of = crear(puerto, demo=demo)
    of.escribir_info()
    log("oficina en %s (pid %d)" % (of.url, os.getpid()))
    hilos = [
        threading.Thread(target=of.bucle_udp, args=(of.udp,), daemon=True),
        threading.Thread(target=of.bucle_transcripts, daemon=True),
        threading.Thread(target=of.bucle_descubrimiento, daemon=True),
        threading.Thread(target=of.bucle_latido, daemon=True),
        threading.Thread(target=of.bucle_difusion, daemon=True),
        threading.Thread(target=of.bucle_sonidos, daemon=True),
    ]
    for h in hilos:
        h.start()

    def _senal(*_):
        of.detener()

    for s in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
        if s is not None:
            try:
                signal.signal(s, _senal)
            except (ValueError, OSError):
                pass
    if abrir:
        of.quizas_abrir_ventana(forzar=True)
    try:
        of.httpd.serve_forever(poll_interval=0.3)
    finally:
        of.corriendo = False
        of.detener()
        try:
            of.udp.close()
        except OSError:
            pass
        of.httpd.server_close()
        log("oficina cerrada")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(correr(abrir="--abrir" in args, demo="--demo" in args))
