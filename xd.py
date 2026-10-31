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


def _drive():
    d = ENV.get("LOTES_DRIVE")
    if not d:
        raise SystemExit("Falta LOTES_DRIVE en .env (carpeta de lotes sincronizada con Drive)")
    d = Path(d)
    if not d.is_dir():
        raise SystemExit(f"No encuentro {d} (revisa Google Drive para escritorio)")
    return d


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
    if nombre != a.archivo or not re.fullmatch(r"(asist_.+|lote_p\d+_.+)\.zip", nombre):
        raise SystemExit(f"{a.archivo!r}: solo un nombre asist_*.zip o lote_p*.zip, sin carpeta")
    dirs = [_buzon(), _drive()]
    f = next((d / nombre for d in dirs if (d / nombre).is_file()), None)
    if not f:
        raise SystemExit(f"No encuentro {nombre} en {[str(d) for d in dirs]}")
    dest = f.parent / "_archivo" / nombre
    print(f"{'moviendo' if a.aplicar else 'MOVERIA'} {f} -> {dest}")
    if not a.aplicar:
        print("SOLO REPORTE: usa --aplicar para archivar")
        return 0
    dest.parent.mkdir(exist_ok=True)
    shutil.move(str(f), str(dest))
    print("OK archivado")
    return 0


def cmd_lote_exportar(a):
    drive = _drive()
    args = [a.proyecto] + (["--limite", a.limite] if a.limite else []) + \
           (["--tareas", a.tareas] if a.tareas else []) + (["--todas"] if a.todas else []) + list(getattr(a, "extra", [])) + (["--modo", a.modo] if getattr(a, "modo", "") else [])
    rc, out = en_motor("exportar_lote.py", *args)
    if rc:
        return rc                                   # incluye "no hay tareas pendientes"
    m = re.search(r"-> (\S+\.zip)", out)
    if not m:
        raise SystemExit("No encontre la ruta del zip en la salida de exportar_lote.py")
    zp = LOTES_LOCAL / PurePosixPath(m.group(1)).name
    shutil.copy2(zp, drive)
    print(f"Copiado a Drive: {drive / zp.name}")
    print("Siguiente: en Colab corre la celda 2; luego  python xd.py lote-importar")
    return 0


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
    extra = ["--muestra", a.muestra, "--semilla", a.semilla, "--minimo", a.minimo] + \
            _prioridad(a.prioridad, a.proyecto)
    if not a.aplicar:
        args = [a.proyecto, *extra, "--modo", a.modo, "--reporte"] + (["--todas"] if a.todas else [])
        rc = en_motor("exportar_lote.py", *args)[0]
        if rc == 0:
            print("Modo reporte. Para generar el lote y copiarlo a Drive agrega --aplicar")
        return rc
    a.limite, a.tareas, a.extra = 0, "", extra
    return cmd_lote_exportar(a)

def cmd_lote_importar(a):
    drive = _drive()
    LOTES_LOCAL.mkdir(parents=True, exist_ok=True)
    nuevos = sorted(f for f in drive.glob("*_pred.json") if not (LOTES_LOCAL / f.name).exists())
    if not nuevos:
        print(f"No hay predicciones nuevas en {drive}")
        return 0
    for f in nuevos:
        destino = LOTES_LOCAL / f.name
        shutil.copy2(f, destino)
        rc, _ = en_motor("importar_lote.py", f.name, *(["--sufijo", a.sufijo] if a.sufijo else []), *(["--fijar-version"] if a.fijar_version else []))
        if rc:
            destino.unlink(missing_ok=True)         # permite reintentar
            raise SystemExit(f"importar fallo: {f.name}")
    return 0


def cmd_dataset(a):
    rc, out = en_motor("exportar_yolo.py", a.proyecto, "--formato", a.formato, "--val", a.val, *(["--correcciones", a.correcciones] if a.correcciones else []))
    if rc:
        return rc
    m = re.search(r"OK -> (\S+\.zip)", out)
    if a.drive and m:
        d = Path(ENV.get("DATASETS_DRIVE") or _drive().parent / "datasets")
        d.mkdir(parents=True, exist_ok=True)
        zp = RAIZ / "motor" / "datasets" / PurePosixPath(m.group(1)).name
        shutil.copy2(zp, d)
        print(f"Copiado a Drive: {d / zp.name}")
    return 0


TESTS_HOST = ("plan", "muestra", "correccion", "registro", "aceptacion", "esquema_llm", "asistente", "buzon", "comparar",
              "plantilla", "notebooks")
TESTS_MOTOR = ("generar", "spec", "hijo", "reglas")      # necesitan el contenedor (torch, rutas /app)


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
    print(f"{a.slug}: {len(e)} errores, {len(av)} avisos")
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
        print(f"NO creo: la spec tiene {len(e)} errores  (python xd.py validar {a.slug})")
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
    print(f"{'carpeta':<14}{'tipo':<10}{'recom':>6}{'tienes':>8}{'faltan':>8}")
    tr = tt = tf = 0
    for f in filas:
        n = _contar(base / f["carpeta"])
        falta = max(0, f["fotos"] - n)
        tr, tt, tf = tr + f["fotos"], tt + n, tf + falta
        print(f"{f['carpeta']:<14}{f['tipo']:<10}{f['fotos']:>6}{n:>8}{falta:>8}")
    print(f"{'TOTAL':<24}{tr:>6}{tt:>8}{tf:>8}")
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
    runs = Path(ENV.get("RUNS_DRIVE") or _drive().parent / "runs")
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

def cmd_ver(a):
    args = [sys.executable, str(RAIZ / "ver_cajas.py"), str(a.proyecto), "--camara", str(a.camara),
            "--conf", str(a.conf)] + (["--modelo", a.modelo] if a.modelo else []) + \
           (["--imgsz", str(a.imgsz)] if a.imgsz else [])
    return subprocess.call(args, cwd=RAIZ)

# ----------------------------------------------------------------- asistente (etapa C)
def _buzon():
    d = Path(ENV.get("ASISTENTE_DRIVE") or _drive().parent / "asistente")
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    print(f"  audio: {e['audio'] or 'no'} | texto: {len(e['texto'])} car. | vocabulario: {e['vocabulario'] or 'no'}"
          f" | respuestas: {'si' if e['respuestas'] else 'no'} | previa: {'si' if previa else 'no'} | {e['modelo_llm']}")
    print("Siguiente: en Colab corre asistente.ipynb (celda 2); luego  python xd.py asistente-importar " + a.slug)
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
    print(f"Siguiente:  python xd.py crear-proyecto {slug}")
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
    p.add_argument("archivo", help="nombre del zip: asist_*.zip o lote_p*.zip")
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
    p.add_argument("--aplicar", action="store_true", help="sin esto solo reporta")
    p.set_defaults(f=cmd_preetiquetar)
    p = sub.add_parser("lote-importar", help="sube a Label Studio los *_pred.json nuevos de Drive")
    p.add_argument("--sufijo", default="")
    p.add_argument("--fijar-version", action="store_true", help="model_version del proyecto = la del lote")
    p.set_defaults(f=cmd_lote_importar)

    p = sub.add_parser("dataset", help="exporta las anotaciones validadas a un dataset YOLO (zip)")
    p.add_argument("proyecto", type=int)
    p.add_argument("--formato", choices=["det", "seg", "ambos"], default="det")
    p.add_argument("--val", type=float, default=0.2)
    p.add_argument("--drive", action="store_true", help="copiar el zip a la carpeta datasets de Drive")
    p.add_argument("--correcciones", default="", help="'ultimo' o archivo de motor/correcciones")
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
    p = sub.add_parser("ver", help="prueba en vivo con webcam del modelo registrado (activo o --modelo)")
    p.add_argument("proyecto", type=int)
    p.add_argument("--modelo", default="")
    p.add_argument("--camara", type=int, default=0)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--imgsz", type=int, default=0)
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
    p.set_defaults(f=cmd_asistente_importar)
    a = ap.parse_args()
    sys.exit(a.f(a))


if __name__ == "__main__":
    main()



