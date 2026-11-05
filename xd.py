#!/usr/bin/env python3
"""CLI del sistema de pre-etiquetado (A.5). Solo biblioteca estandar: corre con cualquier Python >= 3.10
en Windows, Mac o Linux, sin venv. Lee la configuracion del .env de esta carpeta.
Uso: python xd.py <comando> [opciones]    (python xd.py -h)"""
import argparse, json, os, re, shutil, subprocess, sys, time, urllib.request
from pathlib import Path, PurePosixPath

RAIZ = Path(__file__).resolve().parent


def leer_env(ruta=RAIZ / ".env"):
    env = {}
    if ruta.exists():
        for l in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
            l = l.strip()
            if l and not l.startswith("#") and "=" in l:
                k, v = l.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = leer_env()
LS = ENV.get("LS_HOST_URL", "http://127.0.0.1:8080").rstrip("/")
MOTOR = ENV.get("MOTOR_HOST_URL", "http://127.0.0.1:9090").rstrip("/")
LOTES_LOCAL = RAIZ / "motor" / "lotes"          # = /app/lotes en el contenedor (MOTOR_DATOS=/app)
TRABAJOS_DB = Path(ENV.get("TRABAJOS_DB") or RAIZ / "datos" / "trabajos.sqlite")   # P.1: local, nunca en Drive


# ----------------------------------------------------------------- utilidades
def http(metodo, url, datos=None, token=False, timeout=30):
    h = {"Content-Type": "application/json"}
    if token:
        if not ENV.get("LS_API_TOKEN"):
            raise SystemExit("Falta LS_API_TOKEN en .env")
        h["Authorization"] = "Token " + ENV["LS_API_TOKEN"]
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    req = urllib.request.Request(url, data=cuerpo, headers=h, method=metodo)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        txt = r.read()
    return json.loads(txt) if txt else None


def intentar(f, *a, **kw):
    """None si el servicio no responde (arrancando, conexion cortada, timeout)."""
    try:
        return f(*a, **kw)
    except OSError:
        return None


def esperar(cond, limite, cada, que):
    t0 = time.time()
    while time.time() - t0 < limite:
        v = cond()
        if v:
            print(" " * 60, end="\r")
            return v
        print(f"  esperando {que}... {time.time() - t0:.0f}s ", end="\r", flush=True)
        time.sleep(cada)
    raise SystemExit(f"\nTiempo agotado ({limite}s) esperando {que}")


def _estado():
    return intentar(http, "GET", MOTOR + "/estado", timeout=5)


def en_motor(script, *args):
    """Corre /app/<script> dentro del contenedor; muestra la salida en vivo y la devuelve."""
    cmd = ["docker", "compose", "exec", "-T", "motor", "python", f"/app/{script}", *map(str, args)]
    p = subprocess.Popen(cmd, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    salida = []
    for l in p.stdout:
        print(l, end="", flush=True)
        salida.append(l)
    return p.wait(), "".join(salida)


def _transporte():
    """P.2.5: transporte segun TRANSPORTE del .env (Drive por defecto). Se lee cada vez (los tests cambian ENV)."""
    import transporte
    return transporte.elegir(ENV, RAIZ)


def _extraer_grupo(zp, archivo_meta):
    """P.4.3: lee el campo grupo del manifiesto.json o trabajo.json dentro del zip. -> str o None."""
    import zipfile
    try:
        with zipfile.ZipFile(zp, "r") as z:
            contenido = z.read(archivo_meta).decode("utf-8")
            meta = json.loads(contenido)
            return meta.get("grupo")
    except Exception:
        return None


# ----------------------------------------------------------------- comandos
def cmd_estado(a):
    ls = intentar(http, "GET", LS + "/health", timeout=5)
    mh = intentar(http, "GET", MOTOR + "/health", timeout=5)
    print(f"Label Studio {LS:<24} {(ls or {}).get('status', 'NO RESPONDE')}")
    print(f"Motor        {MOTOR:<24} {(mh or {}).get('status', 'NO RESPONDE')}")
    es = _estado()
    for k, v in (es or {}).items():
        print(f"  {k:<18} {v}")
    return 0 if ls and mh else 1


def cmd_precalentar(a):
    esperar(lambda: intentar(http, "GET", MOTOR + "/health", timeout=5), a.limite, 3, "motor (/health)")
    es = _estado() or {}
    if es.get("listo"):
        print(f"SAM 3 ya estaba listo (imgsz={es.get('imgsz')}, device={es.get('device')})")
        return 0
    cfg = http("GET", f"{LS}/api/projects/{a.proyecto}", token=True)["label_config"]
    http("POST", MOTOR + "/predict", {"tasks": [], "label_config": cfg, "project": str(a.proyecto),
                                      "params": {}}, timeout=60)
    print(f"Precalentando proyecto {a.proyecto}...")
    t0 = time.time()
    es = esperar(lambda: (_estado() or {}).get("listo") and _estado(), a.limite, 10, "SAM 3 interactivo")
    print(f"SAM 3 listo en {time.time() - t0:.0f}s (imgsz={es['imgsz']}, device={es['device']})")
    return 0


def cmd_reiniciar_motor(a):
    es = _estado() or {}
    ocupado = sum(int(es.get(k) or 0) for k in ("cola", "cola_pendientes", "precodificando"))
    if ocupado and not a.forzar:
        raise SystemExit(f"El motor tiene trabajo en curso (cola={es.get('cola')}, pendientes="
                         f"{es.get('cola_pendientes')}, precodificando={es.get('precodificando')}); usa --forzar")
    print("Reiniciando motor (docker compose restart motor)...", flush=True)
    rc = subprocess.call(["docker", "compose", "restart", "motor"], cwd=RAIZ)
    if rc:
        return rc
    esperar(lambda: intentar(http, "GET", MOTOR + "/health", timeout=5), a.limite, 3, "motor (/health)")
    print("Motor arriba", flush=True)
    return cmd_precalentar(a) if a.precalentar else 0


def cmd_archivar(a):
    """Mueve un trabajo en espera de Drive a _archivo/ (la lanzadora de Colab ya no lo procesa). No borra nada."""
    nombre = Path(a.archivo).name
    if nombre != a.archivo or not re.fullmatch(r"(asist_.+|lote_p\d+_.+|dataset_p\d+_.+)\.zip", nombre):
        raise SystemExit(f"{a.archivo!r}: solo un nombre asist_*.zip, lote_p*.zip o dataset_p*.zip, sin carpeta")
    tipo = "asistente" if nombre.startswith("asist_") else "preetiquetado" if nombre.startswith("lote_") else "entrenamiento"
    import transporte
    T, c = _transporte(), transporte.carpeta_de(nombre)
    d = T.requerir(c)
    if not (d / nombre).is_file():
        raise SystemExit(f"No encuentro {nombre} en {d}")
    print(f"{'moviendo' if a.aplicar else 'MOVERIA'} {d / nombre} -> {d / '_archivo' / nombre}")
    if not a.aplicar:
        print("SOLO REPORTE: usa --aplicar para archivar")
        return 0
    T.archivar(c, nombre)
    print("OK archivado")
    _en_cola(nombre, _q_archivar, tipo, nombre)
    return 0


def cmd_lote_exportar(a):
    T = _transporte()
    T.requerir("lotes")                             # antes de exportar: sin transporte no hay a donde enviar
    args = [a.proyecto] + (["--limite", a.limite] if a.limite else []) + \
           (["--tareas", a.tareas] if a.tareas else []) + (["--todas"] if a.todas else []) + list(getattr(a, "extra", [])) + (["--modo", a.modo] if getattr(a, "modo", "") else [])
    rc, out = en_motor("exportar_lote.py", *args)
    if rc:
        return rc                                   # incluye "no hay tareas pendientes"
    zips = [LOTES_LOCAL / PurePosixPath(m.group(1)).name for m in re.finditer(r"-> (\S+\.zip)", out)]
    if not zips:
        raise SystemExit("No encontre rutas de zip en la salida de exportar_lote.py")
    ids = []
    for zp in zips:
        grupo = _extraer_grupo(zp, "manifiesto.json")
        ids += _ids_lote(zp)
        _en_cola(zp.name, _q_crear, "preetiquetado", zp.name, "pendiente", proyecto=a.proyecto, grupo=grupo)
        print(f"Enviado ({T.nombre}): {T.enviar('lotes', zp)}")
        _en_cola(zp.name, _q_enviado, "preetiquetado", zp.name)
    if getattr(a, "precodificar", False) and ids:   # P.4.R1: mismas tareas, mismos trozos: el trozo 1 llega con su cache
        print(f"Precodificando las mismas {len(ids)} tareas (trozo {getattr(a, 'trozo', 0) or 'unico'}) para el clic liviano")
        rc = _precodificar(a.proyecto, T, trozo=getattr(a, "trozo", 0), tareas=ids)
        if rc not in (0, 3):
            print(f"AVISO: la precodificacion salio con rc {rc}; el clic no respondera en esas fotos hasta precodificarlas")
    print(_siguiente_externo(T, "python xd.py lote-importar"))
    return 0


def _ids_lote(zp):
    """ids de tarea del manifiesto de un lote, en su orden."""
    import zipfile
    try:
        with zipfile.ZipFile(zp) as z:
            return [t["id"] for t in json.loads(z.read("manifiesto.json"))["tareas"]]
    except Exception:
        return []


def _prioridad(valor, proyecto):
    """'' | 'ultimo' (diag_p<N> mas reciente) | nombre de archivo en motor/diagnosticos."""
    if not valor:
        return []
    d = RAIZ / "motor" / "diagnosticos"
    if valor == "ultimo":
        fs = sorted(d.glob(f"diag_p{proyecto}_*.json"))
        if not fs:
            raise SystemExit(f"No hay diag_p{proyecto}_*.json en {d}")
        f = fs[-1]
    else:
        f = d / Path(valor).name
        if not f.exists():
            raise SystemExit(f"No existe {f} (debe estar en motor/diagnosticos)")
    print(f"Prioridad: {f.name}")
    return ["--prioridad", f"/app/diagnosticos/{f.name}"]


def cmd_preetiquetar(a):
    extra = ["--muestra", a.muestra, "--semilla", a.semilla, "--minimo", a.minimo, "--trozo", a.trozo] + \
            _prioridad(a.prioridad, a.proyecto)
    if not a.aplicar:
        args = [a.proyecto, *extra, "--modo", a.modo, "--reporte"] + (["--todas"] if a.todas else [])
        rc = en_motor("exportar_lote.py", *args)[0]
        if rc == 0:
            print("Modo reporte. Para generar el lote y enviarlo al worker agrega --aplicar")
        return rc
    a.limite, a.tareas, a.extra = 0, "", extra
    return cmd_lote_exportar(a)

def cmd_lote_importar(a):
    drive = _transporte().requerir("lotes")
    LOTES_LOCAL.mkdir(parents=True, exist_ok=True)
    nuevos = sorted(f for f in drive.glob("*_pred.json") if not (LOTES_LOCAL / f.name).exists())
    if not nuevos:
        print(f"No hay predicciones nuevas en {drive}")
        return 0
    for f in nuevos:
        destino = LOTES_LOCAL / f.name
        shutil.copy2(f, destino)
        rc, out = en_motor("importar_lote.py", f.name, *(["--sufijo", a.sufijo] if a.sufijo else []), *(["--fijar-version"] if a.fijar_version else []))
        zp = f.name[:-len("_pred.json")] + ".zip"
        m = re.match(r"^lote_p(\d+)_", f.name)
        n = int(m.group(1)) if m else None
        if rc:
            destino.unlink(missing_ok=True)         # permite reintentar
            _en_cola(zp, _q_fallo, "preetiquetado", zp, f.name, f"importar_lote.py rc {rc}: {out[-500:]}", proyecto=n)
            raise SystemExit(f"importar fallo: {f.name}")
        _en_cola(zp, _q_importado, "preetiquetado", zp, f.name, proyecto=n)
    return 0


ENTRENAMIENTO = ("modelo", "imgsz", "epochs", "patience", "batch", "conf_conteo", "device")   # P.2.3: viajan en trabajo.json


def cmd_precodificar(a):
    """P.3.3: fotos del proyecto sin cache de SAM 3 -> trabajo de precodificacion para el worker (GPU)."""
    T = _transporte()
    T.requerir("lotes")
    if not a.aplicar:
        args = [a.proyecto] + (["--todas"] if a.todas else []) + (["--limite", a.limite] if a.limite else []) + \
               ["--trozo", a.trozo]
        rc = en_motor("exportar_pre.py", *args, "--reporte")[0]
        if rc == 0:
            print("Modo reporte. Para generar el trabajo y enviarlo al worker agrega --aplicar")
        return rc
    rc = _precodificar(a.proyecto, T, trozo=a.trozo, todas=a.todas, limite=a.limite)
    if rc == 0:
        print(_siguiente_externo(T, "python xd.py cache-importar --aplicar"))
    return 0 if rc == 3 else rc


def _precodificar(proyecto, T, trozo=0, todas=False, limite=0, tareas=()):
    """Exporta la precodificacion (opcionalmente de tareas dadas, en su orden) y la deja en la cola.
    -> 0 ok | 3 nada que precodificar (todas con cache) | otro rc de exportar_pre.py"""
    args = [proyecto] + (["--todas"] if todas else []) + (["--limite", limite] if limite else []) + ["--trozo", trozo] + \
           (["--tareas", ",".join(str(i) for i in tareas)] if tareas else [])
    rc, out = en_motor("exportar_pre.py", *args)
    if rc:
        if "ya tienen cache" in out:
            print("Todas esas fotos ya tienen cache: nada que precodificar")
            return 3
        return rc
    zips = [LOTES_LOCAL / PurePosixPath(m.group(1)).name for m in re.finditer(r"-> (\S+\.zip)", out)]
    if not zips:
        raise SystemExit("No encontre rutas de zip en la salida de exportar_pre.py")
    for zp in zips:
        grupo = _extraer_grupo(zp, "trabajo.json")
        _en_cola(zp.name, _q_crear, "precodificacion", zp.name, "pendiente", proyecto=proyecto, grupo=grupo)
        print(f"Enviado ({T.nombre}): {T.enviar('lotes', zp)}")
        _en_cola(zp.name, _q_enviado, "precodificacion", zp.name)
    return 0


def cmd_cache_importar(a):
    """P.3.4: mueve la cache que trajo el worker (transporte: lotes/cache/*.pt) a motor/cache_sam3, donde la usa el clic.
    Las precodificaciones cuyo indice queda completo pasan a importado en la cola."""
    sys.path.insert(0, str(RAIZ / "motor"))
    import cache_sam3 as CS
    T = _transporte()
    lotes = T.carpeta("lotes")
    src = lotes / "cache" if lotes else None
    dest = RAIZ / "motor" / "cache_sam3"
    fs = sorted(src.glob("*.pt")) if src and src.is_dir() else []
    malos = [f for f in fs if not CS.CLAVE.match(f.stem)]
    nuevos = [f for f in fs if f not in malos and not (dest / f.name).is_file()]
    repetidos = [f for f in fs if f not in malos and f not in nuevos]
    mb = sum(f.stat().st_size for f in nuevos) / 1e6
    print(f"origen {src} ({T.nombre}) -> {dest}")
    print(f"  nuevos {len(nuevos)} ({mb:.1f} MB) | ya en el hub {len(repetidos)} | nombre invalido {len(malos)}")
    for f in malos[:5]:
        print(f"  AVISO: {f.name} no tiene forma de clave de cache; se deja donde esta")
    if not a.aplicar:
        if nuevos or repetidos:
            print("SOLO REPORTE: --aplicar los mueve al hub (los repetidos se quitan del transporte)")
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    for f in nuevos:
        tmp = dest / (f.name + ".tmp")
        shutil.copy2(f, tmp)
        tmp.replace(dest / f.name)
        f.unlink()
    for f in repetidos:
        f.unlink()
    print(f"OK {len(nuevos)} archivo(s) en {dest}")
    _en_cola("precodificaciones", _q_cache_importada, lotes, dest)
    return 0


def _q_cache_importada(C, con, lotes, dest):
    """Precodificaciones en listo cuyo indice (<stem>_cache.json) ya esta entero en el hub -> importado."""
    for t in C.listar(con, tipo="precodificacion", estado="listo"):
        f = lotes / (t["resultado"] or "")
        try:
            claves = [x["clave"] for x in json.loads(f.read_text(encoding="utf-8"))["fotos"]]
        except (OSError, ValueError, KeyError, TypeError):
            print(f"AVISO cola: no puedo leer {f.name}; trabajo {t['id']} sigue en listo")
            continue
        falta = [c for c in claves if not (dest / f"{c}.pt").is_file()]
        if falta:
            print(f"AVISO cola: a {t['archivo']} le faltan {len(falta)} de {len(claves)} archivos; sigue en listo")
            continue
        C.mover(con, t["id"], "importado", desde="listo", detalle=f"{len(claves)} archivos de cache en el hub")
        print(f"Cola: {t['archivo']} -> importado ({len(claves)} fotos con cache)")


def cmd_sam3_ligero(a):
    """P.3.5: extrae (una vez) el checkpoint del SAM 3 interactivo sin image encoder para el hub liviano."""
    return en_motor("sam3_ligero.py", *(["--aplicar"] if a.aplicar else []))[0]


def cmd_dataset(a):
    extra = [x for k in ENTRENAMIENTO for x in ((f"--{k.replace('_', '-')}", getattr(a, k, "")) if getattr(a, k, "") else ())]
    rc, out = en_motor("exportar_yolo.py", a.proyecto, "--formato", a.formato, "--val", a.val, *(["--correcciones", a.correcciones] if a.correcciones else []), *extra)
    if rc:
        return rc
    m = re.search(r"OK -> (\S+\.zip)", out)
    if a.drive and m:
        T = _transporte()
        zp = RAIZ / "motor" / "datasets" / PurePosixPath(m.group(1)).name
        _en_cola(zp.name, _q_crear, "entrenamiento", zp.name, "pendiente", proyecto=a.proyecto)
        print(f"Enviado ({T.nombre}): {T.enviar('datasets', zp)}")
        _en_cola(zp.name, _q_enviado, "entrenamiento", zp.name)
        print(_siguiente_externo(T, f"python xd.py registrar {a.proyecto} --run ultimo --activar"))
    return 0


TESTS_HOST = ("plan", "muestra", "correccion", "registro", "aceptacion", "esquema_llm", "asistente", "buzon", "comparar",
              "plantilla", "notebooks", "ver", "cola_trabajos", "xd_trabajos", "worker", "transporte", "kaggle", "lanzador", "cache_sam3")
TESTS_MOTOR = ("generar", "spec", "hijo", "reglas", "concurrencia", "cache_clic")      # necesitan el contenedor (torch, rutas /app)


def _correr(cmd, timeout=600):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=RAIZ, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
        return p.returncode, (p.stdout or "") + (p.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, f"tiempo agotado ({timeout}s)", time.time() - t0


def cmd_test(a):
    """Todos los tests (host + contenedor). rc 0 solo si todos pasan; 2 si la lista de tests esta desactualizada."""
    dm = RAIZ / "motor"
    hay = sorted(f.stem[5:] for f in dm.glob("test_*.py"))
    sin = [x for x in hay if x not in TESTS_HOST + TESTS_MOTOR]
    faltan = [x for x in TESTS_HOST + TESTS_MOTOR if x not in hay]
    if sin or faltan:
        print(f"ERROR: lista de tests desactualizada en xd.py | sin clasificar {sin} | no existen {faltan}")
        return 2
    plan = [(x, "host") for x in TESTS_HOST if a.solo in (None, "host")]
    plan += [(x, "motor") for x in TESTS_MOTOR if a.solo in (None, "motor")]
    plan = [(x, d) for x, d in plan if a.k in x]
    if not plan:
        print(f"ningun test coincide con -k {a.k!r}")
        return 2
    motor_ok = _estado() is not None if any(d == "motor" for _, d in plan) else True
    fallas = []
    for x, d in plan:
        if d == "host":
            rc, out, seg = _correr([sys.executable, str(dm / f"test_{x}.py")])
        elif not motor_ok:
            rc, out, seg = 1, "motor no responde: docker compose up -d", 0.0
        else:
            extra = [str(a.proyecto)] if x == "reglas" and a.proyecto else []
            rc, out, seg = _correr(["docker", "compose", "exec", "-T", "motor", "python", f"/app/test_{x}.py", *extra])
        lineas = [l for l in out.splitlines() if l.strip()]
        print(f"  {'OK   ' if rc == 0 else 'FALLA'} {x:<12} {d:<5} {seg:5.1f}s  {(lineas[-1] if lineas else '')[:80]}")
        if a.verbose or rc != 0:
            for l in (lineas if a.verbose else lineas[-15:]):
                print(f"        | {l}")
        if rc != 0:
            fallas.append(x)
    print(f"{len(plan) - len(fallas)}/{len(plan)} OK" + (f" | fallaron: {fallas}" if fallas else ""))
    return 1 if fallas else 0


def _spec(slug):
    ruta = RAIZ / "motor" / "proyectos" / slug / "spec.json"
    if not ruta.exists():
        raise SystemExit(f"No existe {ruta}")
    return json.loads(ruta.read_text(encoding="utf-8"))


def _dir_cuadernos():
    if ENV.get("CUADERNOS_DRIVE"):
        return Path(ENV["CUADERNOS_DRIVE"])
    if ENV.get("LOTES_DRIVE"):
        return Path(ENV["LOTES_DRIVE"]).parent.parent / "Colab Notebooks"
    raise SystemExit("Define LOTES_DRIVE (o CUADERNOS_DRIVE) en .env")


def cmd_cuadernos(a):
    """notebooks/ (repo, fuente de verdad) <-> copias en Drive. Por defecto solo reporta."""
    import cuadernos as C
    repo, drv = RAIZ / "notebooks", _dir_cuadernos()
    print(f"repo  {repo}\ndrive {drv}")
    cambios = 0
    for n in C.NOMBRES:
        fr, fd = repo / n, drv / n
        r = json.loads(fr.read_text(encoding="utf-8")) if fr.exists() else None
        d = json.loads(fd.read_text(encoding="utf-8")) if fd.exists() else None
        if r is None and d is None:
            print(f"  {n:<22} no existe en ningun lado")
            continue
        estado = "solo en repo" if d is None else "solo en Drive" if r is None else (C.diferencias(r, d) or "igual")
        print(f"  {n:<22} {estado}")
        if estado == "igual":
            continue
        if a.traer and d is not None:
            cambios += 1
            if a.aplicar:
                fr.write_text(C.texto(d), encoding="utf-8", newline="\n")
                print("      -> repo actualizado (sin salidas ni metadatos)")
        if a.llevar and r is not None:
            if d is not None and not a.forzar:
                print("      NO llevo: la copia de Drive tiene cambios que el repo no tiene (traelos o usa --forzar)")
                continue
            cambios += 1
            if a.aplicar:
                drv.mkdir(parents=True, exist_ok=True)
                fd.write_text(C.texto(r), encoding="utf-8", newline="\n")
                print("      -> Drive actualizado")
    for n in C.RETIRADOS:                       # P.2.4: cuadernos viejos que siguen en Drive
        fd = drv / n
        if fd.exists():
            print(f"  {n:<22} retirado (lo reemplaza worker.ipynb); con --llevar se mueve a {drv / '_archivo'}")
            if a.llevar:
                cambios += 1
                if a.aplicar:
                    (drv / "_archivo").mkdir(exist_ok=True)
                    shutil.move(str(fd), str(drv / "_archivo" / n))
                    print("      -> archivado")
    if (a.traer or a.llevar) and cambios and not a.aplicar:
        print("SOLO REPORTE: usa --aplicar")
    return 0


PLANTILLA = RAIZ / "motor" / "plantillas" / "spec_plantilla.json"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validar_spec(spec, slug):
    """spec.validar (puro) + reglas del host: slug = carpeta, raiz dentro de mis_imagenes, sin marcas CAMBIAR."""
    if str(RAIZ / "motor") not in sys.path:
        sys.path.insert(0, str(RAIZ / "motor"))
    import spec as specmod
    e, av = specmod.validar(spec)
    if isinstance(spec, dict):
        pr = spec.get("proyecto") if isinstance(spec.get("proyecto"), dict) else {}
        if pr.get("slug") != slug:
            e.append(f"proyecto.slug={pr.get('slug')!r}: debe ser {slug!r} (el nombre de la carpeta)")
        im = spec.get("imagenes") if isinstance(spec.get("imagenes"), dict) else {}
        raiz = str(im.get("raiz") or f"mis_imagenes/{slug}").strip("/")
        if raiz.split("/")[0] != "mis_imagenes":
            e.append(f"imagenes.raiz={raiz!r}: debe estar dentro de mis_imagenes (unico montaje de Label Studio)")
    n = json.dumps(spec, ensure_ascii=True).count("CAMBIAR")
    if n:
        e.append(f"quedan {n} marcas CAMBIAR de la plantilla: completa esos textos (ver motor/plantillas/LEEME_spec.md)")
    return e, av


def cmd_validar(a):
    ruta = RAIZ / "motor" / "proyectos" / a.slug / "spec.json"
    if not ruta.exists():
        raise SystemExit(f"No existe {ruta}: crea una con  python xd.py spec-nueva {a.slug}")
    try:
        spec = json.loads(ruta.read_text(encoding="utf-8"))
    except ValueError as ex:
        print(f"ERROR: {ruta.name} no es JSON valido: {ex}")
        return 1
    e, av = _validar_spec(spec, a.slug)
    for x in e:
        print("ERROR:", x)
    for x in av:
        print("AVISO:", x)
    print(f"{a.slug}: {len(e)} error(es), {len(av)} aviso(s)")
    return 1 if e else 0


def cmd_spec_nueva(a):
    if not SLUG_RE.match(a.slug):
        raise SystemExit(f"slug={a.slug!r}: solo minusculas, digitos, _ o -")
    ruta = RAIZ / "motor" / "proyectos" / a.slug / "spec.json"
    if ruta.exists():
        raise SystemExit(f"Ya existe {ruta}: editala o borrala; spec-nueva no sobrescribe")
    s = json.loads(PLANTILLA.read_text(encoding="utf-8"))
    s["proyecto"]["slug"] = a.slug
    if a.titulo:
        s["proyecto"]["titulo"] = a.titulo.strip()
    s["imagenes"] = {"raiz": f"mis_imagenes/{a.slug}"}
    e, av = _validar_spec(s, a.slug)
    print(f"spec {'CREADA' if a.aplicar else 'CREARIA'} {ruta} desde {PLANTILLA.name}")
    print(f"  titulo {s['proyecto']['titulo']!r} | clases {[c['nombre'] for c in s['clases']]} | "
          f"carpetas {[k['nombre'] for k in s['carpetas']]}")
    for x in e + av:
        print("  pendiente:", x)
    if not a.aplicar:
        print("SOLO REPORTE: usa --aplicar para crear")
        return 0
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(s, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")
    print(f"Siguiente: edita {ruta} y revisa con  python xd.py validar {a.slug}")
    return 0


def cmd_crear_proyecto(a):
    spec = _spec(a.slug)
    e, _ = _validar_spec(spec, a.slug)
    if e:
        for x in e:
            print("ERROR:", x)
        print(f"NO creo: la spec tiene {len(e)} error(es)  (python xd.py validar {a.slug})")
        return 1
    if a.slug.endswith("-ref"):
        print(f"NO creo: {a.slug} es una spec de referencia (solo para comparar)")
        return 1
    raiz = ((spec.get("imagenes") or {}).get("raiz") or f"mis_imagenes/{a.slug}").strip("/")
    if raiz.split("/")[0] != "mis_imagenes":
        raise SystemExit(f"imagenes.raiz={raiz!r}: debe estar dentro de mis_imagenes (unico montaje de Label Studio)")
    for k in spec.get("carpetas", []):
        d = RAIZ / raiz / k["nombre"]
        if a.aplicar:
            d.mkdir(parents=True, exist_ok=True)
        print(f"carpeta {'lista ' if d.is_dir() else 'CREARIA'} {d}")
    args = [f"/app/proyectos/{a.slug}/spec.json"] + (["--aplicar"] if a.aplicar else [])
    return en_motor("crear_proyecto.py", *args)[0]


def cmd_sincronizar(a):
    return en_motor("sincronizar.py", a.slug)[0]


def cmd_borrar_proyecto(a):
    return en_motor("borrar_proyecto.py", a.slug, *(["--aplicar"] if a.aplicar else []))[0]


EXT_IMG = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _raiz(spec, slug):
    raiz = ((spec.get("imagenes") or {}).get("raiz") or f"mis_imagenes/{slug}").strip("/")
    if raiz.split("/")[0] != "mis_imagenes":
        raise SystemExit(f"imagenes.raiz={raiz!r}: debe estar dentro de mis_imagenes")
    return RAIZ / raiz


def _contar(d):
    return sum(1 for x in d.iterdir() if x.suffix.lower() in EXT_IMG) if d.is_dir() else 0


def cmd_plan(a):
    sys.path.insert(0, str(RAIZ / "motor"))
    from plan import plan_captura
    spec = _spec(a.slug)
    base = _raiz(spec, a.slug)
    filas = plan_captura(spec, a.total or None)
    w = max(14, *(len(f["carpeta"]) for f in filas)) + 2
    print(f"{'carpeta':<{w}}{'tipo':<10}{'recom':>6}{'tienes':>8}{'faltan':>8}")
    tr = tt = tf = 0
    for f in filas:
        n = _contar(base / f["carpeta"])
        falta = max(0, f["fotos"] - n)
        tr, tt, tf = tr + f["fotos"], tt + n, tf + falta
        print(f"{f['carpeta']:<{w}}{f['tipo']:<10}{f['fotos']:>6}{n:>8}{falta:>8}")
    print(f"{'TOTAL':<{w + 10}}{tr:>6}{tt:>8}{tf:>8}")
    if a.variaciones:
        for f in filas:
            print(f"\n{f['carpeta']} ({f['motivo']}):")
            for v in f["variaciones"]:
                print("  -", v)
    return 0


def _registro(proyecto):
    sys.path.insert(0, str(RAIZ / "motor"))
    import registro
    f = RAIZ / "motor" / "modelos" / f"p{proyecto}" / "registro.json"
    reg = json.loads(f.read_text(encoding="utf-8")) if f.exists() else registro.vacio(proyecto)
    return registro, f, reg


def _guardar(f, reg):
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(reg, ensure_ascii=True, indent=1), encoding="utf-8")


def _run(valor, proyecto):
    runs = _transporte().requerir("runs")
    if valor == "ultimo":
        cands = [r for r in runs.glob(f"dataset_p{proyecto}_*") if (r / "weights" / "metricas.json").exists()]
        if not cands:
            raise SystemExit(f"No hay corridas dataset_p{proyecto}_* con metricas.json en {runs}")
        return max(cands, key=lambda r: (r / "weights" / "metricas.json").stat().st_mtime)
    r = runs / valor
    if not (r / "weights" / "metricas.json").exists():
        raise SystemExit(f"No existe {r / 'weights' / 'metricas.json'}")
    return r


def cmd_registrar(a):
    registro, f, reg = _registro(a.proyecto)
    if a.run:
        r = _run(a.run, a.proyecto)
        pt, met_f, origen = r / "weights" / "best.pt", r / "weights" / "metricas.json", f"runs/{r.name}"
        nombre = a.nombre or r.name.removeprefix("dataset_")
    else:
        if not (a.pt and a.metricas):
            raise SystemExit("Usa --run, o bien --pt y --metricas")
        pt, met_f = Path(a.pt), Path(a.metricas)
        origen, nombre = f"manual:{pt}", a.nombre or pt.stem
    for x in (pt, met_f):
        if not x.exists():
            raise SystemExit(f"No existe {x}")
    met = json.loads(met_f.read_text(encoding="utf-8"))
    if met.get("proyecto") not in (None, a.proyecto) and not a.otro_proyecto:
        raise SystemExit(f"{met_f} es del proyecto {met.get('proyecto')}, no del {a.proyecto}")
    dest = f.parent / nombre
    if (dest / "best.pt").exists():
        raise SystemExit(f"Ya existe {dest / 'best.pt'}; usa otro --nombre")
    try:
        nuevo = registro.agregar(reg, nombre, met, f"p{a.proyecto}/{nombre}/best.pt", origen,
                                 time.strftime("%Y-%m-%dT%H:%M:%S"))
        if a.activar:
            nuevo = registro.activar(nuevo, nombre)
    except (ValueError, KeyError) as e:
        raise SystemExit(str(e))
    accion = "copiando" if a.aplicar else "COPIARIA"
    print(f"{accion} {pt} -> {dest / 'best.pt'} ({pt.stat().st_size / 1e6:.1f} MB)")
    print(f"{accion} {met_f} -> {dest / 'metricas.json'}")
    print("\n".join(registro.tabla(nuevo)))
    if not a.aplicar:
        print("SOLO REPORTE: usa --aplicar para copiar y registrar")
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pt, dest / "best.pt")
    if met_f.resolve() != (dest / "metricas.json").resolve():
        shutil.copy2(met_f, dest / "metricas.json")
    _guardar(f, nuevo)
    print(f"OK registrado {nombre} -> {f}")
    if a.run:
        _en_cola(r.name, _q_registrar, int(a.proyecto), r.name)
    return 0


def cmd_modelos(a):
    registro, f, reg = _registro(a.proyecto)
    if not reg["modelos"]:
        print(f"Sin modelos registrados ({f})")
        return 0
    if a.activar:
        try:
            reg = registro.activar(reg, a.activar)
        except KeyError as e:
            raise SystemExit(str(e))
    print("\n".join(registro.tabla(reg)))
    if a.activar:
        if a.aplicar:
            _guardar(f, reg)
            print(f"OK activo = {a.activar}")
        else:
            print("SOLO REPORTE: usa --aplicar para cambiar el activo")
    return 0

def cmd_aceptacion(a):
    return en_motor("medir_aceptacion.py", a.proyecto, *(["--versiones", a.versiones] if a.versiones else []))[0]

def cmd_kaggle_pesos(a):
    """P.2.6: sube sam3.pt + SAM License como dataset PRIVADO <usuario>/xd-pesos (una vez; version si cambia)."""
    import kaggle_xd as K
    u = K.usuario(ENV)
    cred = K.credencial()
    pesos = Path(a.pesos) if a.pesos else RAIZ / "sam3.pt"
    lic = RAIZ / "motor" / "plantillas" / "SAM_LICENSE.txt"
    dataset = f"{u}/{K.SLUG_PESOS}"
    if not pesos.is_file():
        raise SystemExit(f"No existe {pesos} (pidelo al responsable; no va en Git)")
    print(f"dataset   {dataset} (PRIVADO)")
    print(f"pesos     {pesos} ({pesos.stat().st_size / 1e9:.2f} GB)")
    print(f"licencia  {lic.name} -> LICENSE_SAM.txt (obligatoria al distribuir los pesos)")
    print(f"credencial {cred or 'NO HAY: guarda tu API token en ~/.kaggle/access_token'}")
    if not cred:
        if a.aplicar:
            raise SystemExit("Sin credencial de Kaggle no se puede subir")
        print("SOLO REPORTE")
        return 0
    existe = K.estado_dataset(dataset)
    print(f"en Kaggle {'existe (' + existe + '): se sube una VERSION nueva' if existe else 'no existe: se CREA'}")
    if not a.aplicar:
        print("SOLO REPORTE: usa --aplicar (calcula el sha256, arma la carpeta y sube; tarda segun tu conexion)")
        return 0
    carpeta = RAIZ / "datos" / "kaggle" / K.SLUG_PESOS
    t0 = time.time()
    info = K.armar_pesos(pesos, lic, carpeta, u)
    print(f"sha256 {info['sha256']} | {info['modo']} en {carpeta} | {time.time() - t0:.0f} s")
    t0 = time.time()
    try:
        rc, out = K.subir(carpeta, bool(existe), f"sam3.pt sha256 {info['sha256'][:12]}")
        print(K.ocultar(out)[-2000:])                    # segunda barrera: nada con forma de token a la consola
        if rc:
            raise SystemExit(f"la subida fallo (rc {rc})")
        subida = time.time() - t0
        listo = K.esperar_listo(dataset)
        print(f"OK {dataset}: subida {subida:.0f} s | disponible {'tras ' + str(listo) + ' s mas' if listo is not None else 'NO (revisa en kaggle.com)'}")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)       # el enlace duro no borra el original
    return 0


# ----------------------------------------------------------------- P.2.7 worker en Kaggle
ENVIO_DE_KERNEL = {"queued": "lanzado", "new_script": "lanzado", "running": "corriendo", "complete": "terminado",
                   "error": "fallido", "cancel_requested": "corriendo", "cancel_acknowledged": "fallido"}


def _kaggle_dir():
    return RAIZ / "datos" / "kaggle"


def _siguiente_externo(T, despues):
    """Que hacer despues de dejar un trabajo en el transporte (Colab o Kaggle)."""
    if T.nombre == "kaggle":
        return ("Siguiente:  python xd.py worker --enviar --aplicar  (o 'Enviar a Kaggle' en la UI); cuando termine, "
                f"worker --traer --aplicar; luego  {despues}")
    return f"Siguiente: en Colab corre worker.ipynb (celda 2); luego Reconciliar y  {despues}"


def _leer_error(c):
    def leer(nombre):
        for d in (c.get("asistente"), c.get("lotes"), c.get("datasets")):
            if d and (d / nombre).is_file():
                return (d / nombre).read_text(encoding="utf-8", errors="replace")
        return nombre
    return leer


def _trozo(nombre):
    """Numero de trozo de un zip de trabajo (..._t02.zip -> 2); sin trozo cuenta como 1 (va en el primer envio)."""
    m = re.search(r"_t(\d{2})\.zip$", nombre)
    return int(m.group(1)) if m else 1


def cmd_worker(a):
    """Envia a Kaggle los trabajos en espera, consulta el kernel y trae su salida. Todo con reporte primero.
    P.4.R1: un envio por llamada con el trozo mas bajo pendiente (el kernel es uno solo: el siguiente trozo sale cuando
    el anterior termina); --estado y --traer recorren los envios pendientes por version del kernel."""
    import kaggle_xd as K
    import transporte
    T = _transporte()
    if T.nombre != "kaggle":
        raise SystemExit(f"worker es para TRANSPORTE=kaggle (ahora: {T.nombre}); con Drive usa worker.ipynb en Colab")
    if sum(map(bool, (a.enviar, a.estado, a.traer))) != 1:
        raise SystemExit("Usa una de --enviar, --estado o --traer")
    u = K.usuario(ENV)
    kernel = f"{u}/{K.SLUG_KERNEL}"
    cred = K.credencial()
    if not cred:
        raise SystemExit("Sin credencial de Kaggle: guarda tu API token en ~/.kaggle/access_token")
    C = _cola_mod()
    con = _cola(crear=a.aplicar)

    def kv(e):                                     # el kernel de ESE envio (por version) o el ultimo si no la sabemos
        return f"{kernel}/{e['version']}" if e.get("version") else kernel
    try:
        pend = C.envios_pendientes(con, "kaggle") if con else []
        if a.estado:
            if not pend:
                est, msg = K.estado_kernel(kernel)
                print(f"kernel {kernel}: {est or 'sin ejecuciones o sin acceso'}" + (f" | {msg}" if msg else ""))
                print("Sin envios pendientes en la cola")
                return 0
            cambios = 0
            for e in pend:
                est, msg = K.estado_kernel(kv(e))
                n = len(C.trabajos_de(con, e["nombre"]))
                print(f"envio {e['nombre']} (kernel v{e.get('version') or '?'}): {e['estado']} | Kaggle {est or '?'} | "
                      f"{n} trabajo(s) | lanzado {e['creado']}" + (f" | {msg}" if msg else ""))
                nuevo = ENVIO_DE_KERNEL.get(est or "")
                if e["estado"] in ("lanzado", "corriendo") and nuevo and nuevo != e["estado"]:
                    cambios += 1
                    print(f"  envio {e['estado']} -> {nuevo}" + ("  (sus trabajos -> en_proceso)" if nuevo == "corriendo" else ""))
                    if a.aplicar:
                        C.marcar_envio(con, e["nombre"], nuevo, msg or None)
            if cambios:
                print("OK cola al dia" if a.aplicar else "SOLO REPORTE: --aplicar lo anota en la cola")
            return 0
        if a.enviar:
            filas, avisos = [], []
            for t in (C.por_enviar(con) if con else []):
                c = transporte.carpeta_de(t["archivo"])
                f = T.carpeta(c) / t["archivo"] if c else None
                if f is not None and f.is_file():
                    filas.append((t, c, f))
                else:
                    avisos.append(f"trabajo {t['id']} ({t['archivo']}): su zip no esta en el espejo")
            en_cola = {t["archivo"] for t, _, _ in filas} | ({t["archivo"] for t in C.listar(con)} if con else set())
            for c in K.TIPO_DE_CARPETA:
                for f in sorted(T.carpeta(c).glob("*.zip")):
                    if f.name not in en_cola:
                        avisos.append(f"{f.name}: esta en el espejo pero no en la cola (python xd.py trabajos --reconciliar --aplicar)")
            print(f"kernel {kernel} (PRIVADO, GPU T4) | operador {u} | credencial {cred}")
            for v in avisos:
                print(f"AVISO: {v}")
            if not filas:
                print("Nada que enviar")
                return 0
            for e in pend:                             # el kernel es uno solo: nada nuevo mientras corre otro envio
                if e["estado"] in ("lanzado", "corriendo"):
                    est, _ = K.estado_kernel(kv(e))
                    if est in K.ACTIVOS:
                        raise SystemExit(f"El envio {e['nombre']} sigue {est}: el kernel es uno solo; el siguiente sale "
                                         "cuando termine (worker --estado)")
            nivel = min(_trozo(f.name) for _, _, f in filas)
            ahora = [x for x in filas if _trozo(x[2].name) == nivel]
            despues = [x for x in filas if _trozo(x[2].name) != nivel]
            print(f"Este envio (trozo {nivel}): {len(ahora)} trabajo(s)")
            for t, c, f in ahora:
                g = f" | grupo {t['grupo']}" if t.get("grupo") else ""
                print(f"  {t['id']:>4} {t['tipo']:<16}{f.name}  ({f.stat().st_size / 1e6:.1f} MB){g}")
            if despues:
                print(f"Esperan al siguiente envio: {len(despues)} trabajo(s) de trozos posteriores")
            if not a.aplicar:
                print(f"SOLO REPORTE: --aplicar sube este envio (dataset privado {u}/{K.SLUG_ENVIOS}, borra sus versiones "
                      "viejas) y lanza el kernel")
                return 0
            nombre = f"envio_{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}"   # unico (daemon)
            carpeta, kcarp = _kaggle_dir() / "envio", _kaggle_dir() / "kernel"
            try:
                K.armar_envio([(c, f) for _, c, f in ahora], carpeta, u, nombre, u)
                ds = f"{u}/{K.SLUG_ENVIOS}"
                t0 = time.time()
                rc, out = K.subir_envio(carpeta, bool(K.estado_dataset(ds)), nombre)
                print(K.ocultar(out)[-1500:])
                if rc:
                    raise SystemExit(f"no se pudo subir el envio (rc {rc}); nada cambio en la cola")
                subida = round(time.time() - t0, 1)
                listo = K.esperar_listo(ds)
                if listo is None:
                    raise SystemExit(f"{ds} no quedo listo; reintenta worker --enviar mas tarde (nada cambio en la cola)")
                K.armar_kernel(RAIZ / "motor" / "lanzador.py", kcarp, u)
                rc, out = K.push_kernel(kcarp, limite_s=a.limite * 60)
                print(K.ocultar(out)[-1500:])
                if rc:
                    raise SystemExit(f"no se pudo lanzar el kernel (rc {rc}); nada cambio en la cola")
            finally:
                shutil.rmtree(carpeta, ignore_errors=True)
                shutil.rmtree(kcarp, ignore_errors=True)
            version = K.version_push(out)
            C.crear_envio(con, nombre, "kaggle", u, [t["id"] for t, _, _ in ahora], version=version)
            C.marcar_envio(con, nombre, "lanzado", f"trozo {nivel}; subida {subida} s; dataset listo tras {listo} s")
            print(f"OK {nombre} (kernel v{version or '?'}, trozo {nivel}): subida {subida} s | dataset listo tras {listo} s")
            if despues:
                print(f"Quedan {len(despues)} trabajo(s) del trozo siguiente: cuando este envio termine, "
                      "worker --enviar --aplicar (o el daemon) lo lanza")
            print("Siguiente:  python xd.py worker --estado  y, cuando termine,  python xd.py worker --traer --aplicar")
            return 0
        # --traer: cada envio pendiente terminado, por su version del kernel
        if not pend:
            raise SystemExit("No hay envios a Kaggle pendientes de traer")
        listos, archivos_tot = [], 0
        for e in pend:
            est, msg = K.estado_kernel(kv(e))
            if est not in ("complete", "error"):       # no es un error: aun no hay nada que traer de ese envio
                try:
                    hace = f" hace {(time.time() - time.mktime(time.strptime(e['creado'], '%Y-%m-%dT%H:%M:%S'))) / 60:.0f} min"
                except (TypeError, ValueError):
                    hace = ""
                print(f"El envio {e['nombre']} sigue en Kaggle ({est or 'sin estado'}; lanzado{hace}): nada que traer "
                      "todavia; vuelve a pulsar 'Traer de Kaggle' en unos minutos.")
                continue
            sal = _kaggle_dir() / "salida" / e["nombre"]
            rc, out = K.bajar_salida(kv(e), sal)
            if rc:
                print(f"AVISO: no se pudo bajar la salida de {e['nombre']} (rc {rc}): {out[-300:]}")
                continue
            for f in sorted(sal.glob("*.log")):
                print(f"--- {e['nombre']}: {f.name} (final)\n" + K.ocultar(f.read_text(encoding="utf-8", errors="replace"))[-1500:])
            if est == "error":
                print(f"El kernel de {e['nombre']} termino en ERROR: {msg}")
            archivos = K.archivos_salida(sal)
            archivos_tot += len(archivos)
            print(f"envio {e['nombre']} (kernel v{e.get('version') or '?'}): {len(archivos)} archivo(s) de salida")
            for rel, _ in archivos:
                print(f"  {'copiando' if a.aplicar else 'COPIARIA'} {rel} -> espejo")
            listos.append((e, est, msg, sal))
        if not listos:
            return 0
        if not a.aplicar:
            print("SOLO REPORTE: --aplicar los copia al espejo, reconcilia la cola y marca en error lo que no volvio")
            return 0
        for e, est, msg, sal in listos:
            K.integrar(sal, T.raiz)
            if e["estado"] in ("lanzado", "corriendo"):
                C.marcar_envio(con, e["nombre"], ENVIO_DE_KERNEL[est], msg or None)
        c = _carpetas_transporte()
        r = C.reconciliar(C.listar(con), _archivos_transporte(c))
        hechas, av = C.aplicar(con, r["acciones"], leer_error=_leer_error(c))
        for v in av:
            print(f"AVISO: {v}")
        perdidos = 0
        for e, est, msg, sal in listos:
            perdidos += len(C.sin_salida(con, e["nombre"], f"el envio {e['nombre']} termino ({est}) sin resultado para este trabajo"))
            C.marcar_envio(con, e["nombre"], "traido")
        print(f"OK {len(listos)} envio(s), {archivos_tot} archivo(s) en el espejo | {hechas} cambio(s) en la cola"
              + (f" | {perdidos} sin resultado -> error (Reintentar)" if perdidos else ""))
        print("Siguiente: lote-importar --fijar-version y cache-importar --aplicar (o asistente-importar / registrar)")
        if C.por_enviar(con):
            print("Hay trabajos esperando su envio (trozo siguiente):  python xd.py worker --enviar --aplicar")
        return 0
    finally:
        if con:
            con.close()


def cmd_ver(a):
    args = [sys.executable, str(RAIZ / "ver_cajas.py"), str(a.proyecto), "--camara", str(a.camara),
            "--conf", str(a.conf)] + (["--modelo", a.modelo] if a.modelo else []) + \
           (["--imgsz", str(a.imgsz)] if a.imgsz else []) + ["--backend", a.backend]
    return subprocess.call(args, cwd=RAIZ)

# ----------------------------------------------------------------- asistente (etapa C)
def _buzon():
    return _transporte().requerir("asistente", crear=True)


def _texto_o_archivo(v):
    """Ruta a un .txt existente -> su contenido; si no, el texto tal cual."""
    return Path(v).read_text(encoding="utf-8") if v and Path(v).is_file() else (v or "")


def _ultimo_resultado(buzon, slug):
    fs = buzon.resultados(_buzon(), slug)
    return (fs[-1], json.loads(fs[-1].read_text(encoding="utf-8"))) if fs else (None, None)


def cmd_asistente(a):
    sys.path.insert(0, str(RAIZ / "motor"))
    import buzon
    ruta = RAIZ / "motor" / "proyectos" / a.slug / "spec.json"
    texto, voc = _texto_o_archivo(a.texto), [v.strip() for v in a.vocabulario.split(",") if v.strip()]
    previa = None if a.nuevo or not ruta.exists() else json.loads(ruta.read_text(encoding="utf-8"))
    if a.continuar:
        f, res = _ultimo_resultado(buzon, a.slug)
        if not res:
            raise SystemExit(f"No hay resultados del asistente para '{a.slug}' en {_buzon()}")
        texto = (res["transcripcion"] + "\n" + texto).strip()
        previa = (res.get("resultado") or {}).get("spec") or previa
        voc = voc or res.get("vocabulario") or []
        print(f"Continuando {f.name} (texto anterior + spec anterior como previa)")
        if a.audio:
            print("  aviso: tambien se transcribira el audio nuevo y se agrega al texto")
    try:
        zp, e = buzon.armar(RAIZ / "motor", _buzon(), a.slug, texto=texto, audio=a.audio or None,
                            vocabulario=voc, respuestas=_texto_o_archivo(a.respuestas), previa=previa,
                            modelo_llm=a.modelo or buzon.MODELO_LLM)
    except ValueError as x:
        raise SystemExit(str(x))
    print(f"Trabajo -> {zp}")
    _en_cola(zp.name, _q_crear, "asistente", zp.name, "enviado", slug=a.slug)
    if a.continuar:
        _en_cola(zp.name, _q_reemplazar, a.slug, zp.name)
    print(f"  audio: {e['audio'] or 'no'} | texto: {len(e['texto'])} car. | vocabulario: {e['vocabulario'] or 'no'}"
          f" | respuestas: {'si' if e['respuestas'] else 'no'} | previa: {'si' if previa else 'no'} | {e['modelo_llm']}")
    print(_siguiente_externo(_transporte(), f"python xd.py asistente-importar {a.slug}"))
    return 0


def cmd_asistente_importar(a):
    sys.path.insert(0, str(RAIZ / "motor"))
    import asistente, buzon
    from plan import plan_captura
    f, res = _ultimo_resultado(buzon, a.slug)
    errs = buzon.errores(_buzon(), a.slug)
    if errs and (not f or errs[-1].name[-25:-10] > f.name[-30:-15]):
        print(f"El ultimo trabajo fallo en Colab ({errs[-1].name}):")
        print(errs[-1].read_text(encoding="utf-8")[-1500:])
        return 1
    if not res:
        pend = buzon.pendientes(_buzon())
        print(f"No hay resultados en {_buzon()}" + (f"; pendientes en Colab: {[z.name for z in pend]}" if pend else ""))
        return 0
    slug = a.slug or res["slug"]
    pend = [z.name for z in buzon.pendientes(_buzon()) if z.name.startswith(f"asist_{slug}_") and z.name[-19:-4] > res["trabajo"][-15:]]
    if pend: print(f"AVISO: hay trabajos mas nuevos SIN PROCESAR en Colab {pend}; este reporte es del anterior")
    print(f"Trabajo {res['trabajo']} | stt {res.get('stt') or 'no'} | llm {res.get('llm_seg')} s")
    print("TRANSCRIPCION:\n  " + (res.get("transcripcion") or "").replace("\n", "\n  "))
    print(asistente.resumen(res["resultado"]))
    if a.comparar and (res["resultado"] or {}).get("spec"):
        import comparar
        print(f"\nCOMPARACION contra {a.comparar}:\n" + "\n".join(comparar.comparar(res["resultado"]["spec"], _spec(a.comparar))["lineas"]))
    s, err, av = buzon.preparar_spec(res, slug)
    if err:
        print("NO SE PUEDE APLICAR:")
        for x in err:
            print("  -", x)
        print(f"Corrige con:  python xd.py asistente {slug} --continuar --respuestas \"...\"")
        return 1
    print(f"\nPlan de captura (sin --total):")
    for fl in plan_captura(s):
        print(f"  {fl['carpeta']:<16}{fl['tipo']:<10}{fl['fotos']:>5}  {fl['motivo']}")
    ruta = RAIZ / "motor" / "proyectos" / slug / "spec.json"
    if not a.aplicar:
        print(f"SOLO REPORTE: usa --aplicar para escribir {ruta}")
        if res["resultado"].get("preguntas"):
            print(f"Para responder las preguntas:  python xd.py asistente {slug} --continuar --respuestas \"...\"")
        return 0
    if ruta.exists():
        if not a.forzar:
            raise SystemExit(f"Ya existe {ruta}; usa --forzar (se guarda un respaldo .bak)")
        bak = ruta.with_name(f"spec_{time.strftime('%Y%m%d-%H%M%S')}.json.bak")
        shutil.copy2(ruta, bak)
        print(f"Respaldo -> {bak}")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(s, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")
    print(f"OK spec -> {ruta}")
    _en_cola(res["trabajo"], _q_importado, "asistente", res["trabajo"] + ".zip", f.name, slug=slug)
    
    # P.5.4: crear proyecto automaticamente si la spec no tiene errores
    # --si o sin stdin interactivo: crear automaticamente sin preguntar
    if getattr(a, "si", None) is True:
        crear = True
        print(f"Creando proyecto automaticamente: python xd.py crear-proyecto {slug}")
    elif getattr(a, "si", None) is False:
        # Explicitamente rechazado en tests
        crear = False
        print(f"Siguiente:  python xd.py crear-proyecto {slug}")
    else:
        # Modo interactivo: preguntar
        print("\nSpec importada sin errores. Crear proyecto en Label Studio? [S/n] ", end="", flush=True)
        try:
            respuesta = input().strip().lower()
            crear = respuesta in ("", "s", "si")
        except EOFError:
            # stdin redirigido, no crear
            crear = False
            print()
    
    if crear:
        import subprocess
        rc = subprocess.call(["python", str(RAIZ / "xd.py"), "crear-proyecto", slug])
        if rc == 0:
            print(f"OK: proyecto '{slug}' creado en Label Studio")
        else:
            print(f"AVISO: crear-proyecto salio con rc={rc}")
    elif getattr(a, "si", None) is not False:
        print("Creacion omitida. Para crear el proyecto manualmente:")
        print(f"  python xd.py crear-proyecto {slug}")
    return 0

# ----------------------------------------------------------------- P.1 cola de trabajos
def _cola_mod():
    sys.path.insert(0, str(RAIZ / "motor"))
    import cola_trabajos
    return cola_trabajos


def _cola(crear=True):
    """Conexion a la cola; None si aun no existe y crear=False (los reportes no crean la base)."""
    if not crear and not TRABAJOS_DB.exists():
        return None
    return _cola_mod().abrir(TRABAJOS_DB)


def _en_cola(que, op, *args, **kw):
    """Registra en la cola; si falla, avisa y sigue: la cola nunca rompe un paso que ya funciono."""
    try:
        con = _cola()
        try:
            return op(_cola_mod(), con, *args, **kw)
        finally:
            con.close()
    except Exception as e:
        print(f"AVISO cola: no pude registrar {que} ({type(e).__name__}: {e}); "
              "corre  python xd.py trabajos --reconciliar")
        return None


def _q_aviso(t, texto):
    print(f"AVISO cola: trabajo {t['id']} ({t['archivo']}) esta en {t['estado']}: {texto}")


def _q_crear(C, con, tipo, archivo, estado, proyecto=None, slug=None, grupo=None):
    t, nuevo = C.crear(con, tipo, archivo, proyecto=proyecto, slug=slug, estado=estado, grupo=grupo)
    if not nuevo and estado == "enviado" and t["estado"] == "pendiente":
        t = C.mover(con, t["id"], "enviado")
    return t


def _q_enviado(C, con, tipo, archivo):
    t = C.buscar(con, tipo, archivo)
    if t and t["estado"] == "pendiente":
        return C.mover(con, t["id"], "enviado")
    return t


def _q_listo(C, con, tipo, archivo, resultado, proyecto=None, slug=None, detalle="registrado al importar"):
    """Lleva el trabajo hasta listo (creandolo si no estaba). -> trabajo, o None si ya termino."""
    t = C.buscar(con, tipo, archivo)
    if t is None:
        t, _ = C.crear(con, tipo, archivo, proyecto=proyecto, slug=slug, estado="enviado", detalle=detalle)
    if t["estado"] == "pendiente":
        t = C.mover(con, t["id"], "enviado", detalle=detalle)
    if t["estado"] in ("enviado", "en_proceso"):
        t = C.mover(con, t["id"], "listo", resultado=resultado, detalle=detalle)
    if t["estado"] != "listo":
        if t["estado"] != "importado":
            _q_aviso(t, "no se marca como importado")
        return None
    return t


def _q_importado(C, con, tipo, archivo, resultado, proyecto=None, slug=None):
    t = _q_listo(C, con, tipo, archivo, resultado, proyecto, slug)
    return C.mover(con, t["id"], "importado", desde="listo", resultado=resultado) if t else None


def _q_fallo(C, con, tipo, archivo, resultado, detalle, proyecto=None):
    t = _q_listo(C, con, tipo, archivo, resultado, proyecto)
    return C.fallo(con, t["id"], detalle) if t else None


def _q_archivar(C, con, tipo, archivo, detalle="archivado a mano"):
    t = C.buscar(con, tipo, archivo)
    if t is None:
        t, _ = C.crear(con, tipo, archivo, estado="enviado", detalle="registrado al archivar")
    if "archivado" in C.TRANSICIONES[t["estado"]]:
        return C.mover(con, t["id"], "archivado", detalle=detalle)
    if t["estado"] != "archivado":
        _q_aviso(t, "no se puede archivar")
    return t


def _q_reemplazar(C, con, slug, nuevo):
    """asistente --continuar: los resultados listos anteriores del slug quedan archivados (reemplazados)."""
    for t in C.listar(con, tipo="asistente", slug=slug, estado="listo"):
        if t["archivo"] != nuevo:
            C.mover(con, t["id"], "archivado", desde="listo", detalle=f"reemplazado por {nuevo}")
            print(f"Cola: {t['archivo']} -> archivado (reemplazado)")


def _q_registrar(C, con, proyecto, run):
    """registrar --run: el dataset cuyo stem origino el run (el cuaderno nombra el run stem[_formato])."""
    ts = [t for t in C.listar(con, tipo="entrenamiento", proyecto=proyecto)
          if run == t["archivo"][:-4] or run.startswith(t["archivo"][:-4] + "_")]
    if not ts:
        print(f"AVISO cola: no encuentro en la cola el dataset del run {run}; corre  python xd.py trabajos --reconciliar")
        return None
    t = max(ts, key=lambda x: len(x["archivo"]))
    return _q_importado(C, con, "entrenamiento", t["archivo"], run, proyecto=proyecto)


def _carpetas_transporte():
    """Carpetas locales del transporte por tipo (None si no estan). No crea nada."""
    return _transporte().carpetas()


def _archivos_transporte(c):
    """Nombres (y mtimes) que necesita cola_trabajos.reconciliar(). Solo lectura."""
    def mt(d):                                     # None = carpeta no disponible; {} = vacia o aun no creada
        return ({f.name: f.stat().st_mtime for f in d.iterdir() if f.is_file()} if d.is_dir() else {}) if d else None
    def nombres(d):
        return {f.name for f in d.iterdir()} if d and d.is_dir() else set()
    reg = set()
    for f in (RAIZ / "motor" / "modelos").glob("p*/registro.json"):
        try:
            ms = json.loads(f.read_text(encoding="utf-8")).get("modelos") or {}
        except (OSError, ValueError):
            continue
        reg |= {str(m.get("origen")) for m in (ms.values() if isinstance(ms, dict) else ms) if isinstance(m, dict)}
    runs = c["runs"]
    return {"asistente": mt(c["asistente"]), "asistente_archivo": nombres(c["asistente"] and c["asistente"] / "_archivo"),
            "lotes": mt(c["lotes"]), "lotes_archivo": nombres(c["lotes"] and c["lotes"] / "_archivo"),
            "lotes_local": nombres(LOTES_LOCAL), "datasets": mt(c["datasets"]),
            "datasets_archivo": nombres(c["datasets"] and c["datasets"] / "_archivo"),
            "runs": ({r.name for r in runs.iterdir() if (r / "weights" / "metricas.json").exists()} if runs.is_dir() else set())
                    if runs else None,
            "registrados": reg,
            "specs": {f.parent.name: f.stat().st_mtime for f in (RAIZ / "motor" / "proyectos").glob("*/spec.json")}}


def _linea_trabajo(t):
    quien = f"p{t['proyecto']}" if t["proyecto"] is not None else (t["slug"] or "-")
    err = f"  ERROR: {t['error'][-60:]!r}" if t["error"] else ""
    return (f"  {t['id']:>4} {t['tipo']:<16}{quien:<16} {t['estado']:<11}{t['actualizado']:<20}"
            f"{t['intentos']:>3}  {t['archivo']}{err}")


def cmd_trabajos(a):
    C = _cola_mod()
    if a.reconciliar and a.reintentar:
        raise SystemExit("Usa --reconciliar o --reintentar, no los dos")
    if a.reintentar:
        return _reintentar(C, a)
    if a.reconciliar:
        return _reconciliar(C, a)
    con = _cola(crear=False)
    if con is None:
        print(f"Aun no hay cola en {TRABAJOS_DB} (se crea con el primer trabajo o con --reconciliar --aplicar)")
        return 0
    with con:
        ts = C.listar(con, tipo=a.tipo or None, estado=a.estado or None, activos=not (a.todos or a.estado))
    con.close()
    print(f"Cola {TRABAJOS_DB} | {len(ts)} trabajo(s)" + ("" if a.todos or a.estado else " sin terminar (--todos: todos)"))
    if ts:
        print(f"  {'id':>4} {'tipo':<16}{'quien':<16} {'estado':<11}{'actualizado':<20}{'int':>3}  archivo")
        for t in ts:
            print(_linea_trabajo(t))
    return 0


def _reintentar(C, a):
    """error -> pendiente; el _error.txt va a _archivo/ (no se borra) para que Colab lo procese otra vez."""
    con = _cola(crear=False)
    try:
        t = C.obtener(con, a.reintentar) if con else None
        if t is None:
            raise SystemExit(f"No existe el trabajo {a.reintentar} en {TRABAJOS_DB}")
        if t["estado"] != "error":
            raise SystemExit(f"El trabajo {t['id']} esta en {t['estado']}; solo se reintenta desde error")
        T, c = _transporte(), C.CARPETA.get(t["tipo"], "")
        carpeta = T.carpeta(c) if c else None
        if carpeta is None:
            raise SystemExit(f"No encuentro la carpeta de {t['tipo']} en el transporte ({T.nombre})")
        stem, sello = t["archivo"][:-4], time.strftime("%Y%m%d-%H%M%S")
        # el _error.txt y el .estado.json (P.2.4: el worker se salta lo que ya tiene estado) van a _archivo/
        mover = [(f, carpeta / "_archivo" / f"{f.name[:-len(suf)]}_{sello}{suf}")
                 for f, suf in ((carpeta / f"{stem}_error.txt", ".txt"), (carpeta / f"{stem}.estado.json", ".json"))
                 if f.is_file()]
        hay_zip = (carpeta / t["archivo"]).is_file()
        for f, dest in mover:
            print(f"{'moviendo' if a.aplicar else 'MOVERIA'} {f} -> {dest}")
        print(f"trabajo {t['id']}: error -> pendiente" + (f" -> enviado (el zip sigue en el transporte: {T.nombre})" if hay_zip else
              f"; AVISO: {t['archivo']} ya no esta en {carpeta}, se queda pendiente"))
        if not a.aplicar:
            print("SOLO REPORTE: usa --aplicar para reintentar")
            return 0
        for f, dest in mover:
            T.archivar(c, f.name, dest.name)
        t = C.mover(con, t["id"], "pendiente", desde="error", detalle="reintento")
        if hay_zip:
            t = C.mover(con, t["id"], "enviado", desde="pendiente", detalle="reintento")
        print(f"OK trabajo {t['id']} en {t['estado']} (intento {t['intentos']})")
        return 0
    finally:
        if con:
            con.close()


def _reconciliar(C, a):
    c = _carpetas_transporte()
    con = _cola(crear=a.aplicar)
    try:
        ts = C.listar(con) if con else []
        r = C.reconciliar(ts, _archivos_transporte(c), horas=a.horas)
        for v in r["avisos"]:
            print(f"AVISO: {v}")
        if not r["acciones"]:
            print("Cola y transporte coinciden: nada que reconciliar")
            return 0
        for x in r["acciones"]:
            if x["op"] == "mover":
                print(f"  mover   {x['id']:>4} {x['archivo']}: {x['de']} -> {x['a']}" +
                      (f" ({x['resultado'] or x['error_de']})" if x["resultado"] or x["error_de"] else ""))
            else:
                quien = f"p{x['proyecto']}" if x["proyecto"] is not None else x["slug"]
                print(f"  adoptar {x['tipo']:<14}{quien:<16} {x['archivo']} -> {x['estado']}")
        if not a.aplicar:
            print(f"SOLO REPORTE: {len(r['acciones'])} accion(es); usa --aplicar para escribirlas en {TRABAJOS_DB}")
            return 0
        def leer_error(nombre):
            for d in (c["asistente"], c["lotes"], c["datasets"]):
                if d and (d / nombre).is_file():
                    return (d / nombre).read_text(encoding="utf-8", errors="replace")
            return nombre
        hechas, av = C.aplicar(con, r["acciones"], leer_error=leer_error)
        for v in av:
            print(f"AVISO: {v}")
        print(f"OK {hechas}/{len(r['acciones'])} accion(es) en {TRABAJOS_DB}")
        return 0 if hechas == len(r["acciones"]) else 1
    finally:
        if con:
            con.close()


def cmd_daemon(a):
    """Demonio que consulta Kaggle cada N min y si hay trabajos externos OK, los importa."""
    import subprocess
    import time
    
    # Importar módulos necesarios
    sys.path.insert(0, str(RAIZ / "motor"))
    import cola_trabajos as C
    import kaggle_xd as K
    
    intervalo = a.intervalo * 60  # convertir a segundos
    ciclo = 0
    
    usuario = K.usuario(ENV)
    kernel = f"{usuario}/{ENV.get('KAGGLE_KERNEL', 'xd-worker')}"
    
    print(f"daemon: iniciando polling cada {a.intervalo} min (Ctrl+C para detener)")
    print(f"daemon: kernel {kernel}")
    
    try:
        while True:
            ciclo += 1
            ahora = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{ahora}] Ciclo {ciclo}: consultando Kaggle...")
            
            # 1. Consultar estado del kernel
            est, msg = K.estado_kernel(kernel)
            print(f"  kernel: {est or 'sin ejecuciones'}" + (f" | {msg}" if msg else ""))
            
            # 2. Si hay un envío terminado OK, actualizar estado y reconciliar
            con = C.abrir(TRABAJOS_DB)
            try:
                ult = C.ultimo_envio(con, "kaggle")
                if ult and ult["estado"] in ("lanzado", "corriendo"):
                    nuevo = ENVIO_DE_KERNEL.get(est or "")
                    if nuevo and nuevo != ult["estado"]:
                        print(f"  envío {ult['nombre']}: {ult['estado']} -> {nuevo}")
                        C.marcar_envio(con, ult["nombre"], nuevo, msg or None)
                
                # 3. Importar trabajos listos (estado="listo") sin resultado aún
                listos = [
                    (x["id"], x["archivo"])
                    for x in C.listar(con, estado="listo")
                    if x.get("resultado") is None
                ]
                
                if listos:
                    print(f"daemon: {len(listos)} trabajo(s) listo(s) pendiente(s) de importar")
                    for tid, arch in listos:
                        # Solo precodificaciones: importar_pred.py
                        if "lote_" in arch or "pre_" in arch:
                            print(f"  → importando predicciones {tid} ({arch})...")
                            rc_i = subprocess.call(["python", str(RAIZ / "motor" / "importar_pred.py"), arch], cwd=RAIZ)
                            if rc_i != 0:
                                print(f"AVISO: importar_pred.py {arch} rc={rc_i}")
                        else:
                            print(f"  → {tid} ({arch}): tipo no auto-importable, requiere intervención manual")
                else:
                    print("daemon: no hay trabajos listos pendientes de importar")
            finally:
                con.close()
            
            if a.solo_una_vez:
                print("daemon: --solo-una-vez activo, saliendo")
                break
            
            print(f"daemon: durmiendo {a.intervalo} min hasta el próximo ciclo...")
            time.sleep(intervalo)
    
    except KeyboardInterrupt:
        print("\ndaemon: detenido por usuario")
        return 0
    
    return 0


def main():
    ap = argparse.ArgumentParser(prog="xd.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estado", help="salud de Label Studio y del motor").set_defaults(f=cmd_estado)

    p = sub.add_parser("precalentar", help="carga SAM 3 interactivo y espera a que este listo")
    p.add_argument("--proyecto", type=int, default=2)
    p.add_argument("--limite", type=int, default=600, help="segundos maximos de espera")
    p.set_defaults(f=cmd_precalentar)

    p = sub.add_parser("reiniciar-motor", help="docker compose restart motor (+ --precalentar)")
    p.add_argument("--precalentar", action="store_true", help="cargar SAM 3 al terminar")
    p.add_argument("--proyecto", type=int, default=2)
    p.add_argument("--limite", type=int, default=600, help="segundos maximos de espera")
    p.add_argument("--forzar", action="store_true", help="reiniciar aunque haya trabajo en la cola")
    p.set_defaults(f=cmd_reiniciar_motor)
    p = sub.add_parser("archivar", help="mueve un zip en espera de Drive a _archivo (Colab ya no lo procesa)")
    p.add_argument("archivo", help="nombre del zip: asist_*.zip, lote_p*.zip o dataset_p*.zip")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_archivar)
    p = sub.add_parser("lote-exportar", help="exporta tareas pendientes a un zip y lo copia a Drive")
    p.add_argument("proyecto", type=int)
    p.add_argument("--limite", type=int, default=0)
    p.add_argument("--tareas", default="", help="ids separados por coma")
    p.add_argument("--modo", choices=["auto", "sam3", "hijo"], default="auto")
    p.add_argument("--todas", action="store_true", help="incluir tareas que ya tienen la version")
    p.set_defaults(f=cmd_lote_exportar)

    p = sub.add_parser("preetiquetar", help="muestra estratificada de tareas sin anotar -> lote para Colab")
    p.add_argument("proyecto", type=int)
    p.add_argument("--muestra", type=int, required=True, help="tamano de la muestra (20-50)")
    p.add_argument("--semilla", type=int, default=0)
    p.add_argument("--minimo", type=int, default=1, help="minimo por carpeta")
    p.add_argument("--prioridad", default="", help="'ultimo' o archivo de motor/diagnosticos")
    p.add_argument("--modo", choices=["auto", "sam3", "hijo"], default="auto")
    p.add_argument("--todas", action="store_true", help="incluir tareas que ya tienen la version")
    p.add_argument("--trozo", type=int, default=16, help="P.4: si hay mas tareas, genera 2 zips (t01 + t02); 0 = sin trozos")
    p.add_argument("--sin-precodificar", dest="precodificar", action="store_false",
                   help="P.4.R1: no precodificar las mismas tareas (por defecto si: el clic liviano necesita la cache)")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_preetiquetar)
    p = sub.add_parser("lote-importar", help="sube a Label Studio los *_pred.json nuevos de Drive")
    p.add_argument("--sufijo", default="")
    p.add_argument("--fijar-version", action="store_true", help="model_version del proyecto = la del lote")
    p.set_defaults(f=cmd_lote_importar)

    p = sub.add_parser("precodificar", help="P.3: fotos del proyecto sin cache de SAM 3 -> trabajo para el worker")
    p.add_argument("proyecto", type=int)
    p.add_argument("--todas", action="store_true", help="rehacer tambien las fotos que ya tienen cache")
    p.add_argument("--limite", type=int, default=0, help="maximo de fotos")
    p.add_argument("--trozo", type=int, default=16, help="P.4: si hay mas fotos, genera 2 zips (t01 + t02); 0 = sin trozos")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_precodificar)
    p = sub.add_parser("sam3-ligero", help="P.3.5: checkpoint del clic sin image encoder (~47 MB, carga en ~1 s)")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_sam3_ligero)
    p = sub.add_parser("cache-importar", help="P.3: lleva la cache de SAM 3 que trajo el worker al hub (motor/cache_sam3)")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_cache_importar)
    p = sub.add_parser("dataset", help="exporta las anotaciones validadas a un dataset YOLO (zip)")
    p.add_argument("proyecto", type=int)
    p.add_argument("--formato", choices=["det", "seg", "ambos"], default="det")
    p.add_argument("--val", type=float, default=0.2)
    p.add_argument("--drive", action="store_true", help="copiar el zip a la carpeta datasets de Drive")
    p.add_argument("--correcciones", default="", help="'ultimo' o archivo de motor/correcciones")
    for k, ayuda in (("modelo", "yolo11n.pt / yolo11n-seg.pt"), ("imgsz", "960"), ("epochs", "100"), ("patience", "30"),
                     ("batch", "16"), ("conf_conteo", "0.25: umbral del KPI de conteo"),
                     ("device", "auto: todas las GPU; Kaggle T4 x2 -> 0,1")):
        p.add_argument("--" + k.replace("_", "-"), default="", help=f"entrenamiento en el worker (defecto {ayuda})")
    p.set_defaults(f=cmd_dataset)

    p = sub.add_parser("test", help="corre todos los tests (host + contenedor); rc 0 solo si todos pasan")
    p.add_argument("--solo", choices=["host", "motor"])
    p.add_argument("-k", default="", help="solo tests cuyo nombre contiene este texto")
    p.add_argument("-v", "--verbose", action="store_true", help="salida completa de cada test")
    p.add_argument("--proyecto", type=int, help="test_reglas tambien con el perfil real de ese proyecto")
    p.set_defaults(f=cmd_test)

    p = sub.add_parser("cuadernos", help="compara notebooks/ con las copias de Colab en Drive; --traer o --llevar")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--traer", action="store_true", help="Drive -> repo (limpia salidas y metadatos)")
    g.add_argument("--llevar", action="store_true", help="repo -> Drive")
    p.add_argument("--forzar", action="store_true", help="con --llevar: pisa una copia de Drive distinta")
    p.add_argument("--aplicar", action="store_true")
    p.set_defaults(f=cmd_cuadernos)

    p = sub.add_parser("spec-nueva", help="spec desde la plantilla (camino sin asistente); reporte o --aplicar")
    p.add_argument("slug")
    p.add_argument("--titulo", default="")
    p.add_argument("--aplicar", action="store_true")
    p.set_defaults(f=cmd_spec_nueva)

    p = sub.add_parser("validar", help="valida motor/proyectos/<slug>/spec.json; rc 1 si hay errores")
    p.add_argument("slug")
    p.set_defaults(f=cmd_validar)

    p = sub.add_parser("crear-proyecto", help="crea carpetas + proyecto desde motor/proyectos/<slug>/spec.json")
    p.add_argument("slug")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_crear_proyecto)

    p = sub.add_parser("sincronizar", help="re-sincroniza los storages del proyecto (fotos nuevas)")
    p.add_argument("slug")
    p.set_defaults(f=cmd_sincronizar)

    p = sub.add_parser("borrar-proyecto", help="borra un proyecto creado con crear-proyecto (protegido)")
    p.add_argument("slug")
    p.add_argument("--aplicar", action="store_true")
    p.set_defaults(f=cmd_borrar_proyecto)

    p = sub.add_parser("plan", help="fotos recomendadas por carpeta vs las que ya tienes")
    p.add_argument("slug")
    p.add_argument("--total", type=int, default=0, help="presupuesto total de fotos (escala el plan)")
    p.add_argument("--variaciones", action="store_true", help="mostrar que variar en cada carpeta")
    p.set_defaults(f=cmd_plan)

    p = sub.add_parser("registrar", help="copia best.pt + metricas.json al registro de modelos del proyecto")
    p.add_argument("proyecto", type=int)
    p.add_argument("--run", default="", help="corrida en Drive/runs o 'ultimo'")
    p.add_argument("--pt", default="", help="ruta a un .pt (registro manual)")
    p.add_argument("--metricas", default="", help="metricas.json del .pt manual")
    p.add_argument("--otro-proyecto", action="store_true", help="modelo entrenado en otro proyecto con las mismas clases")
    p.add_argument("--nombre", default="")
    p.add_argument("--activar", action="store_true")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_registrar)

    p = sub.add_parser("modelos", help="modelos registrados del proyecto (KPI = conteo)")
    p.add_argument("proyecto", type=int)
    p.add_argument("--activar", default="", help="nombre del modelo a dejar activo")
    p.add_argument("--aplicar", action="store_true")
    p.set_defaults(f=cmd_modelos)
    p = sub.add_parser("aceptacion", help="tasa de aceptacion del pre-etiquetado en las tareas revisadas")
    p.add_argument("proyecto", type=int)
    p.add_argument("--versiones", default="", help="comparar varias (coma); defecto: model_version del proyecto")
    p.set_defaults(f=cmd_aceptacion)
    p = sub.add_parser("worker", help="P.2.7: envia los trabajos a Kaggle, consulta el kernel y trae la salida")
    p.add_argument("--enviar", action="store_true", help="sube los zips pendientes del espejo y lanza el kernel")
    p.add_argument("--estado", action="store_true", help="estado del kernel; con --aplicar lo anota en la cola")
    p.add_argument("--traer", action="store_true", help="baja la salida del kernel al espejo local")
    p.add_argument("--limite", type=int, default=0, help="minutos maximos del kernel (0 = el de Kaggle)")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_worker)
    p = sub.add_parser("kaggle-pesos", help="sube sam3.pt + SAM License como dataset privado de Kaggle (P.2.6)")
    p.add_argument("--pesos", default="", help="ruta de sam3.pt (defecto: la raiz del repo)")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta (lo corre la persona, no un agente)")
    p.set_defaults(f=cmd_kaggle_pesos)
    p = sub.add_parser("ver", help="prueba en vivo con webcam del modelo registrado (activo o --modelo)")
    p.add_argument("proyecto", type=int)
    p.add_argument("--modelo", default="")
    p.add_argument("--camara", type=int, default=0)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--imgsz", type=int, default=0)
    p.add_argument("--backend", choices=["auto", "pt", "openvino"], default="auto",
                   help="auto: OpenVINO en CPU si esta instalado (L.9), si no PyTorch")
    p.set_defaults(f=cmd_ver)
    p = sub.add_parser("asistente", help="describe el caso por audio o texto -> trabajo para Colab (spec con LLM)")
    p.add_argument("slug")
    p.add_argument("--audio", default="", help="grabacion (.m4a, .mp3, .wav...)")
    p.add_argument("--texto", default="", help="archivo .txt o texto entre comillas")
    p.add_argument("--vocabulario", default="", help="nombres propios bien escritos, separados por coma")
    p.add_argument("--respuestas", default="", help="respuestas a las preguntas del asistente (archivo o texto)")
    p.add_argument("--continuar", action="store_true", help="parte del ultimo resultado (texto y spec)")
    p.add_argument("--nuevo", action="store_true", help="no mandar la spec actual del proyecto como previa")
    p.add_argument("--modelo", default="", help="modelo de Ollama (defecto qwen2.5:14b)")
    p.set_defaults(f=cmd_asistente)
    p = sub.add_parser("asistente-importar", help="muestra el ultimo resultado del asistente; --aplicar escribe la spec")
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.add_argument("--forzar", action="store_true", help="reemplazar una spec existente (con respaldo)")
    p.add_argument("--comparar", default="", help="slug de una spec de referencia (solo lectura)")
    p.add_argument("--si", action="store_true", help="P.5.4: confirma automaticamente la creacion del proyecto")
    p.set_defaults(f=cmd_asistente_importar)
    p = sub.add_parser("trabajos", help="cola de trabajos del hub (SQLite); --reconciliar compara con Drive")
    p.add_argument("--tipo", default="", choices=["", "asistente", "preetiquetado", "entrenamiento", "precodificacion"])
    p.add_argument("--estado", default="", help="filtra por estado (incluye terminados)")
    p.add_argument("--todos", action="store_true", help="incluye importados y archivados")
    p.add_argument("--reconciliar", action="store_true", help="avanza estados segun los archivos de Drive y adopta huerfanos")
    p.add_argument("--reintentar", type=int, default=0, metavar="ID", help="vuelve a enviar un trabajo en error")
    p.add_argument("--horas", type=float, default=24, help="aviso si un trabajo lleva mas de estas horas enviado")
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_trabajos)

    p = sub.add_parser("daemon", help="P.5: encadenamiento automatico (polling de Kaggle, traer e importar)")
    p.add_argument("--intervalo", type=int, default=5, help="minutos entre chequeos (defecto 5)")
    p.add_argument("--solo-una-vez", action="store_true", help="chequea una vez y sale (testing)")
    p.set_defaults(f=cmd_daemon)

    a = ap.parse_args()
    sys.exit(a.f(a))


if __name__ == "__main__":
    main()



