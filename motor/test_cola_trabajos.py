"""Pruebas de cola_trabajos.py (P.1) sobre una base temporal, sin datos reales. Uso: python test_cola_trabajos.py"""
import sqlite3, tempfile
from contextlib import closing
from pathlib import Path

import cola_trabajos as C


def _base(t):
    return C.abrir(Path(t) / "datos" / "trabajos.sqlite")


def _falla(exc, f, *a, **kw):
    try:
        f(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"se esperaba {exc.__name__}")


def test_tabla_de_transiciones_coherente():
    assert set(C.TRANSICIONES) == set(C.ESTADOS)
    assert all(a in C.ESTADOS for sig in C.TRANSICIONES.values() for a in sig)
    assert set(C.FINALES) == {"importado", "archivado"}


def test_esquema_y_sobrevive_al_reinicio():
    with tempfile.TemporaryDirectory() as t:
        with closing(_base(t)) as con:
            assert con.execute("PRAGMA user_version").fetchone()[0] == C.ESQUEMA
            assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            tr, nuevo = C.crear(con, "preetiquetado", "lote_p3_a.zip", proyecto="3", ahora=0)
            C.mover(con, tr["id"], "enviado", ahora=1)
        with closing(_base(t)) as con:                        # "reinicio del hub": conexion nueva
            x = C.buscar(con, "preetiquetado", "lote_p3_a.zip")
            assert nuevo and x["estado"] == "enviado" and x["proyecto"] == 3
            assert [(e["de"], e["a"]) for e in C.eventos(con, x["id"])] == [(None, "pendiente"), ("pendiente", "enviado")]


def test_esquema_mas_nuevo_se_niega():
    with tempfile.TemporaryDirectory() as t:
        ruta = Path(t) / "x.sqlite"
        with closing(sqlite3.connect(ruta)) as c:
            c.execute(f"PRAGMA user_version = {C.ESQUEMA + 1}")
        assert "mas nuevo" in str(_falla(RuntimeError, C.abrir, ruta))


def test_crear_idempotente_y_validaciones():
    with tempfile.TemporaryDirectory() as t, closing(_base(t)) as con:
        a, n1 = C.crear(con, "asistente", "asist_caja_20261103-100000.zip", slug="caja", estado="enviado")
        b, n2 = C.crear(con, "asistente", "asist_caja_20261103-100000.zip", slug="caja")
        assert n1 and not n2 and a["id"] == b["id"] and b["estado"] == "enviado"
        assert len(C.eventos(con, a["id"])) == 1
        _falla(ValueError, C.crear, con, "otro", "x.zip")
        _falla(ValueError, C.crear, con, "asistente", "carpeta/x.zip")
        _falla(ValueError, C.crear, con, "asistente", "c:\\x.zip")
        _falla(ValueError, C.crear, con, "asistente", "")
        _falla(ValueError, C.crear, con, "asistente", "y.zip", estado="listo")


def test_camino_feliz_y_transiciones_invalidas():
    with tempfile.TemporaryDirectory() as t, closing(_base(t)) as con:
        tr, _ = C.crear(con, "entrenamiento", "dataset_p4_x.zip", proyecto=4)
        _falla(ValueError, C.mover, con, tr["id"], "listo")           # pendiente -> listo no
        _falla(ValueError, C.mover, con, tr["id"], "raro")
        _falla(KeyError, C.mover, con, 999, "enviado")
        for a in ("enviado", "en_proceso"):
            C.mover(con, tr["id"], a)
        x = C.mover(con, tr["id"], "listo", resultado="dataset_p4_x_run1")
        x = C.mover(con, tr["id"], "importado", desde="listo")
        assert x["estado"] == "importado" and x["resultado"] == "dataset_p4_x_run1"
        _falla(ValueError, C.mover, con, tr["id"], "pendiente")       # final
        _falla(ValueError, C.mover, con, tr["id"], "listo", resultado="a/b")


def test_error_reintento_y_fallo_del_hub():
    with tempfile.TemporaryDirectory() as t, closing(_base(t)) as con:
        tr, _ = C.crear(con, "asistente", "asist_a_20261103-100000.zip", slug="a", estado="enviado")
        x = C.mover(con, tr["id"], "error", detalle="x" * (C.MAX_ERROR + 50) + "FIN")
        assert x["error"].endswith("FIN") and len(x["error"]) == C.MAX_ERROR
        x = C.mover(con, tr["id"], "pendiente")
        assert x["intentos"] == 1 and x["error"] is None
        C.mover(con, tr["id"], "enviado")
        C.mover(con, tr["id"], "listo", resultado="asist_a_20261103-100000_resultado.json")
        x = C.fallo(con, tr["id"], "importar_lote fallo")
        assert x["estado"] == "listo" and x["intentos"] == 2 and x["error"] == "importar_lote fallo"
        x = C.mover(con, tr["id"], "importado")
        assert x["error"] == "importar_lote fallo"                    # se conserva como historia
        assert C.eventos(con, tr["id"])[-2]["detalle"] == "fallo: importar_lote fallo"


def test_conflicto_entre_dos_procesos():
    with tempfile.TemporaryDirectory() as t, closing(_base(t)) as a, closing(_base(t)) as b:
        tr, _ = C.crear(a, "preetiquetado", "lote_p1_z.zip", proyecto=1, estado="enviado")
        C.mover(a, tr["id"], "listo")
        visto = C.obtener(b, tr["id"])["estado"]                      # b leyo "listo"...
        C.mover(a, tr["id"], "importado")                             # ...y a importo antes
        assert isinstance(_falla(C.Conflicto, C.mover, b, tr["id"], "archivado", desde=visto), ValueError)
        assert C.obtener(b, tr["id"])["estado"] == "importado"


def test_listar_filtros():
    with tempfile.TemporaryDirectory() as t, closing(_base(t)) as con:
        C.crear(con, "preetiquetado", "lote_p1_a.zip", proyecto=1)
        b, _ = C.crear(con, "preetiquetado", "lote_p2_b.zip", proyecto=2, estado="enviado")
        c, _ = C.crear(con, "asistente", "asist_s_20261103-100000.zip", slug="s", estado="enviado")
        C.mover(con, c["id"], "archivado")
        assert [x["archivo"] for x in C.listar(con, tipo="preetiquetado", proyecto=2)] == ["lote_p2_b.zip"]
        assert len(C.listar(con, estado=("pendiente", "enviado"))) == 2
        assert [x["id"] for x in C.listar(con, activos=True)] == [1, b["id"]]
        assert [x["slug"] for x in C.listar(con, estado="archivado")] == ["s"]


def _transporte(**kw):
    a = {"asistente": {}, "asistente_archivo": set(), "lotes": {}, "lotes_archivo": set(), "lotes_local": set(),
         "datasets": {}, "runs": set(), "registrados": set(), "specs": {}}
    a.update(kw)
    return a


def test_detectar_por_tipo():
    a = _transporte(asistente={"asist_s_20261103-100000.zip": 1, "asist_s_20261103-100000_resultado.json": 10,
                               "asist_e_20261103-100000.zip": 1, "asist_e_20261103-100000_error.txt": 5},
                    specs={"s": 20},
                    lotes={"lote_p3_a.zip": 1, "lote_p3_a_pred.json": 2, "lote_p3_b.zip": 1},
                    lotes_local={"lote_p3_a_pred.json"}, lotes_archivo={"lote_p3_c.zip"},
                    datasets={"dataset_p4_x.zip": 1}, runs={"dataset_p4_x_yolo", "dataset_p4_xy"},
                    registrados={"runs/dataset_p4_x_yolo"})
    d = C.detectar
    assert d("asistente", "asist_s_20261103-100000.zip", a) == ("importado", "asist_s_20261103-100000_resultado.json")
    a2 = {**a, "specs": {"s": 5}}
    assert d("asistente", "asist_s_20261103-100000.zip", a2)[0] == "listo"           # spec mas vieja que el resultado
    assert d("asistente", "asist_e_20261103-100000.zip", a) == ("error", "asist_e_20261103-100000_error.txt")
    assert d("preetiquetado", "lote_p3_a.zip", a) == ("importado", "lote_p3_a_pred.json")
    assert d("preetiquetado", "lote_p3_b.zip", a) == ("enviado", None)
    assert d("preetiquetado", "lote_p3_c.zip", a) == ("archivado", None)
    assert d("preetiquetado", "lote_p3_z.zip", a) == ("desaparecido", None)
    assert d("entrenamiento", "dataset_p4_x.zip", a) == ("importado", "dataset_p4_x_yolo")   # no confunde _xy
    assert d("entrenamiento", "dataset_p4_x.zip", {**a, "registrados": set()})[0] == "listo"
    assert d("entrenamiento", "dataset_p4_x.zip", {**a, "runs": None}) is None
    a4 = {**a, "lotes": {"pre_p3_c.zip": 1, "pre_p3_c_cache.json": 2, "pre_p3_e.zip": 1, "pre_p3_e_error.txt": 2}}
    assert d("precodificacion", "pre_p3_c.zip", a4) == ("listo", "pre_p3_c_cache.json")       # P.3.3
    assert d("precodificacion", "pre_p3_e.zip", a4) == ("error", "pre_p3_e_error.txt")
    assert d("precodificacion", "pre_p3_z.zip", a4) == ("desaparecido", None)
    assert ("precodificacion", "pre_p3_c.zip") in C._candidatos(a4) and ("preetiquetado", "pre_p3_c.zip") not in C._candidatos(a4)
    # P.2.4: el worker deja _error.txt tambien en lotes y datasets
    a3 = {**a, "lotes": {"lote_p3_e.zip": 1, "lote_p3_e_error.txt": 2}, "datasets": {"dataset_p9_e.zip": 1, "dataset_p9_e_error.txt": 2}}
    assert d("preetiquetado", "lote_p3_e.zip", a3) == ("error", "lote_p3_e_error.txt")
    assert d("entrenamiento", "dataset_p9_e.zip", a3) == ("error", "dataset_p9_e_error.txt")


def test_reconciliar_mueve_avisa_y_no_escribe():
    with tempfile.TemporaryDirectory() as t, closing(_base(t)) as con:
        ok, _ = C.crear(con, "preetiquetado", "lote_p3_a.zip", proyecto=3, estado="enviado", ahora=0)
        er, _ = C.crear(con, "asistente", "asist_e_20261103-100000.zip", slug="e", estado="enviado", ahora=0)
        ar, _ = C.crear(con, "preetiquetado", "lote_p3_c.zip", proyecto=3, estado="enviado", ahora=0)
        se, _ = C.crear(con, "preetiquetado", "lote_p3_d.zip", proyecto=3, estado="enviado", ahora=0)
        vi, _ = C.crear(con, "preetiquetado", "lote_p3_v.zip", proyecto=3, estado="enviado", ahora=0)
        a = _transporte(lotes={"lote_p3_a.zip": 1, "lote_p3_a_pred.json": 2, "lote_p3_v.zip": 1},
                        lotes_archivo={"lote_p3_c.zip"},
                        asistente={"asist_e_20261103-100000.zip": 1, "asist_e_20261103-100000_error.txt": 2})
        r = C.reconciliar(C.listar(con), a, horas=24, ahora=48 * 3600)
        movs = {x["id"]: (x["a"], x["resultado"], x["error_de"]) for x in r["acciones"]}
        assert movs == {ok["id"]: ("listo", "lote_p3_a_pred.json", None),
                        er["id"]: ("error", None, "asist_e_20261103-100000_error.txt"),
                        ar["id"]: ("archivado", None, None)}, movs
        assert any("lote_p3_d.zip" in v and "ya no esta" in v for v in r["avisos"]), r["avisos"]
        assert any("lote_p3_v.zip" in v and "48 h" in v for v in r["avisos"]), r["avisos"]
        assert C.obtener(con, ok["id"])["estado"] == "enviado"                       # reconciliar no escribe
        hechas, av = C.aplicar(con, r["acciones"], leer_error=lambda n: f"Traceback de {n}")
        assert hechas == 3 and not av
        assert C.obtener(con, ok["id"])["estado"] == "listo"
        assert C.obtener(con, er["id"])["error"] == "Traceback de asist_e_20261103-100000_error.txt"
        assert C.reconciliar(C.listar(con), a, ahora=48 * 3600)["acciones"] == []    # idempotente


def test_adoptar_huerfanos():
    with tempfile.TemporaryDirectory() as t, closing(_base(t)) as con:
        a = _transporte(asistente={"asist_s_20261103-100000.zip": 1, "asist_s_20261103-100000_resultado.json": 10},
                        lotes={"lote_p3_a_pred.json": 2, "lote_p3_b.zip": 1, "otra_cosa.zip": 1},
                        lotes_local={"lote_p3_a_pred.json"},
                        datasets={"dataset_p4_a.zip": 1, "dataset_p4_b.zip": 2, "dataset_p5_a.zip": 1},
                        runs={"dataset_p5_a"})
        r = C.reconciliar([], a)
        ad = {x["archivo"]: x["estado"] for x in r["acciones"]}
        assert ad == {"asist_s_20261103-100000.zip": "listo", "lote_p3_a.zip": "importado", "lote_p3_b.zip": "enviado",
                      "dataset_p4_b.zip": "enviado", "dataset_p5_a.zip": "listo"}, ad
        assert any("dataset_p4_a.zip" in v for v in r["avisos"])                     # dataset viejo sin run
        hechas, av = C.aplicar(con, r["acciones"])
        assert hechas == 5 and not av
        x = C.buscar(con, "preetiquetado", "lote_p3_a.zip")
        assert x["estado"] == "importado" and x["proyecto"] == 3 and x["resultado"] == "lote_p3_a_pred.json"
        assert [e["a"] for e in C.eventos(con, x["id"])] == ["enviado", "listo", "importado"]
        assert C.buscar(con, "asistente", "asist_s_20261103-100000.zip")["slug"] == "s"
        assert C.reconciliar(C.listar(con), a)["acciones"] == []
        assert any("no encuentro" in v for v in C.reconciliar([], {**a, "runs": None, "datasets": None})["avisos"])


def test_migracion_1_a_2_conserva_trabajos():
    with tempfile.TemporaryDirectory() as t:
        ruta = Path(t) / "v1.sqlite"
        with closing(sqlite3.connect(ruta)) as c:                    # una base creada por P.1 (esquema 1)
            c.executescript(C._DDL)
            c.execute("INSERT INTO trabajos (tipo, estado, archivo, creado, actualizado) VALUES "
                      "('preetiquetado', 'enviado', 'lote_p1_a.zip', 'x', 'x')")
            c.execute("PRAGMA user_version = 1")
            c.commit()
        with closing(C.abrir(ruta)) as con:
            assert con.execute("PRAGMA user_version").fetchone()[0] == C.ESQUEMA    # llega hasta el ultimo esquema
            tr = C.buscar(con, "preetiquetado", "lote_p1_a.zip")
            assert tr["estado"] == "enviado" and tr["envio"] is None and tr["operador"] is None and tr["grupo"] is None
            assert [x["archivo"] for x in C.por_enviar(con)] == ["lote_p1_a.zip"]
            e = C.crear_envio(con, "envio_1", "kaggle", "emi", [tr["id"]])
            assert e["estado"] == "lanzado" and C.por_enviar(con) == []
            _falla(C.Conflicto, C.crear_envio, con, "envio_2", "kaggle", "emi", [tr["id"]])   # ya va en un envio
            _falla(ValueError, C.marcar_envio, con, "envio_1", "raro")
            _falla(KeyError, C.marcar_envio, con, "no_existe", "corriendo")
            C.marcar_envio(con, "envio_1", "corriendo")
            assert C.obtener(con, tr["id"])["estado"] == "en_proceso"
            assert [x["id"] for x in C.sin_salida(con, "envio_1", "no volvio")] == [tr["id"]]
            assert C.ultimo_envio(con, "kaggle")["nombre"] == "envio_1" and C.ultimo_envio(con, "colab") is None
            assert [e["nombre"] for e in C.envios_pendientes(con, "kaggle")] == ["envio_1"]       # P.4.R1
            C.marcar_envio(con, "envio_1", "parcial")                    # P.4.R6: falta la cache -> sigue pendiente
            assert [e["estado"] for e in C.envios_pendientes(con, "kaggle")] == ["parcial"]
            C.marcar_envio(con, "envio_1", "traido")
            assert C.envios_pendientes(con, "kaggle") == [] and C.envio(con, "envio_1")["version"] is None


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST COLA_TRABAJOS OK")
