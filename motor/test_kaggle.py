"""P.2.6: kaggle_xd.py y xd.py kaggle-pesos con la CLI de Kaggle SIMULADA (sin red ni cuenta). Uso: python test_kaggle.py"""
import io, json, os, shutil, sys, tempfile
from contextlib import closing, redirect_stdout
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


def test_envio_kernel_y_estado():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "lote_p3_x.zip").write_bytes(b"z1")
        (t / "asist_s_1.zip").write_bytes(b"z2")
        e = K.armar_envio([("lotes", t / "lote_p3_x.zip"), ("asistente", t / "asist_s_1.zip")], t / "env", "emi", "envio_1", "emi")
        assert [x["tipo"] for x in e["trabajos"]] == ["preetiquetado", "asistente"]
        assert json.loads((t / "env" / "dataset-metadata.json").read_text())["id"] == "emi/xd-envios"
        assert sorted(f.name for f in (t / "env").iterdir()) == ["asist_s_1.zip.xd", "dataset-metadata.json", "envio.json",
                                                                  "lote_p3_x.zip.xd"]                # Kaggle descomprime los .zip
        assert e["trabajos"][0]["archivo"] == "lote_p3_x.zip" and e["trabajos"][0]["en_envio"] == "lote_p3_x.zip.xd"
        _falla(ValueError, K.armar_envio, [], t / "env2", "emi", "e", "emi")
        (t / "pre_p3_y.zip").write_bytes(b"z3")                                       # P.3.3: viaja en lotes
        e2 = K.armar_envio([("lotes", t / "pre_p3_y.zip")], t / "env3", "emi", "envio_2", "emi")
        assert e2["trabajos"][0]["tipo"] == "precodificacion" and K.tipo_de("otra.zip") is None
        m = K.kernel_metadata("emi")
        assert m["is_private"] is True and m["enable_gpu"] is True and m["title"] == "xd-worker"
        assert m["id"] == "emi/xd-worker" and m["dataset_sources"] == ["emi/xd-pesos", "emi/xd-envios"]
        K.armar_kernel(RAIZ / "motor" / "lanzador.py", t / "k", "emi")
        assert sorted(f.name for f in (t / "k").iterdir()) == ["kernel-metadata.json", "lanzador.py"]
    c = CLI([])
    K.subir_envio("c", True, "envio_1", correr=c)
    K.push_kernel("k", limite_s=600, correr=c)
    assert c.vistos[0] == ["datasets", "version", "-p", "c", "-m", "envio_1", "-r", "skip", "-d"]   # borra versiones viejas
    assert c.vistos[1] == ["kernels", "push", "-p", "k", "--accelerator", "NvidiaTeslaT4", "-t", "600"]
    assert K.estado_kernel("emi/xd-worker", correr=CLI([(0, 'emi/xd-worker has status "KernelWorkerStatus.RUNNING"')])) == ("running", "")
    est, msg = K.estado_kernel("k", correr=CLI([(0, 'k has status "KernelWorkerStatus.ERROR"\nFailure message: "OOM"')]))
    assert (est, msg) == ("error", "OOM")
    assert K.estado_kernel("k", correr=CLI([(1, "404 Not Found")]))[0] is None


def test_integrar_solo_carpetas_de_trabajo():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        for rel in ("lotes/lote_p3_x_pred.json", "runs/dataset_p4_x/weights/best.pt", "xd-worker.log", "otra/x.txt"):
            (t / "sal" / rel).parent.mkdir(parents=True, exist_ok=True)
            (t / "sal" / rel).write_text("x")
        hechas = K.integrar(t / "sal", t / "espejo")
        assert hechas == ["lotes/lote_p3_x_pred.json", "runs/dataset_p4_x/weights/best.pt"]
        assert (t / "espejo" / "runs" / "dataset_p4_x" / "weights" / "best.pt").exists()
        assert not (t / "espejo" / "xd-worker.log").exists() and not (t / "espejo" / "otra").exists()


def test_comando_worker():
    import cola_trabajos as C
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "motor").mkdir()
        shutil.copy2(RAIZ / "motor" / "lanzador.py", t / "motor")
        esp = t / "datos" / "kaggle" / "espejo" / "lotes"
        esp.mkdir(parents=True)
        for n in ("lote_p3_x.zip", "lote_p3_z.zip", "lote_p3_huerfano.zip"):
            (esp / n).write_bytes(b"zip")
        (t / "cfg").mkdir()
        (t / "cfg" / "access_token").write_text(TOKEN)
        db = t / "datos" / "trabajos.sqlite"
        with closing(C.abrir(db)) as con:
            x, _ = C.crear(con, "preetiquetado", "lote_p3_x.zip", proyecto=3, estado="enviado")
            z, _ = C.crear(con, "preetiquetado", "lote_p3_z.zip", proyecto=3, estado="enviado")
        nombres = ("estado_kernel", "estado_dataset", "subir_envio", "esperar_listo", "push_kernel", "bajar_salida")
        viejo = (xd.RAIZ, xd.ENV, xd.TRABAJOS_DB, os.environ.get("KAGGLE_CONFIG_DIR"), {n: getattr(K, n) for n in nombres})
        llamadas, est = [], ["complete"]
        try:
            xd.RAIZ, xd.ENV, xd.TRABAJOS_DB = t, {"KAGGLE_USUARIO": "emi", "TRANSPORTE": "kaggle"}, db
            os.environ["KAGGLE_CONFIG_DIR"] = str(t / "cfg")
            K.estado_kernel = lambda k, **kw: (est[0], "")
            K.estado_dataset = lambda ds, **kw: "ready"
            K.subir_envio = lambda c, existe, n, **kw: (llamadas.append(("subir", sorted(p.name for p in Path(c).iterdir()), existe)) or (0, f"ok {TOKEN}"))
            K.esperar_listo = lambda ds, **kw: 5.0
            K.push_kernel = lambda c, limite_s=0, **kw: (llamadas.append(("push", json.loads((Path(c) / "kernel-metadata.json").read_text())["is_private"], limite_s)) or (0, "Kernel version 1 successfully pushed"))
            def bajar(k, dest, **kw):                     # el kernel solo devolvio resultado para x
                (Path(dest) / "lotes").mkdir(parents=True, exist_ok=True)
                (Path(dest) / "lotes" / "lote_p3_x_pred.json").write_text("{}")
                (Path(dest) / "xd-worker.log").write_text(f"log {TOKEN}")
                return 0, ""
            K.bajar_salida = bajar
            def correr(**kw):
                a = NS(**{"enviar": False, "estado": False, "traer": False, "limite": 0, "aplicar": False, **kw})
                out = io.StringIO()
                with redirect_stdout(out):
                    rc = xd.cmd_worker(a)
                return rc, out.getvalue()
            def fila(i):
                with closing(C.abrir(db)) as con:
                    return C.obtener(con, i)
            rc, out = correr(enviar=True)
            assert rc == 0 and "lote_p3_x.zip" in out and "SOLO REPORTE" in out and not llamadas, out
            assert "lote_p3_huerfano.zip: esta en el espejo pero no en la cola" in out
            rc, out = correr(enviar=True, aplicar=True, limite=30)
            assert rc == 0 and "OK envio_" in out and TOKEN not in out, out
            assert llamadas == [("subir", ["dataset-metadata.json", "envio.json", "lote_p3_x.zip.xd", "lote_p3_z.zip.xd"], True),
                                ("push", True, 1800)]
            assert fila(x["id"])["envio"].startswith("envio_") and fila(x["id"])["operador"] == "emi"
            assert not (t / "datos" / "kaggle" / "envio").exists() and not (t / "datos" / "kaggle" / "kernel").exists()
            assert "Nada que enviar" in correr(enviar=True)[1]                       # ya van en un envio
            est[0] = "running"
            rc, out = correr(estado=True)
            assert "lanzado -> corriendo" in out and "SOLO REPORTE" in out and fila(x["id"])["estado"] == "enviado", out
            correr(estado=True, aplicar=True)
            assert fila(x["id"])["estado"] == "en_proceso" and fila(z["id"])["estado"] == "en_proceso"
            with closing(C.abrir(db)) as con:
                C.crear(con, "preetiquetado", "lote_p3_huerfano.zip", proyecto=3, estado="enviado")
            assert "sigue running" in str(_falla(SystemExit, xd.cmd_worker, NS(enviar=True, estado=False, traer=False, limite=0, aplicar=True)))
            rc, out = correr(traer=True, aplicar=True)                              # aun corriendo: aviso, no error
            assert rc == 0 and "sigue en Kaggle (running" in out and "nada que traer" in out, out
            assert fila(x["id"])["estado"] == "en_proceso"
            est[0] = "complete"
            rc, out = correr(traer=True)
            assert "COPIARIA lotes/lote_p3_x_pred.json" in out and TOKEN not in out and not (esp / "lote_p3_x_pred.json").exists(), out
            rc, out = correr(traer=True, aplicar=True)
            assert rc == 0 and (esp / "lote_p3_x_pred.json").exists() and not (esp.parent / "xd-worker.log").exists(), out
            assert fila(x["id"])["estado"] == "listo" and fila(z["id"])["estado"] == "error", out   # z no volvio
            assert "sin resultado" in fila(z["id"])["error"] and "1 sin resultado" in out
            with closing(C.abrir(db)) as con:
                assert C.ultimo_envio(con, "kaggle")["estado"] == "traido"
                C.mover(con, z["id"], "pendiente")                                   # reintento: sale de su envio
                C.mover(con, z["id"], "enviado")
                assert C.obtener(con, z["id"])["envio"] is None
            rc, out = correr(enviar=True)
            assert "lote_p3_z.zip" in out and "lote_p3_huerfano.zip" in out, out          # se puede volver a enviar
            xd.ENV = {"KAGGLE_USUARIO": "emi"}
            assert "TRANSPORTE=kaggle" in str(_falla(SystemExit, xd.cmd_worker, NS(enviar=True, estado=False, traer=False, limite=0, aplicar=False)))
        finally:
            xd.RAIZ, xd.ENV, xd.TRABAJOS_DB, cfg, f = viejo
            for n, v in f.items():
                setattr(K, n, v)
            if cfg is None:
                os.environ.pop("KAGGLE_CONFIG_DIR", None)
            else:
                os.environ["KAGGLE_CONFIG_DIR"] = cfg

def test_envios_escalonados_por_trozo():
    """P.4.R1: un envio por llamada con el trozo mas bajo; el siguiente cuando el kernel anterior termina;
    --traer baja cada envio por SU version del kernel."""
    import cola_trabajos as C
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "motor").mkdir()
        shutil.copy2(RAIZ / "motor" / "lanzador.py", t / "motor")
        esp = t / "datos" / "kaggle" / "espejo"
        nombres = {"lotes": ["lote_p3_x_t01.zip", "lote_p3_x_t02.zip", "pre_p3_y_t01.zip", "pre_p3_y_t02.zip"],
                   "asistente": ["asist_s_20261105-100000.zip"]}
        for c, ns in nombres.items():
            (esp / c).mkdir(parents=True)
            for n in ns:
                (esp / c / n).write_bytes(b"zip")
        (t / "cfg").mkdir()
        (t / "cfg" / "access_token").write_text(TOKEN)
        db = t / "datos" / "trabajos.sqlite"
        with closing(C.abrir(db)) as con:
            for n in nombres["lotes"]:
                C.crear(con, "precodificacion" if n.startswith("pre_") else "preetiquetado", n, proyecto=3, estado="enviado",
                        grupo=n[:-8])
            C.crear(con, "asistente", nombres["asistente"][0], slug="s", estado="enviado")
        ks = ("estado_kernel", "estado_dataset", "subir_envio", "esperar_listo", "push_kernel", "bajar_salida")
        viejo = (xd.RAIZ, xd.ENV, xd.TRABAJOS_DB, os.environ.get("KAGGLE_CONFIG_DIR"), {n: getattr(K, n) for n in ks})
        estado, subidos, bajados, version = {}, [], [], [0]
        try:
            xd.RAIZ, xd.ENV, xd.TRABAJOS_DB = t, {"KAGGLE_USUARIO": "emi", "TRANSPORTE": "kaggle"}, db
            os.environ["KAGGLE_CONFIG_DIR"] = str(t / "cfg")
            K.estado_kernel = lambda k, **kw: (estado.get(k), "")
            K.estado_dataset = lambda ds, **kw: "ready"
            K.subir_envio = lambda c, existe, n, **kw: (subidos.append(sorted(p.name for p in Path(c).iterdir() if p.suffix == ".xd")) or (0, ""))
            K.esperar_listo = lambda ds, **kw: 1.0
            def push(c, limite_s=0, **kw):
                version[0] += 1
                return 0, f"Kernel version {version[0]} successfully pushed.  Please check progress at https://x"
            K.push_kernel = push
            def bajar(k, dest, **kw):
                bajados.append(k)
                (Path(dest) / "lotes").mkdir(parents=True, exist_ok=True)
                for n in (["lote_p3_x_t01", "pre_p3_y_t01"] if k.endswith("/1") else ["lote_p3_x_t02", "pre_p3_y_t02"]):
                    (Path(dest) / "lotes" / (f"{n}_pred.json" if n.startswith("lote") else f"{n}_cache.json")).write_text("{}")
                return 0, ""
            K.bajar_salida = bajar
            def correr(**kw):
                a = NS(**{"enviar": False, "estado": False, "traer": False, "limite": 0, "aplicar": False, **kw})
                out = io.StringIO()
                with redirect_stdout(out):
                    rc = xd.cmd_worker(a)
                return rc, out.getvalue()
            rc, out = correr(enviar=True, aplicar=True)
            assert rc == 0 and "trozo 1" in out and "kernel v1" in out and "Quedan 2" in out, out
            assert subidos[0] == ["asist_s_20261105-100000.zip.xd", "lote_p3_x_t01.zip.xd", "pre_p3_y_t01.zip.xd"]
            estado["emi/xd-worker/1"] = "running"
            assert "sigue running" in str(_falla(SystemExit, xd.cmd_worker, NS(enviar=True, estado=False, traer=False, limite=0, aplicar=True)))
            estado["emi/xd-worker/1"] = "complete"                                      # termina el 1: sale el trozo 2
            rc, out = correr(enviar=True, aplicar=True)
            assert rc == 0 and "trozo 2" in out and "kernel v2" in out and subidos[1] == ["lote_p3_x_t02.zip.xd", "pre_p3_y_t02.zip.xd"], out
            estado["emi/xd-worker/2"] = "running"
            rc, out = correr(traer=True, aplicar=True)                                  # el 1 se trae aunque el 2 corra
            assert bajados == ["emi/xd-worker/1"] and "sigue en Kaggle (running" in out, out
            with closing(C.abrir(db)) as con:
                est = {x["archivo"]: x["estado"] for x in C.listar(con)}
                assert est["lote_p3_x_t01.zip"] == "listo" and est["pre_p3_y_t01.zip"] == "listo"
                assert est["lote_p3_x_t02.zip"] == "enviado" and est["asist_s_20261105-100000.zip"] == "error"   # no volvio
                assert [e["version"] for e in C.envios_pendientes(con, "kaggle")] == [2]
            estado["emi/xd-worker/2"] = "complete"
            rc, out = correr(traer=True, aplicar=True)
            assert bajados == ["emi/xd-worker/1", "emi/xd-worker/2"], bajados
            with closing(C.abrir(db)) as con:
                assert {x["archivo"]: x["estado"] for x in C.listar(con)}["pre_p3_y_t02.zip"] == "listo"
                assert C.envios_pendientes(con, "kaggle") == []
            assert K.version_push("Kernel version 12 successfully pushed.") == 12 and K.version_push("otra cosa") is None
        finally:
            xd.RAIZ, xd.ENV, xd.TRABAJOS_DB, cfg, f = viejo
            for n, v in f.items():
                setattr(K, n, v)
            if cfg is None:
                os.environ.pop("KAGGLE_CONFIG_DIR", None)
            else:
                os.environ["KAGGLE_CONFIG_DIR"] = cfg


def test_daemon_ciclo_completo():
    """P.5.R1: el daemon encadena estado -> traer -> importar (lotes y cache) -> siguiente trozo; sin --aplicar no escribe."""
    import cola_trabajos as C
    import cache_sam3 as CS
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "motor").mkdir()
        shutil.copy2(RAIZ / "motor" / "lanzador.py", t / "motor")
        esp = t / "datos" / "kaggle" / "espejo" / "lotes"
        esp.mkdir(parents=True)
        for n in ("lote_p3_x_t01.zip", "lote_p3_x_t02.zip"):
            (esp / n).write_bytes(b"zip")
        (t / "cfg").mkdir()
        (t / "cfg" / "access_token").write_text(TOKEN)
        db = t / "datos" / "trabajos.sqlite"
        with closing(C.abrir(db)) as con:
            for n in ("lote_p3_x_t01.zip", "lote_p3_x_t02.zip"):
                C.crear(con, "preetiquetado", n, proyecto=3, estado="enviado", grupo="lote_p3_x")
        clave = CS.clave("a" * 64, 644, "b" * 64, "8.4.174")
        ks = ("estado_kernel", "estado_dataset", "subir_envio", "esperar_listo", "push_kernel", "bajar_salida",
              "version_dataset")
        viejo = (xd.RAIZ, xd.ENV, xd.TRABAJOS_DB, xd.LOTES_LOCAL, xd.en_motor, os.environ.get("KAGGLE_CONFIG_DIR"),
                 {n: getattr(K, n) for n in ks})
        estado, version, importados, bajados, pesos = {}, [0], [], [], []
        try:
            xd.RAIZ, xd.ENV, xd.TRABAJOS_DB = t, {"KAGGLE_USUARIO": "emi", "TRANSPORTE": "kaggle"}, db
            xd.LOTES_LOCAL = t / "motor" / "lotes"
            os.environ["KAGGLE_CONFIG_DIR"] = str(t / "cfg")
            K.estado_kernel = lambda k, **kw: (estado.get(k), "")
            K.estado_dataset = lambda ds, **kw: "ready"
            K.subir_envio = lambda c, existe, n, **kw: (pesos.append(json.loads((Path(c) / "envio.json").read_text()).get("pesos")) or (0, ""))
            K.esperar_listo = lambda ds, **kw: 1.0
            K.version_dataset = lambda ds, **kw: 1                                    # xd-pesos v1
            def push(c, limite_s=0, **kw):
                version[0] += 1
                return 0, f"Kernel version {version[0]} successfully pushed."
            K.push_kernel = push
            def bajar(k, dest, **kw):
                bajados.append(k)
                (Path(dest) / "lotes" / "cache").mkdir(parents=True, exist_ok=True)
                n = "lote_p3_x_t01" if k.endswith("/1") else "lote_p3_x_t02"
                (Path(dest) / "lotes" / f"{n}_pred.json").write_text(json.dumps({"proyecto": 3, "predicciones": []}))
                (Path(dest) / "lotes" / "cache" / f"{clave}.pt").write_bytes(b"pt")
                ver = pesos[len(bajados) - 1] or {}                                   # el kernel verifico si se lo pidieron
                (Path(dest) / "envio_resultado.json").write_text(json.dumps(
                    {"pesos_verificados": ver.get("version") if ver.get("verificar_sha") else None}))
                return 0, ""
            K.bajar_salida = bajar
            def en_motor(script, *args):
                assert script == "importar_lote.py", script
                importados.append(args[0])
                return 0, "OK"
            xd.en_motor = en_motor
            def ciclo(aplicar):
                out = io.StringIO()
                with redirect_stdout(out):
                    assert xd.cmd_daemon(NS(intervalo=0, una_vez=True, aplicar=aplicar)) == 0
                return out.getvalue()
            out = ciclo(False)                                                   # reporte: no escribe nada
            assert "MODO REPORTE" in out and version[0] == 0 and "SOLO REPORTE" in out, out
            out = ciclo(True)                                                    # ciclo 1: sale el trozo 1
            assert version[0] == 1 and "trozo 1" in out and not bajados, out
            assert pesos == [{"version": 1, "verificar_sha": True}] and xd._envio_en_curso()   # P.4.R4
            estado["emi/xd-worker/1"] = "complete"
            out = ciclo(True)                                                    # ciclo 2: trae, importa, trozo 2
            assert bajados == ["emi/xd-worker/1"] and importados == ["lote_p3_x_t01_pred.json"], out
            assert (t / "motor" / "cache_sam3" / f"{clave}.pt").exists() and version[0] == 2 and "trozo 2" in out, out
            assert pesos[1] == {"version": 1, "verificar_sha": False}, pesos        # v1 ya verificada: solo tamano
            estado["emi/xd-worker/2"] = "running"
            out = ciclo(True)                                                    # ciclo 3: el 2 corre; nada que hacer
            assert version[0] == 2 and bajados == ["emi/xd-worker/1"] and "nada que traer" in out, out
            estado["emi/xd-worker/2"] = "complete"
            out = ciclo(True)                                                    # ciclo 4: trae e importa el 2
            assert importados == ["lote_p3_x_t01_pred.json", "lote_p3_x_t02_pred.json"] and "Nada que enviar" in out, out
            with closing(C.abrir(db)) as con:
                assert {x["estado"] for x in C.listar(con)} == {"importado"} and C.envios_pendientes(con, "kaggle") == []
            assert not xd._envio_en_curso()
        finally:
            xd.RAIZ, xd.ENV, xd.TRABAJOS_DB, xd.LOTES_LOCAL, xd.en_motor, cfg, f = viejo
            for n, v in f.items():
                setattr(K, n, v)
            if cfg is None:
                os.environ.pop("KAGGLE_CONFIG_DIR", None)
            else:
                os.environ["KAGGLE_CONFIG_DIR"] = cfg


def test_daemon_intervalo_desde_el_inicio_del_ciclo():
    """P.4.R5: con un envio corriendo, el siguiente ciclo empieza SONDEO_RAPIDO s despues del inicio del anterior."""
    reloj, esperas = [100.0], []
    def sleep(s):
        esperas.append(s)
        raise KeyboardInterrupt                                                  # un ciclo y sale
    def ciclo(aplicar):
        reloj[0] += 6                                                            # el ciclo tarda 6 s (Kaggle)
    viejo = (xd.ciclo_daemon, xd._envio_en_curso, xd._transporte, xd.time)
    try:
        xd.ciclo_daemon, xd._transporte = ciclo, lambda: NS(nombre="kaggle")
        xd.time = NS(strftime=lambda *a: "t", monotonic=lambda: reloj[0], sleep=sleep)
        for corriendo, espera in ((True, xd.SONDEO_RAPIDO - 6), (False, 60 - 6)):
            xd._envio_en_curso = lambda: corriendo
            with redirect_stdout(io.StringIO()):
                assert xd.cmd_daemon(NS(intervalo=1, una_vez=False, aplicar=True)) == 0
            assert esperas[-1] == espera, esperas
    finally:
        xd.ciclo_daemon, xd._envio_en_curso, xd._transporte, xd.time = viejo


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST KAGGLE OK")
