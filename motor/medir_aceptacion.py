"""D.7: tasa de aceptacion del pre-etiquetado sobre las tareas ya revisadas. SOLO LECTURA.
Uso: python /app/medir_aceptacion.py <proyecto> [--versiones v1,v2]  (por defecto: model_version del proyecto)"""
import argparse
from collections import Counter, defaultdict

import requests

from aceptacion import CATS, comparar, conteo_cat, regiones_ls, tasa
from cola import HEADERS, LS_URL
from muestra import carpeta_de
from perfil import leer_perfil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proyecto", type=int)
    ap.add_argument("--versiones", default="", help="separadas por coma")
    a = ap.parse_args()

    pj = requests.get(f"{LS_URL}/api/projects/{a.proyecto}", headers=HEADERS, timeout=30).json()
    perfil = leer_perfil(pj["label_config"])
    fn, campo = perfil["from_name"], perfil["campo_imagen"]
    vers = [v.strip() for v in a.versiones.split(",") if v.strip()] or [pj.get("model_version")]
    ex = requests.get(f"{LS_URL}/api/projects/{a.proyecto}/export", headers=HEADERS,
                      params={"exportType": "JSON"}, timeout=600).json()
    revisadas = []
    for t in ex:
        anots = [x for x in t.get("annotations") or [] if not x.get("was_cancelled")]
        if anots:
            anot = max(anots, key=lambda x: x.get("updated_at") or x.get("created_at") or "")
            preds = requests.get(f"{LS_URL}/api/tasks/{t['id']}", headers=HEADERS, timeout=30).json().get("predictions")
            revisadas.append((t, anot, [p for p in preds or [] if isinstance(p, dict)]))
    print(f"Proyecto {a.proyecto}: {len(revisadas)} tareas revisadas")

    for ver in vers:
        total, por_car, n, sin = Counter(), defaultdict(Counter), 0, 0
        for t, anot, preds in revisadas:
            ps = [p for p in preds if p.get("model_version") == ver]
            if not ps:
                sin += 1
                continue
            pr = max(ps, key=lambda p: p.get("created_at") or "")
            c = comparar(regiones_ls(pr.get("result"), fn), regiones_ls(anot.get("result"), fn))
            total.update(c)
            por_car[carpeta_de(t["data"].get(campo))].update(c)
            n += 1
        k = conteo_cat(total)
        print(f"\n== {ver}: {n} tareas medidas (sin esta version: {sin}) | ACEPTACION {tasa(total):.0%}")
        print("   " + " | ".join(f"{c} {k[c]}" for c in CATS))
        print(f"   {'clase':<14}" + "".join(f"{c[:9]:>10}" for c in CATS) + f"{'tasa':>7}")
        for cl in perfil["clases"]:
            sub = Counter({key: v for key, v in total.items() if key[1] == cl})
            if not sub:
                continue
            kk = conteo_cat(sub)
            print(f"   {cl:<14}" + "".join(f"{kk[c]:>10}" for c in CATS) + f"{tasa(sub):>7.0%}")
        for car in sorted(por_car):
            print(f"   carpeta {car:<14} aceptacion {tasa(por_car[car]):.0%}")


if __name__ == "__main__":
    main()
