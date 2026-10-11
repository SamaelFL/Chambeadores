"""Modelo de la oficina sin servidor: estados, avisos internos y peones."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "latigo"))


class Modelo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LATIGO_DIR"] = self.tmp.name
        import modelo
        import nucleo

        nucleo._cache_config = None
        self.t = [1000.0]
        self.m = modelo.Modelo(reloj=lambda: self.t[0])

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("LATIGO_DIR", None)

    def ev(self, e, **kw):
        d = {"v": 1, "e": e, "s": "s1", "cwd": "/obra/tienda", "t": self.t[0]}
        d.update(kw)
        self.m.aplicar_hook(d)
        return {a["id"]: a for a in self.m.snapshot()["sesiones"][0]["agentes"]}

    def test_aviso_de_subagente_no_es_encargo(self):
        self.ev("UserPromptSubmit", prompt="agrega los módulos de pagos")
        ag = self.ev("UserPromptSubmit", prompt='<task-notification>\n<summary>Agent "Módulo a" finished</summary>\n</task-notification>')
        ses = self.m.snapshot()["sesiones"][0]
        self.assertEqual(ses["encargo"], "agrega los módulos de pagos")
        self.assertEqual(ses["bitacora"][-1]["texto"], "Aviso: Terminó «Módulo a»")
        self.assertEqual(ag["main"]["cat"], "pensando")

    def test_herramientas_en_paralelo_y_permiso(self):
        self.ev("PreToolUse", tool="Read", tid="r1", **{"in": {"file_path": "/obra/tienda/a.ts"}})
        ag = self.ev("PreToolUse", tool="Grep", tid="g1", **{"in": {"pattern": "TODO"}})
        self.assertEqual(ag["main"]["paralelas"], 2)
        self.assertIn("(+1)", ag["main"]["texto"])
        ag = self.ev("PermissionRequest", tool="Bash", **{"in": {"command": "npm install"}})
        self.assertEqual(ag["main"]["cat"], "permiso")
        ag = self.ev("PostToolBatch", tids=["r1", "g1"])
        self.assertEqual(ag["main"]["cat"], "pensando")

    def test_peon_entra_trabaja_termina_y_se_va(self):
        self.ev("PreToolUse", tool="Agent", tid="t1", **{"in": {"subagent_type": "peon", "description": "Pieza A"}})
        ag = self.ev("SubagentStart", a="agent-x1", at="peon")
        self.assertEqual(ag["x1"]["tarea"], "Pieza A")
        self.assertEqual((ag["x1"]["rol"], ag["x1"]["silla"], ag["x1"]["nombre"]), ("peon", 0, "Peón 1"))
        ag = self.ev("PreToolUse", a="agent-x1", at="peon", tool="Edit", tid="e1",
                     **{"in": {"file_path": "/obra/tienda/src/a.ts", "diff": [3, 1]}})
        self.assertEqual(ag["x1"]["texto"], "Editando src/a.ts (+3 −1)")
        ag = self.ev("SubagentStop", a="x1", at="peon", last="Listo")
        self.assertEqual(ag["x1"]["cat"], "terminado")
        self.t[0] += 11
        self.m.tick()
        self.assertEqual({a["id"]: a for a in self.m.snapshot()["sesiones"][0]["agentes"]}["x1"]["cat"], "saliendo")
        self.t[0] += 7
        self.m.tick()
        x1 = {a["id"]: a for a in self.m.snapshot()["sesiones"][0]["agentes"]}["x1"]
        self.assertFalse(x1["visible"])
        self.assertIsNone(x1["silla"])

    def test_subagente_interno_se_ignora(self):
        self.ev("UserPromptSubmit", prompt="hola")
        self.ev("SubagentStop", a="interno", at="")
        self.assertNotIn("interno", {a["id"] for a in self.m.snapshot()["sesiones"][0]["agentes"]})

    def test_transcript_tokens_y_texto(self):
        self.ev("UserPromptSubmit", prompt="hola")
        ts = "2026-10-01T06:00:00.000Z"
        import transcripts
        self.t[0] = transcripts.ts_iso(ts) + 1
        regs = [
            {"type": "assistant", "timestamp": ts, "message": {"id": "m1", "model": "claude-opus-5-5", "content": [{"type": "text", "text": "Va."}],
                                                              "usage": {"input_tokens": 10, "cache_read_input_tokens": 1000, "output_tokens": 5}}},
            {"type": "assistant", "timestamp": ts, "message": {"id": "m1", "model": "claude-opus-5-5", "content": [{"type": "tool_use", "id": "t9", "name": "Read", "input": {}}],
                                                              "usage": {"input_tokens": 10, "cache_read_input_tokens": 1000, "output_tokens": 42}}},
            {"type": "ai-title", "aiTitle": "Agregar pagos a la tienda", "sessionId": "s1"},
        ]
        self.m.aplicar_registros("s1", regs)
        ses = self.m.snapshot()["sesiones"][0]
        cap = ses["agentes"][0]
        self.assertEqual(cap["tokens"]["salida"], 42)
        self.assertEqual(cap["tokens"]["contexto"], 1010)
        self.assertEqual(cap["globo"]["texto"], "Va.")
        self.assertEqual(ses["titulo"], "Agregar pagos a la tienda")

    def test_inicio_tardio_de_herramienta_no_se_queda_colgado(self):
        # Hooks async por UDP: el fin llega antes que el inicio.
        self.ev("UserPromptSubmit", prompt="hola")
        self.ev("PostToolUse", tool="Read", tid="r9")
        ag = self.ev("PreToolUse", tool="Read", tid="r9", **{"in": {"file_path": "/obra/tienda/a.ts"}})
        self.assertEqual(ag["main"]["paralelas"], 0)
        self.assertEqual(ag["main"]["cat"], "pensando")

    def test_sesion_cerrada_no_revive(self):
        self.ev("SessionStart", src="startup")
        self.ev("SessionEnd", reason="exit")
        self.t[0] += 200
        self.m.tick()
        self.assertEqual(self.m.snapshot()["sesiones"], [])
        # El descubrimiento ve su transcript (modificado al cerrar) y no la revive.
        self.assertIsNone(self.m.descubrir("s1", "/x/s1.jsonl", "/obra/tienda", mtime=self.t[0] - 200))
        self.assertEqual(self.m.snapshot()["sesiones"], [])
        # Si el transcript vuelve a crecer después (la reanudaste sin hooks), sí aparece.
        self.t[0] += 120
        self.assertIsNotNone(self.m.descubrir("s1", "/x/s1.jsonl", "/obra/tienda", mtime=self.t[0]))
        # Y los hooks siempre mandan.
        self.m.sesiones.clear()
        self.m.cerradas["s1"] = self.t[0]
        self.ev("UserPromptSubmit", prompt="sigo")
        self.assertNotIn("s1", self.m.cerradas)

    def test_se_olvida_lo_que_ya_no_se_ve(self):
        self.ev("PreToolUse", tool="Agent", tid="t1", **{"in": {"subagent_type": "peon", "description": "Pieza A"}})
        self.ev("SubagentStart", a="agent-x1", at="peon")
        self.ev("SubagentStop", a="x1", at="peon", last="Listo")
        self.ev("PreToolUse", tool="Bash", tid="b1", **{"in": {"command": "sleep 99999"}})
        for _ in range(3):
            self.t[0] += 11
            self.m.tick()
        self.assertFalse(self.m.sesiones["s1"]["agentes"]["x1"]["visible"])
        self.t[0] += 16 * 60
        self.ev("Notification", nt="idle_prompt")  # la sesión sigue viva
        self.m.tick()
        self.assertNotIn("x1", self.m.sesiones["s1"]["agentes"])
        self.t[0] += 15 * 60
        self.ev("Notification", nt="idle_prompt")
        self.m.tick()
        self.assertEqual(self.m.sesiones["s1"]["agentes"]["main"]["pend"], {})

    def test_latigazo_sin_obra_suena(self):
        sonidos = []
        self.m.sonar = sonidos.append
        r = self.m.latigazo_oficina("no-existe")
        self.assertEqual((r["ok"], r["res"]["motivo"]), (True, "sin_obra"))
        self.assertEqual(sonidos, ["latigazo"])

    def test_ventana_solo_al_arrancar(self):
        for src in ("clear", "compact"):
            self.m.pedir_ventana = False
            self.ev("SessionStart", src=src)
            self.assertFalse(self.m.pedir_ventana, src)
        self.ev("SessionStart", src="resume")  # la oficina decide: solo si acaba de arrancar
        self.assertEqual(self.m.pedir_ventana, "resume")
        self.ev("SessionStart", src="startup")
        self.assertEqual(self.m.pedir_ventana, "startup")

    def test_segundo_latigazo_con_el_primero_en_camino_no_suma(self):
        import nucleo

        self.ev("UserPromptSubmit", prompt="agrega pagos")
        self.ev("PreToolUse", tool="Bash", tid="b1", **{"in": {"command": "mvn verify"}})
        r1 = self.m.latigazo_oficina("s1")["res"]
        self.assertTrue(r1["efectivo"])
        self.t[0] += 120  # pasó la calma, pero el capataz sigue en la misma herramienta
        r2 = self.m.latigazo_oficina("s1")["res"]
        self.assertEqual((r2["efectivo"], r2["motivo"]), (False, "en_camino"))
        self.assertEqual(nucleo.leer_bitacora("s1")["nivel"], 1)


if __name__ == "__main__":
    unittest.main()
