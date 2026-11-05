"""P.2.7a: lanzador.py (kernel de Kaggle) con el worker.py REAL y stubs de lote/entrenar/trabajo dentro de los zips
(sin GPU, sin red, sin instalar nada). Uso: python test_lanzador.py"""
import json, re, tempfile, zipfile
from pathlib import Path

import lanzador as L

MOTOR = Path(__file__).resolve().parent

LOTE = '''def procesar(d, cache, nombre, **kw):
    cache["sam3"] = "cargado"
    return {"lote": nombre, "kw": sorted(kw), "predicciones": []}
'''
ENTRENAR = '''import json
from pathlib import Path
def entrenar(d, salida, params, proyecto=None, dataset="", YOLO=None, runs=None):
    r = Path(runs) / Path(dataset).stem / "weights"
    r.mkdir(parents=True, exist_ok=True)
    (r / "metricas.json").write_text(json.dumps({"params": params}))
    return "runs/" + Path(dataset).stem
'''
TRABAJO = '''import asistente
def procesar(d, nombre, **kw):
    return {"esquema": 1, "trabajo": nombre, "resultado": {"ok": True}}
'''


def _zip(ruta, tipo, extra, con_worker=True):
    with zipfile.ZipFile(ruta, "w") as z:
        if con_worker:
            z.write(MOTOR / "worker.py", "codigo/worker.py")
        for n, txt in extra.items():
            z.writestr(n, txt)
        z.writestr("trabajo.json", json.dumps({"esquema": 1, "tipo": tipo, "trabajo": Path(ruta).stem,
                                               "parametros": {"epochs": 3} if tipo == "entrenamiento" else {}}))
    return {"tipo": tipo, "archivo": Path(ruta).name}


def test_versiones_fijas_iguales_al_hub():
    req = (MOTOR / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("ultralytics", "timm"):
        assert f"{pkg}=={re.search(rf'^{pkg}==(\S+)', req, re.M).group(1)}" in L.VISION, pkg
    assert re.search(r"CLIP\.git@([0-9a-f]{40})", req).group(1) in L.VISION
    nb = "".join("".join(c["source"]) for c in json.loads((MOTOR.parent / "notebooks" / "worker.ipynb")
                                                         .read_text(encoding="utf-8"))["cells"])
    for pin in re.findall(r"[\w-]+==[\w.*]+", L.ASISTENTE):
        assert pin in nb, f"{pin}: el lanzador de Kaggle y worker.ipynb deben instalar lo mismo"


def test_buscar_y_verificar_pesos():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        d = t / "input" / "datasets" / "u" / "xd-pesos"                 # Kaggle puede montar mas abajo
        d.mkdir(parents=True)
        (d / "sam3.pt").write_bytes(b"pesos")
        (d / "pesos.json").write_text(json.dumps({"archivo": "sam3.pt", "bytes": 5, "sha256": L.sha256(d / "sam3.pt")}))
        assert L.buscar(t / "input", "pesos.json") == d / "pesos.json" and L.buscar(t, "no.json") is None
        assert L.verificar_pesos(d / "pesos.json") == d / "sam3.pt"
        (d / "sam3.pt").write_bytes(b"corrupto")
        try:
            L.verificar_pesos(d / "pesos.json")
            raise AssertionError("debio rechazar pesos corruptos")
        except RuntimeError as e:
            assert "sha256" in str(e)


def test_envio_completo():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        zips, salida, tmp = t / "input", t / "working", t / "tmp"
        zips.mkdir()
        L.TMP = tmp                                                     # cargar_codigo limpia sys.path con esta raiz
        trabajos = [
            _zip(zips / "asist_s_20261103-100000.zip", "asistente", {"codigo/trabajo.py": TRABAJO,
                                                                     "codigo/asistente.py": "def resumen(r): return 'ok'\n"}),
            _zip(zips / "lote_p1_a.zip", "preetiquetado", {"codigo/lote.py": LOTE, "manifiesto.json": '{"modo": "sam3"}',
                                                           "fotos/1_a.jpg": "FOTO"}),
            _zip(zips / "dataset_p2_det_x.zip", "entrenamiento", {"codigo/entrenar.py": ENTRENAR}),
            _zip(zips / "lote_p1_viejo.zip", "preetiquetado", {"manifiesto.json": "{}"}, con_worker=False),
        ]
        comandos, cache = [], {}
        est = L.ejecutar({"envio": "envio_x", "trabajos": trabajos}, zips, salida, tmp, sh=comandos.append,
                         sam3_pt=t / "sam3.pt", cache=cache)
        por = {e["trabajo"]: e for e in est}
        assert [e["ok"] for e in est] == [False, True, True, True], est             # el roto primero, luego por modelo
        assert "worker.py" in por["lote_p1_viejo"]["error"]
        assert (salida / "lotes" / "lote_p1_viejo_error.txt").exists()
        assert json.loads((salida / "lotes" / "lote_p1_a_pred.json").read_text())["kw"] == ["device", "sam3_pt"]
        assert (salida / "runs" / "dataset_p2_det_x" / "weights" / "metricas.json").exists()
        assert (salida / "datasets" / "dataset_p2_det_x.estado.json").exists()
        assert (salida / "asistente" / "asist_s_20261103-100000_resultado.json").exists()
        assert por["lote_p1_a"]["entorno"]["proveedor"] == "kaggle"
        assert comandos[0] == L.VISION and L.ASISTENTE in comandos and comandos.count(L.VISION) == 1
        assert cache == {}                                                          # liberada al cambiar de grupo
        assert not [f for f in salida.rglob("*") if f.suffix in (".jpg", ".png", ".zip")]   # nada de fotos en la salida
        res = json.loads((salida / "envio_resultado.json").read_text())
        assert res["envio"] == "envio_x" and len(res["estados"]) == 4
        # P.2.7a real: Kaggle descomprime los .zip. Viajan como .zip.xd; si aun asi llega una carpeta, se usa
        xd_ = _zip(zips / "lote_p5_b.zip", "preetiquetado", {"codigo/lote.py": LOTE, "manifiesto.json": '{"modo": "sam3"}'})
        (zips / "lote_p5_b.zip").rename(zips / "lote_p5_b.zip.xd")
        xd_["en_envio"] = "lote_p5_b.zip.xd"
        _zip(zips / "lote_p6_c.zip", "preetiquetado", {"codigo/lote.py": LOTE, "manifiesto.json": '{"modo": "sam3"}'})
        with zipfile.ZipFile(zips / "lote_p6_c.zip") as z:
            z.extractall(zips / "lote_p6_c")
        (zips / "lote_p6_c.zip").unlink()
        falta = {"tipo": "preetiquetado", "archivo": "lote_p7_d.zip", "en_envio": "lote_p7_d.zip.xd"}
        e2 = L.ejecutar({"envio": "z", "trabajos": [xd_, {"tipo": "preetiquetado", "archivo": "lote_p6_c.zip"}, falta]},
                        zips, t / "w3", tmp, sh=lambda c: None)
        assert [e["ok"] for e in e2] == [False, True, True], e2
        assert "no esta lote_p7_d.zip.xd" in e2[0]["error"] and "lote_p5_b.zip.xd" in e2[0]["error"]   # lista lo que hay
        comandos.clear()                                                            # solo asistente: no instala vision
        L.ejecutar({"envio": "y", "trabajos": trabajos[:1]}, zips, t / "w2", tmp, sh=comandos.append)
        assert L.VISION not in comandos


LOTE_GPU = """import json, os
from pathlib import Path
def procesar(d, cache, nombre, **kw):
    man = json.loads((Path(d) / "manifiesto.json").read_text())
    if any(t["id"] == 99 for t in man["tareas"]):
        raise RuntimeError("CUDA out of memory en esta parte")
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES")
    return {"lote": nombre, "version": "v", "predicciones": [{"task": t["id"], "gpu": gpu} for t in man["tareas"]]}
"""


def test_dos_gpus_reparten_un_lote():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        zips, salida, tmp = t / "input", t / "working", t / "tmp"
        zips.mkdir()
        L.TMP = tmp
        tareas = [{"id": i, "foto": f"fotos/{i}.jpg"} for i in range(1, 7)]
        fotos = {f"fotos/{i}.jpg": "x" for i in range(1, 7)}
        man = json.dumps({"modo": "sam3", "tareas": tareas})
        bueno = _zip(zips / "lote_p1_g.zip", "preetiquetado", {"codigo/lote.py": LOTE_GPU, "manifiesto.json": man, **fotos})
        malo = _zip(zips / "lote_p1_m.zip", "preetiquetado", {"codigo/lote.py": LOTE_GPU, "manifiesto.json":
                    json.dumps({"modo": "sam3", "tareas": tareas[:3] + [{"id": 99, "foto": "fotos/1.jpg"}]}), **fotos})
        chico = _zip(zips / "lote_p1_c.zip", "preetiquetado", {"codigo/lote.py": LOTE_GPU, "manifiesto.json":
                     json.dumps({"modo": "sam3", "tareas": tareas[:2]}), **fotos})
        est = {e["trabajo"]: e for e in L.ejecutar({"envio": "g", "trabajos": [bueno, malo, chico]}, zips, salida, tmp,
                                                   sh=lambda c: None, sam3_pt=t / "sam3.pt", n_gpus=2, min_partir=4)}
        e = est["lote_p1_g"]
        assert e["ok"] and e["entorno"]["gpus"] == 2 and [p["fotos"] for p in e["partes"]] == [3, 3], e
        pred = json.loads((salida / "lotes" / "lote_p1_g_pred.json").read_text())["predicciones"]
        assert [p["task"] for p in pred] == [1, 2, 3, 4, 5, 6], pred                 # completas y en orden
        assert [p["gpu"] for p in pred] == ["0"] * 3 + ["1"] * 3                       # una parte por GPU
        assert json.loads((salida / "lotes" / "lote_p1_g.estado.json").read_text())["ok"]
        m = est["lote_p1_m"]                                                          # falla una parte: falla el trabajo
        assert not m["ok"] and "parte 1" in m["error"] and "out of memory" in m["error"], m
        assert (salida / "lotes" / "lote_p1_m_error.txt").exists() and not (salida / "lotes" / "lote_p1_m_pred.json").exists()
        c = est["lote_p1_c"]                                                          # pocas fotos: una sola GPU
        assert c["ok"] and "partes" not in c
        assert not [p for p in tmp.iterdir() if "__parte" in p.name or "__salida" in p.name]   # limpia las partes


def test_juntar_precodificacion():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        salidas = []
        for i in range(2):
            s = t / f"s{i}"
            (s / "cache").mkdir(parents=True)
            (s / "cache" / f"c{i}.pt").write_bytes(b"x")
            (s / "pre_p1_x_cache.json").write_text(json.dumps({"imgsz": 644, "seg": 10 + i, "fotos": [{"tarea": i}]}))
            salidas.append(s)
        assert L.juntar("precodificacion", "pre_p1_x", salidas, t / "out") == "pre_p1_x_cache.json"
        idx = json.loads((t / "out" / "pre_p1_x_cache.json").read_text())
        assert [f["tarea"] for f in idx["fotos"]] == [0, 1] and idx["seg"] == 11
        assert sorted(f.name for f in (t / "out" / "cache").iterdir()) == ["c0.pt", "c1.pt"]


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST LANZADOR OK")
