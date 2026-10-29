"""D.1: diagnostico de SOLO LECTURA: anotaciones vs predicciones por carpeta y clase.
Uso: python /app/diagnostico.py <proyecto> [--pares A,B] [--top 15]
No escribe en Label Studio; guarda el reporte en DATOS/diagnosticos/."""
import argparse, datetime, json, statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import requests

from cola import HEADERS, LS_URL
from config import DATOS
from muestra import carpeta_de
from perfil import CONTROLES, leer_perfil

TIPOS = ("polygonlabels", "rectanglelabels")


def _f(v):
    return float(v) if v not in (None, "") else None


def limites(cfg, from_name):
    for c in ET.fromstring(cfg).iter():
        if c.tag in CONTROLES and c.get("name") == from_name:
            return {l.get("value"): {"max": _f(l.get("max")), "area_min": _f(l.get("area_min")),
                                     "area_max": _f(l.get("area_max"))} for l in c.iter("Label")}
    raise SystemExit(f"No encontre el control {from_name}")


def area(v, tipo):
    if tipo == "rectanglelabels":
        return v["width"] * v["height"] / 1e4
    p = [(x / 100, y / 100) for x, y in v["points"]]
    return abs(sum(p[i][0] * p[i - 1][1] - p[i - 1][0] * p[i][1] for i in range(len(p)))) / 2


def conteos(result, fn):
    c, ar = Counter(), defaultdict(list)
    for r in result or []:
        v, t = r.get("value", {}), r.get("type")
        if r.get("from_name") != fn or t not in TIPOS or not v.get(t):
            continue
        if t == "polygonlabels" and len(v.get("points") or []) < 3:
            continue
        c[v[t][0]] += 1
        ar[v[t][0]].append(area(v, t))
    return c, ar


def prediccion(tid, mv):
    d = requests.get(f"{LS_URL}/api/tasks/{tid}", headers=HEADERS, timeout=30).json()
    preds = [p for p in d.get("predictions") or [] if isinstance(p, dict)]
    if mv:
        preds = [p for p in preds if p.get("model_version") == mv] or preds
    return max(preds, key=lambda p: p.get("created_at") or "") if preds else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proyecto", type=int)
    ap.add_argument("--pares", default="", help="A,B: clases que deberian aparecer en igual cantidad")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()

    pj = requests.get(f"{LS_URL}/api/projects/{a.proyecto}", headers=HEADERS, timeout=30).json()
    cfg, mv = pj["label_config"], pj.get("model_version")
    perfil = leer_perfil(cfg)
    fn, campo, clases = perfil["from_name"], perfil["campo_imagen"], perfil["clases"]
    lim = limites(cfg, fn)

    print("== Limites perdidos en la fusion de prompts")
    for p in perfil["prompts"]:
        if len(p["clases"]) > 1:
            for c in p["clases"]:
                print(f"  '{p['texto']}' {c}: area_max {lim[c]['area_max']} -> {p['area_max']} | "
                      f"max {lim[c]['max']} -> {p['max_por_imagen']}")

    ex = requests.get(f"{LS_URL}/api/projects/{a.proyecto}/export", headers=HEADERS,
                      params={"exportType": "JSON"}, timeout=600).json()
    n_car, anot_car, pred_car = Counter(), defaultdict(Counter), defaultdict(Counter)
    areas, anom = defaultdict(list), defaultdict(list)
    err, exactas, sin_pred, skips = Counter(), 0, 0, 0
    par = [x.strip() for x in a.pares.split(",") if x.strip()]
    for i, t in enumerate(ex, 1):
        print(f"  tarea {i}/{len(ex)}", end="\r", flush=True)
        anots = [x for x in t.get("annotations") or [] if not x.get("was_cancelled")]
        if not anots:
            skips += 1
            continue
        anot = max(anots, key=lambda x: x.get("updated_at") or x.get("created_at") or "")
        car = carpeta_de(t["data"][campo])
        ca, ar = conteos(anot.get("result"), fn)
        pr = prediccion(t["id"], mv)
        sin_pred += pr is None
        cp = conteos(pr.get("result"), fn)[0] if pr else Counter()
        n_car[car] += 1
        anot_car[car].update(ca)
        pred_car[car].update(cp)
        exactas += all(ca[c] == cp[c] for c in clases)
        for c in clases:
            if ca[c] != cp[c]:
                err[c] += abs(ca[c] - cp[c])
                anom[f"pred!=anot {c}"].append(t["id"])
            if lim[c]["max"] and ca[c] > lim[c]["max"]:
                anom[f"excede max {c}"].append(t["id"])
            for x in ar.get(c, []):
                areas[c].append(x)
                if (lim[c]["area_min"] and x < lim[c]["area_min"]) or (lim[c]["area_max"] and x > lim[c]["area_max"]):
                    anom[f"area fuera {c}"].append(t["id"])
        if len(par) == 2 and ca[par[0]] != ca[par[1]]:
            anom[f"par {par[0]}!={par[1]}"].append(t["id"])
    print(" " * 40)
    print(f"Tareas: {len(ex)} | con anotacion {sum(n_car.values())} | skip {skips} | sin prediccion {sin_pred}")

    print("\n== Anotadas (predichas) por carpeta")
    w = max(len(c) for c in clases) + 2
    print(f"{'carpeta':<14}{'n':>4} " + "".join(f"{c[:w - 1]:>{w}}" for c in clases))
    for car in sorted(n_car):
        print(f"{car:<14}{n_car[car]:>4} " + "".join(
            f"{f'{anot_car[car][c]}({pred_car[car][c]})':>{w}}" for c in clases))

    print("\n== Area por clase (% de la imagen)")
    print(f"{'clase':<14}{'n':>5}{'min':>8}{'p10':>8}{'med':>8}{'p90':>8}{'max':>8}  limites")
    for c in clases:
        v = sorted(areas[c])
        if not v:
            print(f"{c:<14}{0:>5}")
            continue
        q = statistics.quantiles(v, n=10) if len(v) > 1 else [v[0]] * 9
        fila = [v[0], q[0], statistics.median(v), q[-1], v[-1]]
        print(f"{c:<14}{len(v):>5}" + "".join(f"{x * 100:>8.3f}" for x in fila) +
              f"  [{lim[c]['area_min']}, {lim[c]['area_max']}]")

    print(f"\n== Prediccion vs anotacion: conteo exacto {exactas}/{sum(n_car.values())}")
    for c in clases:
        print(f"  {c:<14} error absoluto {err[c]}")

    print("\n== Anomalias (ids de tarea)")
    for k in sorted(anom):
        ids = sorted(set(anom[k]))
        print(f"  {k:<28}{len(ids):>4}  {ids[:a.top]}{' ...' if len(ids) > a.top else ''}")

    d = DATOS / "diagnosticos"
    d.mkdir(exist_ok=True)
    f = d / f"diag_p{a.proyecto}_{datetime.datetime.now():%Y%m%d-%H%M}.json"
    f.write_text(json.dumps({"proyecto": a.proyecto, "model_version": mv,
                             "anomalias": {k: sorted(set(v)) for k, v in anom.items()}},
                            ensure_ascii=True, indent=1), encoding="utf-8")
    print(f"\nReporte -> {f}")


if __name__ == "__main__":
    main()
