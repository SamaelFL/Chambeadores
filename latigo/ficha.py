"""`latigo init`: detecta el stack del proyecto y escribe .claude/latigo.md (la ficha).

La ficha es Markdown para humanos y para Claude: el capataz la lee al repartir y a cada
peón le llega al arrancar (hook SubagentStart). Lo que no se pueda detectar queda
marcado para que Claude o el usuario lo corrijan.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

import nucleo

IGNORAR = {"node_modules", ".git", "target", "dist", "build", ".venv", "venv", "__pycache__", ".idea",
           ".vscode", ".angular", ".next", "out", "coverage", ".gradle", ".claude"}


def _leer(path, limite=400_000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limite)
    except OSError:
        return ""


def _json(path):
    try:
        return json.loads(_leer(path))
    except ValueError:
        return {}


def _gestor_node(d):
    if os.path.exists(os.path.join(d, "pnpm-lock.yaml")):
        return "pnpm"
    if os.path.exists(os.path.join(d, "yarn.lock")):
        return "yarn"
    if os.path.exists(os.path.join(d, "bun.lockb")) or os.path.exists(os.path.join(d, "bun.lock")):
        return "bun"
    return "npm"


def _correr_script(gestor, script):
    return "%s run %s" % (gestor, script) if gestor != "yarn" else "yarn %s" % script


def _hay_pruebas_py(d):
    try:
        return any(n.startswith("test") and n.endswith(".py") for n in os.listdir(d))
    except OSError:
        return False


def _version(dep):
    m = re.search(r"(\d+)(?:\.(\d+))?", str(dep or ""))
    return m.group(1) if m else ""


def detectar_componente(d, raiz):
    """Un componente = una carpeta con un marcador de build (angular.json, pom.xml, ...)."""
    rel = os.path.relpath(d, raiz).replace("\\", "/")
    rel = "." if rel == "." else rel
    c = {"ruta": rel, "stack": None, "clave": None, "peon": [], "final": [], "preparar": [], "no_tocar": []}
    pkg = _json(os.path.join(d, "package.json")) if os.path.exists(os.path.join(d, "package.json")) else None
    if pkg is not None:
        deps = {}
        deps.update(pkg.get("dependencies") or {})
        deps.update(pkg.get("devDependencies") or {})
        scripts = pkg.get("scripts") or {}
        g = _gestor_node(d)
        if os.path.exists(os.path.join(d, "angular.json")):
            v = _version(deps.get("@angular/core"))
            c.update(stack="Angular %s (%s)" % (v, g) if v else "Angular (%s)" % g, clave="angular")
            tsapp = "tsconfig.app.json" if os.path.exists(os.path.join(d, "tsconfig.app.json")) else "tsconfig.json"
            c["peon"].append("npx tsc -p %s --noEmit" % tsapp)
            c["final"].append("npx ng build")
            if "test" in scripts:
                c["final"].append("npx ng test --watch=false")
            c["no_tocar"].append("src/environments/ (salvo que la pieza sea de configuración)")
        else:
            if "next" in deps:
                nombre, clave = "Next.js", "next"
            elif "vite" in deps and "react" in deps:
                nombre, clave = "React + Vite", "react"
            elif "react" in deps:
                nombre, clave = "React", "react"
            elif "vue" in deps:
                nombre, clave = "Vue", "vue"
            elif "@nestjs/core" in deps:
                nombre, clave = "NestJS", "node"
            elif "express" in deps:
                nombre, clave = "Node + Express", "node"
            else:
                nombre, clave = "Node", "node"
            c.update(stack="%s (%s)" % (nombre, g), clave=clave)
            if "typecheck" in scripts:
                c["peon"].append(_correr_script(g, "typecheck"))
            elif os.path.exists(os.path.join(d, "tsconfig.json")):
                c["peon"].append("npx tsc --noEmit")
            if "lint" in scripts:
                c["peon"].append(_correr_script(g, "lint"))
            if "build" in scripts:
                c["final"].append(_correr_script(g, "build"))
            if "test" in scripts and "no test specified" not in str(scripts.get("test")):
                c["final"].append(_correr_script(g, "test"))
            if "supabase" in str(deps) or os.path.isdir(os.path.join(d, "supabase")):
                c["no_tocar"].append("supabase/migrations/ (las migraciones se hacen a propósito, no como efecto de una pieza)")
        c["preparar"].append("node_modules")
        c["no_tocar"].append("package-lock.json / pnpm-lock.yaml / yarn.lock (salvo que la pieza sea de dependencias)")
        return c
    if os.path.exists(os.path.join(d, "pom.xml")):
        pom = _leer(os.path.join(d, "pom.xml"))
        java = re.search(r"<(?:java\.version|maven\.compiler\.release|maven\.compiler\.source)>\s*([\d.]+)", pom)
        spring = re.search(r"spring-boot-starter-parent</artifactId>\s*<version>\s*([\d.]+)", pom) or \
            re.search(r"<artifactId>spring-boot[^<]*</artifactId>", pom)
        mvn = "./mvnw" if os.path.exists(os.path.join(d, "mvnw")) else "mvn"
        partes = ["Java %s" % java.group(1) if java else "Java"]
        if spring:
            partes.append("Spring Boot %s" % spring.group(1) if spring.groups() and spring.group(1) else "Spring Boot")
        partes.append("Maven")
        c.update(stack=", ".join(partes), clave="spring" if spring else "maven")
        c["peon"].append("%s -q -o compile" % mvn)
        c["final"].append("%s -q -o test" % mvn)
        c["no_tocar"].append("pom.xml (salvo que la pieza sea de dependencias)")
        return c
    for g in ("build.gradle.kts", "build.gradle"):
        if os.path.exists(os.path.join(d, g)):
            gw = "./gradlew" if os.path.exists(os.path.join(d, "gradlew")) else "gradle"
            c.update(stack="Java/Kotlin + Gradle", clave="gradle")
            c["peon"].append("%s compileJava -q --offline" % gw)
            c["final"].append("%s test -q --offline" % gw)
            return c
    pruebas_py = next((p for p in ("tests", "test", "pruebas") if _hay_pruebas_py(os.path.join(d, p))), None)
    if any(os.path.exists(os.path.join(d, f)) for f in ("pyproject.toml", "requirements.txt", "setup.py")) or pruebas_py:
        texto = _leer(os.path.join(d, "pyproject.toml")) + _leer(os.path.join(d, "requirements.txt"))
        # `python3` en la ficha (en macOS sin Homebrew no hay `python`); la variante de Windows
        # (`py`) se escribe al lado y se deriva sola para los permisos.
        c.update(stack="Python", clave="python")
        c["peon"].append("python3 -m compileall -q .")
        if "pytest" in texto:
            c["final"].append("python3 -m pytest -q")
        elif pruebas_py:
            c["final"].append("python3 -m unittest discover -s %s" % pruebas_py)
        # Las pruebas de Python suelen ser rápidas: el peón también las corre (si tardan, quítalo de la ficha).
        c["peon"].extend(c["final"])
        for venv in (".venv", "venv"):
            if os.path.isdir(os.path.join(d, venv)):
                c["preparar"].append("venv")
                c["venv"] = venv
                break
        return c
    if os.path.exists(os.path.join(d, "go.mod")):
        c.update(stack="Go", clave="go", peon=["go build ./..."], final=["go test ./..."])
        return c
    if os.path.exists(os.path.join(d, "Cargo.toml")):
        c.update(stack="Rust", clave="rust", peon=["cargo check"], final=["cargo test"])
        return c
    return None


def detectar(raiz):
    raiz = os.path.abspath(raiz)
    componentes = []
    principal = detectar_componente(raiz, raiz)
    if principal:
        componentes.append(principal)
    if not principal or principal["clave"] not in ("angular",):
        try:
            hijos = sorted(e for e in os.listdir(raiz) if e not in IGNORAR and not e.startswith("."))
        except OSError:
            hijos = []
        for h in hijos:
            d = os.path.join(raiz, h)
            if os.path.isdir(d):
                c = detectar_componente(d, raiz)
                if c and (not principal or c["clave"] != principal["clave"]):
                    componentes.append(c)
                if len(componentes) >= 6:
                    break
    git = os.path.exists(os.path.join(raiz, ".git"))
    env = []
    for n in (".env", ".env.local", ".env.development", ".env.development.local", "application-local.yml",
              "application-local.properties"):
        if os.path.exists(os.path.join(raiz, n)):
            env.append(n)
    return {"raiz": raiz, "nombre": os.path.basename(raiz.rstrip("/\\")), "git": git, "componentes": componentes, "env": env}


def _ignorados_por_git(raiz, archivos):
    if not archivos:
        return []
    try:
        p = subprocess.run(["git", "check-ignore"] + archivos, cwd=raiz, capture_output=True, text=True, timeout=10)
        return [l.strip() for l in p.stdout.splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def excluir_en_git(raiz, patron, prueba):
    """Agrega `patron` a info/exclude del repo (ignorado solo en esta copia) si git no lo ignora ya.

    `prueba` es una ruta de ejemplo que el patrón cubre. Usa `git rev-parse --git-path`, que
    también funciona dentro de un worktree (donde .git es un archivo y no una carpeta).
    """
    if _ignorados_por_git(raiz, [prueba]):
        return False
    try:
        p = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=raiz, capture_output=True,
                           text=True, timeout=10)
        if p.returncode != 0 or not p.stdout.strip():
            return False
        excluir = os.path.join(raiz, p.stdout.strip())
        actual = _leer(excluir)
        if patron in actual.splitlines():
            return False
        os.makedirs(os.path.dirname(excluir), exist_ok=True)
        with open(excluir, "a", encoding="utf-8", newline="\n") as f:
            f.write(("" if actual.endswith("\n") or not actual else "\n") + patron + "\n")
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def sugerir_skills(componentes):
    mapa = nucleo.config().get("skills_por_stack") or {}
    vistas = []
    for c in componentes:
        for s in mapa.get(c["clave"], []) or []:
            if s not in vistas:
                vistas.append(s)
    return vistas


def _profundidad(ruta_rel):
    return 0 if ruta_rel in (".", "") else len([p for p in ruta_rel.replace("\\", "/").split("/") if p])


def enlace_dependencias(ruta_rel):
    """Comandos (POSIX, PowerShell) para enlazar node_modules del checkout principal.

    Se corren dentro de la carpeta del componente en el worktree del peón. El worktree vive
    en <raíz>/.claude/worktrees/<peón>: subir 3 carpetas + la profundidad del componente
    lleva a la raíz del checkout principal, sin depender de en qué máquina se generó la ficha.
    """
    arriba = "../" * (3 + _profundidad(ruta_rel))
    destino = arriba + ("" if ruta_rel == "." else ruta_rel.replace("\\", "/") + "/") + "node_modules"
    win = destino.replace("/", "\\")
    if not re.fullmatch(r"[A-Za-z0-9_./\\-]+", destino):  # espacios u otros caracteres: entre comillas
        destino, win = '"%s"' % destino, '"%s"' % win
    unix = "ln -s %s node_modules" % destino
    win = "New-Item -ItemType Junction -Path node_modules -Target (Resolve-Path %s)" % win
    return unix, win


def variante_windows(cmd):
    """El mismo comando como se escribe en Windows, si cambia (o None)."""
    for unix, win in (("python3 ", "py "), ("./mvnw ", ".\\mvnw.cmd "), ("./gradlew ", ".\\gradlew.bat ")):
        if cmd.startswith(unix):
            return win + cmd[len(unix):]
    return None


def _linea_verificacion(cmd, ruta_rel):
    linea = "- `%s`" % cmd + ("" if ruta_rel == "." else " (en `%s`)" % ruta_rel)
    win = variante_windows(cmd)
    return linea + (" (en Windows, `%s`)" % win if win else "")


def render(info):
    lineas = ["# Ficha del látigo: %s" % info["nombre"], "",
              "<!-- La lee el capataz antes de repartir y a cada peón le llega al arrancar. Corrígela a mano"
              " cuando quieras: es solo Markdown. -->", ""]
    comps = info["componentes"]
    if comps:
        lineas.append("stack: " + "; ".join(("%s en %s" % (c["stack"], c["ruta"])) if c["ruta"] != "." else c["stack"]
                                           for c in comps))
    else:
        lineas.append("stack: (no se detectó; descríbelo aquí)")
    sug = sugerir_skills(comps)
    lineas.append("skills: " + (", ".join(sug) + "   <!-- sugeridas: confirma que apliquen a este proyecto -->"
                                if sug else "(ninguna; agrega las que apliquen)"))
    lineas.append("checkpoint: si   <!-- 'no' si no quieres un commit de checkpoint antes de repartir -->")
    lineas.append("git: " + ("si (peones en worktrees)" if info["git"] else "no (peones en la misma carpeta: peon-libre)"))
    lineas.append("")
    lineas.append("## Preparar el worktree de un peón")
    prep = []
    con_worktrees = info["git"]  # sin git, los peones trabajan en esta misma carpeta: no hay nada que enlazar
    if con_worktrees and any(("node_modules" in c["preparar"] or "venv" in c["preparar"]) for c in comps):
        prep.append("<!-- Rutas relativas a propósito: tu worktree está en .claude/worktrees/<peón>, así que el checkout"
                    " principal queda tres carpetas arriba en cualquier máquina. -->")
    for c in comps:
        donde = c["ruta"]
        if not con_worktrees:
            continue
        if "node_modules" in c["preparar"]:
            unix, win = enlace_dependencias(donde)
            prep.append("- %s: enlaza las dependencias del checkout principal en vez de instalarlas%s:"
                        % ("Raíz" if donde == "." else donde, "" if donde == "." else " (dentro de `%s`)" % donde))
            prep.append("  - macOS/Linux: `%s`" % unix)
            prep.append("  - Windows (PowerShell): `%s`" % win)
            prep.append("  - Si no existe esa carpeta, instala las dependencias con el gestor del proyecto.")
        if "venv" in c["preparar"]:
            arriba = "../" * (3 + _profundidad(donde))
            venv = c.get("venv") or ".venv"
            prep.append("- %s: usa el Python del entorno del checkout principal: `%s%s%s/bin/python`"
                        " (en Windows, `%s%s%s\\Scripts\\python.exe`)."
                        % ("Raíz" if donde == "." else donde, arriba, "" if donde == "." else donde + "/", venv,
                           arriba.replace("/", "\\"), "" if donde == "." else donde.replace("/", "\\") + "\\", venv))
    if info["env"]:
        prep.append("- Los archivos locales (%s) se copian solos a cada worktree por `.worktreeinclude`." % ", ".join(info["env"]))
    lineas.extend(prep or ["- Nada especial."])
    lineas.append("")
    lineas.append("## Verificación de cada peón (rápida, solo su pieza)")
    v = [_linea_verificacion(cmd, c["ruta"]) for c in comps for cmd in c["peon"]]
    lineas.extend(v or ["- (define un comando rápido: compilar o pruebas de un módulo)"])
    lineas.append("")
    lineas.append("## Verificación final (el capataz, después de mergear)")
    v = [_linea_verificacion(cmd, c["ruta"]) for c in comps for cmd in c["final"]]
    lineas.extend(v or ["- (define el build y las pruebas completas)"])
    lineas.append("")
    lineas.append("## No tocar")
    nt = []
    for c in comps:
        for x in c["no_tocar"]:
            if "- " + x not in nt:
                nt.append("- " + x)
    lineas.extend(nt or ["- (carpetas o archivos que ningún peón debe tocar)"])
    lineas.append("")
    lineas.append("## Notas")
    lineas.append("- (convenciones del equipo que los peones deben respetar)")
    lineas.append("")
    return "\n".join(lineas)


# Comandos de git que peones y capataz usan al repartir e integrar. `git status`, `git diff`
# y `git log` no van: Claude Code ya los corre sin preguntar (son de solo lectura).
# `git commit *` y no `git commit -m *`: en la prueba real el peón escribió `git commit -q -m …`
# y la regla angosta se lo negó. Borrar ramas y worktrees queda acotado a los de los peones
# (`worktree-agent-…`, `.claude/worktrees/agent-…`).
GIT_PEONES = [
    "git add *",
    "git commit *",
    "git merge --no-ff *",
    "git branch -d worktree-agent-*",
    "git worktree remove .claude/worktrees/agent-*",
]

# El `*` final cubre cualquier texto, también un `--force` o un `-D` agregado al final
# (`git worktree remove … --force` borra cambios sin commit; `git branch -d x otra -D` borra
# una rama sin mergear). Estas reglas "ask" le ganan a las "allow": esas variantes siempre
# preguntan. Los ids de los peones son hexadecimales en minúsculas, así que " -f"/"-D" no
# aparecen en una ruta o rama normal.
PREGUNTAR = [
    "git worktree remove *--force*",
    "git worktree remove -f*",
    "git worktree remove * -f*",
    "git branch *-D*",
    "git branch *--force*",
    "git branch -f*",
    "git branch * -f*",
    "git commit *--amend*",
]

# Programas que puede tener un comando de verificación de la ficha. La ficha puede venir del
# repo (escrita por otra persona): no se pre-autoriza `rm`, `curl`, `bash -c` ni nada fuera de esto.
PROGRAMAS = {
    "npm", "npx", "pnpm", "yarn", "bun", "bunx", "node", "ng", "tsc", "deno",
    "mvn", "./mvnw", ".\\mvnw.cmd", "gradle", "./gradlew", ".\\gradlew.bat",
    "python", "python3", "py", "pytest", "go", "cargo", "dotnet", "make", "cmake", "ctest",
    "php", "composer", "ruby", "bundle", "rake", "swift", "flutter", "dart", "java", "javac",
    "mix", "sbt",
}
_SEGURO = re.compile(r"[A-Za-z0-9_./:=@+,%\\ -]+")
_ENLACE_UNIX = re.compile(r'ln -s (?:"(?:\.\./){3,}[^"$`\\|;&<>~]*node_modules"|(?:\.\./){3,}[A-Za-z0-9_./-]*node_modules) node_modules')
_ENLACE_WIN = re.compile(r'New-Item -ItemType Junction -Path node_modules -Target \(Resolve-Path '
                         r'(?:"(?:\.\.\\){3,}[^"$`|;&<>~]*node_modules"|(?:\.\.\\){3,}[A-Za-z0-9_.\\-]*node_modules)\)')


def comando_seguro(cmd):
    """True si el comando se puede pre-autorizar: un enlace de dependencias con la forma que
    escribe `init`, o una verificación con un programa conocido y sin caracteres de shell
    (tuberías, redirecciones, `$`, `~`, comillas, `;`, `&`)."""
    if cmd.startswith("ln -s "):
        return bool(_ENLACE_UNIX.fullmatch(cmd))
    if cmd.startswith("New-Item "):
        return bool(_ENLACE_WIN.fullmatch(cmd))
    if not _SEGURO.fullmatch(cmd) or ".." in cmd.split():
        return False
    return cmd.split()[0] in PROGRAMAS


def _sensible_a_mayusculas(cmd):
    """Las reglas de PowerShell no distinguen mayúsculas: `git branch -d …` ahí también cubriría
    `git branch -D …` (borrar sin mergear). Esos comandos solo se pre-autorizan en Bash."""
    return " -d " in cmd or "-D" in cmd


def _regla(cmd):
    """La regla para la herramienta Bash y, en Windows, también para PowerShell."""
    reglas = ["Bash(%s)" % cmd]
    if os.name == "nt" and not _sensible_a_mayusculas(cmd):
        reglas.append("PowerShell(%s)" % cmd)
    return reglas


def comandos_de_ficha(texto):
    """Los comandos que dice la ficha (ya corregida a mano o por Claude), para darles permiso.

    De "Verificación…" toma el primer `comando` de cada renglón; de "Preparar…", los
    `ln -s …` y `New-Item …`. Lo demás (rutas, notas, la variante de Windows) no cuenta.
    """
    cmds, seccion = [], None
    for linea in texto.splitlines():
        if linea.startswith("## "):
            t = linea.lower()
            seccion = "verif" if "verificaci" in t else ("prep" if "preparar" in t else None)
            continue
        item = linea.strip()
        if not seccion or not item.startswith("- "):
            continue
        hallados = re.findall(r"`([^`]+)`", item)
        if seccion == "verif" and hallados and item.startswith("- `"):
            cmds.append(hallados[0].strip())
        elif seccion == "prep":
            cmds.extend(h.strip() for h in hallados if h.startswith(("ln -s ", "New-Item ")))
    return cmds


def reglas_permisos(info, texto_ficha=None, descartados=None):
    """Reglas allow para que los peones verifiquen y hagan commit sin pedir permiso a cada rato.

    Los comandos de verificación van exactos, sin comodín: con `npx`, `mvn`, `gradle` o
    `npm run`, un argumento extra puede ejecutar cualquier cosa (la documentación de
    permisos lo advierte para los "runners"). Si un peón corre otra variante, Claude Code
    te pregunta como siempre. Si ya hay ficha, mandan sus comandos (los corregidos), no los
    que se detectaron, pero solo los que pasan `comando_seguro`; los demás se anotan en
    `descartados` (si se pasa una lista).
    """
    cmds = list(GIT_PEONES)
    raiz = info["raiz"].rstrip("/\\")
    cmds.append("git worktree remove %s/.claude/worktrees/agent-*" % raiz.replace("\\", "/"))
    if os.name == "nt":
        cmds.append("git worktree remove %s\\.claude\\worktrees\\agent-*" % raiz.replace("/", "\\"))
    propios = []
    if texto_ficha:
        propios = comandos_de_ficha(texto_ficha)
    else:
        for c in info["componentes"]:
            if "node_modules" in c["preparar"] and info.get("git"):
                propios.extend(enlace_dependencias(c["ruta"]))
            propios.extend(x.strip() for x in c["peon"] + c["final"])
    for cmd in propios:
        if comando_seguro(cmd):
            cmds.append(cmd)
        elif descartados is not None and cmd not in descartados:
            descartados.append(cmd)
    reglas = []
    for cmd in cmds:
        if cmd.startswith("New-Item "):
            nuevas = ["PowerShell(%s)" % cmd] if os.name == "nt" else []  # solo existe en PowerShell
        elif cmd.startswith("ln -s "):
            nuevas = ["Bash(%s)" % cmd]  # solo existe en Bash (en Windows, Git Bash)
        else:
            nuevas = _regla(cmd)
            win = variante_windows(cmd) if os.name == "nt" else None
            if win:
                nuevas += _regla(win)
        for r in nuevas:
            if r not in reglas:
                reglas.append(r)
    return reglas


def reglas_preguntar():
    reglas = []
    for cmd in PREGUNTAR:
        for r in _regla(cmd):
            if r not in reglas:
                reglas.append(r)
    return reglas


def leer_ajustes_locales(p):
    """Lee .claude/settings.local.json sin perdonar errores: si está roto, no se toca."""
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8-sig") as f:
        texto = f.read()
    if not texto.strip():
        return {}
    try:
        datos = json.loads(texto)
    except ValueError as e:
        raise ValueError("%s no es JSON válido (%s). Arréglalo a mano; no lo toqué." % (p, e))
    if not isinstance(datos, dict):
        raise ValueError("%s no es un objeto JSON. Arréglalo a mano; no lo toqué." % p)
    perm = datos.get("permissions", {})
    if not isinstance(perm, dict) or not isinstance(perm.get("allow", []), list) \
            or not isinstance(perm.get("ask", []), list):
        raise ValueError("%s tiene `permissions` con otra forma. Arréglalo a mano; no lo toqué." % p)
    return datos


def agregar_permisos(raiz, reglas, preguntar=None):
    """Agrega reglas allow (y ask) a .claude/settings.local.json del proyecto (local, no se sube)."""
    p = os.path.join(raiz, ".claude", "settings.local.json")
    datos = leer_ajustes_locales(p)
    perm = datos.setdefault("permissions", {})
    allow = perm.setdefault("allow", [])
    nuevas = [r for r in reglas if r not in allow]
    ask_actual = perm.get("ask") or []
    nuevas_ask = [r for r in (preguntar or []) if r not in ask_actual]
    if nuevas or nuevas_ask:
        allow.extend(nuevas)
        if nuevas_ask:
            perm["ask"] = list(ask_actual) + nuevas_ask
        nucleo.escribir_json(p, datos, indent=2)
    # Que nunca se cuele en un commit (por ejemplo, el de checkpoint con `git add -A`).
    if os.path.exists(os.path.join(raiz, ".git")):
        excluir_en_git(raiz, ".claude/settings.local.json", ".claude/settings.local.json")
    return p, nuevas, nuevas_ask


def crear(raiz, forzar=False):
    info = detectar(raiz)
    destino_dir = os.path.join(info["raiz"], ".claude")
    destino = os.path.join(destino_dir, "latigo.md")
    if os.path.exists(destino) and not forzar:
        return destino, False, info, "Ya existe %s (usa --forzar para reescribirla)." % destino
    os.makedirs(destino_dir, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(info))
    extra = ""
    if info["git"] and excluir_en_git(info["raiz"], ".claude/worktrees/", ".claude/worktrees/x"):
        extra += " Agregué .claude/worktrees/ a .git/info/exclude (ignorado solo en tu copia)."
    if info["git"] and info["env"]:
        ignorados = _ignorados_por_git(info["raiz"], info["env"])
        wti = os.path.join(info["raiz"], ".worktreeinclude")
        if ignorados and not os.path.exists(wti):
            with open(wti, "w", encoding="utf-8", newline="\n") as f:
                f.write("# Archivos ignorados por git que cada worktree necesita (los copia Claude Code)\n")
                f.write("\n".join(ignorados) + "\n")
            extra += " También escribí .worktreeinclude con: %s." % ", ".join(ignorados)
    return destino, True, info, "Ficha escrita en %s.%s" % (destino, extra)
