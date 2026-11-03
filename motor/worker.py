"""P.2.3: worker unico (contrato en docs/worker_contrato.md). VIAJA en codigo/ de cada zip; lo llaman el kernel de
Kaggle y el cuaderno de Colab (lanzadores delgados). Despacha por tipo a trabajo.py (asistente), lote.py
(pre-etiquetado) y entrenar.py (entrenamiento). Siempre deja <stem>.estado.json; si falla, tambien <stem>_error.txt.
Sin dependencias pesadas al importar: corre en el host (tests) sin GPU."""
import gc, json, platform, time, traceback
from pathlib import Path

ESQUEMA = 1
TIPOS = ("asistente", "preetiquetado", "entrenamiento", "precodificacion")
PREFIJOS = (("asist_", "asistente"), ("lote_p", "preetiquetado"), ("dataset_p", "entrenamiento"))
# un solo modelo pesado a la vez: el lanzador procesa por grupos en este orden y libera memoria entre grupos
ORDEN = ("preetiquetado-sam3", "preetiquetado-hijo", "precodificacion", "entrenamiento", "asistente")


def _ahora():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")      # con zona: Colab y Kaggle corren en UTC


def escribir(ruta, texto):
    """Escritura atomica: nunca un resultado a medias."""
    ruta = Path(ruta)
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(ruta)


def encabezado(tipo, trabajo, proyecto=None, slug=None, parametros=None, creado=None):
    """trabajo.json comun que el hub agrega a cada zip."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo {tipo!r}: debe ser uno de {TIPOS}")
    return {"esquema": ESQUEMA, "tipo": tipo, "trabajo": trabajo, "proyecto": proyecto, "slug": slug,
            "creado": creado or _ahora(), "parametros": dict(parametros or {})}


def tipo_por_nombre(stem):
    return next((t for p, t in PREFIJOS if stem.startswith(p)), None)


def leer_trabajo(d, stem):
    """trabajo.json, o (zips anteriores a P.2.3) el tipo deducido del nombre."""
    f = Path(d) / "trabajo.json"
    if f.is_file():
        t = json.loads(f.read_text(encoding="utf-8"))
        if int(t.get("esquema") or 0) > ESQUEMA:
            raise ValueError(f"{stem}: trabajo.json con esquema {t['esquema']} mas nuevo que el worker ({ESQUEMA}); "
                             "actualiza el lanzador")
        if t.get("tipo") not in TIPOS:
            raise ValueError(f"{stem}: tipo desconocido {t.get('tipo')!r}")
        t.setdefault("parametros", {})
        return t
    tipo = tipo_por_nombre(stem)
    if tipo is None:
        raise ValueError(f"{stem}: sin trabajo.json y con un nombre que no indica el tipo")
    return encabezado(tipo, stem)


def grupo(d, stem):
    """Grupo de modelo del trabajo (para ordenar y liberar memoria entre grupos)."""
    try:
        tipo = leer_trabajo(d, stem)["tipo"]
    except (ValueError, OSError):
        return ORDEN[-1]                                  # que falle al procesar, con su estado.json
    if tipo == "preetiquetado":
        try:
            modo = json.loads((Path(d) / "manifiesto.json").read_text(encoding="utf-8")).get("modo", "sam3")
        except (OSError, ValueError):
            modo = "sam3"
        return f"preetiquetado-{modo if modo in ('sam3', 'hijo') else 'sam3'}"
    return tipo


def ordenar(trabajos):
    """trabajos: [(d, stem)] -> misma lista ordenada por grupo de modelo y nombre."""
    pos = {g: i for i, g in enumerate(ORDEN)}
    return sorted(trabajos, key=lambda x: (pos.get(grupo(*x), len(ORDEN)), x[1]))


def liberar(cache):
    """Entre grupos: suelta los modelos cacheados y la memoria de la GPU."""
    if cache is not None:
        cache.clear()
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def entorno(proveedor="local"):
    """Versiones y GPU (van en cada estado.json). Si torch no esta, se dice."""
    e = {"proveedor": proveedor, "python": platform.python_version(), "torch": None, "cuda": None, "gpu": None,
         "ultralytics": None}
    try:
        import torch
        e["torch"], e["cuda"] = torch.__version__, torch.version.cuda
        if torch.cuda.is_available():
            e["gpu"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    try:
        import ultralytics
        e["ultralytics"] = ultralytics.__version__
    except Exception:
        pass
    return e


# ------------------------------------------------------------------ ejecutores por tipo
def _asistente(d, salida, stem, t, cache, op):
    import trabajo
    r = trabajo.procesar(d, f"{stem}.zip", **({"llm": op["llm"]} if op.get("llm") else {}))
    nombre = f"{stem}_resultado.json"
    escribir(Path(salida) / nombre, json.dumps(r, ensure_ascii=True, indent=1))
    try:
        print(trabajo.asistente.resumen(r["resultado"]))
    except Exception:
        pass
    return nombre


def _preetiquetado(d, salida, stem, t, cache, op):
    import lote
    kw = {k: op[k] for k in ("sam3_pt", "device") if k in op}
    out = lote.procesar(d, cache if cache is not None else {}, f"{stem}.zip", **kw)
    nombre = f"{stem}_pred.json"
    escribir(Path(salida) / nombre, json.dumps(out))
    return nombre


def _entrenamiento(d, salida, stem, t, cache, op):
    import entrenar
    return entrenar.entrenar(d, salida, t.get("parametros") or {}, proyecto=t.get("proyecto"), dataset=f"{stem}.zip",
                             YOLO=op.get("YOLO"), runs=op.get("runs"))


def _precodificacion(d, salida, stem, t, cache, op):
    raise NotImplementedError("la precodificacion de SAM 3 llega en P.3")


EJECUTORES = {"asistente": _asistente, "preetiquetado": _preetiquetado, "entrenamiento": _entrenamiento,
              "precodificacion": _precodificacion}


def procesar(d, salida, cache=None, stem=None, ent=None, ejecutores=None, **op):
    """Procesa el trabajo extraido en d y escribe en salida. -> estado (dict).
    Idempotente: si ya hay <stem>.estado.json lo devuelve sin repetir.
    op: runs (carpeta de corridas; defecto salida/runs), sam3_pt, device e inyecciones de prueba (llm, YOLO)."""
    d, salida = Path(d), Path(salida)
    stem = stem or d.name
    salida.mkdir(parents=True, exist_ok=True)
    f_estado = salida / f"{stem}.estado.json"
    if f_estado.is_file():
        e = json.loads(f_estado.read_text(encoding="utf-8"))
        e["saltado"] = True
        return e
    inicio, t0 = _ahora(), time.time()
    tipo, resultado, error = None, None, None
    print(f"===== {stem}", flush=True)
    try:
        t = leer_trabajo(d, stem)
        tipo = t["tipo"]
        resultado = (ejecutores or EJECUTORES)[tipo](d, salida, stem, t, cache, op)
    except Exception:
        tb = traceback.format_exc()
        escribir(salida / f"{stem}_error.txt", tb)
        error = tb.strip().splitlines()[-1][-500:] if tb.strip() else "error"
        print(tb, flush=True)
    estado = {"esquema": ESQUEMA, "trabajo": stem, "tipo": tipo or tipo_por_nombre(stem), "ok": error is None,
              "inicio": inicio, "fin": _ahora(), "seg": round(time.time() - t0, 1), "resultado": resultado,
              "error": error, "entorno": ent if ent is not None else entorno()}
    escribir(f_estado, json.dumps(estado, ensure_ascii=True, indent=1))
    print(f"{'OK' if estado['ok'] else 'ERROR'} {stem} en {estado['seg']} s -> {resultado or error}", flush=True)
    return estado
