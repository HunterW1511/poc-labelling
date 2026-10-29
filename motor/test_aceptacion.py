"""Prueba de aceptacion.py (host): python motor\test_aceptacion.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aceptacion import comparar, conteo_cat, iou, regiones_ls, tasa


def R(i, c, x1, y1, x2, y2):
    return {"id": i, "clase": c, "caja": (x1, y1, x2, y2)}


def main():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - 1 / 3) < 1e-9

    pred = [R("a", "Base", 0, 0, 50, 50),        # aceptada (mismo id, misma caja)
            R("b", "Tornillos", 60, 0, 65, 5),   # geometria (mismo id, caja movida)
            R("c", "Eje_Externo", 0, 60, 10, 80),# clase (otro id, misma caja, otra clase)
            R("d", "Debajo", 80, 80, 90, 90)]    # borrada
    anot = [R("a", "Base", 0, 0, 50, 50),
            R("b", "Tornillos", 61, 0, 66, 6),
            R("z", "Eje_Interno", 0, 60, 10, 80),
            R("n", "Cabeza", 40, 70, 45, 75)]    # anadida
    c = comparar(pred, anot)
    k = conteo_cat(c)
    assert (k["aceptada"], k["geometria"], k["clase"], k["borrada"], k["anadida"]) == (1, 1, 1, 1, 1), k
    assert c[("clase", "Eje_Externo")] == 1 and c[("anadida", "Cabeza")] == 1
    assert tasa(c) == 0.25
    # sin ids: empareja por IoU misma clase antes que por otra clase
    p2 = [R(None, "A", 0, 0, 10, 10)]
    a2 = [R(None, "B", 0, 0, 10, 10), R(None, "A", 0, 0, 10, 9)]
    k2 = conteo_cat(comparar(p2, a2))
    assert k2["aceptada"] == 1 and k2["anadida"] == 1, k2
    # todo aceptado / nada predicho
    assert tasa(comparar(anot, anot)) == 1.0
    assert tasa(comparar([], anot)) == 0.0 and conteo_cat(comparar([], anot))["anadida"] == 4

    res = [{"from_name": "label", "type": "polygonlabels", "id": "q",
            "value": {"points": [[10, 10], [20, 10], [20, 30]], "polygonlabels": ["Base"]}},
           {"from_name": "label", "type": "rectanglelabels", "id": "r",
            "value": {"x": 1, "y": 2, "width": 3, "height": 4, "rectanglelabels": ["Cabeza"]}},
           {"from_name": "clic", "type": "keypointlabels", "value": {"keypointlabels": ["Base"]}},
           {"from_name": "label", "type": "polygonlabels", "value": {"points": [[1, 1]], "polygonlabels": ["X"]}}]
    rl = regiones_ls(res, "label")
    assert [x["caja"] for x in rl] == [(10, 10, 20, 30), (1, 2, 4, 6)], rl
    print("test_aceptacion OK")


if __name__ == "__main__":
    main()
