"""Prueba de correccion.py (host): python motor\test_correccion.py"""
import math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from correccion import a_pixeles, elongacion, proponer_par


def rect(w, h, x0=0, y0=0, ang=0.0):
    c, s = math.cos(ang), math.sin(ang)
    base = [(0, 0), (w, 0), (w, h), (0, h)]
    return [(x0 + x * c - y * s, y0 + x * s + y * c) for x, y in base]


def main():
    assert abs(elongacion(rect(100, 10)) - 10) < 1e-6
    assert abs(elongacion(rect(30, 30)) - 1) < 1e-6
    assert abs(elongacion(rect(100, 10, ang=0.7)) - 10) < 1e-6, "debe ser invariante a rotacion"
    assert elongacion([(0, 0), (1, 1)]) == float("inf")
    assert elongacion([(0, 0), (1, 1), (2, 2)]) == float("inf")
    # % -> pixeles: un cuadrado en % de una imagen 2:1 es un rectangulo 2:1 en pixeles
    sq = a_pixeles([(0, 0), (10, 0), (10, 10), (0, 10)], 2000, 1000)
    assert abs(elongacion(sq) - 2) < 1e-6

    L, A = "Eje_Externo", "Eje_Interno"
    delgado, ancho = rect(100, 10), rect(40, 30)
    otra = {"id": "z", "clase": "Base", "pts": rect(500, 400)}
    # dos externos -> el ancho pasa a interno
    est, ch, _ = proponer_par([{"id": "a", "clase": L, "pts": delgado},
                               {"id": "b", "clase": L, "pts": ancho}, otra], L, A)
    assert est == "corregida" and ch == [("b", L, A)], (est, ch)
    # invertidos -> se intercambian
    est, ch, _ = proponer_par([{"id": "a", "clase": A, "pts": delgado},
                               {"id": "b", "clase": L, "pts": ancho}], L, A)
    assert est == "corregida" and sorted(ch) == [("a", A, L), ("b", L, A)], ch
    # ya correctos
    est, ch, _ = proponer_par([{"id": "a", "clase": L, "pts": delgado},
                               {"id": "b", "clase": A, "pts": ancho}], L, A)
    assert est == "ok" and ch == []
    # formas parecidas -> dudosa, sin cambios
    est, ch, _ = proponer_par([{"id": "a", "clase": L, "pts": rect(40, 30)},
                               {"id": "b", "clase": L, "pts": rect(41, 30)}], L, A)
    assert est == "dudosa" and ch == []
    # 1 o 3 regiones del par -> omitida
    assert proponer_par([{"id": "a", "clase": L, "pts": delgado}, otra], L, A)[0] == "omitida"
    tres = [{"id": i, "clase": L, "pts": delgado} for i in "abc"]
    assert proponer_par(tres, L, A)[0] == "omitida"
    print("test_correccion OK")


if __name__ == "__main__":
    main()
