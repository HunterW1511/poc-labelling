"""Configuracion UNICA del motor (A.1). Solo este modulo lee variables de entorno
(.env -> docker compose), con defaults seguros. Lo algoritmico generico se queda en el codigo."""
import os
from pathlib import Path

APP = Path(__file__).resolve().parent


def _req(k):
    v = (os.environ.get(k) or "").strip()
    if not v:
        raise RuntimeError(f"Falta la variable de entorno {k} (revisa .env y docker-compose.yml)")
    return v


def _int(k, d):
    return int(os.environ.get(k) or d)


# Label Studio
LS_URL = _req("LABEL_STUDIO_URL").rstrip("/")
LS_API_KEY = _req("LABEL_STUDIO_API_KEY")
HEADERS = {"Authorization": f"Token {LS_API_KEY}"}

# Modelos y datos (DATOS por defecto = carpeta del codigo, como hoy)
SAM3_MODEL = os.environ.get("SAM3_MODEL") or "/data/sam3.pt"
DATOS = Path(os.environ.get("MOTOR_DATOS") or APP)
LOTES, DATASETS, MODELOS = DATOS / "lotes", DATOS / "datasets", DATOS / "modelos"
CACHE_SAM3 = DATOS / "cache_sam3"                # P.3: features de SAM 3 precodificadas por el worker

# Computo: auto | cpu | 0 | cuda:0 ... (formato de select_device de Ultralytics)
DEVICE = (os.environ.get("MOTOR_DEVICE") or "auto").strip().lower()

# Modo interactivo (dependen de la RAM/CPU del equipo)
PREVIAS = _int("MOTOR_PREVIAS", 6)
# P.3.5: liviano = SAM 3 sin image encoder (carga ~1 s, ~0.4 GB) y el clic solo con la cache que precodifica el worker;
# completo = como antes de P.3 (carga 3-7 min, codifica en la CPU la foto que falte)
INTERACTIVO = (os.environ.get("MOTOR_INTERACTIVO") or "liviano").strip().lower()
if INTERACTIVO not in ("liviano", "completo"):
    raise SystemExit(f"MOTOR_INTERACTIVO={INTERACTIVO!r}: liviano o completo")
CACHE_MAX = _int("MOTOR_CACHE_MAX", 8)


def dispositivo():
    """auto -> '0' si hay CUDA, si no 'cpu'. Cualquier otro valor se respeta tal cual."""
    if DEVICE != "auto":
        return DEVICE
    import torch
    return "0" if torch.cuda.is_available() else "cpu"


def resumen():
    """Para logs y diagnostico: nunca incluye el token."""
    return {"LS_URL": LS_URL, "token": "***" + LS_API_KEY[-4:], "SAM3_MODEL": SAM3_MODEL,
            "sam3_existe": Path(SAM3_MODEL).exists(), "DATOS": str(DATOS), "DEVICE": DEVICE,
            "device_real": dispositivo(), "PREVIAS": PREVIAS, "CACHE_MAX": CACHE_MAX, "INTERACTIVO": INTERACTIVO}


if __name__ == "__main__":
    for k, v in resumen().items():
        print(f"{k:<11} {v}")
