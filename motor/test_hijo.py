"""Prueba de hijo.py: docker compose exec -T motor python /app/test_hijo.py"""
import numpy as np

from hijo import OPCIONES, caja_a_mascara, elegir_mascara, fusionar

H, W = 100, 200


def falla(f, exc):
    try:
        f()
    except exc:
        return
    raise AssertionError(f"debio lanzar {exc.__name__}")


def main():
    caja = [20, 10, 60, 50]                                  # 40 x 40 = 1600 px
    assert caja_a_mascara(caja, H, W).sum() == 1600
    assert caja_a_mascara([-5, -5, 300, 300], H, W).sum() == H * W, "debe recortar a la imagen"

    # mascara buena (circulo dentro de la caja) -> sam
    yy, xx = np.mgrid[:H, :W]
    circ = (xx - 40) ** 2 + (yy - 30) ** 2 <= 18 ** 2
    m, f = elegir_mascara(circ, caja, H, W)
    assert f == "sam" and m.sum() == circ.sum()
    # mascara que se escapa: la parte fuera de la caja ampliada se recorta
    fuga = circ.copy(); fuga[0:5, 150:200] = True             # 250 px lejos de la caja
    m, f = elegir_mascara(fuga, caja, H, W)
    assert f == "sam" and m.sum() == circ.sum(), "debe recortar la fuga"
    # mascara casi toda fuera -> caja
    fuera = np.zeros((H, W), bool); fuera[60:100, 100:200] = True; fuera[20:22, 30:32] = True
    assert elegir_mascara(fuera, caja, H, W)[1] == "caja"
    # mascara diminuta (< 15% de la caja) -> caja
    chica = np.zeros((H, W), bool); chica[25:30, 35:40] = True
    assert elegir_mascara(chica, caja, H, W)[1] == "caja"
    # None, vacia o de otro tamano -> caja
    for mm in (None, np.zeros((H, W), bool), np.ones((10, 10), bool)):
        m, f = elegir_mascara(mm, caja, H, W)
        assert f == "caja" and m.sum() == 1600

    lim = {"Tornillos": {"max": 2, "area_min": 0.0001, "area_max": None},
           "Base": {"max": 1, "area_min": 0.2, "area_max": None},
           "Eje": {"max": None, "area_min": None, "area_max": 0.01}}
    dets = [{"clase": "Tornillos", "conf": 0.9, "caja": [0, 0, 5, 5]},
            {"clase": "Tornillos", "conf": 0.5, "caja": [10, 0, 15, 5]},
            {"clase": "Tornillos", "conf": 0.7, "caja": [20, 0, 25, 5]},
            {"clase": "Base", "conf": 0.8, "caja": [0, 0, 200, 100]},
            {"clase": "Base", "conf": 0.6, "caja": [0, 0, 150, 100]},
            {"clase": "Eje", "conf": 0.9, "caja": [0, 0, 100, 50]},      # 25% > area_max
            {"clase": "Otra", "conf": 0.9, "caja": [0, 0, 5, 5]}]
    sin_area, d0 = fusionar(dets, [None] * len(dets), lim, H, W)
    assert d0["area"] == 0 and any(i["clases"][0] == "Eje" for i in sin_area), "por defecto no filtra area"
    inst, desc = fusionar(dets, [None] * len(dets), lim, H, W, {**OPCIONES, "usar_area": True})
    got = [(i["clases"][0], i["conf"]) for i in inst]
    assert got == [("Tornillos", 0.9), ("Base", 0.8), ("Tornillos", 0.7)], got
    assert desc["maximo"] == 2 and desc["area"] == 1 and desc["clase_desconocida"] == 1, desc
    assert desc["fuente_caja"] == 3 and desc["fuente_sam"] == 0
    assert all(len(i["clases"]) == 1 for i in inst), "nunca ambiguas"
    falla(lambda: fusionar(dets, [None], lim, H, W), ValueError)
    assert fusionar([], [], lim, H, W)[0] == []
    print("test_hijo OK |", dict(desc))


if __name__ == "__main__":
    main()
