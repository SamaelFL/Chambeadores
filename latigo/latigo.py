#!/usr/bin/env python3
"""latigo: utilidades del látigo para Claude Code.

  abrir            abre la caseta (y arranca la oficina si no corre)
  demo             abre la demostración (no necesita Claude Code)
  init [carpeta]   crea la ficha del proyecto: .claude/latigo.md
                   --forzar la reescribe; --permisos pre-autoriza a los peones (solo tu copia)
  estado           dice si la oficina corre, en qué puerto y qué sesiones ve
  parar            apaga la oficina
  servidor         corre la oficina en primer plano (para ver errores)
  sonar <nombre>   prueba un sonido: latigazo, peon_listo, permiso, listo, error
  diagnostico      revisa que todo esté bien instalado
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

import nucleo  # noqa: E402

VERSION_MINIMA_CLAUDE = (2, 1, 198)


def _url():
    info = nucleo.info_servidor()
    return info.get("url") or "http://127.0.0.1:%d/" % int(nucleo.config().get("puerto") or 47821)


def _abrir_local(req, timeout=4):
    """urllib sin proxy: con un proxy configurado en el entorno, 127.0.0.1 no debe pasar por él."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)


def _pedir(ruta, datos=None):
    """GET (sin datos) o POST a la oficina, con el token de esta instalación."""
    if datos is None:
        req = urllib.request.Request(_url().rstrip("/") + ruta)
    else:
        req = urllib.request.Request(_url().rstrip("/") + ruta, data=json.dumps(datos).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
    req.add_header("X-Latigo-Token", nucleo.token_oficina())
    return json.loads(_abrir_local(req).read() or b"{}")


def _post(ruta, datos=None):
    return _pedir(ruta, datos or {})


def _url_caseta(demo=False):
    """URL de la caseta con un boleto de un solo uso (el token nunca va en la línea de comandos)."""
    try:
        return _post("/api/boleto", {"demo": demo})["url"]
    except (OSError, ValueError, KeyError):
        return _url() + ("?demo" if demo else "")  # sin boleto: la caseta pide abrirse de nuevo


def asegurar_servidor():
    if nucleo.servidor_vivo():
        return True
    print("Arrancando la oficina…")
    ok = nucleo.arrancar_servidor(esperar=6.0)
    if not ok:
        print("No arrancó. Prueba `latigo servidor` para ver el error, o revisa %s"
              % os.path.join(nucleo.dir_estado(), "errores.log"))
    return ok


def cmd_abrir(args):
    if not asegurar_servidor():
        return 1
    import ventana

    modo = ventana.abrir(_url_caseta())
    print("La caseta está en %s (%s)." % (_url(), "ventana de app" if modo == "app" else "navegador"))
    return 0


def cmd_demo(args):
    if not asegurar_servidor():
        return 1
    import ventana

    ventana.abrir(_url_caseta(demo=True))
    print("Demostración abierta: %s?demo" % _url())
    return 0


def cmd_init(args):
    import ficha

    forzar = "--forzar" in args
    carpetas = [a for a in args if not a.startswith("--")]
    raiz = os.path.abspath(carpetas[0] if carpetas else os.getcwd())
    raiz_git = _raiz_git(raiz)
    if raiz_git and raiz_git != raiz:
        print("Uso la raíz del repo: %s" % raiz_git)
        raiz = raiz_git
    destino, escrita, info, mensaje = ficha.crear(raiz, forzar=forzar)
    print(mensaje)
    if escrita:
        for c in info["componentes"]:
            print("  - %s%s" % (c["stack"], "" if c["ruta"] == "." else " en " + c["ruta"]))
        if not info["componentes"]:
            print("  No reconocí el stack: completa la ficha a mano.")
    try:
        with open(destino, "r", encoding="utf-8") as f:
            texto_ficha = f.read()  # la ficha ya corregida manda sobre lo detectado
    except OSError:
        texto_ficha = None
    descartados = []
    reglas = ficha.reglas_permisos(info, texto_ficha, descartados)
    preguntar = ficha.reglas_preguntar()
    if not escrita and _ficha_del_repo(raiz, destino):
        print("Ojo: la ficha viene del repo tal cual (alguien más la escribió). Revisa sus comandos antes de autorizarlos.")
    if descartados:
        print("No pre-autorizo estos comandos de la ficha (no parecen de verificación o traen caracteres de shell):")
        for c in descartados:
            print("  %s" % c)
    if "--permisos" in args:
        try:
            p, nuevas, nuevas_ask = ficha.agregar_permisos(raiz, reglas, preguntar)
        except (OSError, ValueError) as e:
            print("No agregué permisos: %s" % e)
            return 1
        if nuevas or nuevas_ask:
            print("Agregué a %s (solo tu copia):" % p)
            for r in nuevas:
                print("  permitir  %s" % r)
            for r in nuevas_ask:
                print("  preguntar %s" % r)
        else:
            print("Los permisos para los peones ya estaban en %s." % p)
    else:
        print("\nLos peones corren en segundo plano: cada permiso que pidan te llega a la sesión principal.")
        print("Con --permisos agrego a .claude/settings.local.json (solo tu copia, no se sube):")
        for r in reglas:
            print("  permitir  %s" % r)
        for r in preguntar:
            print("  preguntar %s" % r)
    return 0


def _ficha_del_repo(raiz, destino):
    """True si la ficha está commiteada y sin cambios locales: la trajo el repo, no la escribiste tú."""
    rel = os.path.relpath(destino, raiz)
    try:
        conocida = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=raiz, capture_output=True,
                                  text=True, timeout=10).returncode == 0
        if not conocida:
            return False
        return subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=raiz, capture_output=True,
                              timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _raiz_git(d):
    try:
        p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=d, capture_output=True, text=True, timeout=5)
        if p.returncode == 0 and p.stdout.strip():
            return os.path.abspath(p.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def cmd_estado(args):
    if not nucleo.servidor_vivo():
        print("La oficina no está corriendo. Se arranca sola con Claude Code, o con `latigo abrir`.")
        return 1
    info = nucleo.info_servidor()
    print("Oficina en %s (pid %s, versión %s)" % (info.get("url"), info.get("pid"), info.get("version")))
    try:
        est = _pedir("/api/estado")
    except (OSError, ValueError) as e:
        print("No respondió: %s" % e)
        return 1
    if not est.get("sesiones"):
        print("Sin sesiones de Claude Code a la vista.")
    for s in est.get("sesiones", []):
        cap = next((a for a in s["agentes"] if a["rol"] == "capataz"), {})
        peones = [a for a in s["agentes"] if a["rol"] == "peon" and a["visible"]]
        lat = s.get("latigo") or {}
        print("- %s: %s · %s %s · peones %d · latigazo %s/techo %s" % (
            s["proyecto"], s.get("titulo") or "", cap.get("icono", ""), cap.get("texto", ""), len(peones),
            lat.get("nivel", 0), lat.get("techo", 0)))
    return 0


def cmd_parar(args):
    if not nucleo.servidor_vivo():
        print("La oficina no estaba corriendo.")
        return 0
    info = nucleo.info_servidor()
    try:
        _post("/api/parar")
        print("Oficina apagada.")
        return 0
    except (OSError, ValueError) as e:
        error = e
    pid = int(info.get("pid") or 0)
    if pid and pid != os.getpid():
        try:
            import signal

            os.kill(pid, signal.SIGTERM)
            print("No respondió por HTTP (%s); terminé su proceso (pid %d)." % (error, pid))
            return 0
        except OSError as e:
            print("No pude apagarla: %s; %s" % (error, e))
            return 1
    print("No pude apagarla por HTTP (%s)." % error)
    return 1


def cmd_servidor(args):
    import servidor

    return servidor.correr(abrir="--abrir" in args)


def cmd_sonar(args):
    nombre = args[0] if args else "latigazo"
    if nombre not in nucleo.SONIDOS:
        print("Sonidos: %s" % ", ".join(nucleo.SONIDOS))
        return 1
    ok = nucleo.reproducir(nombre, desde_hook=True, forzar=True)
    print("Sonando %s" % nombre if ok else "No encontré cómo reproducir audio en este sistema.")
    time.sleep(0.6)
    return 0 if ok else 1


def version_claude():
    exe = shutil.which("claude")
    if not exe:
        return None, None
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", p.stdout + p.stderr)
        if m:
            return tuple(int(x) for x in m.groups()), exe
    except (OSError, subprocess.SubprocessError):
        pass
    return None, exe


def cmd_diagnostico(args):
    ok = True

    def linea(bien, texto):
        nonlocal ok
        ok = ok and bien
        print(("  ✔ " if bien else "  ✘ ") + texto)

    print("Látigo %s en %s" % (nucleo.VERSION, nucleo.dir_base()))
    linea(sys.version_info >= (3, 8), "Python %s (%s)" % (sys.version.split()[0], sys.executable))
    ver, exe = version_claude()
    if ver:
        linea(ver >= VERSION_MINIMA_CLAUDE, "Claude Code %s (se necesita %s o más nuevo)"
              % (".".join(map(str, ver)), ".".join(map(str, VERSION_MINIMA_CLAUDE))))
    else:
        print("  ? No encontré `claude` en el PATH para revisar su versión (se necesita %s o más nuevo)."
              % ".".join(map(str, VERSION_MINIMA_CLAUDE)))
    ajustes = os.path.join(nucleo.dir_claude(), "settings.json")
    datos = nucleo.leer_json(ajustes, None)
    if datos is None:
        linea(False, "No pude leer %s" % ajustes)
    else:
        hooks = datos.get("hooks") or {}
        nuestros = sum(1 for ev in hooks.values() for g in ev for h in g.get("hooks", [])
                       if "hook.py" in json.dumps(h) and "latigo" in json.dumps(h))
        linea(nuestros >= 15, "%d hooks del látigo en settings.json" % nuestros)
        if datos.get("disableAllHooks"):
            linea(False, "disableAllHooks está activo en settings.json: los hooks no corren")
        base = (datos.get("worktree") or {}).get("baseRef")
        linea(base == "head", "worktree.baseRef = %s (los peones parten de tu HEAD si es \"head\")" % (base or "fresh (por defecto)"))
    for rel in ("skills/latigo/SKILL.md", "agents/peon.md", "agents/peon-libre.md"):
        linea(os.path.exists(os.path.join(nucleo.dir_claude(), *rel.split("/"))), rel)
    faltan = [n for n in nucleo.SONIDOS if not os.path.exists(nucleo.ruta("sonidos", n + ".wav"))]
    linea(not faltan, "sonidos generados" + (" (faltan: %s)" % ", ".join(faltan) if faltan else ""))
    vivo = nucleo.servidor_vivo()
    print(("  ✔ " if vivo else "  · ") + ("oficina corriendo en %s" % _url() if vivo else "la oficina no está corriendo ahorita (se arranca sola con Claude Code)"))
    errores = os.path.join(nucleo.dir_estado(), "errores.log")
    if os.path.exists(errores) and os.path.getsize(errores) > 0:
        print("  · hay errores registrados en %s" % errores)
    print("Todo bien." if ok else "Hay cosas por arreglar (ver ✘).")
    return 0 if ok else 1


COMANDOS = {
    "abrir": cmd_abrir, "demo": cmd_demo, "init": cmd_init, "estado": cmd_estado, "parar": cmd_parar,
    "servidor": cmd_servidor, "sonar": cmd_sonar, "diagnostico": cmd_diagnostico, "diagnóstico": cmd_diagnostico,
}


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "ayuda"):
        print(__doc__.strip())
        return 0
    fn = COMANDOS.get(argv[0])
    if not fn:
        print("No conozco «%s».\n\n%s" % (argv[0], __doc__.strip()))
        return 2
    return fn(argv[1:])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # consola de Windows
    except (AttributeError, ValueError):
        pass
    sys.exit(main(sys.argv[1:]))
