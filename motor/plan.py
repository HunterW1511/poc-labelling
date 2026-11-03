"""Plan de captura (B.5): cuantas fotos por carpeta y que variaciones cubrir. PURO y solo biblioteca estandar
(se importa tambien desde el host: xd.py y capturar.py).
Uso: python plan.py <spec.json> [--total N]"""
import argparse, math

from spec import cargar, validar

POR_IMPORTANCIA = {"alta": 60, "media": 40, "baja": 25}
MEZCLA_MIN, MEZCLA_POR_CLASE, MEZCLA_EXTRA_ALTA = 50, 15, 20
NEG_FRACCION, NEG_MIN = 0.12, 20                    # negativos ~12% del total
MINIMOS = {"pieza": 10, "mezcla": 20, "negativo": 10}  # piso al escalar con --total
VARIACIONES = ["posicion en la imagen: centro, esquinas y bordes", "rotacion de la pieza",
               "distancia a la camara", "iluminacion (luz directa, lateral, tenue)"]
VARIACIONES_NEG = ["fondo vacio desde distintas posiciones de camara", "sombras e iluminacion variada",
                   "objetos ajenos que NO son piezas (manos, herramientas, papeles)"]
ORDEN_IMP = ["baja", "media", "alta"]


def _imp(c):
    return c.get("importancia") or "media"


def plan_captura(spec, total=None):
    """-> [{"carpeta", "tipo", "clases", "fotos", "motivo", "variaciones"}] en el orden de la spec."""
    err, _ = validar(spec)
    if err:
        raise ValueError("especificacion invalida:\n  " + "\n  ".join(err))
    clases = {c["nombre"]: c for c in spec["clases"]}
    grupos = {}
    for c in spec["clases"]:
        for p in c.get("prompts") or []:
            grupos.setdefault(p.split("@")[0].strip(), set()).add(c["nombre"])
    compartidas = [sorted(g) for g in grupos.values() if len(g) > 1]

    filas = []
    for k in spec["carpetas"]:
        t, cl = k["tipo"], list(k.get("clases") or [])
        f = {"carpeta": k["nombre"], "tipo": t, "clases": cl, "fotos": None, "motivo": "", "variaciones": []}
        if t == "pieza":
            imp = max((_imp(clases[x]) for x in cl), key=ORDEN_IMP.index)
            f["fotos"], f["motivo"] = POR_IMPORTANCIA[imp], f"pieza, importancia {imp}"
            f["variaciones"] = list(VARIACIONES)
        elif t == "mezcla":
            alta = any(_imp(clases[x]) == "alta" for x in cl)
            f["fotos"] = max(MEZCLA_MIN, MEZCLA_POR_CLASE * len(cl)) + (MEZCLA_EXTRA_ALTA if alta else 0)
            f["motivo"] = f"mezcla de {len(cl)} clases" + (" + extra por clase alta" if alta else "")
            f["variaciones"] = list(VARIACIONES)
            for x in cl:
                mx = clases[x].get("max_por_imagen")
                if mx and mx > 1:
                    f["variaciones"].append(f"{x}: variar la cantidad de 1 a {mx}")
            for g in compartidas:
                if set(g) <= set(cl):
                    f["variaciones"].append(f"{' y '.join(g)} juntas (comparten prompt, se confunden)")
        else:
            f["variaciones"] = list(VARIACIONES_NEG)
        filas.append(f)

    pos = sum(f["fotos"] for f in filas if f["tipo"] != "negativo")
    negs = [f for f in filas if f["tipo"] == "negativo"]
    if negs:
        tot_neg = max(NEG_MIN, math.ceil(NEG_FRACCION * pos / (1 - NEG_FRACCION)))
        for f in negs:
            f["fotos"] = math.ceil(tot_neg / len(negs))
            f["motivo"] = f"negativos ~{NEG_FRACCION:.0%} del total"

    if total:
        factor = total / sum(f["fotos"] for f in filas)
        for f in filas:
            f["fotos"] = max(MINIMOS[f["tipo"]], round(f["fotos"] * factor))
            f["motivo"] += f" | escalado a total {total}"
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--total", type=int, default=0)
    a = ap.parse_args()
    filas = plan_captura(cargar(a.spec), a.total or None)
    w = max(14, *(len(f["carpeta"]) for f in filas)) + 1
    for f in filas:
        print(f"{f['carpeta']:<{w}} {f['tipo']:<9} {f['fotos']:>4}  {f['motivo']}")
    print(f"TOTAL {sum(f['fotos'] for f in filas)}")


if __name__ == "__main__":
    main()
