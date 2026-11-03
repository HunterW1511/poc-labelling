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


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST COLA_TRABAJOS OK")
