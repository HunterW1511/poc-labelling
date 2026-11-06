"""P.2.7: lanzador del worker en Kaggle (es el code_file del kernel privado <usuario>/xd-worker). Biblioteca estandar:
la logica de cada trabajo esta en el worker.py que trae su zip. Lee envio.json y pesos.json de /kaggle/input (los
datasets xd-envios y xd-pesos), verifica el sha256 de sam3.pt, instala las versiones fijas que hagan falta, procesa
los trabajos agrupados por modelo y escribe en /kaggle/working/{asistente,lotes,datasets,runs} con los nombres de
siempre. Los zips se extraen en /tmp: las fotos NUNCA quedan en la salida del kernel. Probado en el host con stubs."""
import hashlib, importlib, json, math, os, shutil, subprocess, sys, threading, time, zipfile
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
# P.3.6: estos grupos se parten por fotos entre las GPU (un subproceso y un SAM 3 por GPU); el resto usa una sola
POR_GPU = {"preetiquetado-sam3": ("manifiesto.json", "tareas"), "preetiquetado-hijo": ("manifiesto.json", "tareas"),
           "precodificacion": ("fotos.json", "fotos")}
MIN_PARTIR = 16                                  # con menos fotos no compensa cargar otro SAM 3 (~30 s)
VERIFICADO = {}                                  # ruta de sam3.pt -> sha256 ya comprobado
PESOS_VERIFICADOS = {}                           # P.4.R4: version de xd-pesos verificada entera en este envio
PRECALENTANDO = {}                               # P.4.R5: ruta de sam3.pt -> hilo que la lee entera (cache de paginas)


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


def verificar_pesos(pesos_json, completo=True):
    """-> ruta de sam3.pt si su sha256 coincide con pesos.json; si no, error (nunca usar pesos corruptos).
    completo=False (P.4.R4): esa version del dataset ya se verifico entera en un envio anterior: solo el tamano.
    El sha queda en VERIFICADO (la precodificacion lo pone en la clave de la cache)."""
    info = json.loads(Path(pesos_json).read_text(encoding="utf-8"))
    pt = Path(pesos_json).parent / info["archivo"]
    if not completo:
        if pt.stat().st_size != info["bytes"]:
            raise RuntimeError(f"{pt.name}: {pt.stat().st_size} bytes, se esperaban {info['bytes']}")
        log(f"pesos OK: {pt} (tamano; sha verificado antes en esta version del dataset)")
        VERIFICADO[str(pt)] = info["sha256"]
        precalentar(pt)
        return pt
    t = time.time()
    real = sha256(pt)
    if real != info["sha256"]:
        raise RuntimeError(f"{pt.name}: sha256 {real[:12]} distinto del esperado {info['sha256'][:12]}")
    log(f"pesos OK: {pt} ({info['bytes'] / 1e9:.2f} GB, sha256 en {time.time() - t:.0f} s)")
    VERIFICADO[str(pt)] = real
    return pt


def precalentar(pt, bloque=64 << 20):
    """P.4.R5: lee sam3.pt entera y en orden en un hilo (mientras corre el pip) para dejarla en la cache de paginas.
    Medido el 06/11/2026: sin el sha (que la leia asi), 2 SAM 3 cargando en frio a la vez desde /kaggle/input
    tardaban 172-328 s; en R3, tras el sha (lectura secuencial), 33 s. Si falla, solo avisa (la carga dira lo que pase)."""
    def leer():
        t, n, buf = time.time(), 0, bytearray(bloque)
        try:
            with open(pt, "rb", buffering=0) as f:
                while (k := f.readinto(buf)):
                    n += k
            log(f"pesos en memoria: {n / 1e9:.2f} GB leidos en {time.time() - t:.0f} s")
        except OSError as e:
            log(f"AVISO no pude precalentar {pt}: {e}")
    h = threading.Thread(target=leer, name="precalentar", daemon=True)
    h.start()
    PRECALENTANDO[str(pt)] = h
    return h


def esperar_precalentado(pt):
    """Antes de cargar SAM 3: termina la lectura secuencial de precalentar (si la hay)."""
    h = PRECALENTANDO.pop(str(pt), None)
    if h is not None and h.is_alive():
        t = time.time()
        h.join()
        log(f"espere {time.time() - t:.0f} s a que sam3.pt quedara en memoria")


def gpus():
    """Cuantas GPU NVIDIA ve la sesion (nvidia-smi -L; sin importar torch). 0 si no hay."""
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=30)
        return sum(1 for l in r.stdout.splitlines() if l.startswith("GPU ")) if r.returncode == 0 else 0
    except (OSError, subprocess.TimeoutExpired):
        return 0


def partir(d, stem, grupo, n, tmp):
    """Copia (enlaces duros) la carpeta del trabajo en n partes con el manifiesto repartido en tramos contiguos
    (el orden se conserva al juntar). -> [(carpeta, cuantos)]"""
    archivo, clave = POR_GPU[grupo]
    man = json.loads((Path(d) / archivo).read_text(encoding="utf-8"))
    items = man[clave]
    k = math.ceil(len(items) / n)
    partes = []
    for i in range(n):
        tramo = items[i * k:(i + 1) * k]
        if not tramo:
            break
        di = Path(tmp) / f"{stem}__parte{i}"
        shutil.rmtree(di, ignore_errors=True)
        try:
            shutil.copytree(d, di, copy_function=os.link)
        except OSError:
            shutil.copytree(d, di)
        (di / archivo).unlink()                            # era un enlace al original: se reescribe aparte
        (di / archivo).write_text(json.dumps({**man, clave: tramo}, ensure_ascii=True), encoding="utf-8")
        partes.append((di, len(tramo)))
    return partes


PARTE = """import json, sys
sys.path.insert(0, sys.argv[1])
import worker
op = json.loads(sys.argv[4])
e = worker.procesar(sys.argv[2], sys.argv[3], {}, stem=op.pop("stem"), ent=worker.entorno(op.pop("proveedor")), **op)
sys.exit(0 if e.get("ok") else 1)
"""


def juntar(grupo, stem, salidas, carpeta):
    """Une los resultados de las partes en el resultado de siempre. -> nombre del resultado."""
    if grupo.startswith("preetiquetado"):
        res = [json.loads((s / f"{stem}_pred.json").read_text(encoding="utf-8")) for s in salidas]
        out = {**res[0], "predicciones": [p for r in res for p in r["predicciones"]]}
        nombre = f"{stem}_pred.json"
        tmp = Path(carpeta) / (nombre + ".tmp")
        tmp.write_text(json.dumps(out), encoding="utf-8")
        tmp.replace(Path(carpeta) / nombre)
        return nombre
    idx = [json.loads((s / f"{stem}_cache.json").read_text(encoding="utf-8")) for s in salidas]
    (Path(carpeta) / "cache").mkdir(parents=True, exist_ok=True)
    for s in salidas:
        for f in (s / "cache").glob("*.pt"):           # shutil.move: en Kaggle /tmp y /kaggle/working son discos
            shutil.move(str(f), str(Path(carpeta) / "cache" / f.name))   # distintos (os.replace da EXDEV)
    out = {**idx[0], "seg": max(i.get("seg", 0) for i in idx), "fotos": [f for i in idx for f in i["fotos"]]}
    nombre = f"{stem}_cache.json"
    (Path(carpeta) / nombre).write_text(json.dumps(out, ensure_ascii=True, indent=1), encoding="utf-8")
    return nombre


def en_paralelo(d, stem, grupo, carpeta, n, tmp, op, proveedor, correr=subprocess.Popen):
    """Un subproceso (y un SAM 3) por GPU sobre su tramo de fotos; junta lo que sale. -> estado del trabajo."""
    t0, inicio = time.time(), time.strftime("%Y-%m-%dT%H:%M:%S%z")
    partes = partir(d, stem, grupo, n, tmp)
    log(f"{stem}: {len(partes)} partes en {len(partes)} GPU ({', '.join(str(c) for _, c in partes)} fotos)")
    procs, salidas = [], []
    for i, (di, _) in enumerate(partes):
        si = Path(tmp) / f"{stem}__salida{i}"
        shutil.rmtree(si, ignore_errors=True)
        salidas.append(si)
        args = {**{k: (str(v) if isinstance(v, Path) else v) for k, v in op.items()}, "device": 0, "stem": stem,
                "proveedor": proveedor}
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(i)}
        procs.append(correr([sys.executable, "-c", PARTE, str(di / "codigo"), str(di), str(si), json.dumps(args)], env=env))
    rcs = [p.wait() for p in procs]
    estados = [json.loads((s / f"{stem}.estado.json").read_text(encoding="utf-8"))
               if (s / f"{stem}.estado.json").is_file() else {"ok": False, "error": f"parte sin estado (rc {rc})"}
               for s, rc in zip(salidas, rcs)]
    ok = all(e.get("ok") for e in estados)
    resultado, error = None, None
    if ok:
        try:
            resultado = juntar(grupo, stem, salidas, carpeta)
        except Exception as e:
            ok, error = False, f"no pude juntar las partes: {type(e).__name__}: {e}"
    else:
        error = " | ".join(f"parte {i}: {e.get('error')}" for i, e in enumerate(estados) if not e.get("ok"))
    if error:
        (Path(carpeta) / f"{stem}_error.txt").write_text(error + "\n", encoding="utf-8")
    ent = {**(estados[0].get("entorno") or {}), "gpus": len(partes)}
    est = {"esquema": 1, "trabajo": stem, "tipo": estados[0].get("tipo"), "ok": ok, "inicio": inicio,
           "fin": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seg": round(time.time() - t0, 1), "resultado": resultado,
           "error": error, "entorno": ent,
           "partes": [{"fotos": c, "seg": e.get("seg"), "ok": e.get("ok")} for (_, c), e in zip(partes, estados)]}
    (Path(carpeta) / f"{stem}.estado.json").write_text(json.dumps(est, ensure_ascii=True, indent=1), encoding="utf-8")
    for p in [di for di, _ in partes] + salidas:
        shutil.rmtree(p, ignore_errors=True)
    log(f"{'OK' if ok else 'ERROR'} {stem} en {est['seg']} s con {len(partes)} GPU -> {resultado or error}")
    return est


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


def ejecutar(envio, zips, salida, tmp, proveedor="kaggle", sh=_sh, sam3_pt=None, device=0, cache=None, n_gpus=None,
             min_partir=MIN_PARTIR):
    """Procesa los trabajos de envio.json. -> lista de estados (tambien en salida/envio_resultado.json).
    n_gpus: None = las que vea la sesion; con 2 o mas, los trabajos SAM 3 grandes se parten (P.3.6)."""
    envio, zips, salida, tmp = dict(envio), Path(zips), Path(salida), Path(tmp)
    cache = {} if cache is None else cache
    listos, estados = {}, []
    for t in envio["trabajos"]:
        stem, carpeta = Path(t["archivo"]).stem, salida / CARPETA.get(t["tipo"], "otros")
        carpeta.mkdir(parents=True, exist_ok=True)
        d = tmp / stem
        shutil.rmtree(d, ignore_errors=True)
        try:
            zp = zips / t.get("en_envio", t["archivo"])      # <zip>.xd: Kaggle descomprime los .zip de un dataset
            ya = next((c for c in (zips / t["archivo"], zips / stem) if c.is_dir()), None)
            if zp.is_file():
                with zipfile.ZipFile(zp) as z:
                    z.extractall(d)
            elif ya is not None:                             # por si Kaggle lo descomprimio igual
                shutil.copytree(ya, d)
            else:
                hay = sorted(p.name for p in zips.iterdir())[:30]
                raise FileNotFoundError(f"no esta {zp.name} en {zips}; hay: {hay}")
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
            sh(VISION)                                  # mientras, precalentar lee sam3.pt (P.4.R5)
        if sam3_pt:
            esperar_precalentado(sam3_pt)
        previo, asistente_listo = None, False
        n_gpus = gpus() if n_gpus is None else n_gpus
        if n_gpus > 1:
            log(f"{n_gpus} GPU: los trabajos SAM 3 de {min_partir} fotos o mas se reparten entre ellas")
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
                if str(sam3_pt) in VERIFICADO:
                    op["sha_modelo"] = VERIFICADO[str(sam3_pt)]
            items = 0
            if g in POR_GPU and n_gpus > 1:
                archivo, clave = POR_GPU[g]
                items = len(json.loads((d / archivo).read_text(encoding="utf-8")).get(clave) or [])
            if items >= min_partir:
                worker.liberar(cache)                   # el proceso principal no retiene ningun SAM 3
                estados.append(en_paralelo(d, stem, g, listos[stem][1], n_gpus, tmp, op, proveedor))
            else:
                estados.append(worker.procesar(d, listos[stem][1], cache, stem=stem, ent=worker.entorno(proveedor), **op))
            previo = g
    res = {"esquema": 1, "envio": envio.get("envio"), "fin": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "estados": estados,
           "pesos_verificados": PESOS_VERIFICADOS.get("version")}
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
        p = envio.get("pesos") or {}
        sam3 = verificar_pesos(f_pesos, completo=p.get("verificar_sha", True))
        if p.get("verificar_sha", True) and p.get("version"):
            PESOS_VERIFICADOS["version"] = p["version"]
    ejecutar(envio, f_envio.parent, SALIDA, TMP, sam3_pt=sam3)
    shutil.rmtree(TMP, ignore_errors=True)
    log(f"total {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
