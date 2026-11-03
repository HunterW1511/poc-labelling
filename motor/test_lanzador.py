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
        comandos.clear()                                                            # solo asistente: no instala vision
        L.ejecutar({"envio": "y", "trabajos": trabajos[:1]}, zips, t / "w2", tmp, sh=comandos.append)
        assert L.VISION not in comandos


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST LANZADOR OK")
