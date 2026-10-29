"""Version unica del modelo: hash del perfil + hash del nucleo puro (reglas.py, pipeline.py).
La usan model.py, exportar_lote.py y (en D) el registro de modelos. No duplicar esta formula."""
import hashlib, json
from pathlib import Path

APP = Path(__file__).resolve().parent
NUCLEO = ("reglas.py", "pipeline.py")


def huella_perfil(perfil):
    return hashlib.sha1(json.dumps(perfil, sort_keys=True).encode()).hexdigest()[:8]


def huella_nucleo(carpeta=APP, archivos=NUCLEO):
    """CRLF -> LF para que Windows, Linux y Colab den el mismo hash."""
    h = hashlib.sha1()
    for n in archivos:
        h.update(n.encode())
        h.update((Path(carpeta) / n).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:4]


def version_modelo(perfil, prefijo="sam3", carpeta=APP, archivos=NUCLEO):
    return f"{prefijo}-{huella_perfil(perfil)}-{huella_nucleo(carpeta, archivos)}"


def version_hijo(perfil, modelo, carpeta=APP):
    """Pre-etiquetado con modelo hijo + SAM 3 por caja: el hash incluye hijo.py."""
    return version_modelo(perfil, f"hijo-{modelo}", carpeta, NUCLEO + ("hijo.py",))
