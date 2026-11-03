"""Pruebas de comparar.py (C.5 + L.5). PURO. Uso: python test_comparar.py"""
import copy

import comparar as C
import esquema_llm as E

REF = E.completar(E.EJEMPLO["spec"])


def test_identica():
    r = C.comparar(copy.deepcopy(REF), REF)
    assert r["aciertos"] == r["total"] == 2 * 3 + 4, r["lineas"]


def test_diferencias():
    g = copy.deepcopy(REF)
    g["clases"][0]["nombre"] = "Manzanas"                     # plural: se empareja
    g["carpetas"][0]["clases"] = ["Manzanas"]
    g["carpetas"][2]["clases"] = ["Manzanas", "Platano"]
    g["clases"][0]["max_por_imagen"] = 3                      # fallo de maximo
    g["clases"].append({"nombre": "Pera", "prompts": ["pear"]})  # sobra
    g["carpetas"].pop(3)                                      # falta Fondo
    r = C.comparar(g, REF)
    t = "\n".join(r["lineas"])
    assert "generada como 'Manzanas'" in t and "'Pera' sobra" in t and "Fondo (negativo" in t
    assert r["aciertos"] == r["total"] - 3, t


def test_sinonimos():
    g = copy.deepcopy(REF)
    g["clases"][0]["nombre"] = "Poma"                         # nada parecido a Manzana
    for k in g["carpetas"]:
        k["clases"] = ["Poma" if x == "Manzana" else x for x in k["clases"]]
    assert "FALTA" in "\n".join(C.comparar(g, REF)["lineas"])
    r = C.comparar(g, REF, sinonimos="Manzana=Poma")
    assert r["aciertos"] == r["total"], r["lineas"]


def test_carpeta_con_otras_clases_y_todas_las_sobrantes():
    g = copy.deepcopy(REF)
    g["carpetas"][2]["clases"] = ["Manzana"]                  # mezcla sin Platano
    g["carpetas"] += [{"nombre": "Extra1", "tipo": "pieza", "clases": ["Manzana"]},
                      {"nombre": "Extra2", "tipo": "pieza", "clases": ["Manzana"]}]
    t = "\n".join(C.comparar(g, REF)["lineas"])
    assert "con otras clases" in t and "faltan ['Platano']" in t, t
    assert "'Extra1' (pieza) sobra" in t and "'Extra2' (pieza) sobra" in t, t


def test_expertos_y_compartidos():
    ref = copy.deepcopy(REF)
    ref["clases"][0]["contencion"] = 1.01
    ref["clases"][1]["prompts"] = ["red apple"]
    t = "\n".join(C.comparar(REF, ref)["lineas"])
    assert "Manzana.contencion" in t and "comparte 'red apple'" in t


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)