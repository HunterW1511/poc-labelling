"""P.2.6: kaggle_xd.py y xd.py kaggle-pesos con la CLI de Kaggle SIMULADA (sin red ni cuenta). Uso: python test_kaggle.py"""
import io, json, os, shutil, sys, tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace as NS

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import kaggle_xd as K
import xd

TOKEN = "KGAT_0123456789abcdefSECRETO"
K.comando = lambda: ["kaggle"]                       # sin depender de que la CLI este instalada


def _falla(exc, f, *a, **kw):
    try:
        f(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"se esperaba {exc.__name__}")


class CLI:
    """Simula subprocess.run de la CLI: registra los comandos y responde segun un guion."""
    def __init__(self, respuestas):
        self.respuestas, self.vistos = list(respuestas), []

    def __call__(self, cmd, **kw):
        self.vistos.append(cmd[1:])
        rc, out = self.respuestas.pop(0) if self.respuestas else (0, "ready")
        return NS(returncode=rc, stdout=out, stderr="")


def test_ocultar_y_credencial():
    assert TOKEN not in K.ocultar(f"token {TOKEN} fin") and "***" in K.ocultar(TOKEN)
    assert "0123456789abcdef0123456789abcdef" not in K.ocultar("key 0123456789abcdef0123456789abcdef")
    assert '"key": "***"' in K.ocultar('{"username": "u", "key": "abc"}')
    with tempfile.TemporaryDirectory() as t:
        env = {"KAGGLE_CONFIG_DIR": t}
        assert K.credencial(env) is None
        (Path(t) / "kaggle.json").write_text('{"key": "x"}')
        assert K.credencial(env) == "kaggle.json (legacy)"
        (Path(t) / "access_token").write_text(TOKEN)
        assert K.credencial(env) == "access_token"                          # el token nuevo manda
        assert K.credencial({**env, "KAGGLE_API_TOKEN": TOKEN}) == "KAGGLE_API_TOKEN"
    _falla(SystemExit, K.usuario, {})
    _falla(SystemExit, K.usuario, {"KAGGLE_USUARIO": "a b"})
    assert K.usuario({"KAGGLE_USUARIO": " emiliano-r "}) == "emiliano-r"


def test_cli_nunca_publico_y_oculta():
    c = CLI([(0, f"ok {TOKEN}")])
    rc, out = K.cli("datasets", "status", "u/x", correr=c)
    assert rc == 0 and TOKEN not in out and c.vistos == [["datasets", "status", "u/x"]]
    for publico in ("-u", "--public"):
        _falla(ValueError, K.cli, "datasets", "create", publico, correr=c)
    c = CLI([])
    K.subir("carpeta", False, "m", correr=c)
    K.subir("carpeta", True, "nota", correr=c)
    assert c.vistos == [["datasets", "create", "-p", "carpeta", "-r", "skip"],
                        ["datasets", "version", "-p", "carpeta", "-m", "nota", "-r", "skip"]]
    assert all("-u" not in v and "--public" not in v for v in c.vistos)


def test_estado_y_espera():
    assert K.estado_dataset("u/x", correr=CLI([(0, "ready\n")])) == "ready"
    assert K.estado_dataset("u/x", correr=CLI([(1, "404 Not Found")])) is None
    t = [0.0]
    c = CLI([(0, "pending"), (0, "pending"), (0, "ready")])
    seg = K.esperar_listo("u/x", limite=100, cada=10, correr=c, dormir=lambda s: t.__setitem__(0, t[0] + s),
                          reloj=lambda: t[0])
    assert seg == 20.0 and len(c.vistos) == 3
    t[0] = 0.0
    assert K.esperar_listo("u/x", limite=15, cada=10, correr=CLI([(0, "pending")] * 5),
                           dormir=lambda s: t.__setitem__(0, t[0] + s), reloj=lambda: t[0]) is None


def test_armar_pesos():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "sam3.pt").write_bytes(b"pesos falsos")
        (t / "LIC.txt").write_text("SAM License", encoding="utf-8")
        info = K.armar_pesos(t / "sam3.pt", t / "LIC.txt", t / "sube", "emiliano")
        assert sorted(f.name for f in (t / "sube").iterdir()) == ["LICENSE_SAM.txt", "dataset-metadata.json",
                                                                  "pesos.json", "sam3.pt"]
        meta = json.loads((t / "sube" / "dataset-metadata.json").read_text())
        assert meta["id"] == "emiliano/xd-pesos" and 6 <= len(meta["title"]) <= 50 and "isPrivate" not in meta
        assert json.loads((t / "sube" / "pesos.json").read_text())["sha256"] == K.sha256(t / "sam3.pt")
        assert info["modo"] in ("enlace", "copia") and info["bytes"] == 12
        _falla(SystemExit, K.armar_pesos, t / "no.pt", t / "LIC.txt", t / "x", "u")
        _falla(SystemExit, K.armar_pesos, t / "sam3.pt", t / "no.txt", t / "x", "u")
        _falla(ValueError, K.metadata, "u", "XD", "titulo largo")
        _falla(ValueError, K.metadata, "u", "xd-pesos", "corto")


def test_comando_kaggle_pesos_reporte_y_aplicar():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "motor" / "plantillas").mkdir(parents=True)
        shutil.copy2(RAIZ / "motor" / "plantillas" / "SAM_LICENSE.txt", t / "motor" / "plantillas")
        (t / "sam3.pt").write_bytes(b"pesos falsos")
        (t / "cfg").mkdir()
        (t / "cfg" / "access_token").write_text(TOKEN)
        viejo = (xd.RAIZ, xd.ENV, os.environ.get("KAGGLE_CONFIG_DIR"), K.estado_dataset, K.subir, K.esperar_listo)
        llamadas = []
        try:
            xd.RAIZ, xd.ENV = t, {"KAGGLE_USUARIO": "emiliano"}
            os.environ["KAGGLE_CONFIG_DIR"] = str(t / "cfg")
            K.estado_dataset = lambda ds, **kw: None
            K.subir = lambda carpeta, existe, msg, **kw: (llamadas.append((sorted(p.name for p in Path(carpeta).iterdir()), existe, msg)) or (0, f"subido {TOKEN}"))
            K.esperar_listo = lambda ds, **kw: 42.0
            out = io.StringIO()
            with redirect_stdout(out):
                rc = xd.cmd_kaggle_pesos(NS(pesos="", aplicar=False))
            assert rc == 0 and "SOLO REPORTE" in out.getvalue() and "se CREA" in out.getvalue() and not llamadas
            out = io.StringIO()
            with redirect_stdout(out):
                rc = xd.cmd_kaggle_pesos(NS(pesos="", aplicar=True))
            txt = out.getvalue()
            assert rc == 0 and "OK emiliano/xd-pesos" in txt and "42.0" in txt, txt
            assert llamadas[0][0] == ["LICENSE_SAM.txt", "dataset-metadata.json", "pesos.json", "sam3.pt"]
            assert llamadas[0][1] is False and llamadas[0][2].startswith("sam3.pt sha256 ")
            assert TOKEN not in txt                                             # el token nunca se imprime
            assert not (t / "datos" / "kaggle" / "xd-pesos").exists()           # carpeta temporal borrada
            assert (t / "sam3.pt").read_bytes() == b"pesos falsos"              # el original intacto
            (t / "cfg" / "access_token").unlink()
            assert "Sin credencial" in str(_falla(SystemExit, xd.cmd_kaggle_pesos, NS(pesos="", aplicar=True)))
        finally:
            xd.RAIZ, xd.ENV, cfg, K.estado_dataset, K.subir, K.esperar_listo = viejo
            if cfg is None:
                os.environ.pop("KAGGLE_CONFIG_DIR", None)
            else:
                os.environ["KAGGLE_CONFIG_DIR"] = cfg


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST KAGGLE OK")
