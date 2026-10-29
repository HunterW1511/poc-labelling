"""D.3: correccion de pares de clases que se confunden por forma. PURO (solo biblioteca estandar).
Regla: si una tarea tiene exactamente 2 regiones de {largo, ancho}, la mas alargada es 'largo' y la otra 'ancho'.
Si la diferencia de elongacion es menor que 'umbral' (cociente), la tarea queda 'dudosa' y no se cambia."""
import math


def elongacion(pts):
    """Cociente de ejes principales (>= 1) de los vertices [(x, y)] EN PIXELES. inf si es degenerado."""
    n = len(pts)
    if n < 3:
        return float("inf")
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts) / n
    syy = sum((p[1] - my) ** 2 for p in pts) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    disc = math.sqrt(max(0.0, tr * tr / 4 - det))
    l1, l2 = tr / 2 + disc, tr / 2 - disc
    return math.sqrt(l1 / l2) if l2 > 1e-12 else float("inf")


def a_pixeles(points_pct, ancho, alto):
    """Puntos de Label Studio (% de la imagen) -> pixeles."""
    return [(x * ancho / 100, y * alto / 100) for x, y in points_pct]


def proponer_par(regiones, largo, ancho, umbral=1.15):
    """regiones: [{"id", "clase", "pts" (pixeles)}] -> (estado, cambios[(id, de, a)], elongaciones).
    estado: ok | corregida | dudosa | omitida (no hay exactamente 2 regiones del par)."""
    sel = [r for r in regiones if r["clase"] in (largo, ancho)]
    if len(sel) != 2:
        return "omitida", [], []
    e = [(elongacion(r["pts"]), r) for r in sel]
    e.sort(key=lambda x: -x[0])
    (e1, r1), (e2, r2) = e
    el = [round(e1, 2), round(e2, 2)]
    cambios = [(r["id"], r["clase"], nueva) for r, nueva in ((r1, largo), (r2, ancho)) if r["clase"] != nueva]
    if not cambios:
        return "ok", [], el
    if e2 > 0 and e1 / e2 < umbral:
        return "dudosa", [], el
    return "corregida", cambios, el
