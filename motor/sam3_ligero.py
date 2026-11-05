"""P.3.5: SAM 3 interactivo SIN image encoder para el hub (el clic usa la cache que precodifica el worker).
- extraer: una vez, construye el modelo sin backbone desde sam3.pt (82 s, pico 3.7 GB) y guarda su state_dict
  (~12 M parametros) en motor/cache_sam3/sam3_interactivo_<sha12>.pt con el sha de sam3.pt y la version.
- Liviano: SAM3Predictor cuyo get_model construye la arquitectura sin pesos y carga ese state_dict (strict=True).
  Si el checkpoint ligero aun no existe, se construye desde sam3.pt (mas lento, mismo resultado).
Uso (en el contenedor): python /app/sam3_ligero.py [--aplicar]   (sin --aplicar solo reporta)"""
import argparse, os, sys, threading, time
from importlib.metadata import version
from pathlib import Path

import cache_sam3 as CS
from config import CACHE_SAM3, SAM3_MODEL

ESQUEMA = 1
_parche = threading.Lock()


def ruta(sha_sam3, carpeta=CACHE_SAM3):
    return Path(carpeta) / f"sam3_interactivo_{sha_sam3[:12]}.pt"


def _sin_pesos():
    """Arquitectura del interactivo sin backbone y SIN leer sam3.pt (build_interactive_sam3 siempre carga un
    checkpoint: se desactiva un momento)."""
    import ultralytics.models.sam.build_sam3 as B
    with _parche:
        orig = B._load_checkpoint
        B._load_checkpoint = lambda model, checkpoint, interactive=False: model
        try:
            return B.build_interactive_sam3("", with_backbone=False)
        finally:
            B._load_checkpoint = orig


def construir(sam3_pt=SAM3_MODEL, carpeta=CACHE_SAM3):
    """-> (modelo sin backbone en eval, origen). Usa el checkpoint ligero si coincide con sam3.pt; si no, sam3.pt."""
    import torch
    sha = CS.sha_memorizado(sam3_pt, Path(carpeta) / "modelo.json")
    f = ruta(sha, carpeta) if sha else None
    if f is not None and f.is_file():
        p = torch.load(f, map_location="cpu", weights_only=True)
        if p.get("esquema") == ESQUEMA and p.get("sha_sam3") == sha:
            m = _sin_pesos()
            m.load_state_dict(p["state_dict"], strict=True)
            return m.eval(), f"ligero {f.name}"
    from ultralytics.models.sam.build_sam3 import build_interactive_sam3
    return build_interactive_sam3(str(sam3_pt), with_backbone=False), "sam3.pt completo (sin checkpoint ligero)"


def predictor_liviano():
    from ultralytics.models.sam import SAM3Predictor

    class Liviano(SAM3Predictor):
        """El clic solo usa prompt encoder + mask decoder; las features vienen de la cache de disco."""
        origen = None

        def get_model(self):
            m, Liviano.origen = construir()
            return m
    return Liviano


def extraer(sam3_pt=SAM3_MODEL, carpeta=CACHE_SAM3):
    import torch
    from ultralytics.models.sam.build_sam3 import build_interactive_sam3
    sha = CS.sha_modelo(sam3_pt, Path(carpeta) / "modelo.json")
    t = time.time()
    m = build_interactive_sam3(str(sam3_pt), with_backbone=False)
    sd = {k: v.detach().cpu() for k, v in m.state_dict().items()}
    f = ruta(sha, carpeta)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    torch.save({"esquema": ESQUEMA, "sha_sam3": sha, "ultralytics": version("ultralytics"), "state_dict": sd}, tmp)
    os.replace(tmp, f)
    return f, time.time() - t, sum(v.numel() for v in sd.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    sha = CS.sha_memorizado(SAM3_MODEL, CACHE_SAM3 / "modelo.json")
    f = ruta(sha) if sha else None
    print(f"sam3.pt {SAM3_MODEL} | sha {sha[:12] if sha else '(sin calcular: ~50 s al aplicar)'}")
    print(f"checkpoint ligero {f or CACHE_SAM3 / 'sam3_interactivo_<sha12>.pt'}: "
          f"{'YA EXISTE (' + format(f.stat().st_size / 1e6, '.0f') + ' MB)' if f and f.is_file() else 'no existe'}")
    if not a.aplicar:
        print("SOLO REPORTE: --aplicar lo extrae (lee sam3.pt una vez: ~1.5 min y ~3.7 GB de RAM en la laptop)")
        return
    f, seg, n = extraer()
    print(f"extraido en {seg:.0f} s: {n / 1e6:.1f} M parametros, {f.stat().st_size / 1e6:.0f} MB -> {f}")
    t = time.time()
    m, origen = construir()
    print(f"verificado: carga desde {origen} en {time.time() - t:.1f} s (strict=True)")


if __name__ == "__main__":
    sys.exit(main())
