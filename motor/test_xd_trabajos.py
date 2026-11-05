"""P.1.4: los comandos de xd.py registran sus trabajos en la cola. Raiz temporal, Drive falso, en_motor falso:
sin Docker, sin Drive ni Label Studio. Uso: python test_xd_trabajos.py"""
import io, json, shutil, sys, tempfile, zipfile
from contextlib import closing, redirect_stdout
from pathlib import Path
from types import SimpleNamespace as NS

MOTOR = Path(__file__).resolve().parent
sys.path.insert(0, str(MOTOR))
sys.path.insert(1, str(MOTOR.parent))
import buzon
import cola_trabajos as C
import esquema_llm as E
import trabajo
import xd

xd._estado = lambda: None          # P.3.7: el tablero lee avisos del motor; los tests no dependen del motor real

MET = {"esquema": 1, "creado": "2026-11-03T10:00:00", "dataset": "dataset_p4_x.zip", "formato": "det",
       "modelo_base": "yolo11n.pt", "params": {"imgsz": 640}, "conteo": {"exactas": 1, "imagenes": 2, "tasa": 0.5},
       "map50": 0.5, "map50_95": 0.3, "por_clase": {}, "proyecto": 4}


def _correr(f, a):
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            rc = f(a)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
            if not isinstance(e.code, int):
                print(e.code)
    return rc, out.getvalue()


def _preparar(t):
    """Raiz y Drive falsos; xd apunta a ellos."""
    raiz, drive = t / "repo", t / "drive"
    (raiz / "motor").mkdir(parents=True)
    for m in buzon.MODULOS:
        shutil.copy2(MOTOR / m, raiz / "motor" / m)
    for d in ("lotes", "asistente", "datasets", "runs"):
        (drive / d).mkdir(parents=True)
    xd.RAIZ, xd.LOTES_LOCAL = raiz, raiz / "motor" / "lotes"
    xd.ENV = {"LOTES_DRIVE": str(drive / "lotes")}
    xd.TRABAJOS_DB = raiz / "datos" / "trabajos.sqlite"
    return raiz, drive


def _uno(tipo, archivo):
    with closing(C.abrir(xd.TRABAJOS_DB)) as con:
        return C.buscar(con, tipo, archivo)


def _reconciliar():
    rc, out = _correr(xd.cmd_trabajos, NS(reconciliar=True, reintentar=0, aplicar=True, horas=24, tipo="", estado="",
                                          todos=False))
    assert rc == 0, out
    return out


def _colab_asistente(bz, zp):
    """Lo que hace el cuaderno asistente: procesa el zip y deja <trabajo>_resultado.json."""
    d = bz.parent / f"x_{zp.stem}"
    zipfile.ZipFile(zp).extractall(d)
    r = trabajo.procesar(d, zp.name, llm=lambda msgs, esq: (json.dumps(E.EJEMPLO), {}))
    (bz / f"{zp.stem}_resultado.json").write_text(json.dumps(r), encoding="utf-8")


def test_asistente_continuar_importar_y_reintentar():
    with tempfile.TemporaryDirectory() as t:
        raiz, drive = _preparar(Path(t))
        bz = drive / "asistente"
        a = NS(slug="prueba", texto="una caja", audio="", vocabulario="", respuestas="", nuevo=False,
               continuar=False, modelo="")
        rc, out = _correr(xd.cmd_asistente, a)
        assert rc == 0, out
        z1 = sorted(bz.glob("asist_prueba_*.zip"))[-1]
        assert _uno("asistente", z1.name)["estado"] == "enviado"
        _colab_asistente(bz, z1)
        _reconciliar()
        assert _uno("asistente", z1.name)["estado"] == "listo"
        # --continuar: el resultado anterior queda archivado (reemplazado)
        import time
        time.sleep(1.1)                                       # el nombre del trabajo lleva la hora al segundo
        rc, out = _correr(xd.cmd_asistente, NS(**{**vars(a), "continuar": True, "respuestas": "si"}))
        assert rc == 0 and "reemplazado" in out, out
        z2 = sorted(bz.glob("asist_prueba_*.zip"))[-1]
        assert z2 != z1 and _uno("asistente", z1.name)["estado"] == "archivado"
        assert _uno("asistente", z2.name)["estado"] == "enviado"
        # falla en Colab -> error -> reintentar (reporte no cambia nada; --aplicar mueve el _error.txt)
        (bz / f"{z2.stem}_error.txt").write_text("Traceback: boom", encoding="utf-8")
        (bz / f"{z2.stem}.estado.json").write_text('{"ok": false}', encoding="utf-8")      # lo deja el worker
        _reconciliar()
        t2 = _uno("asistente", z2.name)
        assert t2["estado"] == "error" and "boom" in t2["error"]
        r = NS(reconciliar=False, reintentar=t2["id"], aplicar=False, horas=24, tipo="", estado="", todos=False)
        rc, out = _correr(xd.cmd_trabajos, r)
        assert rc == 0 and "SOLO REPORTE" in out and (bz / f"{z2.stem}_error.txt").exists()
        assert _uno("asistente", z2.name)["estado"] == "error"
        r.aplicar = True
        rc, out = _correr(xd.cmd_trabajos, r)
        t2 = _uno("asistente", z2.name)
        assert rc == 0 and t2["estado"] == "enviado" and t2["intentos"] == 1, out
        assert not (bz / f"{z2.stem}_error.txt").exists() and list((bz / "_archivo").glob(f"{z2.stem}_error_*.txt"))
        assert not (bz / f"{z2.stem}.estado.json").exists() and list((bz / "_archivo").glob(f"{z2.stem}.estado_*.json"))
        # Colab lo procesa bien; asistente-importar --aplicar marca importado ESE trabajo
        _colab_asistente(bz, z2)
        rc, out = _correr(xd.cmd_asistente_importar, NS(slug="prueba", aplicar=True, forzar=False, comparar="", si=False))
        assert rc == 0 and (raiz / "motor" / "proyectos" / "prueba" / "spec.json").exists(), out
        t2 = _uno("asistente", z2.name)
        assert t2["estado"] == "importado" and t2["resultado"] == f"{z2.stem}_resultado.json"
        assert "AVISO" not in out, out


def test_lote_exportar_importar_con_fallo():
    with tempfile.TemporaryDirectory() as t:
        raiz, drive = _preparar(Path(t))
        rc_import = [1]

        def en_motor(script, *args):
            if script == "exportar_lote.py":
                xd.LOTES_LOCAL.mkdir(parents=True, exist_ok=True)
                (xd.LOTES_LOCAL / "lote_p3_x.zip").write_bytes(b"z")
                return 0, "OK -> /app/lotes/lote_p3_x.zip"
            assert script == "importar_lote.py", script
            return rc_import[0], "detalle del fallo" if rc_import[0] else "OK"
        xd.en_motor = en_motor
        a = NS(proyecto=3, limite=0, tareas="", todas=False, extra=[], modo="")
        rc, out = _correr(xd.cmd_lote_exportar, a)
        assert rc == 0 and _uno("preetiquetado", "lote_p3_x.zip")["estado"] == "enviado", out
        (drive / "lotes" / "lote_p3_x_pred.json").write_text("{}", encoding="utf-8")       # Colab termino
        imp = NS(sufijo="", fijar_version=True)
        rc, out = _correr(xd.cmd_lote_importar, imp)
        x = _uno("preetiquetado", "lote_p3_x.zip")
        assert rc == 1 and x["estado"] == "listo" and x["intentos"] == 1 and "detalle del fallo" in x["error"], (out, x)
        assert not (xd.LOTES_LOCAL / "lote_p3_x_pred.json").exists()                       # se puede reintentar
        rc_import[0] = 0
        rc, out = _correr(xd.cmd_lote_importar, imp)
        x = _uno("preetiquetado", "lote_p3_x.zip")
        assert rc == 0 and x["estado"] == "importado" and x["proyecto"] == 3, (out, x)
        assert "nada que reconciliar" in _reconciliar()


def test_dataset_registrar_y_archivar():
    with tempfile.TemporaryDirectory() as t:
        raiz, drive = _preparar(Path(t))

        def en_motor(script, *args):
            assert script == "exportar_yolo.py", script
            d = raiz / "motor" / "datasets"
            d.mkdir(parents=True, exist_ok=True)
            n = args[0]
            (d / f"dataset_p{n}_x.zip").write_bytes(b"z")
            return 0, f"OK -> /app/datasets/dataset_p{n}_x.zip"
        xd.en_motor = en_motor
        a = NS(proyecto=4, formato="det", val="0.2", correcciones="", drive=True)
        rc, out = _correr(xd.cmd_dataset, a)
        assert rc == 0 and _uno("entrenamiento", "dataset_p4_x.zip")["estado"] == "enviado", out
        w = drive / "runs" / "dataset_p4_x_det" / "weights"                                # el cuaderno usa stem_formato
        w.mkdir(parents=True)
        (w / "best.pt").write_bytes(b"pt")
        (w / "metricas.json").write_text(json.dumps(MET), encoding="utf-8")
        r = NS(proyecto=4, run="ultimo", pt="", metricas="", nombre="", otro_proyecto=False, activar=True, aplicar=True)
        rc, out = _correr(xd.cmd_registrar, r)
        x = _uno("entrenamiento", "dataset_p4_x.zip")
        assert rc == 0 and x["estado"] == "importado" and x["resultado"] == "dataset_p4_x_det", (out, x)
        # archivar un dataset en espera (nuevo en P.1.4) lo marca archivado
        rc, out = _correr(xd.cmd_dataset, NS(**{**vars(a), "proyecto": 5}))
        rc, out = _correr(xd.cmd_archivar, NS(archivo="dataset_p5_x.zip", aplicar=False))
        assert rc == 0 and _uno("entrenamiento", "dataset_p5_x.zip")["estado"] == "enviado", out
        rc, out = _correr(xd.cmd_archivar, NS(archivo="dataset_p5_x.zip", aplicar=True))
        assert rc == 0 and _uno("entrenamiento", "dataset_p5_x.zip")["estado"] == "archivado", out
        assert (drive / "datasets" / "_archivo" / "dataset_p5_x.zip").exists()
        assert "nada que reconciliar" in _reconciliar()


def test_cola_rota_no_rompe_el_comando():
    with tempfile.TemporaryDirectory() as t:
        raiz, drive = _preparar(Path(t))
        xd.TRABAJOS_DB.mkdir(parents=True)                    # una carpeta en lugar de la base: sqlite no abre
        rc, out = _correr(xd.cmd_asistente, NS(slug="rota", texto="x", audio="", vocabulario="", respuestas="",
                                               nuevo=False, continuar=False, modelo=""))
        assert rc == 0 and "AVISO cola" in out and "--reconciliar" in out, out
        assert list((drive / "asistente").glob("asist_rota_*.zip"))


def test_tablero_lee_la_cola_sin_escribir():
    with tempfile.TemporaryDirectory() as t:
        raiz, drive = _preparar(Path(t))
        import tablero
        tablero.PROYECTOS, tablero.MODELOS = raiz / "motor" / "proyectos", raiz / "motor" / "modelos"
        bz, lo = drive / "asistente", drive / "lotes"
        for f, txt in (("asist_s_20261103-100000.zip", "z"), ("asist_s_20261103-100000_error.txt", "Traceback boom")):
            (bz / f).write_text(txt, encoding="utf-8")
        for f in ("lote_p3_x.zip", "lote_p3_x_pred.json", "lote_p3_y.zip"):
            (lo / f).write_text("{}", encoding="utf-8")
        x = tablero.externos()                                # sin base: adopcion EN MEMORIA
        assert not xd.TRABAJOS_DB.exists() and x["sin_guardar"] == 3, x
        est = {(i["tipo"], i["estado"]): i for i in x["items"]}
        assert set(est) == {("asistente", "error"), ("preetiquetado", "listo"), ("preetiquetado", "en_espera")}, est
        assert est[("asistente", "error")]["accion"] is None   # sin id guardado no se ofrece reintentar
        assert tablero.lotes(tablero.vista()) == {3: {"en_colab": ["lote_p3_y.zip"], "sin_importar": ["lote_p3_x_pred.json"]}}
        a = tablero._asistente(tablero.vista(), "s")
        assert a["ultimo"] == "error" and a["trabajo"] == "asist_s_20261103-100000_error.txt" and not a["aplicada"]
        _reconciliar()                                        # se guarda: misma vista, ya sin cambios pendientes
        x = tablero.externos()
        est = {(i["tipo"], i["estado"]): i for i in x["items"]}
        assert x["sin_guardar"] == 0 and est[("asistente", "error")]["archivable"]
        assert est[("asistente", "error")]["accion"]["opciones"] == {"--reintentar": est[("asistente", "error")]["id"]}
        assert "boom" in est[("asistente", "error")]["texto"]


def test_tablero_en_modo_kaggle():
    with tempfile.TemporaryDirectory() as t:
        raiz, _ = _preparar(Path(t))
        import tablero
        tablero.PROYECTOS, tablero.MODELOS = raiz / "motor" / "proyectos", raiz / "motor" / "modelos"
        xd.ENV = {"TRANSPORTE": "kaggle"}
        x = tablero.externos()
        assert x["ejecutor"] == "kaggle" and x["items"] == [] and not x["avisos"], x       # sin avisos falsos
        assert not (raiz / "datos").exists()                                            # el tablero no crea nada
        esp = xd._transporte().requerir("lotes", crear=True)
        (esp / "lote_p3_x.zip").write_bytes(b"z")
        with closing(C.abrir(xd.TRABAJOS_DB)) as con:
            tr, _ = C.crear(con, "preetiquetado", "lote_p3_x.zip", proyecto=3, estado="enviado")
        it = tablero.externos()["items"]
        assert len(it) == 1 and it[0]["texto"].startswith("Listo para Kaggle"), it
        with closing(C.abrir(xd.TRABAJOS_DB)) as con:
            C.crear_envio(con, "envio_1", "kaggle", "emi", [tr["id"]])
            C.marcar_envio(con, "envio_1", "corriendo")
        x = tablero.externos()
        assert x["items"][0]["texto"] == "En Kaggle (envio_1): corriendo; 'Traer de Kaggle' cuando termine", x
        assert x["envio"]["nombre"] == "envio_1" and x["envio"]["estado"] == "corriendo"
        assert tablero.siguiente({"slug": "s", "n": 3, "spec": True, "lotes": {"en_colab": ["lote_p3_x.zip"]}})["donde"] == "kaggle"


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST XD_TRABAJOS OK")
