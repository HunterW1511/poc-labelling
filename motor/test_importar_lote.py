"""P.4.R6: importar_lote sube un lote con UN GET (lo que ya existe) y UN POST (/import/predictions), sin duplicados.
Label Studio simulado (sin red). Uso (en el contenedor): python test_importar_lote.py"""
from types import SimpleNamespace as NS

import importar_lote as IL


class LS:
    """Simula requests.get/post de Label Studio y registra cada peticion."""
    def __init__(self, existentes):
        self.existentes, self.vistas = existentes, []

    def get(self, url, params=None, **kw):
        self.vistas.append(("GET", url.split("/api/", 1)[1], params))
        return NS(raise_for_status=lambda: None, json=lambda: self.existentes)

    def post(self, url, json=None, **kw):
        self.vistas.append(("POST", url.split("/api/", 1)[1], json))
        return NS(raise_for_status=lambda: None)


def _pred(task, ver="sam3-a-b"):
    return {"task": task, "model_version": ver, "score": 0.9, "result": [{"id": "r"}] * task}


def test_un_get_y_un_post_sin_duplicados():
    viejo = (IL.requests.get, IL.requests.post)
    ls = LS([{"task": 1, "model_version": "sam3-a-b", "result": []}, {"task": 2, "model_version": "otra"}])
    try:
        IL.requests.get, IL.requests.post = ls.get, ls.post
        subidas, omitidas = IL.subir_en_bloque(7, [_pred(1), _pred(2), _pred(3), _pred(3)])
        assert (subidas, omitidas) == (2, 2), (subidas, omitidas)             # 1 ya estaba; 3 repetida en el lote
        assert [v[:2] for v in ls.vistas] == [("GET", "predictions"), ("POST", "projects/7/import/predictions")], ls.vistas
        assert ls.vistas[0][2] == {"project": 7}
        enviadas = ls.vistas[1][2]
        assert [(p["task"], p["model_version"]) for p in enviadas] == [(2, "sam3-a-b"), (3, "sam3-a-b")]
        assert set(enviadas[0]) == {"task", "model_version", "score", "result"} and len(enviadas[1]["result"]) == 3

        ls.vistas.clear()                                                   # con sufijo: otra version, se sube
        assert IL.subir_en_bloque(7, [_pred(1)], sufijo="colab") == (1, 0)
        assert ls.vistas[1][2][0]["model_version"] == "sam3-a-b-colab"

        ls.vistas.clear()                                                   # todo repetido: sin POST
        assert IL.subir_en_bloque(7, [_pred(1)]) == (0, 1)
        assert [v[0] for v in ls.vistas] == ["GET"], ls.vistas
    finally:
        IL.requests.get, IL.requests.post = viejo


if __name__ == "__main__":
    test_un_get_y_un_post_sin_duplicados()
    print("TEST IMPORTAR LOTE OK: un GET y un POST por lote; omite lo que ya existe y lo repetido")
