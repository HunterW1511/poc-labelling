"""Prueba de muestra.py (host, solo biblioteca estandar): python motor\test_muestra.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muestra import RAIZ, SIN_RUTA, carpeta_de, muestra_estratificada, repartir

P = "/data/local-files/?d=mis_imagenes/"


def tareas(tam):
    out, i = [], 1
    for c, k in tam.items():
        for _ in range(k):
            out.append({"id": i, "data": {"image": f"{P}{c}/{c}_{i}.jpg"}})
            i += 1
    return out


def main():
    # carpeta_de
    assert carpeta_de(P + "Ensamble/Ensamble_1.jpg") == "Ensamble"
    assert carpeta_de("/data/local-files/?d=mis_imagenes%2FMi%20Carpeta%2Fx.jpg") == "Mi Carpeta"
    assert carpeta_de(P + "slug/Fondo/x.jpg") == "Fondo"
    assert carpeta_de("/data/local-files/?d=x.jpg") == RAIZ
    assert carpeta_de("mis_imagenes/Base/x.jpg") == "Base"
    assert carpeta_de(None) == SIN_RUTA and carpeta_de("") == SIN_RUTA

    # repartir
    tam = {"A": 100, "B": 50, "C": 10}
    c = repartir(tam, 32)
    assert sum(c.values()) == 32, c
    assert abs(c["A"] - 20) <= 1 and abs(c["B"] - 10) <= 1 and abs(c["C"] - 2) <= 1, c
    assert repartir(tam, 500) == tam
    assert repartir(tam, 0) == {"A": 0, "B": 0, "C": 0}
    assert repartir({"A": 100, "B": 1, "C": 1}, 3) == {"A": 1, "B": 1, "C": 1}
    assert repartir({"A": 100, "B": 5, "C": 1}, 2) == {"A": 1, "B": 1, "C": 0}
    assert repartir({"A": 100, "B": 2}, 10, minimo=5) == {"A": 8, "B": 2}
    assert repartir({"A": 0, "B": 4}, 3) == {"A": 0, "B": 3}
    assert repartir({}, 5) == {}
    for bad in ((-1, 1), (1, -1)):
        try:
            repartir(tam, *bad)
            raise AssertionError("debio fallar")
        except ValueError:
            pass

    # muestra_estratificada
    t = tareas({"Base": 40, "Ensamble": 100, "Fondo": 8})
    m = muestra_estratificada(t, 30)
    assert len(m) == 30 and len(set(m)) == 30 and m == sorted(m)
    assert set(m) <= {x["id"] for x in t}
    por = {}
    for x in t:
        if x["id"] in m:
            por[carpeta_de(x["data"]["image"])] = por.get(carpeta_de(x["data"]["image"]), 0) + 1
    assert set(por) == {"Base", "Ensamble", "Fondo"}, por
    assert m == muestra_estratificada(t, 30), "no determinista"
    assert m != muestra_estratificada(t, 30, semilla=1), "la semilla no cambia nada"
    assert muestra_estratificada(t, 1000) == sorted(x["id"] for x in t)
    assert muestra_estratificada([], 10) == []
    assert muestra_estratificada(t, 0) == []
    sin = [{"id": 1, "data": {}}, {"id": 2}]
    assert muestra_estratificada(sin, 5) == [1, 2]
    # prioridad: entra primero dentro del cupo de su carpeta, sin cambiar los cupos
    def cuenta(ids):
        k = {}
        for x in t:
            if x["id"] in ids:
                cc = carpeta_de(x["data"]["image"])
                k[cc] = k.get(cc, 0) + 1
        return k
    fondo = [x["id"] for x in t if "/Fondo/" in x["data"]["image"]]
    base = [x["id"] for x in t if "/Base/" in x["data"]["image"]]
    pri = fondo[-2:] + base[:3]
    mp = muestra_estratificada(t, 30, prioridad=pri + [99999])
    assert len(mp) == 30 and set(pri) <= set(mp), mp
    assert cuenta(mp) == cuenta(m), (cuenta(mp), cuenta(m))
    m3 = muestra_estratificada(t, 30, prioridad=fondo)
    assert cuenta(m3) == cuenta(m)
    assert muestra_estratificada(t, 30, prioridad=[]) == m
    print("test_muestra OK (cupos 100/50/10 con n=32 ->", c, ")")


if __name__ == "__main__":
    main()
