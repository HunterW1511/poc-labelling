"""Etapa E.2: tablero por proyecto, SOLO LECTURA (biblioteca estandar).
Junta lo que ya saben xd.py, plan.py, buzon.py y registro.py; no escribe nada.
Prueba: python tablero.py   (imprime el JSON)"""
import json, re, sys
from pathlib import Path

import xd

sys.path.insert(0, str(xd.RAIZ / "motor"))
import buzon                                   # noqa: E402
import registro                                # noqa: E402
from plan import plan_captura                  # noqa: E402

PROYECTOS = xd.RAIZ / "motor" / "proyectos"
DATASETS = xd.RAIZ / "motor" / "datasets"
MODELOS = xd.RAIZ / "motor" / "modelos"
PROTEGIDOS = {int(x) for x in xd.ENV.get("UI_PROTEGIDOS", "1,2").split(",") if x.strip().isdigit()}
LOTE = re.compile(r"^lote_p(\d+)_.+(_pred\.json|\.zip)$")
ASIST = re.compile(r"^asist_(.+)_(\d{8}-\d{6})")


def _json(f):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ls(ruta):
    try:
        return xd.http("GET", xd.LS + ruta, token=True, timeout=15)
    except (OSError, SystemExit, ValueError):
        return None


def servicios():
    ls = xd.intentar(xd.http, "GET", xd.LS + "/health", timeout=5)
    mh = xd.intentar(xd.http, "GET", xd.MOTOR + "/health", timeout=5)
    return {"label_studio": bool(ls), "motor": bool(mh), "estado": xd._estado() if mh else None, "ls_url": xd.LS}


def _drive():
    d = xd.ENV.get("LOTES_DRIVE")
    return Path(d) if d and Path(d).is_dir() else None


def _lotes(drive):
    """{N: {"en_colab": [...], "sin_importar": [...]}} por nombre lote_p<N>_... (misma regla que lote-importar)."""
    out = {}
    if not drive:
        return out
    for f in drive.iterdir():
        m = LOTE.match(f.name)
        if not m:
            continue
        d = out.setdefault(int(m.group(1)), {"en_colab": [], "sin_importar": []})
        if m.group(2) == ".zip":
            if not (drive / (f.name[:-4] + "_pred.json")).exists():
                d["en_colab"].append(f.name)
        elif not (xd.LOTES_LOCAL / f.name).exists():
            d["sin_importar"].append(f.name)
    return out


def _slug_asist(nombre):
    m = ASIST.match(nombre)
    return m.group(1) if m else None


def _fecha(nombre):
    m = re.search(r"\d{8}-\d{6}", nombre)
    return m.group(0) if m else ""


def _asistente(bz, slug, ruta_spec):
    if not bz:
        return None
    res, err = buzon.resultados(bz, slug), buzon.errores(bz, slug)
    pend = [z for z in buzon.pendientes(bz) if _slug_asist(z.name) == slug]
    cands = [(_fecha(f.name), tipo, f) for tipo, fs in (("resultado", res), ("error", err), ("pendiente", pend))
             for f in fs]
    if not cands:
        return None
    fecha, tipo, f = max(cands, key=lambda x: (x[0], x[1]))
    aplicada = tipo == "resultado" and ruta_spec.exists() and ruta_spec.stat().st_mtime >= f.stat().st_mtime
    return {"ultimo": tipo, "trabajo": f.name, "fecha": fecha, "aplicada": aplicada,
            "resultados": len(res), "pendientes": len(pend)}


def _fotos(spec, slug):
    try:
        base = xd._raiz(spec, slug)
        return [{"carpeta": f["carpeta"], "tipo": f["tipo"], "recom": f["fotos"],
                 "tienes": xd._contar(base / f["carpeta"])} for f in plan_captura(spec)], None
    except (SystemExit, ValueError) as e:
        return None, str(e)


def _modelos(n):
    reg = _json(MODELOS / f"p{n}" / "registro.json")
    if not reg:
        return {"n": 0, "activo": None, "tabla": []}, set()
    ms = reg.get("modelos") or {}
    vals = list(ms.values()) if isinstance(ms, dict) else list(ms)
    try:
        tabla = registro.tabla(reg)
    except Exception as e:                        # solo lectura: mostrar el error en vez de caer
        tabla = [f"(registro.tabla fallo: {e})"]
    origenes = {str(m.get("origen")) for m in vals if isinstance(m, dict)}
    return {"n": len(vals), "activo": reg.get("activo"), "tabla": tabla}, origenes


def _runs(runs_dir, n, origenes):
    if not runs_dir or not runs_dir.is_dir():
        return []
    return sorted(r.name for r in runs_dir.glob(f"dataset_p{n}_*")
                  if (r / "weights" / "metricas.json").exists() and f"runs/{r.name}" not in origenes)


def _datos(t, n, det, lotes, runs_dir):
    t["ls"] = {k: (det or {}).get(k) for k in ("task_number", "num_tasks_with_annotations",
                                                "total_predictions_number", "model_version")} if det else None
    t["lotes"] = lotes.get(n, {"en_colab": [], "sin_importar": []})
    t["modelos"], origenes = _modelos(n)
    t["runs_sin_registrar"] = _runs(runs_dir, n, origenes)
    t["datasets"] = sorted(f.name for f in DATASETS.glob(f"dataset_p{n}_*.zip"))[-3:] if DATASETS.is_dir() else []


def _sig(donde, texto, cmd=""):
    return {"donde": donde, "texto": texto, "cmd": cmd}


def siguiente(t):
    s, n = t.get("slug"), t.get("n")
    if t.get("protegido"):
        return _sig("", "Proyecto protegido: solo lectura")
    a = t.get("asistente") or {}
    if a.get("ultimo") == "pendiente":
        return _sig("colab", "Esperando a Colab: abre asistente.ipynb y corre la celda 2")
    if a.get("ultimo") == "error":
        return _sig("cli", "El asistente fallo en Colab: revisa el error", f"python xd.py asistente-importar {s}")
    if a.get("ultimo") == "resultado" and not a.get("aplicada"):
        return _sig("cli", "Revisa el resultado del asistente y aplica la spec",
                    f"python xd.py asistente-importar {s}")
    if s and not t.get("spec"):
        return _sig("cli", "Describe el caso por audio o texto", f"python xd.py asistente {s} --audio ARCHIVO")
    if not n:
        return _sig("cli", "Proyecto borrado; si lo quieres de nuevo, crealo" if t.get("borrado") else "Crea el proyecto en Label Studio", f"python xd.py crear-proyecto {s}")
    ls, fotos, lo = t.get("ls") or {}, t.get("fotos") or [], t.get("lotes") or {}
    tareas, anot = ls.get("task_number") or 0, ls.get("num_tasks_with_annotations") or 0
    tienes = sum(f["tienes"] for f in fotos)
    if lo.get("en_colab"):
        return _sig("colab", "Esperando a Colab: notebook de pre-etiquetado, celda 2")
    if lo.get("sin_importar"):
        return _sig("cli", "Importa las predicciones de Colab", "python xd.py lote-importar --fijar-version")
    if s and fotos and any(f["tienes"] == 0 for f in fotos):
        return _sig("host", "Captura fotos: hay carpetas vacias", f"python capturar.py {s}")
    if s and tienes > tareas:
        return _sig("cli", f"Hay {tienes - tareas} fotos sin tarea: sincroniza", f"python xd.py sincronizar {s}")
    if t.get("runs_sin_registrar"):
        return _sig("cli", "Registra el modelo entrenado en Colab",
                    f"python xd.py registrar {n} --run ultimo --activar")
    if not (t.get("modelos") or {}).get("activo"):
        if anot == 0 and not ls.get("total_predictions_number"):
            return _sig("cli", "Pre-etiqueta una muestra con SAM 3", f"python xd.py preetiquetar {n} --muestra 30")
        if anot == 0:
            return _sig("label_studio", "Revisa la muestra en Label Studio y da Submit")
        if t.get("datasets"):
            return _sig("colab", "Entrena en Colab con el ultimo dataset (o exporta otro si revisaste mas)",
                        f"python xd.py dataset {n} --drive")
        return _sig("cli", "Exporta el dataset para entrenar", f"python xd.py dataset {n} --drive")
    if tareas > anot:
        return _sig("cli", f"{tareas - anot} tareas sin anotar: pre-etiqueta con el hijo",
                    f"python xd.py preetiquetar {n} --muestra 30")
    return _sig("cli", "Valida el modelo: aceptacion y prueba en vivo", f"python xd.py aceptacion {n}")


def proyecto_de(slug):
    """N del proyecto vinculado al slug (proyecto.json o titulo), o None. Lo usa ui.py para proteger 1 y 2."""
    reg = _json(PROYECTOS / slug / "proyecto.json")
    if reg and reg.get("proyecto"):
        return reg["proyecto"]
    titulo = ((_json(PROYECTOS / slug / "spec.json") or {}).get("proyecto") or {}).get("titulo")
    lista = _ls("/api/projects?page_size=200")
    lista = (lista.get("results") if isinstance(lista, dict) else lista) or []
    return next((p["id"] for p in lista if titulo and p.get("title") == titulo), None)

def _buzon_dir(drive):
    bz = Path(xd.ENV.get("ASISTENTE_DRIVE") or (drive.parent / "asistente" if drive else ""))
    return bz if str(bz) not in ("", ".") and bz.is_dir() else None


def asistente_detalle(slug):
    """Ultimo trabajo del asistente para el slug, listo para mostrar (SOLO LECTURA).
    La spec pasa por buzon.preparar_spec: el mismo camino que asistente-importar."""
    bz = _buzon_dir(_drive())
    ruta = PROYECTOS / slug / "spec.json"
    out = {"slug": slug, "spec_existe": ruta.exists(), "estado": _asistente(bz, slug, ruta) if bz else None}
    if not bz:
        out["error"] = "No encuentro el buzon del asistente en Drive (ASISTENTE_DRIVE o LOTES_DRIVE)"
        return out
    st = out["estado"] or {}
    if st.get("ultimo") == "error":
        out["error_colab"] = (bz / st["trabajo"]).read_text(encoding="utf-8", errors="replace")[-1500:]
    fs = buzon.resultados(bz, slug)
    if not fs:
        return out
    res = _json(fs[-1]) or {}
    r = res.get("resultado") or {}
    out["resultado"] = {k: res.get(k) for k in ("trabajo", "stt", "llm_seg", "transcripcion", "vocabulario")}
    out["resultado"].update({k: r.get(k) for k in ("ok", "preguntas", "supuestos", "avisos", "problemas", "conteos")})
    s, errores, avisos = buzon.preparar_spec(res, slug)
    out["errores"], out["avisos_spec"] = list(errores), list(avisos)
    if s:
        out["raiz"] = (s.get("imagenes") or {}).get("raiz")
        out["clases"] = [{"nombre": c.get("nombre"), "prompts": c.get("prompts"), "max": c.get("max_por_imagen"),
                          "importancia": c.get("importancia")} for c in s.get("clases") or [] if isinstance(c, dict)]
        out["carpetas"] = [{"nombre": k.get("nombre"), "tipo": k.get("tipo"), "clases": k.get("clases")}
                           for k in s.get("carpetas") or [] if isinstance(k, dict)]
        if not errores:
            try:
                out["plan"] = [{"carpeta": f["carpeta"], "tipo": f["tipo"], "fotos": f["fotos"], "motivo": f["motivo"]}
                               for f in plan_captura(s)]
            except ValueError as e:
                out["errores"].append(str(e))
    return out

EJECUTOR = xd.ENV.get("EJECUTOR", "colab")
# Pasos externos: al desplegar (RunPod/AWS) solo se agrega otra columna aqui; la UI no cambia
PASOS = {
    "asistente": {"colab": "Colab: abre asistente.ipynb y corre la celda 2 (la 1 si la sesion es nueva)"},
    "preetiquetado": {"colab": "Colab: abre el notebook de pre-etiquetado y corre la celda 2 (la 1 si la sesion es nueva)"},
    "entrenamiento": {"colab": "Colab: notebook de entrenamiento; en la celda 1 pon DS = '{archivo}' y PROYECTO = {n}; corre las celdas 1, 2 y 3"},
}
DS_RE = re.compile(r"^dataset_p(\d+)_.+\.zip$")


def _instr(tipo, **kw):
    t = (PASOS.get(tipo) or {}).get(EJECUTOR)
    return t.format(**kw) if t else f"{EJECUTOR}: sin instrucciones para {tipo}"


def _item(tipo, archivo, estado, texto, n=None, slug=None, accion=None):
    return {"tipo": tipo, "archivo": archivo, "estado": estado, "texto": texto, "n": n, "slug": slug,
            "accion": accion, "protegido": n in PROTEGIDOS,
            "archivable": estado == "en_espera" and tipo in ("asistente", "preetiquetado")}


def externos():
    """Trabajos que esperan o vuelven del ejecutor externo (SOLO LECTURA)."""
    drive = _drive()
    out = {"ejecutor": EJECUTOR, "items": [], "avisos": []}
    if not drive:
        out["avisos"].append("No encuentro LOTES_DRIVE (Google Drive para escritorio)")
        return out
    it = out["items"]
    bz = _buzon_dir(drive)
    if bz:
        for z in buzon.pendientes(bz):
            it.append(_item("asistente", z.name, "en_espera", _instr("asistente"), slug=_slug_asist(z.name)))
        for e in buzon.errores(bz):
            s = _slug_asist(e.name)
            res = buzon.resultados(bz, s) if s else []
            if not res or _fecha(res[-1].name) < _fecha(e.name):
                it.append(_item("asistente", e.name, "error", "Fallo en Colab: revisalo en Asistente; para reintentar "
                                "borra el _error.txt y vuelve a correr la celda 2", slug=s))
    for n, l in sorted(_lotes(drive).items()):
        for f in sorted(l["en_colab"]):
            it.append(_item("preetiquetado", f, "en_espera", _instr("preetiquetado"), n=n))
        for f in sorted(l["sin_importar"]):
            it.append(_item("preetiquetado", f, "listo", "Predicciones listas: importalas a Label Studio", n=n,
                            accion={"accion": "lote-importar", "opciones": {"--fijar-version": True}}))
    ds_dir = Path(xd.ENV.get("DATASETS_DRIVE") or drive.parent / "datasets")
    runs_dir = Path(xd.ENV.get("RUNS_DRIVE") or drive.parent / "runs")
    runs = [r for r in runs_dir.iterdir() if r.is_dir()] if runs_dir.is_dir() else []
    ultimos = {}
    if ds_dir.is_dir():
        for f in sorted(ds_dir.glob("dataset_p*.zip")):
            m = DS_RE.match(f.name)
            if m:
                ultimos[int(m.group(1))] = f
    for n, f in sorted(ultimos.items()):
        if not any(r.name.startswith(f.stem) for r in runs):
            it.append(_item("entrenamiento", f.name, "en_espera", _instr("entrenamiento", archivo=f.name, n=n), n=n))
    for n in sorted({int(m.group(1)) for r in runs for m in [re.match(r"^dataset_p(\d+)_", r.name)] if m}):
        _, origenes = _modelos(n)
        for r in _runs(runs_dir, n, origenes):
            it.append(_item("entrenamiento", r, "listo", "Corrida terminada con metricas.json: registrala", n=n,
                            accion={"accion": "registrar", "n": n, "opciones": {"--run": r, "--activar": True}}))
    for tipo in ("asistente", "preetiquetado"):
        k = sum(1 for x in it if x["tipo"] == tipo and x["estado"] == "en_espera")
        if k > 1:
            out["avisos"].append(f"Hay {k} trabajos de {tipo} en espera: la lanzadora los procesa TODOS; archiva los que no quieras")
    return out

def proyectos():
    avisos = []
    lista = _ls("/api/projects?page_size=200")
    if lista is None:
        avisos.append("Label Studio no responde: sin tareas ni anotadas")
    lista = (lista.get("results") if isinstance(lista, dict) else lista) or []
    ls = {p["id"]: p for p in lista if isinstance(p, dict) and "id" in p}
    drive = _drive()
    if not drive:
        avisos.append("No encuentro LOTES_DRIVE (Google Drive para escritorio): sin lotes, runs ni asistente")
    bz = Path(xd.ENV.get("ASISTENTE_DRIVE") or (drive.parent / "asistente" if drive else ""))
    bz = bz if str(bz) not in ("", ".") and bz.is_dir() else None
    runs_dir = Path(xd.ENV["RUNS_DRIVE"]) if xd.ENV.get("RUNS_DRIVE") else (drive.parent / "runs" if drive else None)
    lotes = _lotes(drive)
    slugs = {d.name for d in PROYECTOS.iterdir() if d.is_dir()} if PROYECTOS.is_dir() else set()
    if bz:
        slugs |= {x for x in (_slug_asist(f.name) for f in bz.glob("asist_*")) if x}
    por_titulo = {p.get("title"): pid for pid, p in ls.items()}
    tarjetas, usados, compartidas = [], set(), {}
    for slug in sorted(slugs):
        ruta = PROYECTOS / slug / "spec.json"
        spec, reg = _json(ruta), _json(PROYECTOS / slug / "proyecto.json")
        titulo = ((spec or {}).get("proyecto") or {}).get("titulo")
        n, vinculo = (reg or {}).get("proyecto"), "proyecto.json"
        if not n:
            n, vinculo = (por_titulo.get(titulo) if titulo else None), "titulo"
        if n and ls and n not in ls:
            avisos.append(f"{slug}: el proyecto {n} ya no existe en Label Studio")
            n = None
        t = {"slug": slug, "titulo": titulo or slug, "spec": bool(spec), "n": n, "vinculo": vinculo if n else None,
             "protegido": n in PROTEGIDOS, "asistente": _asistente(bz, slug, ruta)}
        if spec:
            t["fotos"], t["error_spec"] = _fotos(spec, slug)
            try:
                base = xd._raiz(spec, slug)
                for k in spec.get("carpetas") or []:
                    d = base / k["nombre"]
                    compartidas.setdefault(str(d.resolve()).lower(), [str(d), []])[1].append(slug)
            except (SystemExit, KeyError, TypeError):
                pass
        borr = sorted((PROYECTOS / slug).glob("proyecto_borrado_*.json"))
        t["borrado"] = borr[-1].name if borr and not n else None
        if n:
            usados.add(n)
            _datos(t, n, _ls(f"/api/projects/{n}"), lotes, runs_dir)
        t["siguiente"] = siguiente(t)
        tarjetas.append(t)
    for pid, p in sorted(ls.items()):
        if pid not in usados:
            t = {"slug": None, "titulo": p.get("title") or f"Proyecto {pid}", "spec": False, "n": pid,
                 "vinculo": None, "protegido": pid in PROTEGIDOS, "asistente": None}
            _datos(t, pid, _ls(f"/api/projects/{pid}"), lotes, runs_dir)
            t["siguiente"] = siguiente(t)
            tarjetas.append(t)
    for ruta_c, ss in sorted(compartidas.values()):
        if len(set(ss)) > 1:
            avisos.append(f"Carpeta compartida por {sorted(set(ss))}: {ruta_c} (sus fotos cuentan en todos)")
    tarjetas.sort(key=lambda t: (t["protegido"], t["n"] is None, str(t["titulo"])))
    return {"tarjetas": tarjetas, "avisos": avisos}


if __name__ == "__main__":
    print(json.dumps({"servicios": servicios(), **proyectos()}, indent=1, ensure_ascii=True, default=str))
