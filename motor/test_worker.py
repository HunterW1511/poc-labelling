"""P.2.3: worker.py y entrenar.py con modelos FALSOS (sin GPU, sin ultralytics real, sin red). Uso: python test_worker.py"""
import json, tempfile, zipfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace as NS

import buzon
import entrenar
import esquema_llm as E
import lote
import registro
import worker

MOTOR = Path(__file__).resolve().parent


def _falla(exc, f, *a, **kw):
    try:
        f(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"se esperaba {exc.__name__}")


def _llm(msgs, esquema):
    return json.dumps(E.EJEMPLO), {}


ENT = {"proveedor": "test"}


def test_encabezado_y_lectura():
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "lote_p3_x"
        d.mkdir()
        assert worker.leer_trabajo(d, d.name)["tipo"] == "preetiquetado"          # zip anterior: por nombre
        _falla(ValueError, worker.leer_trabajo, d, "otra_cosa")
        _falla(ValueError, worker.encabezado, "raro", "x")
        h = worker.encabezado("entrenamiento", "dataset_p4_det_x", proyecto=4, parametros={"epochs": 5})
        (d / "trabajo.json").write_text(json.dumps(h), encoding="utf-8")
        assert worker.leer_trabajo(d, d.name)["parametros"] == {"epochs": 5}     # manda trabajo.json
        (d / "trabajo.json").write_text(json.dumps({**h, "esquema": worker.ESQUEMA + 1}), encoding="utf-8")
        assert "mas nuevo" in str(_falla(ValueError, worker.leer_trabajo, d, d.name))


def test_asistente_por_el_worker_e_idempotencia():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        zp, _ = buzon.armar(MOTOR, t / "buzon", "prueba", texto="una caja", ahora=0)
        d = t / "x" / zp.stem
        with zipfile.ZipFile(zp) as z:
            assert {"trabajo.json", "codigo/worker.py"} <= set(z.namelist())
            assert json.loads(z.read("trabajo.json"))["tipo"] == "asistente"
            z.extractall(d)
        e = worker.procesar(d, t / "buzon", ent=ENT, llm=_llm)
        assert e["ok"] and e["tipo"] == "asistente" and e["resultado"] == f"{zp.stem}_resultado.json", e
        r = json.loads((t / "buzon" / e["resultado"]).read_text(encoding="utf-8"))
        assert r["slug"] == "prueba" and r["resultado"]["ok"]
        assert json.loads((t / "buzon" / f"{zp.stem}.estado.json").read_text(encoding="utf-8"))["entorno"] == ENT
        assert worker.procesar(d, t / "buzon", ent=ENT, llm=None).get("saltado")     # no repite (ni llama al LLM)
        assert buzon.pendientes(t / "buzon") == []                                  # el hub lo ve como hoy


def test_preetiquetado_y_aislamiento_de_fallos():
    original = lote.procesar
    try:
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            ok, malo = t / "lote_p3_a", t / "lote_p3_b"
            for d in (ok, malo):
                d.mkdir()
                (d / "manifiesto.json").write_text(json.dumps({"modo": "sam3"}), encoding="utf-8")
            vistos = []

            def falso(d, cache, nombre, **kw):
                vistos.append((nombre, kw))
                if "lote_p3_b" in nombre:
                    raise RuntimeError("CUDA out of memory")
                cache["sem"] = "modelo"
                return {"lote": nombre, "predicciones": [1, 2]}
            lote.procesar = falso
            cache = {}
            e1 = worker.procesar(malo, t / "out", cache, ent=ENT, device=0)
            e2 = worker.procesar(ok, t / "out", cache, ent=ENT, device=0)
            assert not e1["ok"] and "CUDA out of memory" in e1["error"] and e1["resultado"] is None
            assert "Traceback" in (t / "out" / "lote_p3_b_error.txt").read_text(encoding="utf-8")
            assert e2["ok"] and json.loads((t / "out" / "lote_p3_a_pred.json").read_text())["predicciones"] == [1, 2]
            assert vistos[1] == ("lote_p3_a.zip", {"device": 0}) and cache == {"sem": "modelo"}
            worker.liberar(cache)
            assert cache == {}
    finally:
        lote.procesar = original


def test_precodificacion_y_tipo_roto_dejan_estado():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        d = t / "pre_x"
        d.mkdir()
        (d / "trabajo.json").write_text(json.dumps(worker.encabezado("precodificacion", "pre_x")), encoding="utf-8")
        e = worker.procesar(d, t / "out", ent=ENT)
        assert not e["ok"] and "P.3" in e["error"] and (t / "out" / "pre_x.estado.json").exists()
        r = t / "raro"
        r.mkdir()
        e = worker.procesar(r, t / "out", ent=ENT)
        assert not e["ok"] and e["tipo"] is None and (t / "out" / "raro_error.txt").exists()


def test_ordenar_por_modelo():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        def mk(nombre, modo=None, tipo=None):
            d = t / nombre
            d.mkdir()
            if modo:
                (d / "manifiesto.json").write_text(json.dumps({"modo": modo}), encoding="utf-8")
            if tipo:
                (d / "trabajo.json").write_text(json.dumps(worker.encabezado(tipo, nombre)), encoding="utf-8")
            return (d, nombre)
        xs = [mk("asist_a_20261103-100000"), mk("dataset_p1_det_x"), mk("lote_p2_h", "hijo"), mk("lote_p1_s", "sam3"),
              mk("pre_1", tipo="precodificacion")]
        assert [s for _, s in worker.ordenar(xs)] == ["lote_p1_s", "lote_p2_h", "pre_1", "dataset_p1_det_x",
                                                      "asist_a_20261103-100000"]


def test_parametros_y_kpi():
    p = entrenar.parametros({"formato": "seg", "epochs": "5", "imgsz": ""})
    assert p["epochs"] == 5 and p["imgsz"] == 960 and p["modelo"] == "yolo11n-seg.pt"
    for malo in ({"formato": "obb"}, {"epochs": 0}, {"conf_conteo": 1.5}, {"lr": 0.1}):
        _falla(ValueError, entrenar.parametros, malo)
    assert entrenar.nombre_run("dataset_p4_det_20261103-1000", "det") == "dataset_p4_det_20261103-1000"
    assert entrenar.nombre_run("dataset_p4_ambos_20261103-1000", "det") == "dataset_p4_ambos_20261103-1000_det"
    ex, err, real = entrenar.kpi_conteo([(Counter({0: 2}), Counter({0: 2})), (Counter({1: 1}), Counter({0: 1}))])
    assert ex == 1 and err == Counter({1: 1, 0: 1}) and real == Counter({0: 2, 1: 1})


class _Lista:
    def __init__(self, v):
        self.v = v

    def int(self):
        return self

    def tolist(self):
        return list(self.v)


PRED = {"a": [0, 0], "b": []}


class YOLOFalso:
    visto = {}

    def __init__(self, modelo):
        self.modelo, self.names = str(modelo), {0: "tornillo", 1: "base"}

    def train(self, data, project, name, **kw):
        w = Path(project) / name / "weights"
        w.mkdir(parents=True, exist_ok=True)
        (w / "best.pt").write_bytes(b"pt")
        (Path(project) / name / "results.csv").write_text("epoch,loss\n1,0.5\n2,0.4\n", encoding="utf-8")
        YOLOFalso.visto = {"modelo": self.modelo, "data": data, **kw}

    def val(self, data, imgsz, plots):
        return NS(box=NS(ap_class_index=[0, 1], ap50=[0.9, 0.8], ap=[0.6, 0.5], map50=0.85, map=0.55))

    def predict(self, ruta, imgsz, conf, verbose):
        return [NS(boxes=NS(cls=_Lista(PRED[Path(ruta).stem])))]


def test_entrenamiento_por_el_worker():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        stem = "dataset_p4_det_20261103-1000"
        d = t / stem
        for s in ("images/val", "labels/val", "images/train", "labels/train"):
            (d / "det" / s).mkdir(parents=True)
        (d / "det" / "data.yaml").write_text("path: .\ntrain: images/train\nval: images/val\nnames:\n  0: tornillo\n  1: base\n",
                                             encoding="utf-8")
        for n, txt in (("a", "0 0.5 0.5 0.1 0.1\n0 0.2 0.2 0.1 0.1\n"), ("b", "1 0.5 0.5 0.3 0.3\n")):
            (d / "det" / "images" / "val" / f"{n}.jpg").write_bytes(b"x")
            (d / "det" / "labels" / "val" / f"{n}.txt").write_text(txt, encoding="utf-8")
        (d / "resumen.json").write_text(json.dumps({"proyecto": 4, "imagenes": {"val": 2}}), encoding="utf-8")
        (d / "trabajo.json").write_text(json.dumps(worker.encabezado("entrenamiento", stem, proyecto=4,
                                                                     parametros={"epochs": 3, "imgsz": 640})),
                                        encoding="utf-8")
        e = worker.procesar(d, t / "out", ent=ENT, YOLO=YOLOFalso)
        assert e["ok"] and e["resultado"] == f"runs/{stem}", e
        assert YOLOFalso.visto["epochs"] == 3 and YOLOFalso.visto["imgsz"] == 640 and YOLOFalso.visto["modelo"] == "yolo11n.pt"
        assert json.loads((d / "det" / "data.yaml").read_text().splitlines()[0][6:]) == str((d / "det").resolve())
        met = json.loads((t / "out" / "runs" / stem / "weights" / "metricas.json").read_text(encoding="utf-8"))
        assert met["conteo"] == {"exactas": 1, "imagenes": 2, "tasa": 0.5} and met["proyecto"] == 4
        assert met["por_clase"]["base"]["error_abs"] == 1 and met["por_clase"]["tornillo"]["ap50"] == 0.9
        assert met["epocas_ejecutadas"] == 2 and met["dataset"] == f"{stem}.zip"
        assert registro.normalizar(met)["conteo_tasa"] == 0.5          # registrar lo acepta como siempre


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST WORKER OK")
