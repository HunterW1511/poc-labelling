"""D.3: propone correcciones de un par de clases confundidas por forma. SOLO LECTURA en Label Studio.
Uso: python /app/corregir_pares.py <proyecto> --largo A --ancho B [--umbral 1.15]
Escribe DATOS/correcciones/corr_p<N>_<largo>-<ancho>_<fecha>.json; se aplica con exportar_yolo.py --correcciones."""
import argparse, datetime, json
from collections import Counter

import requests
from PIL import Image

from cola import HEADERS, LS_URL, get_local_path
from config import DATOS
from correccion import a_pixeles, proponer_par
from perfil import leer_perfil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proyecto", type=int)
    ap.add_argument("--largo", required=True, help="clase alargada")
    ap.add_argument("--ancho", required=True, help="clase ancha")
    ap.add_argument("--umbral", type=float, default=1.15)
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()

    cfg = requests.get(f"{LS_URL}/api/projects/{a.proyecto}", headers=HEADERS, timeout=30).json()["label_config"]
    perfil = leer_perfil(cfg)
    fn, campo = perfil["from_name"], perfil["campo_imagen"]
    for c in (a.largo, a.ancho):
        if c not in perfil["clases"]:
            raise SystemExit(f"La clase {c} no existe en el proyecto {a.proyecto}")
    ex = requests.get(f"{LS_URL}/api/projects/{a.proyecto}/export", headers=HEADERS,
                      params={"exportType": "JSON"}, timeout=600).json()

    estados, cambios, dudosas, ejemplos, sin_dim = Counter(), [], [], [], 0
    antes, despues = Counter(), Counter()
    for t in ex:
        anots = [x for x in t.get("annotations") or [] if not x.get("was_cancelled")]
        if not anots:
            continue
        anot = max(anots, key=lambda x: x.get("updated_at") or x.get("created_at") or "")
        regs, dim = [], None
        for r in anot.get("result") or []:
            v, tipo = r.get("value", {}), r.get("type")
            if r.get("from_name") != fn or tipo not in ("polygonlabels", "rectanglelabels") or not v.get(tipo):
                continue
            w, h = r.get("original_width"), r.get("original_height")
            if not (w and h):
                if dim is None:
                    with Image.open(get_local_path(t["data"][campo], task_id=t["id"])) as im:
                        dim = im.size
                    sin_dim += 1
                w, h = dim
            if tipo == "polygonlabels":
                pct = v.get("points") or []
            else:
                pct = [(v["x"], v["y"]), (v["x"] + v["width"], v["y"]),
                       (v["x"] + v["width"], v["y"] + v["height"]), (v["x"], v["y"] + v["height"])]
            regs.append({"id": r.get("id"), "clase": v[tipo][0], "pts": a_pixeles(pct, w, h)})
        est, ch, el = proponer_par(regs, a.largo, a.ancho, a.umbral)
        estados[est] += 1
        nueva = {rid: b for rid, _, b in ch}
        for r in regs:
            antes[r["clase"]] += 1
            despues[nueva.get(r["id"], r["clase"])] += 1
        if est == "dudosa":
            dudosas.append(t["id"])
        for rid, de, b in ch:
            cambios.append({"tarea": t["id"], "anotacion": anot["id"], "region": rid, "de": de, "a": b})
        if ch and len(ejemplos) < a.top:
            ejemplos.append((t["id"], el, [(de, b) for _, de, b in ch]))

    print(f"Tareas: {sum(estados.values())} | " + " | ".join(f"{k} {v}" for k, v in sorted(estados.items())))
    print(f"Regiones a cambiar: {len(cambios)} | tareas sin original_width/height: {sin_dim}")
    for c in (a.largo, a.ancho):
        print(f"  {c:<14} antes {antes[c]:>4} -> despues {despues[c]:>4}")
    print("Ejemplos (tarea, elongaciones [mayor, menor], cambios):")
    for e in ejemplos:
        print("  ", e)
    print(f"Dudosas ({len(dudosas)}), revisar a mano si quieres: {dudosas[:30]}")

    d = DATOS / "correcciones"
    d.mkdir(exist_ok=True)
    f = d / f"corr_p{a.proyecto}_{a.largo}-{a.ancho}_{datetime.datetime.now():%Y%m%d-%H%M}.json"
    f.write_text(json.dumps({"proyecto": a.proyecto, "largo": a.largo, "ancho": a.ancho, "umbral": a.umbral,
                             "creado": datetime.datetime.now().isoformat(timespec="seconds"),
                             "estados": dict(estados), "dudosas": dudosas, "cambios": cambios},
                            ensure_ascii=True, indent=1), encoding="utf-8")
    print(f"Propuesta -> {f}  (no se escribio nada en Label Studio)")


if __name__ == "__main__":
    main()
