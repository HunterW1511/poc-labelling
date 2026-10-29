"""D.7: tasa de aceptacion de un pre-etiquetado. PURO (solo biblioteca estandar).
Empareja regiones predichas con las de la anotacion final: por id, luego IoU misma clase, luego IoU otra clase.
Categorias por region predicha: aceptada | geometria | clase | borrada. Region anotada sin pareja: anadida."""
from collections import Counter

CATS = ("aceptada", "geometria", "clase", "borrada", "anadida")


def regiones_ls(result, from_name):
    """result de Label Studio -> [{"id", "clase", "caja": (x1, y1, x2, y2) en %}]. Ignora clics y otros controles."""
    out = []
    for r in result or []:
        v, t = r.get("value", {}), r.get("type")
        if r.get("from_name") != from_name or t not in ("polygonlabels", "rectanglelabels") or not v.get(t):
            continue
        if t == "polygonlabels":
            pts = v.get("points") or []
            if len(pts) < 3:
                continue
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            caja = (min(xs), min(ys), max(xs), max(ys))
        else:
            caja = (v["x"], v["y"], v["x"] + v["width"], v["y"] + v["height"])
        out.append({"id": r.get("id"), "clase": v[t][0], "caja": caja})
    return out


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def comparar(pred, anot, par=0.5, aceptada=0.9):
    """-> Counter {(categoria, clase): n}. Clase = la predicha (o la anotada para 'anadida')."""
    res, libres_p, libres_a = Counter(), list(range(len(pred))), list(range(len(anot)))

    def cerrar(i, j):
        p, a = pred[i], anot[j]
        if p["clase"] != a["clase"]:
            cat = "clase"
        else:
            cat = "aceptada" if iou(p["caja"], a["caja"]) >= aceptada else "geometria"
        res[(cat, p["clase"])] += 1
        libres_p.remove(i)
        libres_a.remove(j)

    ids_a = {a["id"]: j for j, a in enumerate(anot) if a.get("id")}
    for i in list(libres_p):                                  # 1) mismo id
        j = ids_a.get(pred[i].get("id"))
        if j is not None and j in libres_a:
            cerrar(i, j)
    for misma in (True, False):                               # 2) IoU misma clase, 3) IoU otra clase
        pares = sorted(((iou(pred[i]["caja"], anot[j]["caja"]), i, j) for i in libres_p for j in libres_a
                        if (pred[i]["clase"] == anot[j]["clase"]) == misma), reverse=True)
        for v, i, j in pares:
            if v >= par and i in libres_p and j in libres_a:
                cerrar(i, j)
    for i in libres_p:
        res[("borrada", pred[i]["clase"])] += 1
    for j in libres_a:
        res[("anadida", anot[j]["clase"])] += 1
    return res


def tasa(conteo):
    """Aceptadas / predichas (las anadidas no cuentan como predichas)."""
    pred = sum(n for (c, _), n in conteo.items() if c != "anadida")
    return conteo_cat(conteo)["aceptada"] / pred if pred else 0.0


def conteo_cat(conteo):
    out = Counter({c: 0 for c in CATS})
    for (c, _), n in conteo.items():
        out[c] += n
    return out
