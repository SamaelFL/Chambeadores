#!/usr/bin/env python3
"""Instalador del látigo para Claude Code (macOS, Windows y Linux). Solo usa Python.

  python3 instalar.py                 instala o actualiza
  python3 instalar.py --desinstalar   quita todo lo que puso y restaura lo que había reemplazado

Opciones:
  --sin-baseref    no cambia worktree.baseRef (por defecto lo pone en "head" si no lo tienes)
  --no-abrir       la caseta no se abre sola cuando arranca Claude Code
  --sin-ventana    no abre la demostración al terminar de instalar
  --puerto N       puerto de la oficina (por defecto 47821)

Qué toca:
  ~/.claude/latigo/            el código, la config, los sonidos y el estado
  ~/.claude/skills/latigo/     la skill con el protocolo del latigazo
  ~/.claude/agents/peon*.md    los dos tipos de peón
  ~/.claude/settings.json      los hooks y worktree.baseRef
  ~/.claude/latigo-respaldos/  respaldos de lo anterior (no se borran al desinstalar)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
FUENTE = os.path.join(RAIZ, "latigo")
PLANTILLAS = os.path.join(RAIZ, "plantillas")
# 2.1.198: los subagentes corren en segundo plano por defecto y sus permisos se piden en la
# sesión principal; el protocolo del látigo cuenta con eso. 2.1.139 trae la forma exec de los hooks.
VERSION_MINIMA = (2, 1, 198)

ARCHIVOS = [
    "nucleo.py", "hook.py", "servidor.py", "modelo.py", "transcripts.py", "etiquetas.py", "ventana.py",
    "ficha.py", "latigo.py",
    "web/index.html", "web/estilos.css", "web/iso.js", "web/figuras.js", "web/escena.js", "web/panel.js", "web/demo.js",
    "web/icono.svg",
    "web/fuentes/archivo-expanded-800.woff2", "web/fuentes/archivo-semiexpanded-600.woff2",
    "web/fuentes/geist-400.woff2", "web/fuentes/geist-500.woff2",
    "web/fuentes/geist-mono-400.woff2", "web/fuentes/geist-mono-500.woff2",
]

# Pistas para `latigo init`: qué skills sugerir según el stack (clave del stack -> nombres de tus skills).
# Vacío por defecto; se llena en ~/.claude/latigo/config.json, p. ej. {"angular": ["mi-skill-de-angular"]}.
SKILLS_SUGERIDAS = {}

# (evento, matcher, modo, async, timeout)
HOOKS = [
    ("SessionStart", None, "inicio", True, 30),
    ("UserPromptSubmit", None, "control", False, 10),
    ("UserPromptExpansion", "latigo", "control", False, 10),
    ("PreToolUse", "*", "telemetria", True, None),
    ("PreToolUse", "Skill", "control", False, 10),
    ("PermissionRequest", "*", "telemetria", True, None),
    ("PermissionDenied", None, "telemetria", True, None),
    ("PostToolUse", "*", "telemetria", True, None),
    ("PostToolUseFailure", "*", "telemetria", True, None),
    ("PostToolBatch", None, "control", False, 10),
    ("Notification", None, "telemetria", True, None),
    ("SubagentStart", None, "telemetria", True, None),
    ("SubagentStart", "peon|peon-libre", "control", False, 10),
    ("SubagentStop", None, "telemetria", True, None),
    ("Stop", None, "control", False, 10),
    ("StopFailure", None, "telemetria", True, None),
    ("PreCompact", None, "telemetria", True, None),
    ("PostCompact", None, "telemetria", True, None),
    ("SessionEnd", None, "telemetria", True, None),
]

# Archivos nuestros fuera de ~/.claude/latigo, con la marca que los identifica.
PROPIOS = [
    (("skills", "latigo", "SKILL.md"), "Látigo del usuario"),
    (("agents", "peon.md"), "Peón del látigo"),
    (("agents", "peon-libre.md"), "Peón del látigo"),
]


def dir_claude():
    d = os.environ.get("CLAUDE_CONFIG_DIR")
    return os.path.abspath(os.path.expanduser(d)) if d else os.path.join(os.path.expanduser("~"), ".claude")


def destino():
    return os.path.join(dir_claude(), "latigo")


def dir_respaldos():
    return os.path.join(dir_claude(), "latigo-respaldos")


# ---------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------

def leer_json(p, defecto=None):
    """Lectura estricta: si el archivo existe y está roto, no se toca nada."""
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            texto = f.read()
    except FileNotFoundError:
        return defecto
    if not texto.strip():
        return defecto
    try:
        return json.loads(texto)
    except ValueError as e:
        raise SystemExit("No pude leer %s: no es JSON válido (%s). No toqué nada." % (p, e))


def leer_json_suave(p):
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _reemplazar(origen, final):
    for intento in range(10):
        try:
            os.replace(origen, final)
            return
        except PermissionError:
            # Windows: otro proceso (Claude Code, un antivirus) puede tenerlo abierto un instante.
            if intento == 9:
                raise
            time.sleep(0.05 * (intento + 1))


def escribir_json(p, datos):
    """Escribe atómico. Si `p` es un enlace (dotfiles), escribe en el archivo real y conserva el enlace y los permisos."""
    real = os.path.realpath(p)
    modo = None
    try:
        modo = stat.S_IMODE(os.stat(real).st_mode)
    except OSError:
        pass
    os.makedirs(os.path.dirname(real), exist_ok=True)
    tmp = real + ".tmp-latigo"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
            f.write("\n")
        if modo is not None:
            try:
                os.chmod(tmp, modo)
            except OSError:
                pass
        _reemplazar(tmp, real)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def respaldar(p):
    """Copia `p` a ~/.claude/latigo-respaldos/ (fuera de lo que borra el desinstalador)."""
    if not os.path.exists(p):
        return None
    d = dir_respaldos()
    os.makedirs(d, exist_ok=True)
    base = "%s.%s" % (os.path.basename(p), time.strftime("%Y%m%d-%H%M%S"))
    copia = os.path.join(d, base)
    n = 1
    while os.path.exists(copia):
        n += 1
        copia = os.path.join(d, "%s-%d" % (base, n))
    shutil.copy2(p, copia)
    return copia


def escribir_si_cambia(p, contenido, marca, reemplazados):
    """Escribe un archivo nuestro. Si había uno distinto que no era nuestro, lo respalda y lo anota."""
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            previo = f.read()
        if previo == contenido:
            return False
        if marca not in previo:
            copia = respaldar(p)
            reemplazados[p] = copia
            print("· %s ya existía y no era del látigo: lo respaldé en %s (se restaura al desinstalar)." % (p, copia))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp-latigo"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(contenido)
    _reemplazar(tmp, p)
    return True


# ---------------------------------------------------------------------------
# Hooks en settings.json
# ---------------------------------------------------------------------------

def es_nuestro(handler):
    if not isinstance(handler, dict):
        return False
    piezas = [str(handler.get("command") or "")] + [str(a) for a in (handler.get("args") or [])]
    return any(p.replace("\\", "/").rstrip("/").endswith("latigo/hook.py") for p in piezas)


def quitar_nuestros(hooks):
    for ev in list(hooks):
        grupos = hooks.get(ev)
        if not isinstance(grupos, list):
            continue
        nuevos = []
        for g in grupos:
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                nuevos.append(g)
                continue
            quedan = [h for h in g["hooks"] if not es_nuestro(h)]
            if len(quedan) == len(g["hooks"]):
                nuevos.append(g)
            elif quedan:
                g2 = dict(g)
                g2["hooks"] = quedan
                nuevos.append(g2)
        if nuevos:
            hooks[ev] = nuevos
        else:
            del hooks[ev]
    return hooks


def nuestros_hooks(py, hook):
    out = {}
    for evento, matcher, modo, asincrono, timeout in HOOKS:
        h = {"type": "command", "command": py, "args": ["-S", hook, modo]}
        if asincrono:
            h["async"] = True
        if timeout:
            h["timeout"] = timeout
        grupo = {"hooks": [h]}
        if matcher:
            grupo = {"matcher": matcher, "hooks": [h]}
        out.setdefault(evento, []).append(grupo)
    return out


def leer_ajustes(p_set):
    ajustes = leer_json(p_set, {})
    if not isinstance(ajustes, dict):
        raise SystemExit("%s no es un objeto JSON; no toqué nada." % p_set)
    if "hooks" in ajustes and not isinstance(ajustes["hooks"], dict):
        raise SystemExit("En %s, `hooks` no es un objeto; arréglalo a mano. No toqué nada." % p_set)
    return ajustes


# ---------------------------------------------------------------------------
# Oficina corriendo
# ---------------------------------------------------------------------------

def _abrir_local(req, timeout=3):
    """urllib sin proxy: con un proxy configurado en el entorno, 127.0.0.1 no debe pasar por él."""
    import urllib.request

    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)


def _proceso_vivo(pid):
    if os.name == "nt":
        try:
            p = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True, timeout=10)
            return str(pid) in p.stdout
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def parar_oficina(dest):
    """Apaga la oficina si está corriendo: primero le pide salir por HTTP y, si no responde, termina su proceso."""
    estado = os.path.join(dest, "estado")
    info = leer_json_suave(os.path.join(estado, "servidor.json"))
    try:
        viva = time.time() - float(info.get("latido") or 0) < 8
    except (TypeError, ValueError):
        viva = False
    if not viva:
        return
    token = info.get("token") or ""
    if not token:
        try:
            with open(os.path.join(estado, "token"), "r", encoding="ascii") as f:
                token = f.read().strip()
        except OSError:
            pass
    pid = int(info.get("pid") or 0)
    try:
        import urllib.request

        req = urllib.request.Request(str(info.get("url") or "").rstrip("/") + "/api/parar", data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Latigo-Token", token)
        _abrir_local(req).read()
    except (OSError, ValueError):
        if pid:
            try:
                import signal

                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    limite = time.time() + 4
    while pid and time.time() < limite and _proceso_vivo(pid):
        time.sleep(0.1)
    if pid and _proceso_vivo(pid):
        print("· La oficina (pid %d) no se apagó; ciérrala a mano si algo falla." % pid)
    else:
        print("· Apagué la oficina que estaba corriendo (se vuelve a abrir con Claude Code).")


def version_claude():
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", (p.stdout or "") + (p.stderr or ""))
        return tuple(int(x) for x in m.groups()) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def interprete_estable():
    """El Python con el que corren los hooks.

    En macOS y Linux, si el `python3` del PATH es el mismo que corre el instalador, se usa esa
    ruta y no la real: con Homebrew, `/opt/homebrew/bin/python3` sobrevive a `brew upgrade`,
    pero `…/opt/python@3.13/bin/python3.13` desaparece al pasar a 3.14 y todos los hooks
    fallarían.
    """
    py = sys.executable or "python3"
    if os.name == "nt":
        if os.path.basename(py).lower() == "pythonw.exe":
            py = os.path.join(os.path.dirname(py), "python.exe")
        return py
    cand = shutil.which("python3")
    try:
        if cand and os.path.realpath(cand) == os.path.realpath(py):
            return cand
    except OSError:
        pass
    return py


def leer_version():
    try:
        with open(os.path.join(FUENTE, "nucleo.py"), "r", encoding="utf-8") as f:
            m = re.search(r'VERSION = "([^"]+)"', f.read())
            return m.group(1) if m else "?"
    except OSError:
        return "?"


# ---------------------------------------------------------------------------
# Instalar
# ---------------------------------------------------------------------------

def instalar(opciones):
    if sys.version_info < (3, 8):
        raise SystemExit("Se necesita Python 3.8 o más nuevo (tienes %s)." % sys.version.split()[0])
    claude = dir_claude()
    dest = destino()

    # 0. Validar todo antes de copiar nada.
    puerto = None
    if "--puerto" in opciones:
        try:
            puerto = int(opciones[opciones.index("--puerto") + 1])
            if not 1024 <= puerto <= 65000:
                raise ValueError
        except (IndexError, ValueError):
            raise SystemExit("--puerto necesita un número entre 1024 y 65000. No toqué nada.")
    p_set = os.path.join(claude, "settings.json")
    ajustes = leer_ajustes(p_set)
    p_cfg = os.path.join(dest, "config.json")
    cfg = leer_json(p_cfg, {}) or {}
    if not isinstance(cfg, dict):
        raise SystemExit("%s no es un objeto JSON; no toqué nada." % p_cfg)
    p_man = os.path.join(dest, "instalacion.json")
    manifiesto_previo = leer_json_suave(p_man)

    print("Instalando el látigo en %s" % dest)
    os.makedirs(dest, exist_ok=True)
    parar_oficina(dest)

    # 1. Código
    if os.path.abspath(FUENTE) != os.path.abspath(dest):
        for rel in ARCHIVOS:
            origen = os.path.join(FUENTE, *rel.split("/"))
            final = os.path.join(dest, *rel.split("/"))
            os.makedirs(os.path.dirname(final), exist_ok=True)
            shutil.copy2(origen, final)
    hook = os.path.join(dest, "hook.py")
    py = interprete_estable()

    # 2. Config (respeta lo que ya tengas)
    if puerto:
        cfg["puerto"] = puerto
    if "--no-abrir" in opciones:
        cfg["abrir_oficina_al_iniciar"] = False
    if not cfg.get("skills_por_stack"):
        cfg["skills_por_stack"] = SKILLS_SUGERIDAS
    escribir_json(p_cfg, cfg)

    # 3. Sonidos
    sys.path.insert(0, dest)
    try:
        import nucleo  # noqa: E402  (el recién copiado)

        nucleo._cache_config = None
        os.environ.pop("LATIGO_DIR", None)
        nucleo.generar_sonidos()
        print("· Sonidos generados.")
    except Exception as e:  # pragma: no cover
        print("· No pude generar los sonidos (%s); se generan solos al primer uso." % e)

    # 4. Skill y peones (si reemplazo algo tuyo, queda respaldado y anotado para restaurarlo)
    reemplazados = dict(manifiesto_previo.get("reemplazados") or {})
    with open(os.path.join(PLANTILLAS, "skill", "SKILL.md"), "r", encoding="utf-8") as f:
        skill = f.read().replace("{{PY}}", py.replace("\\", "/")).replace("{{DIR}}", dest.replace("\\", "/"))
    contenidos = {PROPIOS[0][0]: skill}
    for nombre in ("peon.md", "peon-libre.md"):
        with open(os.path.join(PLANTILLAS, "agentes", nombre), "r", encoding="utf-8") as f:
            contenidos[("agents", nombre)] = f.read()
    for partes, marca in PROPIOS:
        escribir_si_cambia(os.path.join(claude, *partes), contenidos[partes], marca, reemplazados)
    print("· Skill latigo y peones listos.")

    # 5. settings.json
    copia = respaldar(p_set)
    hooks = quitar_nuestros(ajustes.get("hooks") or {})
    for ev, grupos in nuestros_hooks(py, hook).items():
        hooks.setdefault(ev, []).extend(grupos)
    ajustes["hooks"] = hooks
    baseref_nuestro = bool(manifiesto_previo.get("baseref_puesto"))
    if "--sin-baseref" not in opciones:
        wt = ajustes.get("worktree") if isinstance(ajustes.get("worktree"), dict) else {}
        if "baseRef" not in wt:
            wt["baseRef"] = "head"
            ajustes["worktree"] = wt
            baseref_nuestro = True
            print("· worktree.baseRef = \"head\": los peones arrancan desde tu último commit, no desde main.")
        elif wt.get("baseRef") != "head":
            print("· Ojo: tienes worktree.baseRef = %r; con eso los peones arrancan desde tu rama por defecto."
                  % wt.get("baseRef"))
    if ajustes.get("disableAllHooks"):
        print("· Ojo: tienes disableAllHooks activo; mientras siga así, el látigo no funciona.")
    escribir_json(p_set, ajustes)
    print("· Hooks agregados a %s%s." % (p_set, (" (respaldo: %s)" % copia) if copia else ""))

    # 6. Manifiesto (lo usa el desinstalador)
    escribir_json(p_man, {
        "version": leer_version(), "fecha": time.strftime("%Y-%m-%d %H:%M:%S"), "python": py,
        "baseref_puesto": baseref_nuestro, "respaldo_settings": copia, "reemplazados": reemplazados,
    })

    ver = version_claude()
    if ver and ver < VERSION_MINIMA:
        print("· Ojo: tu Claude Code es %s y el látigo necesita %s o más nuevo. Actualízalo con `claude update`."
              % (".".join(map(str, ver)), ".".join(map(str, VERSION_MINIMA))))
    elif not ver:
        print("· No encontré `claude` en el PATH para revisar la versión (se necesita %s o más nueva)."
              % ".".join(map(str, VERSION_MINIMA)))

    lanzador = '"%s" "%s"' % (py, os.path.join(dest, "latigo.py"))
    print("""
Listo. Qué sigue:
  1. Reinicia Claude Code (los hooks se leen al arrancar). La caseta se abre sola.
  2. En cada proyecto, una vez:   /latigo init    (crea la ficha .claude/latigo.md)
  3. Para azotar: clic en el capataz en la caseta, o escribe "latigazo" mientras trabaja.

Atajos (en la terminal):
  %s abrir         abre la caseta
  %s demo          demostración sin Claude Code
  %s diagnostico   revisa la instalación
""" % (lanzador, lanzador, lanzador))
    if "--sin-ventana" not in opciones:
        try:
            subprocess.Popen([py, os.path.join(dest, "latigo.py"), "demo"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            print("Abriendo la demostración…")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Desinstalar
# ---------------------------------------------------------------------------

def _quitar_solo_lectura(funcion, path, _exc):
    """Windows: rmtree falla con archivos de solo lectura; se les quita el atributo y se reintenta."""
    try:
        os.chmod(path, stat.S_IWRITE)
        funcion(path)
    except OSError:
        pass


def desinstalar():
    claude = dir_claude()
    dest = destino()
    p_set = os.path.join(claude, "settings.json")
    ajustes = leer_ajustes(p_set) if os.path.exists(p_set) else None  # si está roto, no se toca nada
    manifiesto = leer_json_suave(os.path.join(dest, "instalacion.json"))
    parar_oficina(dest)

    if ajustes is not None:
        copia = respaldar(p_set)
        if isinstance(ajustes.get("hooks"), dict):
            ajustes["hooks"] = quitar_nuestros(ajustes["hooks"])
            if not ajustes["hooks"]:
                del ajustes["hooks"]
        if manifiesto.get("baseref_puesto") and isinstance(ajustes.get("worktree"), dict):
            if ajustes["worktree"].get("baseRef") == "head":
                ajustes["worktree"].pop("baseRef", None)
            if not ajustes["worktree"]:
                del ajustes["worktree"]
        escribir_json(p_set, ajustes)
        print("· Quité los hooks de %s (respaldo: %s)." % (p_set, copia))

    reemplazados = manifiesto.get("reemplazados") or {}
    for partes, marca in PROPIOS:
        p = os.path.join(claude, *partes)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                nuestro = marca in f.read()
        except OSError:
            nuestro = False
        if nuestro:
            try:
                os.remove(p)
                print("· Quité %s" % p)
            except OSError as e:
                print("· No pude quitar %s (%s)" % (p, e))
                continue
        original = reemplazados.get(p)
        if original and os.path.exists(original) and not os.path.exists(p):
            try:
                shutil.copy2(original, p)
                print("· Restauré tu %s original." % p)
            except OSError as e:
                print("· No pude restaurar %s desde %s (%s)" % (p, original, e))
    try:
        os.rmdir(os.path.join(claude, "skills", "latigo"))
    except OSError:
        pass

    if os.path.isdir(dest) and os.path.abspath(dest) != os.path.abspath(FUENTE):
        error = None
        manejo = {"onexc": _quitar_solo_lectura} if sys.version_info >= (3, 12) else {"onerror": _quitar_solo_lectura}
        for _ in range(6):
            try:
                shutil.rmtree(dest, **manejo)
            except OSError as e:
                error = e
            if not os.path.exists(dest):
                break
            time.sleep(0.5)
        if os.path.exists(dest):
            print("· No pude borrar %s (%s). Bórrala a mano después de cerrar Claude Code." % (dest, error or "en uso"))
        else:
            print("· Borré %s" % dest)
    print("Listo: el látigo quedó desinstalado. Los respaldos están en %s. Reinicia Claude Code." % dir_respaldos())


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
    elif "--desinstalar" in args:
        desinstalar()
    else:
        instalar(args)
