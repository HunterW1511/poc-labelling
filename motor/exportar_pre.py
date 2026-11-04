"""P.3.3: exporta un trabajo de PRECODIFICACION (fotos de un proyecto sin cache de SAM 3 en el hub) para el worker.
Uso (en el contenedor): python /app/exportar_pre.py <proyecto> [--todas] [--limite N] [--reporte]
Genera /app/lotes/pre_p<id>_<fecha>.zip con fotos/, fotos.json (tarea, foto, sha256), trabajo.json (imgsz, sha de
sam3.pt y version de ultralytics: el worker las comprueba) y codigo/ (worker.py, cache_sam3.py)."""
import argparse, datetime, json, zipfile
from importlib.metadata import version
from pathlib import Path

import requests

import cache_sam3 as CS
from cola import HEADERS, LS_URL, get_local_path
from config import CACHE_SAM3, LOTES, SAM3_MODEL
from perfil import leer_perfil
from worker import encabezado

APP = Path(__file__).resolve().parent
CODIGO = ["worker.py", "cache_sam3.py"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proyecto", type=int)
    ap.add_argument("--todas", action="store_true", help="incluir fotos que ya tienen cache")
    ap.add_argument("--limite", type=int, default=0, help="maximo de fotos (0 = sin limite)")
    ap.add_argument("--reporte", action="store_true", help="no crear el zip; solo contar")
    a = ap.parse_args()

    r = requests.get(f"{LS_URL}/api/projects/{a.proyecto}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    perfil = leer_perfil(r.json()["label_config"])
    imgsz, campo = int(perfil["imgsz"]), perfil["campo_imagen"]
    sha_m = CS.sha_modelo(SAM3_MODEL, CACHE_SAM3 / "modelo.json")
    ver = version("ultralytics")
    r = requests.get(f"{LS_URL}/api/projects/{a.proyecto}/export", headers=HEADERS, timeout=600,
                     params={"exportType": "JSON", "download_all_tasks": "true"})
    r.raise_for_status()
    faltan, ya = [], 0
    for t in r.json():
        ruta = Path(get_local_path(t["data"][campo], task_id=t["id"]))
        sha = CS.sha256_archivo(ruta)
        if not a.todas and CS.archivo(CACHE_SAM3, CS.clave(sha, imgsz, sha_m, ver)).is_file():
            ya += 1
            continue
        faltan.append((t["id"], ruta, sha))
    if a.limite:
        faltan = faltan[:a.limite]
    print(f"Proyecto {a.proyecto} | imgsz {imgsz} | sam3 {sha_m[:12]} | ultralytics {ver} | "
          f"con cache {ya} | a precodificar {len(faltan)}")
    if not faltan:
        raise SystemExit(f"Todas las fotos del proyecto {a.proyecto} ya tienen cache (usa --todas para rehacerla)")
    if a.reporte:
        print(f"REPORTE {len(faltan)} fotos | ids {','.join(str(i) for i, _, _ in faltan[:50])}"
              + (" ..." if len(faltan) > 50 else ""))
        return
    LOTES.mkdir(exist_ok=True)
    zp = LOTES / f"pre_p{a.proyecto}_{datetime.datetime.now():%Y%m%d-%H%M%S}.zip"
    fotos = []
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:      # las fotos ya vienen comprimidas
        for i, (tid, ruta, sha) in enumerate(faltan, 1):
            nombre = f"fotos/{tid}_{ruta.name}"
            z.write(ruta, nombre)
            fotos.append({"tarea": tid, "foto": nombre, "sha": sha})
            if i % 50 == 0:
                print(f"  [{i}/{len(faltan)}]")
        for c in CODIGO:
            z.write(APP / c, f"codigo/{c}")
        z.writestr("fotos.json", json.dumps({"esquema": 1, "fotos": fotos}, ensure_ascii=True, indent=1))
        par = {"imgsz": imgsz, "sha_modelo": sha_m, "ultralytics": ver}
        z.writestr("trabajo.json", json.dumps(encabezado("precodificacion", zp.stem, proyecto=a.proyecto,
                                                         parametros=par), ensure_ascii=True, indent=1))
    print(f"OK {len(fotos)} fotos | {zp.stat().st_size / 1e6:.1f} MB -> {zp}")


if __name__ == "__main__":
    main()
