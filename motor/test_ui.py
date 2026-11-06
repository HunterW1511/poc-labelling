"""P.7.3: reglas de la UI con el automatico (daemon): probar un ciclo es una accion de reporte; activarlo exige ese
reporte OK; con el daemon activo no se aplican a mano sus pasos; parar deja el pedido. Sin lanzar procesos.
Uso: python test_ui.py"""
import json, sys, tempfile, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import ui

xd = ui.tablero.xd


def _falla(exc, f, *a):
    try:
        f(*a)
    except exc as e:
        return str(e)
    raise AssertionError(f"se esperaba {exc.__name__}")


def test_daemon_desde_la_ui():
    viejo = xd.TRABAJOS_DB
    with tempfile.TemporaryDirectory() as t:
        try:
            xd.TRABAJOS_DB = Path(t) / "trabajos.sqlite"
            assert ui.armar({"accion": "daemon", "opciones": {"--una-vez": True}}) == ("daemon", ["--una-vez"], "xd.py")
            assert "no tiene modo --aplicar" in _falla(ValueError, ui.armar, {"accion": "daemon", "aplicar": True})
            assert "Probar un ciclo" in _falla(PermissionError, ui.daemon, {"op": "iniciar", "intervalo": 5})
            assert "entre 1 y 60" in _falla(ValueError, ui.daemon, {"op": "iniciar", "intervalo": 0})
            assert "op invalida" in _falla(ValueError, ui.daemon, {"op": "otra"})
            assert ui.daemon({"op": "parar"})["activo"] is False                 # nada que parar: no deja pedido
            assert not (Path(t) / "daemon.parar").exists()

            (Path(t) / "daemon.json").write_text(json.dumps(                     # daemon activo (latido fresco)
                {"pid": 1, "estado": "esperando", "ciclo": 3, "aplicar": True, "latido": time.time()}), encoding="utf-8")
            assert "ya esta activo" in _falla(RuntimeError, ui.daemon, {"op": "iniciar", "intervalo": 5})
            for d in ({"accion": "worker", "opciones": {"--traer": True}, "aplicar": True},
                      {"accion": "lote-importar", "opciones": {"--fijar-version": True}},
                      {"accion": "trabajos", "opciones": {"--reconciliar": True}, "aplicar": True}):
                assert "automatico" in _falla(PermissionError, ui.armar, d), d
            assert ui.armar({"accion": "worker", "opciones": {"--estado": True}})[0] == "worker"   # el reporte si
            assert ui.daemon({"op": "parar"})["activo"] is True
            assert (Path(t) / "daemon.parar").exists()                           # el daemon lo ve y termina
        finally:
            xd.TRABAJOS_DB = viejo



def test_caso_nuevo_y_su_titulo():
    """P.7.4: caso-nuevo crea motor/proyectos/<slug>/caso.json (reporte primero, no pisa uno existente) y su titulo
    manda en spec-nueva (y en asistente-importar)."""
    import io
    from contextlib import redirect_stdout
    from types import SimpleNamespace as NS
    viejo = xd.RAIZ
    with tempfile.TemporaryDirectory() as t:
        try:
            xd.RAIZ = Path(t)
            d = Path(t) / "motor" / "proyectos" / "tornillos"
            with redirect_stdout(io.StringIO()) as out:
                assert xd.cmd_caso_nuevo(NS(slug="tornillos", titulo="Conteo de tornillos", aplicar=False)) == 0
            assert "SOLO REPORTE" in out.getvalue() and not d.exists()
            assert "Falta --titulo" in _falla(SystemExit, xd.cmd_caso_nuevo, NS(slug="tornillos", titulo=" ", aplicar=True))
            with redirect_stdout(io.StringIO()):
                assert xd.cmd_caso_nuevo(NS(slug="tornillos", titulo="Conteo de tornillos", aplicar=True)) == 0
            assert json.loads((d / "caso.json").read_text(encoding="utf-8"))["titulo"] == "Conteo de tornillos"
            assert xd.titulo_caso("tornillos") == "Conteo de tornillos" and xd.titulo_caso("otro") is None
            assert "Ya existe" in _falla(SystemExit, xd.cmd_caso_nuevo, NS(slug="tornillos", titulo="X", aplicar=True))
            with redirect_stdout(io.StringIO()):
                xd.cmd_spec_nueva(NS(slug="tornillos", titulo="", aplicar=True))
            spec = json.loads((d / "spec.json").read_text(encoding="utf-8"))
            assert spec["proyecto"]["titulo"] == "Conteo de tornillos", spec["proyecto"]
            assert ui.armar({"accion": "caso-nuevo", "slug": "x", "opciones": {"--titulo": "Mi caso"}})[1] == ["x", "--titulo", "Mi caso"]
        finally:
            xd.RAIZ = viejo


if __name__ == "__main__":
    test_caso_nuevo_y_su_titulo()
    test_daemon_desde_la_ui()
    print("TEST UI OK: daemon desde la UI con reporte previo; sus pasos no se aplican a mano mientras corre")
