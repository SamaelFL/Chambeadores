"""Punta a punta: instalar en una carpeta temporal, simular a Claude Code ejecutando los
hooks tal como quedaron en settings.json, latigazos, ficha y desinstalar."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PEON_PROPIO = "---\nname: peon\ndescription: mi peón de antes\n---\nYo ya tenía este.\n"


def escribir(p, texto):
    with open(p, "w", encoding="utf-8") as f:
        f.write(texto)


def leer(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class ClaudeFalso:
    """Despacha eventos a los hooks de settings.json como lo hace Claude Code."""

    MATCH_TOOL = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"}

    def __init__(self, settings_path, env):
        self.settings_path = settings_path
        self.env = env
        self.fondo = []

    def _coincide(self, matcher, valor):
        if matcher in (None, "", "*"):
            return True
        if re.fullmatch(r"[A-Za-z0-9_\-|, ]+", matcher):
            return valor in [m.strip() for m in re.split(r"[|,]", matcher)]
        return re.search(matcher, valor or "") is not None

    def evento(self, nombre, datos):
        cfg = json.loads(leer(self.settings_path))
        payload = dict(datos, hook_event_name=nombre)
        valor = {"SubagentStart": payload.get("agent_type"), "SubagentStop": payload.get("agent_type"),
                 "UserPromptExpansion": payload.get("command_name"), "Notification": payload.get("notification_type"),
                 "SessionStart": payload.get("source")}.get(nombre, payload.get("tool_name"))
        salidas = []
        for grupo in cfg.get("hooks", {}).get(nombre, []):
            if not self._coincide(grupo.get("matcher"), valor or ""):
                continue
            for h in grupo["hooks"]:
                if "args" not in h:
                    continue  # hooks ajenos en forma shell (de otras herramientas): no son parte de la prueba
                cmd = [h["command"]] + h.get("args", [])
                entrada = json.dumps(payload).encode()
                if h.get("async"):
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
                    p.stdin.write(entrada)
                    p.stdin.close()
                    self.fondo.append(p)
                else:
                    p = subprocess.run(cmd, input=entrada, capture_output=True, env=self.env, timeout=h.get("timeout", 60))
                    assert p.returncode == 0, p.stderr
                    out = p.stdout.decode().strip()
                    if out:
                        salidas.append(json.loads(out))
        return salidas

    def esperar_fondo(self):
        for p in self.fondo:
            p.wait(15)
            p.stdout.close()
            p.stderr.close()
        self.fondo = []


class Instalador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.claude = os.path.join(cls.tmp, "claude")
        os.makedirs(os.path.join(cls.claude, "projects"))
        cls.ajeno = {"type": "command", "command": "echo hook-ajeno >/dev/null"}
        with open(os.path.join(cls.claude, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"model": "opus", "hooks": {"SessionStart": [{"hooks": [cls.ajeno]}]}}, f)
        # Un agente "peon" que el usuario ya tenía: se respalda y vuelve al desinstalar.
        os.makedirs(os.path.join(cls.claude, "agents"))
        with open(os.path.join(cls.claude, "agents", "peon.md"), "w", encoding="utf-8") as f:
            f.write(PEON_PROPIO)
        cls.env = dict(os.environ, CLAUDE_CONFIG_DIR=cls.claude)
        cls.env.pop("LATIGO_DIR", None)
        cls.puerto = puerto_libre()
        cls.instalar()

    @classmethod
    def instalar(cls, *extra):
        p = subprocess.run([sys.executable, os.path.join(RAIZ, "instalar.py"), "--sin-ventana", "--no-abrir",
                            "--puerto", str(cls.puerto)] + list(extra), capture_output=True, text=True, env=cls.env, timeout=120)
        assert p.returncode == 0, p.stdout + p.stderr
        return p.stdout

    @classmethod
    def tearDownClass(cls):
        dest = os.path.join(cls.claude, "latigo")
        subprocess.run([sys.executable, os.path.join(dest, "latigo.py"), "parar"], env=cls.env, capture_output=True, timeout=20)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def settings(self):
        return json.loads(leer(os.path.join(self.claude, "settings.json")))

    def token(self):
        with open(os.path.join(self.claude, "latigo", "estado", "token"), encoding="ascii") as f:
            return f.read().strip()

    def estado(self):
        req = urllib.request.Request("http://127.0.0.1:%d/api/estado" % self.puerto)
        req.add_header("X-Latigo-Token", self.token())
        return json.loads(LOCAL.open(req, timeout=3).read())

    def esperar(self, cond, seg=6):
        limite = time.time() + seg
        while time.time() < limite:
            try:
                e = self.estado()
                if cond(e):
                    return e
            except OSError:
                pass
            time.sleep(0.15)
        self.fail("no se cumplió la condición")

    def test_1_archivos_y_settings(self):
        dest = os.path.join(self.claude, "latigo")
        for rel in ("hook.py", "servidor.py", "web/index.html", "sonidos/latigazo.wav", "config.json"):
            self.assertTrue(os.path.exists(os.path.join(dest, rel)), rel)
        skill = leer(os.path.join(self.claude, "skills", "latigo", "SKILL.md"))
        self.assertNotIn("{{PY}}", skill)
        sys.path.insert(0, RAIZ)
        import instalar

        self.assertIn(instalar.interprete_estable().replace("\\", "/"), skill)
        for a in ("peon.md", "peon-libre.md"):
            self.assertTrue(os.path.exists(os.path.join(self.claude, "agents", a)))
        with open(os.path.join(self.claude, "agents", "peon.md"), encoding="utf-8") as f:
            self.assertIn("Peón del látigo", f.read())
        respaldos = os.listdir(os.path.join(self.claude, "latigo-respaldos"))
        self.assertTrue(any(n.startswith("peon.md.") for n in respaldos), respaldos)
        self.assertTrue(any(n.startswith("settings.json.") for n in respaldos), respaldos)
        self.assertFalse(os.path.exists(os.path.join(self.claude, "latigo", "respaldos")))
        s = self.settings()
        self.assertEqual(s["model"], "opus")
        self.assertEqual(s["worktree"]["baseRef"], "head")
        self.assertIn(self.ajeno, s["hooks"]["SessionStart"][0]["hooks"])
        nuestros = [h for ev in s["hooks"].values() for g in ev for h in g["hooks"] if "hook.py" in " ".join(h.get("args", []))]
        self.assertEqual(len(nuestros), 19)

    def test_2_reinstalar_no_duplica(self):
        self.instalar()
        s = self.settings()
        nuestros = [h for ev in s["hooks"].values() for g in ev for h in g["hooks"] if "hook.py" in " ".join(h.get("args", []))]
        self.assertEqual(len(nuestros), 19)
        self.assertEqual(sum(1 for g in s["hooks"]["SessionStart"] for h in g["hooks"] if h == self.ajeno), 1)

    def test_3_sesion_simulada(self):
        cc = ClaudeFalso(os.path.join(self.claude, "settings.json"), self.env)
        sid = "sesion-e2e"
        base = {"session_id": sid, "cwd": os.path.join(self.tmp, "tienda"),
                "transcript_path": os.path.join(self.claude, "projects", "p", sid + ".jsonl")}
        cc.evento("SessionStart", dict(base, source="startup", model="claude-opus-5-5"))
        cc.esperar_fondo()  # el hook de inicio arranca la oficina
        self.esperar(lambda e: any(s["id"] == sid for s in e["sesiones"]))
        self.assertEqual(cc.evento("UserPromptSubmit", dict(base, prompt="agrega pagos")), [])
        cc.evento("PreToolUse", dict(base, tool_name="Read", tool_use_id="r1", tool_input={"file_path": base["cwd"] + "/src/a.ts"}))
        cc.esperar_fondo()
        e = self.esperar(lambda e: next(s for s in e["sesiones"] if s["id"] == sid)["agentes"][0]["cat"] == "leyendo")
        # latigazo desde la oficina -> se entrega en el siguiente PostToolBatch
        req = urllib.request.Request("http://127.0.0.1:%d/api/latigo" % self.puerto, method="POST",
                                     data=json.dumps({"sesion": sid, "objetivo": "capataz"}).encode())
        req.add_header("X-Latigo-Token", self.token())
        res = json.loads(LOCAL.open(req, timeout=3).read())
        self.assertTrue(res["res"]["efectivo"], res)
        cc.evento("PostToolUse", dict(base, tool_name="Read", tool_use_id="r1", tool_input={}, tool_response={}))
        salidas = cc.evento("PostToolBatch", dict(base, tool_calls=[{"tool_use_id": "r1"}]))
        self.assertEqual(len(salidas), 1)
        self.assertIn("latigazo efectivo #1", salidas[0]["hookSpecificOutput"]["additionalContext"])
        # Claude carga la skill: no cuenta doble
        self.assertEqual(cc.evento("PreToolUse", dict(base, tool_name="Skill", tool_use_id="s1", tool_input={"skill": "latigo"})), [])
        # peones
        cc.evento("SubagentStart", dict(base, agent_id="agent-p1", agent_type="peon"))
        cc.esperar_fondo()
        self.esperar(lambda e: next(s for s in e["sesiones"] if s["id"] == sid)["latigo"]["peones_activos"] == 1)
        # latigazo escrito con un peón trabajando: no cuenta y Claude lo sabe
        out = cc.evento("UserPromptSubmit", dict(base, prompt="¡latigazo!", prompt_id="p2"))
        self.assertIn("no cuenta", out[0]["hookSpecificOutput"]["additionalContext"])
        cc.evento("SubagentStop", dict(base, agent_id="agent-p1", agent_type="peon", last_assistant_message="listo"))
        cc.esperar_fondo()
        cc.evento("Stop", dict(base, background_tasks=[], last_assistant_message="Terminé"))
        e = self.esperar(lambda e: next(s for s in e["sesiones"] if s["id"] == sid)["latigo"]["nivel"] == 0)
        cap = next(s for s in e["sesiones"] if s["id"] == sid)["agentes"][0]
        self.assertEqual(cap["cat"], "esperando")

    def test_4_ficha(self):
        proy = os.path.join(self.tmp, "tienda-ng")
        os.makedirs(proy)
        escribir(os.path.join(proy, "package.json"), json.dumps(
            {"dependencies": {"@angular/core": "^18.2.0"}, "scripts": {"test": "ng test", "build": "ng build"}}))
        escribir(os.path.join(proy, "angular.json"), "{}")
        escribir(os.path.join(proy, "tsconfig.app.json"), "{}")
        p = subprocess.run([sys.executable, os.path.join(self.claude, "latigo", "latigo.py"), "init", proy],
                           capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        ficha = leer(os.path.join(proy, ".claude", "latigo.md"))
        self.assertIn("Angular 18 (npm)", ficha)
        self.assertIn("skills: (ninguna; agrega las que apliquen)", ficha)
        self.assertIn("npx tsc -p tsconfig.app.json --noEmit", ficha)
        self.assertIn("npx ng build", ficha)
        # El hook SubagentStart de un peón le pasa esta ficha
        cc = ClaudeFalso(os.path.join(self.claude, "settings.json"), self.env)
        out = cc.evento("SubagentStart", {"session_id": "s-ficha", "cwd": proy, "agent_id": "a9", "agent_type": "peon"})
        cc.esperar_fondo()
        self.assertIn("Angular 18", out[0]["hookSpecificOutput"]["additionalContext"])

    def test_5_maven(self):
        proy = os.path.join(self.tmp, "api-pedidos")
        os.makedirs(proy)
        escribir(os.path.join(proy, "pom.xml"), 
            "<project><parent><artifactId>spring-boot-starter-parent</artifactId><version>3.3.2</version></parent>"
            "<properties><java.version>21</java.version></properties></project>")
        p = subprocess.run([sys.executable, os.path.join(self.claude, "latigo", "latigo.py"), "init", proy],
                           capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        ficha = leer(os.path.join(proy, ".claude", "latigo.md"))
        self.assertIn("Java 21, Spring Boot 3.3.2, Maven", ficha)
        self.assertIn("mvn -q -o compile", ficha)
        self.assertIn("skills: (ninguna; agrega las que apliquen)", ficha)

    def test_9_desinstalar(self):
        p = subprocess.run([sys.executable, os.path.join(RAIZ, "instalar.py"), "--desinstalar"], capture_output=True,
                           text=True, env=self.env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        s = self.settings()
        self.assertEqual(s["hooks"], {"SessionStart": [{"hooks": [self.ajeno]}]})
        self.assertNotIn("worktree", s)
        self.assertFalse(os.path.exists(os.path.join(self.claude, "latigo")))
        self.assertFalse(os.path.exists(os.path.join(self.claude, "agents", "peon-libre.md")))
        self.assertFalse(os.path.exists(os.path.join(self.claude, "skills", "latigo")))
        with open(os.path.join(self.claude, "agents", "peon.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), PEON_PROPIO)  # el que ya tenías volvió
        self.assertTrue(os.listdir(os.path.join(self.claude, "latigo-respaldos")))  # los respaldos se quedan
        self.assertIn("Borré", p.stdout)
        self.instalar()  # para que tearDown pueda parar la oficina sin errores


class InstaladorCuidadoso(unittest.TestCase):
    """settings.json roto o enlazado (dotfiles): no se rompe nada."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.claude = os.path.join(self.tmp, "claude")
        os.makedirs(self.claude)
        self.env = dict(os.environ, CLAUDE_CONFIG_DIR=self.claude)
        self.env.pop("LATIGO_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def correr(self, *args):
        return subprocess.run([sys.executable, os.path.join(RAIZ, "instalar.py"), "--sin-ventana", "--no-abrir",
                               "--puerto", str(puerto_libre())] + list(args), capture_output=True, text=True,
                              env=self.env, timeout=120)

    def test_settings_roto_no_toca_nada(self):
        with open(os.path.join(self.claude, "settings.json"), "w", encoding="utf-8") as f:
            f.write('{"model": "opus",}')
        p = self.correr()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("No toqué nada", p.stdout + p.stderr)
        self.assertEqual(sorted(os.listdir(self.claude)), ["settings.json"])

    @unittest.skipIf(os.name == "nt", "enlaces simbólicos")
    def test_settings_enlazado_sigue_enlazado(self):
        dotfiles = os.path.join(self.tmp, "dotfiles")
        os.makedirs(dotfiles)
        real = os.path.join(dotfiles, "settings.json")
        with open(real, "w", encoding="utf-8") as f:
            json.dump({"model": "opus"}, f)
        os.chmod(real, 0o640)
        enlace = os.path.join(self.claude, "settings.json")
        os.symlink(real, enlace)
        p = self.correr()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(os.path.islink(enlace))
        self.assertEqual(os.stat(real).st_mode & 0o777, 0o640)
        with open(real, encoding="utf-8") as f:
            self.assertIn("hooks", json.load(f))
        p = subprocess.run([sys.executable, os.path.join(RAIZ, "instalar.py"), "--desinstalar"], capture_output=True,
                           text=True, env=self.env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(os.path.islink(enlace))
        with open(real, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"model": "opus"})


if __name__ == "__main__":
    unittest.main()
