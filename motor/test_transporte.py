"""P.2.5: transporte.py (Drive falso y espejo local en carpetas temporales). Uso: python test_transporte.py"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import transporte as T


def _falla(exc, f, *a, **kw):
    try:
        f(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"se esperaba {exc.__name__}")


def test_drive_carpetas_y_mensajes():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        assert "Falta LOTES_DRIVE" in str(_falla(SystemExit, T.Drive({}).requerir, "lotes"))
        assert "revisa Google Drive" in str(_falla(SystemExit, T.Drive({"LOTES_DRIVE": str(t / "no")}).requerir, "runs"))
        (t / "PoC" / "lotes").mkdir(parents=True)
        d = T.Drive({"LOTES_DRIVE": str(t / "PoC" / "lotes")})
        assert d.carpetas() == {"asistente": None, "lotes": t / "PoC" / "lotes", "datasets": None, "runs": None}
        assert d.requerir("asistente", crear=True) == t / "PoC" / "asistente"              # junto a lotes, como siempre
        otra = t / "otra_runs"
        otra.mkdir()
        assert T.Drive({"LOTES_DRIVE": str(t / "PoC" / "lotes"), "RUNS_DRIVE": str(otra)}).carpeta("runs") == otra
        _falla(ValueError, d.carpeta, "raro")


def test_enviar_archivar_y_traer():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        for tr in (T.Drive({"LOTES_DRIVE": str((t / "d" / "lotes").resolve())}), T.Espejo(t / "e")):
            if tr.nombre == "drive":
                (t / "d" / "lotes").mkdir(parents=True)
            src = t / "lote_p3_x.zip"
            src.write_bytes(b"zip")
            dest = tr.enviar("lotes", src)
            assert dest.read_bytes() == b"zip" and not list(dest.parent.glob("*.tmp")), tr
            assert tr.enviar("datasets", src).parent.name == "datasets"                    # crea la carpeta
            a = tr.archivar("lotes", "lote_p3_x.zip", "lote_p3_x_viejo.zip")
            assert a == dest.parent / "_archivo" / "lote_p3_x_viejo.zip" and not dest.exists()
            _falla(FileNotFoundError, tr.archivar, "lotes", "no_existe.zip")
            assert tr.traer() == []


def test_carpeta_de_y_elegir():
    assert T.carpeta_de("asist_s_20261103-100000.zip") == "asistente"
    assert T.carpeta_de("lote_p3_x.zip") == "lotes" and T.carpeta_de("dataset_p4_x.zip") == "datasets"
    assert T.carpeta_de("otra.zip") is None
    assert isinstance(T.elegir({}, "."), T.Drive) and isinstance(T.elegir({"TRANSPORTE": "Drive "}, "."), T.Drive)
    with tempfile.TemporaryDirectory() as t:
        k = T.elegir({"TRANSPORTE": "kaggle"}, t)
        assert isinstance(k, T.Kaggle) and k.raiz == Path(t) / "datos" / "kaggle" / "espejo"
        assert k.carpetas() == {c: k.raiz / c for c in T.CARPETAS}          # siempre hay ruta (sin avisos falsos)...
        assert not k.raiz.exists()                                          # ...pero leer no crea nada
        assert k.requerir("lotes", crear=True).is_dir()
    _falla(SystemExit, T.elegir, {"TRANSPORTE": "s3"}, ".")


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST TRANSPORTE OK")
