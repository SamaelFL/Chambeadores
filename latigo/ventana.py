"""Abre la oficina en una ventana tipo app (sin barra de direcciones) si hay un navegador
basado en Chromium; si no, en el navegador por defecto."""
from __future__ import annotations

import os
import shutil
import sys

import nucleo

_MAC = {
    "chrome": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
    "edge": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
    "brave": ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
    "chromium": ["/Applications/Chromium.app/Contents/MacOS/Chromium"],
}


def _win():
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    return {
        "edge": [os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
                 os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe")],
        "chrome": [os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
                   os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
                   os.path.join(local, r"Google\Chrome\Application\chrome.exe")],
        "brave": [os.path.join(pf, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
                  os.path.join(local, r"BraveSoftware\Brave-Browser\Application\brave.exe")],
    }


_LINUX = {
    "chrome": ["google-chrome", "google-chrome-stable"],
    "chromium": ["chromium", "chromium-browser"],
    "edge": ["microsoft-edge"],
    "brave": ["brave-browser"],
}


def buscar_navegador(preferido: str = "auto"):
    if sys.platform == "darwin":
        tabla, orden = _MAC, ["chrome", "edge", "brave", "chromium"]
    elif os.name == "nt":
        tabla, orden = _win(), ["edge", "chrome", "brave"]
    else:
        tabla, orden = _LINUX, ["chrome", "chromium", "edge", "brave"]
    if preferido in tabla:
        orden = [preferido] + [o for o in orden if o != preferido]
    for clave in orden:
        for cand in tabla.get(clave, []):
            ruta = os.path.expanduser(cand)
            if os.path.isabs(ruta):
                if os.path.exists(ruta):
                    return ruta
            else:
                encontrado = shutil.which(ruta)
                if encontrado:
                    return encontrado
    return None


def abrir(url: str, ancho: int = 1200, alto: int = 780) -> str:
    preferido = str(nucleo.config().get("navegador") or "auto")
    exe = None if preferido == "sistema" else buscar_navegador(preferido)
    if exe:
        if nucleo.lanzar_desacoplado([exe, "--app=" + url, "--window-size=%d,%d" % (ancho, alto)]):
            return "app"
    import webbrowser

    webbrowser.open(url)
    return "navegador"
