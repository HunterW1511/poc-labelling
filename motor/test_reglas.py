"""Prueba de reglas.py con mascaras sinteticas (sin SAM 3). Uso: python test_reglas.py [id_proyecto]"""
import os
import sys
from collections import Counter

import numpy as np

import reglas

H = W = 1000


def caja(x1, y1, x2, y2):
    m = np.zeros((H, W), bool)
    m[y1:y2, x1:x2] = True
    return m


def pr(texto, clases, area_min, mx=None, cont=None):
    return {"texto": texto, "clases": clases, "conf": 0.2, "area_min": area_min, "area_max": 1.0,
            "max_por_imagen": mx, "contencion": cont}


PERFIL = {"iou_duplicado": 0.6, "contencion": 0.85, "cobertura_negativo": 0.5, "conf_negativo": 0.3,
          "negativos": ["shadow"], "prompts": [
              pr("screw", ["Tornillos"], 0.0002), pr("screw head", ["Tornillos"], 0.0002),
              pr("black plastic part", ["Base"], 0.01, mx=1),
              pr("yellow plastic part", ["Eje_Externo", "Eje_Interno"], 0.0015, mx=2, cont=1.01)]}

DET = [
    ("screw", 0.90, caja(100, 100, 140, 140)),
    ("screw head", 0.50, caja(102, 100, 140, 140)),
    ("screw", 0.90, caja(500, 500, 505, 505)),
    ("screw", 0.10, caja(50, 800, 90, 840)),
    ("screw", 0.50, caja(900, 900, 950, 950)),
    ("shadow", 0.60, caja(890, 890, 960, 960)),
    ("black plastic part", 0.80, caja(300, 300, 500, 500)),
    ("yellow plastic part", 0.50, caja(305, 300, 500, 500)),
    ("black plastic part", 0.40, caja(310, 310, 450, 450)),
    ("black plastic part", 0.30, caja(700, 700, 850, 850)),
    ("yellow plastic part", 0.70, caja(600, 100, 700, 300)),
    ("yellow plastic part", 0.60, caja(630, 120, 670, 280)),
]


def main():
    reglas.revisar_perfil(PERFIL)
    inst, desc, conf = reglas.aplicar([{"prompt": t, "conf": c, "mask": m} for t, c, m in DET], PERFIL)
    cnt = Counter("|".join(i["clases"]) for i in inst)
    print("conteo    :", dict(cnt))
    print("descartes :", dict(desc))
    print("conflictos:", conf)
    assert cnt == Counter({"Tornillos": 1, "Base": 1, "Eje_Externo|Eje_Interno": 2}), cnt
    assert desc == Counter(duplicado=2, area=1, conf=1, sombra=1, fragmento=1, maximo=1), desc
    assert conf == 1, conf
    print("SINTETICO OK")

    if len(sys.argv) > 1:
        import requests
        import perfil
        from config import HEADERS, LS_URL as url
        r = requests.get(f"{url}/api/projects/{sys.argv[1]}", timeout=30,
                         headers=HEADERS)
        r.raise_for_status()
        p = perfil.leer_perfil(r.json()["label_config"])
        reglas.revisar_perfil(p)
        print(f"PERFIL REAL proyecto {sys.argv[1]} OK:", [x["texto"] for x in p["prompts"]])


if __name__ == "__main__":
    main()


