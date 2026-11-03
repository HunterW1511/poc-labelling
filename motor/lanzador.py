"""P.2.7: lanzador del worker en Kaggle (es el code_file del kernel privado <usuario>/xd-worker). Biblioteca estandar:
la logica de cada trabajo esta en el worker.py que trae su zip. Lee envio.json y pesos.json de /kaggle/input (los
datasets xd-envios y xd-pesos), verifica el sha256 de sam3.pt, instala las versiones fijas que hagan falta, procesa
los trabajos agrupados por modelo y escribe en /kaggle/working/{asistente,lotes,datasets,runs} con los nombres de
siempre. Los zips se extraen en /tmp: las fotos NUNCA quedan en la salida del kernel. Probado en el host con stubs."""
import hashlib, importlib, json, shutil, subprocess, sys, time, zipfile
from pathlib import Path

ENTRADA, SALIDA, TMP = Path("/kaggle/input"), Path("/kaggle/working"), Path("/tmp/xd")
CARPETA = {"asistente": "asistente", "preetiquetado": "lotes", "entrenamiento": "datasets", "precodificacion": "lotes"}
# versiones fijas = hub (motor/requirements.txt y cuaderno); test_lanzador lo verifica
VISION = ("pip -q install ultralytics==8.4.174 timm==1.0.30 "
          "\"clip @ git+https://github.com/ultralytics/CLIP.git@7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40\"")
ASISTENTE = ("pip -q install faster-whisper==1.2.1 ctranslate2==4.8.4 nvidia-cublas-cu12 "
             "'nvidia-cudnn-cu12==9.*' nvidia-cuda-runtime-cu12")
OLLAMA = "apt-get -qq install -y zstd lshw > /dev/null && curl -fsSL https://ollama.com/install.sh | sh"
NECESITA_SAM3 = ("preetiquetado", "precodificacion")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def buscar(raiz, nombre):
    """Primer archivo con ese nombre bajo raiz (Kaggle monta los datasets en /kaggle/input/<slug>/ o mas abajo)."""
    return next(iter(sorted(Path(raiz).rglob(nombre))), None)


def sha256(ruta, bloque=8 << 20):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(bloque), b""):
            h.update(b)
    return h.hexdigest()


def verificar_pesos(pesos_json):
    """-> ruta de sam3.pt si su sha256 coincide con pesos.json; si no, error (nunca usar pesos corruptos)."""
    info = json.loads(Path(pesos_json).read_text(encoding="utf-8"))
    pt = Path(pesos_json).parent / info["archivo"]
    t = time.time()
    real = sha256(pt)
    if real != info["sha256"]:
        raise RuntimeError(f"{pt.name}: sha256 {real[:12]} distinto del esperado {info['sha256'][:12]}")
    log(f"pesos OK: {pt} ({info['bytes'] / 1e9:.2f} GB, sha256 en {time.time() - t:.0f} s)")
    return pt


def cargar_codigo(d):
    """Siempre el codigo que trae el zip (se quitan los modulos del trabajo anterior)."""
    for m in [p.stem for p in (Path(d) / "codigo").glob("*.py")]:
        sys.modules.pop(m, None)
    sys.path[:] = [p for p in sys.path if not p.startswith(str(TMP))]
    sys.path.insert(0, str(Path(d) / "codigo"))
    return importlib.import_module("worker")


def _sh(cmd):
    log("$", cmd[:120])
    subprocess.run(cmd, shell=True, check=True)


def ejecutar(envio, zips, salida, tmp, proveedor="kaggle", sh=_sh, sam3_pt=None, device=0, cache=None):
    """Procesa los trabajos de envio.json. -> lista de estados (tambien en salida/envio_resultado.json)."""
    envio, zips, salida, tmp = dict(envio), Path(zips), Path(salida), Path(tmp)
    cache = {} if cache is None else cache
    listos, estados = {}, []
    for t in envio["trabajos"]:
        zp = zips / t["archivo"]
        stem, carpeta = zp.stem, salida / CARPETA.get(t["tipo"], "otros")
        carpeta.mkdir(parents=True, exist_ok=True)
        d = tmp / stem
        shutil.rmtree(d, ignore_errors=True)
        try:
            with zipfile.ZipFile(zp) as z:
                z.extractall(d)
            if not (d / "codigo" / "worker.py").is_file():
                raise RuntimeError("zip sin codigo/worker.py (exportado antes de P.2.3): vuelve a exportarlo")
        except Exception as e:
            (carpeta / f"{stem}_error.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
            estados.append({"trabajo": stem, "tipo": t["tipo"], "ok": False, "error": str(e)})
            log("ERROR", stem, e)
            continue
        listos[stem] = (d, carpeta)
    if listos:
        orden = cargar_codigo(next(iter(listos.values()))[0]).ordenar([(d, s) for s, (d, _) in listos.items()])
        grupos = {cargar_codigo(d).grupo(d, s) for d, s in orden}
        if grupos - {"asistente"}:
            sh(VISION)
        previo, asistente_listo = None, False
        for d, stem in orden:
            worker = cargar_codigo(d)
            g = worker.grupo(d, stem)
            if previo and g != previo:
                worker.liberar(cache)                   # un solo modelo pesado a la vez
            if g == "asistente" and not asistente_listo:
                sh(ASISTENTE)
                if not shutil.which("ollama"):
                    sh(OLLAMA)
                asistente_listo = True
            op = {"runs": salida / "runs", "device": device}
            if sam3_pt:
                op["sam3_pt"] = str(sam3_pt)
            estados.append(worker.procesar(d, listos[stem][1], cache, stem=stem, ent=worker.entorno(proveedor), **op))
            previo = g
    res = {"esquema": 1, "envio": envio.get("envio"), "fin": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "estados": estados}
    (salida / "envio_resultado.json").write_text(json.dumps(res, ensure_ascii=True, indent=1), encoding="utf-8")
    log(f"envio {envio.get('envio')}: {sum(1 for e in estados if e.get('ok'))}/{len(estados)} OK")
    return estados


def main():
    t0 = time.time()
    f_envio = buscar(ENTRADA, "envio.json")
    if f_envio is None:
        raise SystemExit("no encuentro envio.json en /kaggle/input (dataset xd-envios)")
    envio = json.loads(f_envio.read_text(encoding="utf-8"))
    log(f"envio {envio.get('envio')} de {envio.get('operador')}: {len(envio['trabajos'])} trabajo(s)")
    sam3 = None
    if any(t["tipo"] in NECESITA_SAM3 for t in envio["trabajos"]):
        f_pesos = buscar(ENTRADA, "pesos.json")
        if f_pesos is None:
            raise SystemExit("no encuentro pesos.json en /kaggle/input (dataset xd-pesos)")
        sam3 = verificar_pesos(f_pesos)
    ejecutar(envio, f_envio.parent, SALIDA, TMP, sam3_pt=sam3)
    shutil.rmtree(TMP, ignore_errors=True)
    log(f"total {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
