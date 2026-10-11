"""Integración: hooks reales (subproceso) -> UDP -> servidor -> /api/estado y SSE.

Levanta el servidor en un puerto libre con carpetas temporales para LATIGO_DIR y
CLAUDE_CONFIG_DIR, así no toca nada del usuario.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODIGO = os.path.join(RAIZ, "latigo")
# Sin proxy: con HTTP_PROXY en el entorno (por ejemplo en CI), 127.0.0.1 no debe pasar por él.
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Integracion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.dir_latigo = os.path.join(cls.tmp, "latigo")
        cls.dir_claude = os.path.join(cls.tmp, "claude")
        os.makedirs(os.path.join(cls.dir_claude, "projects"))
        os.makedirs(cls.dir_latigo)
        cls.puerto = puerto_libre()
        with open(os.path.join(cls.dir_latigo, "config.json"), "w") as f:
            json.dump({"puerto": cls.puerto, "abrir_oficina_al_iniciar": False, "autoiniciar_servidor": False,
                       "sonidos": {"latigazo": False, "peon_listo": False, "permiso": False, "listo": False,
                                   "error": False}}, f)
        cls.env = dict(os.environ, LATIGO_DIR=cls.dir_latigo, CLAUDE_CONFIG_DIR=cls.dir_claude)
        cls.proc = subprocess.Popen([sys.executable, os.path.join(CODIGO, "servidor.py")], env=cls.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        limite = time.time() + 10
        while time.time() < limite:
            try:
                LOCAL.open("http://127.0.0.1:%d/api/salud" % cls.puerto, timeout=0.5).read()
                break
            except OSError:
                time.sleep(0.1)
        with open(os.path.join(cls.dir_latigo, "estado", "servidor.json"), encoding="utf-8") as f:
            cls.token = json.load(f)["token"]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait(5)
        cls.proc.stdout.close()
        cls.proc.stderr.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- utilidades

    def hook(self, ev, modo="telemetria"):
        p = subprocess.run([sys.executable, "-S", os.path.join(CODIGO, "hook.py"), modo],
                           input=json.dumps(ev).encode(), capture_output=True, env=self.env, timeout=20)
        self.assertEqual(p.returncode, 0)
        out = p.stdout.decode().strip()
        return json.loads(out) if out else None

    def estado(self):
        req = urllib.request.Request("http://127.0.0.1:%d/api/estado" % self.puerto)
        req.add_header("X-Latigo-Token", self.token)
        return json.loads(LOCAL.open(req, timeout=3).read())

    def esperar(self, cond, seg=4.0):
        limite = time.time() + seg
        ultimo = None
        while time.time() < limite:
            ultimo = self.estado()
            if cond(ultimo):
                return ultimo
            time.sleep(0.1)
        self.fail("no se cumplió la condición; último estado: %s" % json.dumps(ultimo)[:1500])

    def post(self, ruta, datos, token=None, host=None, origen=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.puerto, ruta), data=json.dumps(datos).encode(),
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Latigo-Token", self.token if token is None else token)
        if host:
            req.add_header("Host", host)
        if origen:
            req.add_header("Origin", origen)
        try:
            r = LOCAL.open(req, timeout=3)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    @staticmethod
    def ses(est, sid):
        for s in est["sesiones"]:
            if s["id"] == sid:
                return s
        return None

    @staticmethod
    def ag(ses, rol=None, aid=None):
        for a in ses["agentes"]:
            if (aid and a["id"] == aid) or (rol and a["rol"] == rol and not aid):
                return a
        return None

    def base(self, sid, nombre, **kw):
        d = {"session_id": sid, "hook_event_name": nombre, "cwd": "/proyectos/tienda",
             "transcript_path": os.path.join(self.dir_claude, "projects", "x", sid + ".jsonl")}
        d.update(kw)
        return d

    # -- pruebas

    def test_1_flujo_capataz(self):
        sid = "s-flujo"
        self.hook(self.base(sid, "SessionStart", source="startup", model="claude-opus-5-5"), modo="inicio")
        est = self.esperar(lambda e: self.ses(e, sid) is not None)
        self.assertEqual(self.ses(est, sid)["proyecto"], "tienda")
        self.hook(self.base(sid, "UserPromptSubmit", prompt="arregla el login"), modo="control")
        self.esperar(lambda e: self.ag(self.ses(e, sid), "capataz")["cat"] == "pensando")
        self.hook(self.base(sid, "PreToolUse", tool_name="Edit", tool_use_id="t1",
                            tool_input={"file_path": "/proyectos/tienda/src/app/login.ts",
                                        "old_string": "a", "new_string": "b\nc"}))
        est = self.esperar(lambda e: self.ag(self.ses(e, sid), "capataz")["cat"] == "escribiendo")
        cap = self.ag(self.ses(est, sid), "capataz")
        self.assertIn("src/app/login.ts", cap["texto"])
        self.assertIn("(+2 −1)", cap["texto"])
        self.hook(self.base(sid, "PermissionRequest", tool_name="Bash", tool_input={"command": "npm test"}))
        self.esperar(lambda e: self.ag(self.ses(e, sid), "capataz")["cat"] == "permiso")
        self.hook(self.base(sid, "PostToolUse", tool_name="Edit", tool_use_id="t1", tool_input={}))
        self.hook(self.base(sid, "Stop", last_assistant_message="Listo, ya quedó.", background_tasks=[]), modo="control")
        est = self.esperar(lambda e: self.ag(self.ses(e, sid), "capataz")["cat"] == "esperando")
        self.assertEqual(self.ag(self.ses(est, sid), "capataz")["globo"]["texto"], "Listo, ya quedó.")

    def test_2_peones_y_latigazo_desde_oficina(self):
        sid = "s-latigo"
        self.hook(self.base(sid, "SessionStart", source="startup"), modo="inicio")
        self.hook(self.base(sid, "UserPromptSubmit", prompt="agrega los 3 módulos"), modo="control")
        self.esperar(lambda e: self.ses(e, sid) and self.ag(self.ses(e, sid), "capataz")["cat"] == "pensando")
        # Latigazo con el capataz trabajando: queda pendiente y se entrega en el siguiente PostToolBatch.
        st, r = self.post("/api/latigo", {"sesion": sid, "objetivo": "capataz"})
        self.assertEqual(st, 200)
        self.assertTrue(r["res"]["efectivo"], r)
        est = self.esperar(lambda e: self.ses(e, sid)["latigo"]["pendiente"] is not None)
        self.assertEqual(self.ses(est, sid)["latigo"]["nivel"], 1)
        out = self.hook(self.base(sid, "PostToolBatch", tool_calls=[{"tool_use_id": "x"}]), modo="control")
        self.assertIn("desde la oficina", out["hookSpecificOutput"]["additionalContext"])
        self.esperar(lambda e: self.ses(e, sid)["latigo"]["pendiente"] is None)
        # Llegan 3 peones.
        for i in range(3):
            self.hook(self.base(sid, "PreToolUse", tool_name="Agent", tool_use_id="ag%d" % i,
                                tool_input={"subagent_type": "peon", "description": "Pieza %d" % i, "prompt": "..."}))
        for i in range(3):
            self.hook(self.base(sid, "SubagentStart", agent_id="agent-p%d" % i, agent_type="peon"))
        est = self.esperar(lambda e: len([a for a in self.ses(e, sid)["agentes"] if a["rol"] == "peon"]) == 3)
        peones = [a for a in self.ses(est, sid)["agentes"] if a["rol"] == "peon"]
        self.assertEqual(sorted(p["silla"] for p in peones), [0, 1, 2])
        self.assertEqual(sorted(p["tarea"] for p in peones), ["Pieza 0", "Pieza 1", "Pieza 2"])
        self.esperar(lambda e: self.ses(e, sid)["latigo"]["peones_activos"] == 3)
        # Un peón trabaja (evento con agent_id) y otro pide permiso.
        self.hook(self.base(sid, "PreToolUse", agent_id="agent-p1", agent_type="peon", tool_name="Bash",
                            tool_use_id="b1", tool_input={"command": "mvn -q test", "description": "Corre las pruebas"}))
        self.hook(self.base(sid, "PermissionRequest", agent_id="agent-p2", agent_type="peon", tool_name="Write",
                            tool_input={"file_path": "/proyectos/tienda/x.ts", "content": "1"}))
        est = self.esperar(lambda e: self.ag(self.ses(e, sid), aid="p1")["cat"] == "terminal"
                           and self.ag(self.ses(e, sid), aid="p2")["cat"] == "permiso")
        self.assertEqual(self.ag(self.ses(est, sid), aid="p1")["texto"], "Corre las pruebas")
        # Latigazo con peones trabajando: no cuenta.
        st, r = self.post("/api/latigo", {"sesion": sid, "objetivo": "capataz"})
        self.assertFalse(r["res"]["efectivo"])
        self.assertEqual(r["res"]["motivo"], "peones_trabajando")
        # Terminan.
        for i in range(3):
            self.hook(self.base(sid, "SubagentStop", agent_id="agent-p%d" % i, agent_type="peon",
                                last_assistant_message="Hecho %d" % i))
        est = self.esperar(lambda e: all(a["cat"] == "terminado" for a in self.ses(e, sid)["agentes"] if a["rol"] == "peon"))
        self.esperar(lambda e: self.ses(e, sid)["latigo"]["peones_activos"] == 0)
        self.hook(self.base(sid, "Stop", background_tasks=[]), modo="control")
        self.esperar(lambda e: self.ses(e, sid)["latigo"]["nivel"] == 0)

    def test_3_latigazo_con_capataz_esperando_no_cuenta(self):
        sid = "s-quieto"
        self.hook(self.base(sid, "SessionStart", source="startup"), modo="inicio")
        self.esperar(lambda e: self.ses(e, sid) is not None)
        st, r = self.post("/api/latigo", {"sesion": sid, "objetivo": "capataz"})
        self.assertEqual(r["res"]["motivo"], "capataz_esperando")
        self.assertFalse(os.path.exists(os.path.join(self.dir_latigo, "estado", "latigo", sid + ".inyeccion")))

    def test_4_seguridad(self):
        st, _ = self.post("/api/latigo", {"sesion": "x"}, token="malo")
        self.assertEqual(st, 403)
        st, _ = self.post("/api/latigo", {"sesion": "x"}, origen="https://evil.example")
        self.assertEqual(st, 403)
        st, _ = self.post("/api/latigo", {"sesion": "x"}, host="evil.example:%d" % self.puerto)
        self.assertEqual(st, 403)
        req = urllib.request.Request("http://127.0.0.1:%d/api/estado" % self.puerto)
        req.add_header("Host", "rebind.example")
        req.add_header("X-Latigo-Token", self.token)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            LOCAL.open(req, timeout=3)
        self.assertEqual(cm.exception.code, 403)
        # Sin token no se lee el estado ni los eventos (otros usuarios de la máquina).
        for ruta in ("/api/estado", "/api/eventos", "/api/eventos?t=malo"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                LOCAL.open("http://127.0.0.1:%d%s" % (self.puerto, ruta), timeout=3)
            self.assertEqual(cm.exception.code, 403, ruta)
        # El HTML no lleva el token: llega en el fragmento de la URL.
        html = LOCAL.open("http://127.0.0.1:%d/" % self.puerto, timeout=3).read().decode()
        self.assertNotIn(self.token, html)
        self.assertNotIn("{{TOKEN}}", html)

    def test_4b_error_temprano_cierra_la_conexion(self):
        import http.client

        c = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=3)
        cuerpo = json.dumps({"sesion": "x", "relleno": "y" * 500})
        c.request("POST", "/api/latigo", body=cuerpo, headers={"Content-Type": "application/json", "X-Latigo-Token": "malo"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 403)
        self.assertEqual((r.getheader("Connection") or "").lower(), "close")
        c.close()
        # Y la oficina sigue contestando bien en una conexión nueva.
        self.assertIn("sesiones", self.estado())

    def test_4c_boleto_de_un_solo_uso(self):
        st, r = self.post("/api/boleto", {"demo": False})
        self.assertEqual(st, 200)
        self.assertIn("#p=", r["url"])
        self.assertNotIn(self.token, r["url"])  # el token nunca va en la URL
        boleto = r["url"].split("#p=", 1)[1]
        st, r = self.post("/api/canjear", {"boleto": boleto}, token="")
        self.assertEqual((st, r.get("token")), (200, self.token))
        st, _ = self.post("/api/canjear", {"boleto": boleto}, token="")  # ya se gastó
        self.assertEqual(st, 403)
        st, _ = self.post("/api/canjear", {"boleto": "inventado"}, token="")
        self.assertEqual(st, 403)
        st, _ = self.post("/api/boleto", {}, token="malo")
        self.assertEqual(st, 403)

    def test_4d_sonido_publico(self):
        r = LOCAL.open("http://127.0.0.1:%d/sonidos/latigazo.wav" % self.puerto, timeout=5)
        self.assertEqual(r.headers.get("Content-Type"), "audio/wav")
        self.assertEqual(r.read(4), b"RIFF")
        with self.assertRaises(urllib.error.HTTPError):
            LOCAL.open("http://127.0.0.1:%d/sonidos/..%%2Fconfig.wav" % self.puerto, timeout=5)

    def test_5_sse_entrega_estado(self):
        r = LOCAL.open("http://127.0.0.1:%d/api/eventos?t=%s" % (self.puerto, self.token), timeout=5)
        linea1 = r.readline().decode()
        self.assertEqual(linea1.strip(), "event: estado")
        datos = json.loads(r.readline().decode()[len("data: "):])
        self.assertIn("sesiones", datos)
        r.close()

    def test_5b_token_persiste_y_puerto_se_repara(self):
        estado = os.path.join(self.dir_latigo, "estado")
        with open(os.path.join(estado, "token"), encoding="ascii") as f:
            self.assertEqual(f.read().strip(), self.token)
        if os.name != "nt":
            self.assertEqual(os.stat(os.path.join(estado, "token")).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.join(estado, "servidor.json")).st_mode & 0o777, 0o600)
        os.remove(os.path.join(estado, "puerto"))
        limite = time.time() + 4
        while time.time() < limite and not os.path.exists(os.path.join(estado, "puerto")):
            time.sleep(0.1)
        with open(os.path.join(estado, "puerto"), encoding="ascii") as f:
            self.assertEqual(int(f.read()), self.puerto)
        self.assertFalse(os.path.exists(os.path.join(estado, "arranque.lock")))

