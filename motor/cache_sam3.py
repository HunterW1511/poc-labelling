"""P.3: cache de codificaciones de SAM 3 (features del image encoder) para el clic del hub. Diseno: docs/cache_sam3.md.
Lo usan el worker (precodificar en GPU), el exportador (que fotos faltan) y el motor (clic, P.3.4). VIAJA en los zips.
Clave = sha256 de la foto + imgsz + sha256 de sam3.pt (12) + version de ultralytics: otra foto, otros pesos u otra
version = otra clave (nunca se usa una cache equivocada). Archivo: torch.save de un dict con tensores f16 en CPU;
se carga con weights_only=True (un archivo manipulado no ejecuta codigo) y se validan esquema, clave y formas.
torch solo se importa al guardar o cargar."""
import hashlib, json, os, re
from pathlib import Path

ESQUEMA = 1
CLAVE = re.compile(r"^[0-9a-f]{64}_\d{2,5}_[0-9a-f]{12}_[0-9][0-9A-Za-z.+-]*$")


def sha256_archivo(ruta, bloque=8 << 20):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(bloque), b""):
            h.update(b)
    return h.hexdigest()


def clave(sha_foto, imgsz, sha_modelo, version_ul):
    c = f"{sha_foto}_{int(imgsz)}_{str(sha_modelo)[:12]}_{version_ul}"
    if not CLAVE.match(c):
        raise ValueError(f"clave invalida: {c!r}")
    return c


def archivo(carpeta, c):
    return Path(carpeta) / f"{c}.pt"


def _firma(ruta_pt):
    st = Path(ruta_pt).stat()
    return {"ruta": str(ruta_pt), "bytes": st.st_size, "mtime": int(st.st_mtime)}


def sha_memorizado(ruta_pt, memo):
    """sha de sam3.pt si el memo sigue valido (mismo tamano y mtime); None si hay que calcularlo. No calcula nada."""
    try:
        m = json.loads(Path(memo).read_text(encoding="utf-8"))
        return m["sha256"] if {k: m.get(k) for k in ("ruta", "bytes", "mtime")} == _firma(ruta_pt) else None
    except (OSError, ValueError, KeyError):
        return None


def sha_modelo(ruta_pt, memo=None):
    """sha256 de sam3.pt; con memo (json) no se recalcula mientras no cambien tamano y mtime (3.45 GB: ~50 s)."""
    if memo:
        sha = sha_memorizado(ruta_pt, memo)
        if sha:
            return sha
    sha = sha256_archivo(ruta_pt)
    if memo:
        Path(memo).parent.mkdir(parents=True, exist_ok=True)
        Path(memo).write_text(json.dumps({**_firma(ruta_pt), "sha256": sha}, indent=1), encoding="utf-8")
    return sha


def formas(features):
    """{'image_embed': (..), 'high_res_feats': [(..), (..)]} -> lista de formas en orden (para validar)."""
    return [tuple(features["image_embed"].shape)] + [tuple(t.shape) for t in features["high_res_feats"]]


def empaquetar(features, c, imgsz):
    """features de SAM3Predictor.set_image -> dict serializable (f16, CPU, sin referencias al grafo)."""
    def h(t):
        return t.detach().to("cpu").half().contiguous()
    return {"esquema": ESQUEMA, "clave": c, "imgsz": int(imgsz), "dtype": "float16",
            "features": {"image_embed": h(features["image_embed"]),
                         "high_res_feats": [h(t) for t in features["high_res_feats"]]}}


def guardar(ruta, paquete):
    import torch
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    torch.save(paquete, tmp)
    os.replace(tmp, ruta)
    return ruta


def cargar(ruta, c, formas_esperadas=None, dtype=None, device="cpu", espacial=None):
    """-> features listas para p.features. ValueError si el archivo no corresponde (y entonces se codifica como siempre).
    formas_esperadas: formas completas; espacial: solo (alto, ancho) de [image_embed, high_res 0, high_res 1]."""
    import torch
    p = torch.load(ruta, map_location="cpu", weights_only=True)
    if not isinstance(p, dict) or p.get("esquema") != ESQUEMA:
        raise ValueError(f"{Path(ruta).name}: esquema {p.get('esquema') if isinstance(p, dict) else '?'} no soportado")
    if p.get("clave") != c:
        raise ValueError(f"{Path(ruta).name}: la clave interna no coincide")
    f = p["features"]
    if formas_esperadas is not None and formas(f) != [tuple(x) for x in formas_esperadas]:
        raise ValueError(f"{Path(ruta).name}: formas {formas(f)} distintas de las esperadas {formas_esperadas}")
    if espacial is not None and [x[-2:] for x in formas(f)] != [tuple(x) for x in espacial]:
        raise ValueError(f"{Path(ruta).name}: tamanos {[x[-2:] for x in formas(f)]} distintos de {espacial}")
    dt = dtype or torch.float32
    return {"image_embed": f["image_embed"].to(device=device, dtype=dt),
            "high_res_feats": [t.to(device=device, dtype=dt) for t in f["high_res_feats"]]}


def espacial_de(bb_feat_sizes):
    """SAM2Predictor._bb_feat_sizes (escalas 1/4, 1/2, 1) -> orden de formas(): [image_embed, high_res 0, high_res 1]."""
    b = [tuple(int(v) for v in x) for x in bb_feat_sizes]
    return [b[2], b[0], b[1]]


def buscar(carpeta, foto, imgsz, sha_m, version_ul, espacial=None, device="cpu"):
    """Cache de la foto local, si hay una que valga. -> (features o None, motivo). Nunca lanza: ante cualquier problema
    el clic codifica como siempre."""
    try:
        c = clave(sha256_archivo(foto), imgsz, sha_m, version_ul)
    except (OSError, ValueError) as e:
        return None, f"sin clave: {e}"
    f = archivo(carpeta, c)
    if not f.is_file():
        return None, "sin cache"
    try:
        return cargar(f, c, espacial=espacial, device=device), "disco"
    except Exception as e:                       # archivo danado, otra version de torch, formas: se codifica
        return None, f"cache no valida: {type(e).__name__}: {e}"


def hay(carpeta, foto, imgsz, sha_m, version_ul):
    """Hay archivo de cache para la foto (sin cargarlo)."""
    try:
        return archivo(carpeta, clave(sha256_archivo(foto), imgsz, sha_m, version_ul)).is_file()
    except (OSError, ValueError):
        return False
