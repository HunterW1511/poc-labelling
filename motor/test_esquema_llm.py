"""Pruebas de esquema_llm.py (C.2). PURO. Uso: python test_esquema_llm.py"""
import copy, json

import esquema_llm as E
import spec


def test_clasificacion_completa():
    """Si spec.py agrega o quita una clave y nadie la clasifica, falla aqui."""
    for sec, claves in spec.CLAVES.items():
        g = [set(E.LLM.get(sec, {})), E.fijas(sec), set(E.EXPERTO.get(sec, set()))]
        todas = set().union(*g)
        assert todas == claves, f"{sec}: sin clasificar {sorted(claves - todas)}, sobran {sorted(todas - claves)}"
        assert sum(map(len, g)) == len(claves), f"{sec}: una clave esta en dos grupos"
    assert set(E.ORDEN) <= spec.CLAVES["raiz"]


def test_esquema_json_coincide():
    j = E.esquema_json()
    json.dumps(j)
    s = j["properties"]["spec"]["properties"]
    assert set(s) == set(E.LLM["raiz"])
    assert set(s["proyecto"]["properties"]) == set(E.LLM["proyecto"])
    assert set(s["clases"]["items"]["properties"]) == set(E.LLM["clase"])
    assert set(s["carpetas"]["items"]["properties"]) == set(E.LLM["carpeta"])
    assert set(s["tipo"]["enum"]) == spec.TIPOS
    assert set(s["carpetas"]["items"]["properties"]["tipo"]["enum"]) == spec.TIPOS_CARPETA
    assert set(s["clases"]["items"]["properties"]["importancia"]["anyOf"][0]["enum"]) == spec.IMPORTANCIA - {None, ""}


def test_ejemplo_valido():
    e, a = spec.validar(E.completar(E.EJEMPLO["spec"]))
    assert not e, e
    assert not a, a


def test_completar():
    p = copy.deepcopy(E.EJEMPLO["spec"])
    p["clases"][0]["color"] = None
    p["motor"] = {"url": "http://otro:1"}            # el LLM no puede pisar lo fijo
    s = E.completar(p)
    assert "color" not in s["clases"][0]
    assert s["esquema"] == spec.ESQUEMA and s["motor"] == E.FIJO["motor"]
    assert list(s)[0] == "esquema"


def test_instrucciones_mencionan_todo():
    t = E.instrucciones()
    for sec, campos in E.LLM.items():
        for k in campos:
            assert f"{sec}.{k}:" in t, f"falta {sec}.{k}"


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
