"""Núcleo del látigo.

Lo comparten hook.py (lo llama Claude Code), servidor.py (la oficina) y latigo.py (CLI):
rutas, configuración, la bitácora del látigo por sesión (nivel, enfriamiento, peones),
la inyección pendiente de un latigazo dado desde la oficina, la telemetría UDP hacia la
oficina y los sonidos sintetizados.

Solo biblioteca estándar y compatible con Python 3.8+ (el python3 de macOS es 3.9).
Todo lo que se escribe a disco es atómico (archivo temporal + os.replace) y lo que se
lee y modifica entre procesos va bajo un candado de archivo, porque varios hooks corren
en paralelo (por ejemplo, cinco SubagentStart casi al mismo tiempo).
"""
from __future__ import annotations

import json
import os
import sys
import time

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

DIR_CODIGO = os.path.dirname(os.path.abspath(__file__))


def dir_base() -> str:
    """Carpeta del látigo instalado (código, config, estado y sonidos).

    LATIGO_DIR permite apuntar a otra carpeta (pruebas) sin mover el código.
    """
    d = os.environ.get("LATIGO_DIR")
    return os.path.abspath(os.path.expanduser(d)) if d else DIR_CODIGO


def dir_claude() -> str:
    d = os.environ.get("CLAUDE_CONFIG_DIR")
    if d:
        return os.path.abspath(os.path.expanduser(d))
    return os.path.join(os.path.expanduser("~"), ".claude")


def dir_estado() -> str:
    d = os.path.join(dir_base(), "estado")
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    return d


def dir_latigos() -> str:
    d = os.path.join(dir_estado(), "latigo")
    os.makedirs(d, exist_ok=True)
    return d


def ruta(*partes: str) -> str:
    return os.path.join(dir_base(), *partes)


def id_seguro(sid: str) -> str:
    """Convierte un session_id en un nombre de archivo seguro."""
    limpio = "".join(c for c in str(sid or "") if c.isalnum() or c in "-_")
    return limpio[:80] or "sin-sesion"


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

CONFIG_DEFECTO = {
    "puerto": 47821,
    "autoiniciar_servidor": True,
    "abrir_oficina_al_iniciar": True,
    # Latigazo efectivo n.º 1 => techo 3 peones, n.º 2 en adelante => 5.
    "techo_por_nivel": [3, 5],
    "tope_peones": 5,
    "enfriamiento_segundos": 60,
    # Un latigazo de la oficina espera a que el capataz termine su herramienta en curso
    # (una compilación larga, por ejemplo). Si no llega en este tiempo, se cancela y no cuenta.
    "inyeccion_expira_segundos": 600,
    "peon_vencido_minutos": 45,
    "tipos_peon": ["peon", "peon-libre"],
    "sonidos": {
        "latigazo": True,
        "peon_listo": True,
        "permiso": True,
        "listo": True,
        "error": True,
    },
    # Solo suena "listo" si el turno duró al menos esto (evita ruido en respuestas cortas).
    "sonido_listo_min_segundos": 20,
    "volumen": 0.7,
    # Silencio general (botón de la bocina en la oficina).
    "silencio": False,
    # Si no hay sesiones ni ventanas abiertas por este tiempo, la oficina se apaga sola.
    "apagar_tras_inactividad_min": 180,
    # Skills a precargar por stack en la ficha que genera `latigo init`.
    "skills_por_stack": {},
    # auto | chrome | edge | brave | chromium | sistema
    "navegador": "auto",
}

_cache_config = None  # type: ignore[var-annotated]


def _mezclar(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _mezclar(out[k], v)
        else:
            out[k] = v
    return out


def config(recargar: bool = False) -> dict:
    global _cache_config
    if _cache_config is not None and not recargar:
        return _cache_config
    datos = leer_json(ruta("config.json"), {})
    _cache_config = _mezclar(CONFIG_DEFECTO, datos if isinstance(datos, dict) else {})
    return _cache_config


def guardar_config(cambios: dict) -> dict:
    actual = leer_json(ruta("config.json"), {})
    if not isinstance(actual, dict):
        actual = {}
    nuevo = _mezclar(actual, cambios)
    escribir_json(ruta("config.json"), nuevo)
    return config(recargar=True)


# ---------------------------------------------------------------------------
# Archivos: JSON atómico, candado entre procesos, bitácora de errores
# ---------------------------------------------------------------------------

def leer_json(path: str, defecto=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def reemplazar(origen: str, destino: str, intentos: int = 8) -> None:
    """os.replace con reintentos: en Windows el destino puede estar abierto un instante."""
    for intento in range(intentos):
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            if intento == intentos - 1:
                raise
            time.sleep(0.01 * (intento + 1))


def escribir_json(path: str, datos, indent: int = 1, modo: int = None) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp.%d.%d" % (path, os.getpid(), int(time.time() * 1000) % 100000)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(datos, f, ensure_ascii=False, indent=indent)
            f.write("\n")
        if modo is not None:
            try:
                os.chmod(tmp, modo)
            except OSError:
                pass
        reemplazar(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class Candado:
    """Candado de archivo portátil (macOS, Linux y Windows) con O_CREAT|O_EXCL.

    Si un proceso murió con el candado tomado, el candado se considera vencido
    después de `vence` segundos y se roba.
    """

    def __init__(self, path: str, espera: float = 3.0, vence: float = 8.0):
        self.path = path
        self.espera = espera
        self.vence = vence
        self.tomado = False

    def __enter__(self):
        limite = time.time() + self.espera
        while time.time() < limite:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.vence:
                        os.remove(self.path)  # vencido: su dueño murió con el candado tomado
                        continue
                except OSError:
                    pass  # desapareció o no se pudo quitar: se reintenta abajo, sin pasar del plazo
                time.sleep(0.005)
                continue
            except OSError:
                return self  # sin permisos o sin disco: seguir sin candado
            try:
                os.write(fd, str(os.getpid()).encode())
            finally:
                os.close(fd)
            self.tomado = True
            return self
        # Mejor seguir sin candado que bloquear a Claude.
        return self

    def __exit__(self, *exc):
        if self.tomado:
            try:
                os.remove(self.path)
            except OSError:
                pass
        return False


def log_error(contexto: str, err: BaseException = None) -> None:
    try:
        p = os.path.join(dir_estado(), "errores.log")
        if os.path.exists(p) and os.path.getsize(p) > 200_000:
            os.replace(p, p + ".1")
        import traceback

        with open(p, "a", encoding="utf-8") as f:
            f.write("%s %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), contexto, err or ""))
            if err is not None:
                f.write("".join(traceback.format_exception(type(err), err, err.__traceback__))[-2000:])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Bitácora del látigo por sesión
# ---------------------------------------------------------------------------

def _ruta_bitacora(sid: str) -> str:
    return os.path.join(dir_latigos(), id_seguro(sid) + ".json")


def _candado(sid: str) -> Candado:
    return Candado(os.path.join(dir_latigos(), id_seguro(sid) + ".lock"))


def _bitacora_vacia(sid: str) -> dict:
    return {
        "sesion": sid,
        "nivel": 0,
        "ultimo_efectivo": 0.0,
        "latigazos": 0,
        "latigazos_total": 0,
        "peones": {},
        "pendiente_skill": 0.0,
        "ultimo_prompt_id": None,
        "ultimo_resultado": None,
        "historial": [],
    }


def leer_bitacora(sid: str) -> dict:
    datos = leer_json(_ruta_bitacora(sid), None)
    if not isinstance(datos, dict):
        return _bitacora_vacia(sid)
    base = _bitacora_vacia(sid)
    base.update(datos)
    if not isinstance(base.get("peones"), dict):
        base["peones"] = {}
    return base


def _guardar_bitacora(sid: str, datos: dict) -> None:
    datos["historial"] = list(datos.get("historial") or [])[-20:]
    escribir_json(_ruta_bitacora(sid), datos)


def techo_para(nivel: int, cfg: dict = None) -> int:
    cfg = cfg or config()
    tabla = [int(x) for x in (cfg.get("techo_por_nivel") or [3, 5]) if int(x) > 0] or [3]
    tope = max(1, int(cfg.get("tope_peones") or 5))
    if nivel <= 0:
        return 0
    return min(tabla[min(nivel, len(tabla)) - 1], tope)


def _limpiar_peones(bit: dict, ahora: float, cfg: dict) -> None:
    vence = float(cfg.get("peon_vencido_minutos") or 45) * 60
    bit["peones"] = {
        k: v for k, v in bit["peones"].items()
        if isinstance(v, dict) and ahora - float(v.get("desde", 0)) < vence
    }


def registrar_latigazo(sid: str, origen: str, prompt_id: str = None, ahora: float = None) -> dict:
    """Cuenta un latigazo y decide si es efectivo.

    Efectivo = sube el nivel y fija el techo de peones. No es efectivo (solo suena) si
    hay peones trabajando o si cae dentro del enfriamiento. Devuelve el resultado.
    """
    cfg = config()
    ahora = time.time() if ahora is None else ahora
    with _candado(sid):
        bit = leer_bitacora(sid)
        _limpiar_peones(bit, ahora, cfg)
        if prompt_id and bit.get("ultimo_prompt_id") == prompt_id and bit.get("ultimo_resultado"):
            # UserPromptSubmit y UserPromptExpansion disparan para el mismo /latigo.
            res = dict(bit["ultimo_resultado"])
            res["duplicado"] = True
            return res
        if not prompt_id and origen == "comando" and ahora - float(bit.get("ultimo_terminal") or 0) < 3:
            # Sin prompt_id (no debería pasar desde 2.1.196): el gemelo llega en milisegundos.
            res = dict(bit.get("ultimo_resultado") or {})
            res["duplicado"] = True
            return res
        bit["latigazos"] = int(bit.get("latigazos") or 0) + 1
        bit["latigazos_total"] = int(bit.get("latigazos_total") or 0) + 1
        activos = len(bit["peones"])
        enfriamiento = float(cfg.get("enfriamiento_segundos") or 0)
        transcurrido = ahora - float(bit.get("ultimo_efectivo") or 0)
        res = {
            "sesion": sid,
            "origen": origen,
            "ts": ahora,
            "efectivo": False,
            "motivo": "",
            "nivel": int(bit.get("nivel") or 0),
            "techo": techo_para(int(bit.get("nivel") or 0), cfg),
            "peones_activos": activos,
            "restante": 0,
            "latigazos": bit["latigazos"],
        }
        if activos > 0:
            res["motivo"] = "peones_trabajando"
        elif transcurrido < enfriamiento:
            res["motivo"] = "enfriamiento"
            res["restante"] = int(round(enfriamiento - transcurrido + 0.49))
        else:
            bit["efectivo_previo"] = float(bit.get("ultimo_efectivo") or 0)
            bit["nivel"] = int(bit.get("nivel") or 0) + 1
            bit["ultimo_efectivo"] = ahora
            bit["pendiente_skill"] = ahora
            res.update(efectivo=True, nivel=bit["nivel"], techo=techo_para(bit["nivel"], cfg))
        bit["ultimo_prompt_id"] = prompt_id
        bit["ultimo_resultado"] = res
        if origen in ("comando", "mensaje"):
            bit["ultimo_terminal"] = ahora
        bit["historial"].append({k: res[k] for k in ("ts", "origen", "efectivo", "motivo", "nivel", "techo")})
        _guardar_bitacora(sid, bit)
        return res


def anotar_entrega(sid: str, prompt_id: str, res: dict) -> None:
    """Un mensaje o /latigo entregó un latigazo de la oficina que estaba pendiente: el evento
    gemelo del mismo prompt (UserPromptExpansion) no debe contar uno nuevo."""
    with _candado(sid):
        bit = leer_bitacora(sid)
        bit["ultimo_prompt_id"] = prompt_id
        bit["ultimo_resultado"] = dict(res or {}, entregado=True)
        bit["ultimo_terminal"] = time.time()
        _guardar_bitacora(sid, bit)


def revertir_latigazo(sid: str, res: dict) -> bool:
    """Deshace un latigazo efectivo que nunca le llegó a Claude (su aviso venció o se descartó).

    Solo si sigue siendo el último: si después hubo otro latigazo o terminó la tarea, no toca nada.
    """
    if not isinstance(res, dict) or not res.get("efectivo"):
        return False
    with _candado(sid):
        bit = leer_bitacora(sid)
        try:
            mismo = (int(bit.get("nivel") or 0) == int(res.get("nivel") or -1)
                     and abs(float(bit.get("ultimo_efectivo") or 0) - float(res.get("ts") or -1)) < 1e-3)
        except (TypeError, ValueError):
            mismo = False
        if not mismo:
            return False
        bit["nivel"] = max(0, int(bit["nivel"]) - 1)
        bit["ultimo_efectivo"] = float(bit.get("efectivo_previo") or 0)
        bit["pendiente_skill"] = 0.0
        bit["ultimo_resultado"] = None
        bit["historial"].append({"ts": time.time(), "origen": res.get("origen"), "efectivo": False,
                                 "motivo": "no_llego", "nivel": bit["nivel"], "techo": techo_para(bit["nivel"])})
        _guardar_bitacora(sid, bit)
        return True


def tomar_pendiente_skill(sid: str, ventana: float = 600.0) -> bool:
    """True si ya hubo un latigazo efectivo anunciado que la skill todavía no consumió."""
    with _candado(sid):
        bit = leer_bitacora(sid)
        marca = float(bit.get("pendiente_skill") or 0)
        if marca and time.time() - marca < ventana:
            bit["pendiente_skill"] = 0.0
            _guardar_bitacora(sid, bit)
            return True
        return False


def peon_inicio(sid: str, agent_id: str, tipo: str, ahora: float = None) -> None:
    ahora = time.time() if ahora is None else ahora
    with _candado(sid):
        bit = leer_bitacora(sid)
        bit["peones"][str(agent_id)] = {"tipo": tipo, "desde": ahora}
        _guardar_bitacora(sid, bit)


def peon_fin(sid: str, agent_id: str) -> None:
    with _candado(sid):
        bit = leer_bitacora(sid)
        if bit["peones"].pop(str(agent_id), None) is not None:
            _guardar_bitacora(sid, bit)


def fin_de_tarea(sid: str, quedan_subagentes: bool) -> bool:
    """Al terminar el turno sin subagentes en vuelo, el nivel vuelve a 0.

    Si Claude Code dice que no queda ningún subagente corriendo, los peones que
    sigan anotados son restos de un SubagentStop perdido y se limpian.
    Devuelve True si reinició el nivel.
    """
    if quedan_subagentes:
        return False
    with _candado(sid):
        bit = leer_bitacora(sid)
        cambio = bool(bit["peones"]) or int(bit.get("nivel") or 0) != 0 or int(bit.get("latigazos") or 0) != 0
        bit["peones"] = {}
        bit["nivel"] = 0
        bit["latigazos"] = 0
        bit["pendiente_skill"] = 0.0
        if cambio:
            _guardar_bitacora(sid, bit)
        return cambio


def reiniciar_sesion(sid: str) -> None:
    with _candado(sid):
        _guardar_bitacora(sid, _bitacora_vacia(sid))


# ---------------------------------------------------------------------------
# Inyección pendiente (latigazo dado desde la oficina)
# ---------------------------------------------------------------------------

def _ruta_inyeccion(sid: str) -> str:
    return os.path.join(dir_latigos(), id_seguro(sid) + ".inyeccion")


def hay_inyeccion(sid: str) -> bool:
    return os.path.exists(_ruta_inyeccion(sid))


def poner_inyeccion(sid: str, texto: str, datos: dict = None) -> None:
    cfg = config()
    ahora = time.time()
    payload = {
        "texto": texto,
        "creado": ahora,
        "expira": ahora + float(cfg.get("inyeccion_expira_segundos") or 300),
        "datos": datos or {},
    }
    escribir_json(_ruta_inyeccion(sid), payload)


def _reclamar(p: str):
    """Mueve el archivo a un nombre propio y devuelve ese nombre, o None si otro lo reclamó antes.

    En Windows el rename falla con PermissionError mientras otro proceso lo tiene abierto (la
    oficina lo lee cada segundo), así que se reintenta un momento antes de rendirse.
    """
    tomada = "%s.tomada.%d" % (p, os.getpid())
    for intento in range(20):
        try:
            os.replace(p, tomada)
            return tomada
        except FileNotFoundError:
            return None  # otro hook la reclamó primero
        except PermissionError:
            time.sleep(0.01 * (intento + 1))
        except OSError:
            return None
    return None


def _leer_y_borrar(tomada: str):
    datos = leer_json(tomada, None)
    try:
        os.remove(tomada)
    except OSError:
        pass
    return datos if isinstance(datos, dict) else None


def tomar_inyeccion(sid: str):
    """Reclama la inyección pendiente (una sola vez aunque haya hooks en paralelo)."""
    p = _ruta_inyeccion(sid)
    if not os.path.exists(p):
        return None
    tomada = _reclamar(p)
    if not tomada:
        return None
    datos = _leer_y_borrar(tomada)
    if not datos or not datos.get("texto"):
        return None
    if time.time() > float(datos.get("expira") or 0):
        revertir_latigazo(sid, datos.get("datos"))
        return None
    return datos


def descartar_inyeccion(sid: str, mas_vieja_que: float = 0.0) -> bool:
    """Tira el latigazo pendiente que no alcanzó a entregarse y deshace lo que contó."""
    p = _ruta_inyeccion(sid)
    datos = leer_json(p, None)
    if datos is None:
        return False
    if isinstance(datos, dict) and time.time() - float(datos.get("creado") or 0) < mas_vieja_que:
        return False
    tomada = _reclamar(p)
    if not tomada:
        return False
    datos = _leer_y_borrar(tomada)
    if datos:
        revertir_latigazo(sid, datos.get("datos"))
    return True


def leer_inyeccion(sid: str):
    datos = leer_json(_ruta_inyeccion(sid), None)
    return datos if isinstance(datos, dict) else None


# ---------------------------------------------------------------------------
# Textos que ve Claude (redactados como hechos, no como órdenes de sistema)
# ---------------------------------------------------------------------------

_ORIGEN = {
    "oficina": "desde la oficina",
    "mensaje": "con un mensaje",
    "comando": "con /latigo",
    "skill": "y se cargó la skill latigo",
}


def texto_latigazo(res: dict) -> str:
    hora = time.strftime("%H:%M", time.localtime(float(res.get("ts") or time.time())))
    origen = _ORIGEN.get(res.get("origen"), "")
    if res.get("efectivo"):
        return (
            "Aviso del látigo (hook que el usuario configuró en Claude Code): el usuario azotó el látigo "
            "%s a las %s para que esta tarea avance más rápido. Es el latigazo efectivo #%d de esta tarea; "
            "el techo de peones es %d y ahora mismo no hay peones trabajando. Lo que el usuario espera con un "
            "latigazo está en la skill `latigo`: cargarla con la herramienta Skill y seguirla antes de continuar."
            % (origen, hora, int(res.get("nivel") or 1), int(res.get("techo") or 3))
        )
    if res.get("motivo") == "peones_trabajando":
        n = int(res.get("peones_activos") or 0)
        return (
            "Aviso del látigo: el usuario azotó el látigo %s, pero hay %d peón%s trabajando. Según las "
            "reglas del usuario, este latigazo no cuenta y no se lanzan peones nuevos mientras ellos "
            "terminan." % (origen, n, "" if n == 1 else "es")
        )
    return (
        "Aviso del látigo: el usuario volvió a azotar el látigo %s, pero cae dentro del enfriamiento "
        "(faltan %d s). Según las reglas del usuario, este latigazo no cuenta: el techo sigue en %d "
        "peones y no se lanzan peones nuevos." % (origen, int(res.get("restante") or 0), int(res.get("techo") or 0))
    )


def motivo_corto(res: dict) -> str:
    """Texto corto para la oficina."""
    if res.get("efectivo"):
        return "¡Latigazo #%d! Techo: %d peones" % (res.get("nivel"), res.get("techo"))
    if res.get("motivo") == "peones_trabajando":
        return "Ya hay %d peones chambeando" % res.get("peones_activos")
    if res.get("motivo") == "enfriamiento":
        return "Calma: faltan %d s" % res.get("restante")
    if res.get("motivo") == "capataz_esperando":
        return "El capataz te está esperando"
    if res.get("motivo") == "sin_obra":
        return "¡Chas! No hay obra abierta"
    if res.get("motivo") == "en_camino":
        return "Ya va un latigazo en camino"
    return "Solo sonó"


# ---------------------------------------------------------------------------
# Ficha del proyecto (.claude/latigo.md)
# ---------------------------------------------------------------------------

def _raiz_git(d: str):
    """La carpeta con .git más cercana hacia arriba (sin pasar de la carpeta personal)."""
    casa = os.path.abspath(os.path.expanduser("~"))
    for _ in range(40):
        if os.path.exists(os.path.join(d, ".git")):
            return d
        padre = os.path.dirname(d)
        if padre == d or d == casa:
            return None
        d = padre
    return None


def _checkout_principal(d: str):
    """Si d está dentro del worktree de un peón (<raíz>/.claude/worktrees/<x>), devuelve <raíz>."""
    partes = d.replace("\\", "/").split("/")
    for i in range(len(partes) - 2):
        if partes[i] == ".claude" and partes[i + 1] == "worktrees" and i > 0:
            return os.sep.join(partes[:i]) or os.sep
    return None


def buscar_ficha(cwd: str):
    """Busca .claude/latigo.md desde cwd hasta la raíz de su repo, nunca más arriba.

    Fuera de un repo solo mira cwd. Dentro del worktree de un peón, si la ficha no está
    commiteada, la toma del checkout principal (de ahí salió el worktree).
    """
    if not cwd:
        return None, None
    d = os.path.abspath(cwd)
    raiz = _raiz_git(d)
    candidatos = []
    actual = d
    while True:
        candidatos.append(os.path.join(actual, ".claude", "latigo.md"))
        if raiz is None or actual == raiz:
            break
        padre = os.path.dirname(actual)
        if padre == actual:
            break
        actual = padre
    principal = _checkout_principal(d)
    if principal:
        candidatos.append(os.path.join(principal, ".claude", "latigo.md"))
    for p in candidatos:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    return p, f.read()
            except OSError:
                return None, None
    return None, None


# ---------------------------------------------------------------------------
# Servidor de la oficina: latido, puerto, telemetría UDP, arranque
# ---------------------------------------------------------------------------

def info_servidor() -> dict:
    datos = leer_json(os.path.join(dir_estado(), "servidor.json"), {})
    return datos if isinstance(datos, dict) else {}


def servidor_vivo(max_edad: float = 6.0) -> bool:
    info = info_servidor()
    try:
        return time.time() - float(info.get("latido") or 0) < max_edad
    except (TypeError, ValueError):
        return False


def puerto_servidor():
    try:
        with open(os.path.join(dir_estado(), "puerto"), "r", encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _leer_token(p: str) -> str:
    try:
        with open(p, "r", encoding="ascii") as f:
            t = f.read().strip()
        return t if len(t) >= 32 and all(c in "0123456789abcdef" for c in t) else ""
    except (OSError, ValueError):
        return ""


def token_oficina() -> str:
    """Token de la oficina: se crea una vez (estado/token, 0600) y sobrevive a los reinicios.

    Así una caseta abierta sigue funcionando cuando la oficina se reinicia. Nunca viaja en
    una línea de comandos: la página lo obtiene canjeando un boleto de un solo uso.
    """
    p = os.path.join(dir_estado(), "token")
    t = _leer_token(p)
    if t:
        return t
    import secrets

    nuevo = secrets.token_hex(16)
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        # Otro proceso lo está creando en este instante, o quedó vacío/roto.
        for _ in range(40):
            t = _leer_token(p)
            if t:
                return t
            time.sleep(0.01)
        try:
            if time.time() - os.path.getmtime(p) < 5:
                return ""
        except OSError:
            pass
        tmp = "%s.%d" % (p, os.getpid())
        try:
            fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(nuevo)
            reemplazar(tmp, p)
            return nuevo
        except OSError:
            return ""
    except OSError:
        return ""
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(nuevo)
    return nuevo


def enviar_telemetria(evento: dict) -> bool:
    puerto = puerto_servidor()
    if not puerto:
        return False
    try:
        import socket

        datos = json.dumps(evento, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(datos) > 60000:
            return False
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.sendto(datos, ("127.0.0.1", puerto))
        finally:
            s.close()
        return True
    except OSError:
        return False


def interprete(sin_consola: bool = False) -> str:
    exe = sys.executable or "python3"
    if sin_consola and os.name == "nt":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(w):
            return w
    return exe


def lanzar_desacoplado(args: list, cwd: str = None) -> bool:
    """Lanza un proceso que sobrevive al hook que lo creó."""
    import subprocess

    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              cwd=cwd or dir_base(), close_fds=True)
    if os.name == "nt":
        base = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        for flags in (base | 0x01000000, base):  # + CREATE_BREAKAWAY_FROM_JOB si se puede
            try:
                subprocess.Popen(args, creationflags=flags, **kw)
                return True
            except OSError:
                continue
        return False
    try:
        subprocess.Popen(args, start_new_session=True, **kw)
        return True
    except OSError:
        return False


def ruta_arranque() -> str:
    return os.path.join(dir_estado(), "arranque.lock")


def _esperar_vivo(segundos: float) -> bool:
    limite = time.time() + segundos
    while time.time() < limite:
        if servidor_vivo():
            return True
        time.sleep(0.05)
    return servidor_vivo()


def arrancar_servidor(esperar: float = 2.0) -> bool:
    """Arranca la oficina si no corre. Cinco hooks a la vez lanzan un solo proceso.

    El candado de arranque se toma con O_EXCL y lo suelta la oficina cuando ya escribió su
    latido (o vence a los 15 s si no arrancó), no este proceso: así nadie lanza otra mientras
    la primera todavía está cargando.
    """
    if servidor_vivo():
        return True
    lock = ruta_arranque()
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            vencido = time.time() - os.path.getmtime(lock) > 15
        except OSError:
            vencido = False
        if not vencido:
            return _esperar_vivo(esperar)  # otro proceso la está arrancando
        try:
            os.remove(lock)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return _esperar_vivo(esperar)
    except OSError:
        return False
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)
    ok = lanzar_desacoplado([interprete(sin_consola=True), os.path.join(DIR_CODIGO, "servidor.py")])
    if not ok:
        try:
            os.remove(lock)
        except OSError:
            pass
        return False
    return _esperar_vivo(esperar)


# ---------------------------------------------------------------------------
# Sonidos: sintetizados aquí mismo (sin archivos de terceros ni licencias)
# ---------------------------------------------------------------------------

TASA = 44100  # el chasquido del látigo tiene mucho agudo: a 22 kHz suena apagado
SONIDOS = ("latigazo", "peon_listo", "permiso", "listo", "error")


LATIGAZO = {
    "zumbido_seg": 0.22, "zumbido": 0.35,             # silbido corto del látigo acercándose
    "chas_hz": 1500, "chas": 9.0, "chas_ms": 9,       # "¡chas!" de cuero contra piel
    "punta": 0.5,                                     # chispazo de la punta
    "carne": 0.9, "carne_ms": 35,                     # golpe sordo de la carne
    "cuero": 0.6,                                     # el cuero vibrando después
    "cuarto": 1.0,                                    # rebotes de un cuarto chico
}


def _latigazo(rnd, p=None) -> list:
    """Latigazo contra una persona (no el chasquido en el aire): silbido corto, "¡chas!" seco
    de cuero contra piel que se apaga en milisegundos (la piel absorbe), golpe sordo de carne,
    el cuero vibrando y un cuarto chico. Todo sintetizado aquí: no se copia ningún sonido.
    Se ajusta con los valores de LATIGAZO.
    """
    import math

    p = dict(LATIGAZO, **(p or {}))
    T = TASA

    def n(seg):
        return int(seg * T)

    out = []
    dur = n(p["zumbido_seg"])
    y1 = y2 = 0.0
    for i in range(dur):
        x = i / dur
        f = 400 + 2600 * x ** 2
        r = 0.97 - 0.03 * x
        w = 2 * math.pi * f / T
        y = (rnd.random() * 2 - 1) * (1 - r) + 2 * r * math.cos(w) * y1 - r * r * y2
        y2, y1 = y1, y
        out.append(y * p["zumbido"] * x ** 3)
    imp = n(0.35)
    lp = bp1 = bp2 = 0.0
    fase = 0.0
    rr = 0.93
    wc = 2 * math.pi * p["chas_hz"] / T
    for i in range(imp):
        t = i / T
        ruido = rnd.random() * 2 - 1
        b = ruido * (1 - rr) + 2 * rr * math.cos(wc) * bp1 - rr * rr * bp2
        bp2, bp1 = bp1, b
        chas = b * p["chas"] * math.exp(-t / (p["chas_ms"] / 1000)) * min(1, t / 0.0004)
        punta = ruido * p["punta"] * math.exp(-t / 0.0015)
        f = 90 + 110 * math.exp(-t / 0.012)
        fase += 2 * math.pi * f / T
        carne = math.sin(fase) * p["carne"] * math.exp(-t / (p["carne_ms"] / 1000)) * min(1, t / 0.001)
        lp += 0.3 * (ruido - lp)
        cuero = lp * p["cuero"] * math.exp(-t / 0.03) * (1 if t > 0.004 else 0)
        out.append(chas + punta + carne + cuero)
    out.extend([0.0] * n(0.3))
    rev = [0.0] * len(out)
    for ms, g in ((11, 0.25), (17, 0.18), (29, 0.12), (41, 0.08), (63, 0.05)):
        k = n(ms / 1000)
        for i in range(k, len(out)):
            rev[i] += out[i - k] * g
    m = [a + b * p["cuarto"] for a, b in zip(out, rev)]
    pk = max(abs(v) for v in m) or 1.0
    m = [math.tanh(v / pk * 1.2) / math.tanh(1.2) for v in m]  # saturación ligera, sin aplanar
    c = n(0.08)
    for i in range(c):
        m[-c + i] *= 1 - i / c
    return m


def _sintetizar(nombre: str) -> list:
    import math
    import random

    rnd = random.Random(7 + SONIDOS.index(nombre) if nombre in SONIDOS else 7)
    m = []

    def n(seg):
        return int(seg * TASA)

    if nombre == "latigazo":
        m = _latigazo(rnd)
    elif nombre == "peon_listo":
        for f, d in ((1318.5, 0.07), (1760.0, 0.20)):
            k = n(d)
            for i in range(k):
                t = i / TASA
                env = min(1.0, i / 40) * math.exp(-t / (d * 0.45))
                v = 0.5 * math.sin(2 * math.pi * f * t) + 0.18 * math.sin(2 * math.pi * 2 * f * t)
                m.append(v * env * 0.75)
    elif nombre == "permiso":
        for rep in range(2):
            k = n(0.10)
            for i in range(k):
                t = i / TASA
                env = min(1.0, i / 120) * min(1.0, (k - i) / 300)
                m.append(math.sin(2 * math.pi * 784 * t) * env * 0.45)
            m.extend([0.0] * n(0.07))
    elif nombre == "listo":
        notas = (523.25, 659.25, 783.99, 1046.5)
        for j, f in enumerate(notas):
            d = 0.085 if j < len(notas) - 1 else 0.32
            k = n(d)
            for i in range(k):
                t = i / TASA
                fase = (f * t) % 1.0
                tri = 4 * abs(fase - 0.5) - 1  # onda triangular, suave
                env = min(1.0, i / 60) * math.exp(-t / (d * 0.7))
                m.append(tri * env * 0.42)
    elif nombre == "error":
        k = n(0.32)
        for i in range(k):
            t = i / TASA
            f = 196 - 60 * (i / k)
            cuadrada = 1.0 if math.sin(2 * math.pi * f * t) >= 0 else -1.0
            m.append(cuadrada * math.exp(-t / 0.12) * 0.28)
    else:
        m = [0.0] * n(0.05)
    return m


def _escribir_wav(path: str, muestras: list, volumen: float) -> None:
    import struct
    import wave

    pico = max(1e-6, max(abs(v) for v in muestras))
    escala = 32767 * max(0.0, min(1.0, volumen)) / pico * 0.95
    datos = struct.pack("<%dh" % len(muestras), *(int(max(-32767, min(32767, v * escala))) for v in muestras))
    tmp = path + ".tmp"
    w = wave.open(tmp, "wb")
    try:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TASA)
        w.writeframes(datos)
    finally:
        w.close()
    os.replace(tmp, path)


def generar_sonidos(volumen: float = None) -> list:
    volumen = config().get("volumen", 0.7) if volumen is None else volumen
    d = ruta("sonidos")
    os.makedirs(d, exist_ok=True)
    hechos = []
    for nombre in SONIDOS:
        p = os.path.join(d, nombre + ".wav")
        _escribir_wav(p, _sintetizar(nombre), float(volumen))
        hechos.append(p)
    escribir_json(os.path.join(d, "volumen.json"), {"volumen": float(volumen)})
    return hechos


def ruta_sonido(nombre: str):
    if nombre not in SONIDOS:
        return None
    p = ruta("sonidos", nombre + ".wav")
    vol = leer_json(ruta("sonidos", "volumen.json"), {}) or {}
    if not os.path.exists(p) or abs(float(vol.get("volumen", -1)) - float(config().get("volumen", 0.7))) > 1e-6:
        try:
            generar_sonidos()
        except Exception as e:  # pragma: no cover - disco lleno, permisos...
            log_error("generar_sonidos", e)
            return None
    return p if os.path.exists(p) else None


def sonido_activo(nombre: str) -> bool:
    cfg = config(recargar=True)
    return not cfg.get("silencio") and bool((cfg.get("sonidos") or {}).get(nombre, False))


def reproducir(nombre: str, desde_hook: bool = False, forzar: bool = False) -> bool:
    """Toca un sonido sin bloquear. desde_hook=True usa un proceso aparte (el hook muere pronto)."""
    if not forzar and not sonido_activo(nombre):
        return False
    p = ruta_sonido(nombre)
    if not p:
        return False
    try:
        if sys.platform == "darwin":
            return lanzar_desacoplado(["afplay", p])
        if os.name == "nt":
            if desde_hook:
                codigo = "import sys,winsound;winsound.PlaySound(sys.argv[1],winsound.SND_FILENAME)"
                return lanzar_desacoplado([interprete(sin_consola=True), "-c", codigo, p])
            import winsound

            winsound.PlaySound(p, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        import shutil

        for cmd in (["paplay", p], ["aplay", "-q", p], ["pw-play", p]):
            if shutil.which(cmd[0]):
                return lanzar_desacoplado(cmd)
    except Exception as e:
        log_error("reproducir", e)
    return False
