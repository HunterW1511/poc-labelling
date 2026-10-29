"""D.3: exporta las anotaciones (Submit) de un proyecto a YOLO para entrenar en Colab.
Uso (en el contenedor): python /app/exportar_yolo.py <proyecto> [--formato det|seg|ambos] [--val 0.2]
Poligonos = fuente de verdad; las cajas se derivan. Se ignoran los clics (keypointlabels) y los Skip."""
import argparse, datetime, hashlib, json, zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import requests

from cola import HEADERS, LS_URL, get_local_path
from config import DATASETS, DATOS
from perfil import leer_perfil

APP = Path(__file__).resolve().parent


def clases(label_config, from_name):
    for c in ET.fromstring(label_config).iter():
        if c.get("name") == from_name:
            return [l.get("value") for l in c.iter("Label")]
    raise SystemExit(f"No encontre el control {from_name} en el XML")


def split(tid, val):
    """Determinista: la misma tarea cae siempre en el mismo split."""
    return "val" if int(hashlib.md5(str(tid).encode()).hexdigest(), 16) % 1000 < val * 1000 else "train"


def regiones(anot, from_name):
    for r in anot.get("result", []):
        if r.get("from_name") != from_name:
            continue
        v = r.get("value", {})
        if r.get("type") == "polygonlabels" and v.get("points") and v.get("polygonlabels"):
            yield v["polygonlabels"][0], [(x / 100, y / 100) for x, y in v["points"]]
        elif r.get("type") == "rectanglelabels" and v.get("rectanglelabels"):
            x, y, w, h = v["x"] / 100, v["y"] / 100, v["width"] / 100, v["height"] / 100
            yield v["rectanglelabels"][0], [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _c(v):
    return min(1.0, max(0.0, v))


def lineas(regs, idx):
    det, seg, usadas = [], [], []
    for nombre, pts in regs:
        if nombre not in idx:
            continue
        pts = [(_c(x), _c(y)) for x, y in pts]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue
        c = idx[nombre]
        det.append(f"{c} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {x2 - x1:.6f} {y2 - y1:.6f}")
        if len(pts) >= 3:
            seg.append(f"{c} " + " ".join(f"{x:.6f} {y:.6f}" for x, y in pts))
        usadas.append(nombre)
    return det, seg, usadas


def cargar_correcciones(valor, proyecto):
    """'' | 'ultimo' (corr_p<N> mas reciente) | archivo en DATOS/correcciones -> {(tarea, region): cambio}."""
    if not valor:
        return {}
    d = DATOS / "correcciones"
    if valor == "ultimo":
        fs = sorted(d.glob(f"corr_p{proyecto}_*.json"))
        if not fs:
            raise SystemExit(f"No hay corr_p{proyecto}_*.json en {d}")
        f = fs[-1]
    else:
        f = Path(valor) if Path(valor).is_absolute() else d / Path(valor).name
    j = json.loads(f.read_text(encoding="utf-8"))
    if j.get("proyecto") != proyecto:
        raise SystemExit(f"{f.name} es del proyecto {j.get('proyecto')}, no del {proyecto}")
    print(f"Correcciones: {f.name} ({len(j['cambios'])} cambios)")
    return {(c["tarea"], c["region"]): c for c in j["cambios"]}


def corregir(anot, tid, corr):
    """Cambia en memoria la clase de las regiones corregidas. Solo si la anotacion y la clase original coinciden."""
    n = 0
    for r in anot.get("result") or []:
        c = corr.get((tid, r.get("id")))
        if not c or c["anotacion"] != anot.get("id"):
            continue
        v, tipo = r.get("value", {}), r.get("type")
        if v.get(tipo) and v[tipo][0] == c["de"]:
            v[tipo] = [c["a"]]
            n += 1
    return n

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proyecto", type=int)
    ap.add_argument("--formato", choices=["det", "seg", "ambos"], default="det")
    ap.add_argument("--val", type=float, default=0.2)
    ap.add_argument("--correcciones", default="", help="archivo de corregir_pares.py o 'ultimo'")
    a = ap.parse_args()
    corr = cargar_correcciones(a.correcciones, a.proyecto)

    r = requests.get(f"{LS_URL}/api/projects/{a.proyecto}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    cfg = r.json()["label_config"]
    perfil = leer_perfil(cfg)
    fn = perfil["from_name"]
    names = clases(cfg, fn)
    idx = {n: i for i, n in enumerate(names)}

    r = requests.get(f"{LS_URL}/api/projects/{a.proyecto}/export", headers=HEADERS, timeout=600,
                     params={"exportType": "JSON"})          # sin download_all_tasks: solo tareas anotadas
    r.raise_for_status()
    tareas = r.json()

    formatos = ["det", "seg"] if a.formato == "ambos" else [a.formato]
    out = DATASETS
    out.mkdir(exist_ok=True)
    zp = out / f"dataset_p{a.proyecto}_{a.formato}_{datetime.datetime.now():%Y%m%d-%H%M}.zip"
    n, por_clase, vacias = Counter(), {"train": Counter(), "val": Counter()}, 0
    n_corr = 0
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for t in tareas:
            anots = [x for x in t.get("annotations") or [] if not x.get("was_cancelled")]
            if not anots:
                continue
            anot = max(anots, key=lambda x: x.get("updated_at") or x.get("created_at") or "")
            n_corr += corregir(anot, t["id"], corr)
            det, seg, usadas = lineas(regiones(anot, fn), idx)
            s = split(t["id"], a.val)
            ruta = Path(get_local_path(t["data"][perfil["campo_imagen"]], task_id=t["id"]))
            base = f"{t['id']}_{ruta.stem}"
            for f in formatos:
                txt = det if f == "det" else seg
                z.write(ruta, f"{f}/images/{s}/{base}{ruta.suffix}")
                z.writestr(f"{f}/labels/{s}/{base}.txt", "\n".join(txt) + ("\n" if txt else ""))
            n[s] += 1
            por_clase[s].update(usadas)
            vacias += 0 if usadas else 1
        yaml = "path: .\ntrain: images/train\nval: images/val\nnames:\n" + \
               "".join(f"  {i}: {nm}\n" for i, nm in enumerate(names))
        for f in formatos:
            z.writestr(f"{f}/data.yaml", yaml)
        z.writestr("resumen.json", json.dumps({"proyecto": a.proyecto, "clases": names, "imagenes": dict(n),
                                               "instancias": {k: dict(v) for k, v in por_clase.items()}, "correcciones": a.correcciones or None, "n_correcciones": n_corr},
                                              ensure_ascii=True, indent=1))

    print(f"Imagenes: train {n['train']} | val {n['val']} | sin regiones {vacias}")
    print(f"{'clase':<14}{'train':>7}{'val':>6}")
    for nm in names:
        print(f"{nm:<14}{por_clase['train'][nm]:>7}{por_clase['val'][nm]:>6}")
    if not n["val"]:
        print("AVISO: val vacio; etiqueta mas fotos o sube --val")
    if corr:
        print(f"Correcciones aplicadas: {n_corr}/{len(corr)}")
    print(f"OK -> {zp} ({zp.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

