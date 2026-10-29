"""D.5: registro de modelos por proyecto. PURO (solo biblioteca estandar, sin disco).
registro = {"proyecto": N, "activo": nombre|None, "modelos": [{nombre, ruta_pt, origen, registrado, resumen}]}
El KPI es el CONTEO exacto por imagen en val, no el mAP."""
import copy


def vacio(proyecto):
    return {"esquema": 1, "proyecto": proyecto, "activo": None, "modelos": []}


def normalizar(met):
    """metricas.json (formato v1 manual o del notebook D.4) -> resumen comun."""
    if "conteo" in met:                                   # notebook D.4
        c, pc = met["conteo"], met.get("por_clase") or {}
        ex, im = c.get("exactas"), c.get("imagenes")
        r = {"dataset": met.get("dataset"), "formato": met.get("formato"), "base": met.get("modelo_base"),
             "imgsz": (met.get("params") or {}).get("imgsz"), "entrenado": met.get("creado"),
             "map50": met.get("map50"), "map50_95": met.get("map50_95"),
             "error_abs": {k: v.get("error_abs") for k, v in pc.items() if "error_abs" in v}}
    elif "conteo_val" in met:                             # v1 escrito a mano
        c, mv = met["conteo_val"], met.get("metricas_val") or {}
        ex, im = c.get("exacto"), c.get("imagenes")
        r = {"dataset": met.get("dataset"), "formato": met.get("tarea"), "base": met.get("arquitectura"),
             "imgsz": met.get("imgsz"), "entrenado": met.get("entrenado"),
             "map50": mv.get("mAP50"), "map50_95": mv.get("mAP50_95"), "error_abs": c.get("error_abs") or {}}
    else:
        raise ValueError("metricas.json sin 'conteo' ni 'conteo_val': no se puede medir el KPI")
    if ex is None or not im:
        raise ValueError("metricas.json sin conteo exacto o sin imagenes de val")
    if isinstance(r["dataset"], str) and r["dataset"].endswith(".zip"):
        r["dataset"] = r["dataset"][:-4]
    r.update(conteo_exactas=ex, conteo_imagenes=im, conteo_tasa=round(ex / im, 3))
    return r


def _buscar(reg, nombre):
    m = next((m for m in reg["modelos"] if m["nombre"] == nombre), None)
    if m is None:
        raise KeyError(f"No existe el modelo {nombre!r} en el registro del proyecto {reg['proyecto']}")
    return m


def agregar(reg, nombre, met, ruta_pt, origen, ahora):
    if any(m["nombre"] == nombre for m in reg["modelos"]):
        raise ValueError(f"Ya existe el modelo {nombre!r}; usa otro --nombre")
    out = copy.deepcopy(reg)
    out["modelos"].append({"nombre": nombre, "ruta_pt": ruta_pt, "origen": origen, "registrado": ahora,
                           "resumen": normalizar(met)})
    return out


def activar(reg, nombre):
    _buscar(reg, nombre)
    out = copy.deepcopy(reg)
    out["activo"] = nombre
    return out


def mejor(reg):
    """Nombre del mejor por tasa de conteo; empate -> mAP50; empate -> mas reciente."""
    if not reg["modelos"]:
        return None
    k = lambda m: (m["resumen"]["conteo_tasa"], m["resumen"].get("map50") or 0, m.get("registrado") or "")
    return max(reg["modelos"], key=k)["nombre"]


def tabla(reg):
    best = mejor(reg)
    filas = [f"{'':2}{'modelo':<26}{'conteo':>10}{'tasa':>7}{'mAP50':>7}  {'dataset':<32}registrado"]
    for m in reg["modelos"]:
        r = m["resumen"]
        marca = ("*" if m["nombre"] == reg["activo"] else " ") + ("+" if m["nombre"] == best else " ")
        filas.append(f"{marca}{m['nombre']:<26}{str(r['conteo_exactas']) + '/' + str(r['conteo_imagenes']):>10}"
                     f"{r['conteo_tasa']:>7.0%}{(r.get('map50') or 0):>7.3f}  {str(r.get('dataset')):<32}"
                     f"{m.get('registrado')}")
    filas.append("  * activo   + mejor por conteo")
    return filas
