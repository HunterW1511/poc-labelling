"""Pruebas de buzon.py + trabajo.py (C.4) con un LLM FALSO, sin red ni GPU. Uso: python test_buzon.py"""
import json, tempfile, zipfile
from pathlib import Path

import buzon
import esquema_llm as E
import trabajo

MOTOR = Path(__file__).resolve().parent


def _llm(msgs, esquema):
    return json.dumps(E.EJEMPLO), {}


def test_armar_y_procesar():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        zp, e = buzon.armar(MOTOR, t / "buzon", "prueba", texto="hola", vocabulario=["A", ""], ahora=0)
        nombres = zipfile.ZipFile(zp).namelist()
        assert set(f"codigo/{m}" for m in buzon.MODULOS) <= set(nombres) and "entrada.json" in nombres
        assert e["vocabulario"] == ["A"] and e["audio"] is None and buzon.pendientes(t / "buzon") == [zp]
        d = t / "x"
        zipfile.ZipFile(zp).extractall(d)
        r = trabajo.procesar(d, zp.name, llm=_llm)
        assert r["resultado"]["ok"] and r["transcripcion"] == "hola" and r["slug"] == "prueba"
        (t / "buzon" / f"{zp.stem}_resultado.json").write_text(json.dumps(r), encoding="utf-8")
        assert buzon.pendientes(t / "buzon") == [] and len(buzon.resultados(t / "buzon", "prueba")) == 1
        s, err, _ = buzon.preparar_spec(r, "prueba")
        assert not err and s["proyecto"]["slug"] == "prueba"


def test_errores_de_entrada():
    with tempfile.TemporaryDirectory() as t:
        for kw in ({}, {"texto": "x", "audio": Path(t) / "no.m4a"}, {"texto": "x", "audio": Path(__file__)}):
            try:
                buzon.armar(MOTOR, t, "prueba", **kw)
                raise AssertionError(f"deberia fallar: {kw}")
            except ValueError:
                pass
        try:
            buzon.armar(MOTOR, t, "Mal Slug", texto="x")
            raise AssertionError("slug invalido aceptado")
        except ValueError:
            pass


def test_resultados_por_slug():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        for n in ("asist_caras_20261015-100000", "asist_caras_x_20261015-110000", "asist_caras_20261016-090000"):
            (t / f"{n}_resultado.json").write_text("{}")
        assert [f.name[:-15] for f in buzon.resultados(t, "caras")] == \
               ["asist_caras_20261015-100000", "asist_caras_20261016-090000"]
        assert len(buzon.resultados(t)) == 3 and buzon.resultados(t)[-1].name.startswith("asist_caras_2026101")


def test_preparar_spec_fuerza_slug_y_reporta_problemas():
    r = {"resultado": {"spec": E.completar(E.EJEMPLO["spec"]), "problemas": ["algo"]}}
    s, err, _ = buzon.preparar_spec(r, "otro")
    assert s["proyecto"]["slug"] == "otro" and err == ["asistente: algo"]
    assert buzon.preparar_spec({"resultado": {"spec": None}}, "x")[0] is None


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
