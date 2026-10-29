"""Pruebas de asistente.py (C.3) con un LLM FALSO, sin red. PURO. Uso: python test_asistente.py"""
import copy, json

import asistente as A
import esquema_llm as E


def falso(respuestas):
    llamadas = []

    def llm(msgs, esquema):
        llamadas.append(copy.deepcopy(msgs))
        return respuestas[len(llamadas) - 1], {}
    return llm, llamadas


def _resp(mod=None):
    r = copy.deepcopy(E.EJEMPLO)
    if mod:
        mod(r["spec"])
    return json.dumps(r, ensure_ascii=False)


def test_bien_a_la_primera():
    llm, ll = falso([_resp()])
    r = A.generar_spec("texto", llm)
    assert r["ok"] and r["intentos"] == 1 and len(ll) == 1, A.resumen(r)
    assert r["preguntas"] == E.EJEMPLO["preguntas"]


def test_repara_error_de_validacion():
    malo = _resp(lambda s: s["carpetas"][0]["clases"].append("Pera"))
    llm, ll = falso([malo, _resp()])
    r = A.generar_spec("texto", llm)
    assert r["ok"] and r["intentos"] == 2, A.resumen(r)
    ultimo = ll[1][-1]["content"]
    assert "Pera" in ultimo and ll[1][-2]["role"] == "assistant"


def test_repara_json_invalido():
    llm, _ = falso(["{no es json", _resp()])
    r = A.generar_spec("texto", llm)
    assert r["ok"] and r["intentos"] == 2


def test_se_rinde_tras_n_intentos():
    malo = _resp(lambda s: s["clases"][1]["prompts"].__setitem__(0, "red apple"))
    llm, ll = falso([malo] * 5)
    r = A.generar_spec("texto", llm, intentos=3)
    assert not r["ok"] and r["intentos"] == 3 and len(ll) == 3
    assert any("repetido" in p for p in r["problemas"])


def test_normaliza_sin_gastar_intento():
    def mod(s):
        s["clases"][1]["nombre"] = "Pl\u00e1tano verde"
        s["carpetas"][1]["clases"] = ["Pl\u00e1tano verde"]
        s["carpetas"][2]["clases"] = ["Manzana", "Pl\u00e1tano verde"]
        s["clases"][1]["color"] = "rojo"
        s["carpetas"].pop()                         # sin carpeta negativo
        s["proyecto"]["slug"] = "Mis Frutas"
    llm, _ = falso([_resp(mod)])
    r = A.generar_spec("texto", llm)
    assert r["ok"] and r["intentos"] == 1, A.resumen(r)
    s = r["spec"]
    assert s["clases"][1]["nombre"] == "Platano_verde" and s["carpetas"][2]["clases"][1] == "Platano_verde"
    assert s["clases"][1]["color"] != "rojo" and s["proyecto"]["slug"] == "mis_frutas"
    assert any(k["tipo"] == "negativo" for k in s["carpetas"]) and len(r["correcciones"]) == 4


def test_conteos():
    llm, ll = falso([json.dumps({**E.EJEMPLO, "conteos": [{"objeto": "clases", "numero": 3, "cita": "tres frutas"}]}),
                     _resp()])
    r = A.generar_spec("texto", llm)
    assert r["ok"] and r["intentos"] == 2 and "tres frutas" in ll[1][-1]["content"], A.resumen(r)
    s = E.completar(E.EJEMPLO["spec"])
    assert A.verificar_conteos(s, [{"objeto": "carpetas_pieza", "numero": 2, "cita": "x"},
                                   {"objeto": "carpetas", "numero": 4, "cita": "y"}]) == []

def test_mensaje_usuario():
    m = A.mensaje_usuario("hola", respuestas="hasta 3", vocabulario=["Gansito"], previa={"a": 1})
    assert "Gansito" in m and "hasta 3" in m and "ESPECIFICACION ANTERIOR" in m


def test_vocabulario():
    def mod(s):
        s["clases"][1]["nombre"] = "Platno"
        s["carpetas"][1]["nombre"] = "Platno"
        s["carpetas"][1]["clases"] = ["Platno"]
        s["carpetas"][2]["clases"] = ["Manzana", "Platno"]
    llm, _ = falso([_resp(mod)])
    r = A.generar_spec("texto", llm, vocabulario=["Pl\u00e1tano", "Gansito"])
    s = r["spec"]
    assert r["ok"], A.resumen(r)
    assert s["clases"][1]["nombre"] == "Platano" and s["clases"][0]["nombre"] == "Manzana"
    assert s["carpetas"][1]["nombre"] == "Platano" and s["carpetas"][2]["clases"] == ["Manzana", "Platano"]
    assert any("vocabulario" in x for x in r["correcciones"])
    p, cor = A.aplicar_vocabulario({"clases": [{"nombre": "Gancito"}, {"nombre": "Chocorrol"}]},
                                   ["Gansito", "Pinguino", "Chocorol"])
    assert [c["nombre"] for c in p["clases"]] == ["Gansito", "Chocorol"], p

if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
