"""Etapa E.2: tablero por proyecto, SOLO LECTURA (biblioteca estandar).
Junta lo que ya saben xd.py, plan.py, buzon.py y registro.py; no escribe nada.
P.1.5: el estado de los trabajos sale de la cola (SQLite) mas la reconciliacion EN MEMORIA (vista()).
Prueba: python tablero.py   (imprime el JSON)"""
import json, re, sys
from pathlib import Path

import xd

sys.path.insert(0, str(xd.RAIZ / "motor"))
import buzon                                   # noqa: E402
import cola_trabajos as C                      # noqa: E402
import registro                                # noqa: E402
from plan import plan_captura                  # noqa: E402

PROYECTOS = xd.RAIZ / "motor" / "proyectos"
DATASETS = xd.RAIZ / "motor" / "datasets"
MODELOS = xd.RAIZ / "motor" / "modelos"
PROTEGIDOS = {int(x) for x in xd.ENV.get("UI_PROTEGIDOS", "1,2").split(",") if x.strip().isdigit()}
ESPERA = ("pendiente", "enviado", "en_proceso")


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
    """Carpeta de lotes del transporte (None si no esta): sin ella no hay lotes, runs ni asistente."""
    try:
        return xd._transporte().carpeta("lotes")
    except SystemExit:
        return None


def vista():
    """Trabajos de la cola + lo que la reconciliacion cambiaria, aplicado EN MEMORIA (no escribe ni crea la base).
    -> {"trabajos": [...], "sin_guardar": N, "avisos": [...]}"""
    avisos, ts = [], []
    try:
        con = xd._cola(crear=False)
        if con:
            try:
                ts = C.listar(con)
            finally:
                con.close()
    except Exception as e:                          # solo lectura: mostrar el error en vez de caer
        avisos.append(f"No pude leer la cola {xd.TRABAJOS_DB}: {e}")
    r = C.reconciliar(ts, xd._archivos_transporte(xd._carpetas_transporte()))
    return {"trabajos": C.proyectar(ts, r["acciones"]), "sin_guardar": len(r["acciones"]), "avisos": avisos + r["avisos"]}


def _envio(nombre=None):
    """Envio de la cola (el ultimo de Kaggle si no se da nombre). SOLO LECTURA; None si no hay cola."""
    try:
        con = xd._cola(crear=False)
        if not con:
            return None
        try:
            return C.envio(con, nombre) if nombre else C.ultimo_envio(con, "kaggle")
        finally:
            con.close()
    except Exception:
        return None


def _ultimo_envio():
    e = _envio()
    return {k: e[k] for k in ("nombre", "estado", "creado", "actualizado", "detalle")} if e else None


def lotes(v):
    """{N: {"en_colab": [zips en espera], "sin_importar": [_pred.json listos]}} (mismas claves que antes de P.1)."""
    out = {}
    for t in v["trabajos"]:
        if t["tipo"] != "preetiquetado" or t["proyecto"] is None:
            continue
        d = out.setdefault(t["proyecto"], {"en_colab": [], "sin_importar": []})
        if t["estado"] in ESPERA:
            d["en_colab"].append(t["archivo"])
        elif t["estado"] == "listo":
            d["sin_importar"].append(t["resultado"])
    for d in out.values():
        d["en_colab"].sort()
        d["sin_importar"].sort()
    return out


def _fecha(nombre):
    m = re.search(r"\d{8}-\d{6}", nombre)
    return m.group(0) if m else ""


def _asist_vivos(v, slug):
    """Trabajos del asistente del slug que no se archivaron, del mas viejo al mas nuevo (la fecha va en el nombre)."""
    return sorted((t for t in v["trabajos"] if t["tipo"] == "asistente" and t["slug"] == slug
                   and t["estado"] != "archivado"), key=lambda t: _fecha(t["archivo"]))


def _asistente(v, slug):
    """Estado del ultimo trabajo del asistente del slug (mismas claves que antes de P.1)."""
    todos = [t for t in v["trabajos"] if t["tipo"] == "asistente" and t["slug"] == slug]
    vivos = _asist_vivos(v, slug)
    if not vivos:
        return None
    t = vivos[-1]
    if t["estado"] in ("listo", "importado"):
        ultimo, archivo = "resultado", t["resultado"]
    elif t["estado"] == "error":
        ultimo, archivo = "error", t["archivo"][:-4] + "_error.txt"
    else:
        ultimo, archivo = "pendiente", t["archivo"]
    return {"ultimo": ultimo, "trabajo": archivo, "fecha": _fecha(t["archivo"]), "aplicada": t["estado"] == "importado",
            "id": t["id"], "resultados": sum(1 for x in todos if x["resultado"]),
            "pendientes": sum(1 for x in todos if x["estado"] in ESPERA)}


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


def _runs(v, n):
    """Runs terminados (con metricas.json) que aun no se registran: entrenamientos listos del proyecto."""
    return sorted(t["resultado"] for t in v["trabajos"]
                  if t["tipo"] == "entrenamiento" and t["proyecto"] == n and t["estado"] == "listo")


def _datos(t, n, det, lotes, v):
    t["ls"] = {k: (det or {}).get(k) for k in ("task_number", "num_tasks_with_annotations",
                                                "total_predictions_number", "model_version")} if det else None
    t["lotes"] = lotes.get(n, {"en_colab": [], "sin_importar": []})
    t["modelos"], _ = _modelos(n)
    t["runs_sin_registrar"] = _runs(v, n)
    t["datasets"] = sorted(f.name for f in DATASETS.glob(f"dataset_p{n}_*.zip"))[-3:] if DATASETS.is_dir() else []


def _sig(donde, texto, cmd=""):
    return {"donde": donde, "texto": texto, "cmd": cmd}


def siguiente(t):
    s, n = t.get("slug"), t.get("n")
    if t.get("protegido"):
        return _sig("", "Proyecto protegido: solo lectura")
    a = t.get("asistente") or {}
    if a.get("ultimo") == "pendiente":
        return _sig(ejecutor(), TEXTO_ESPERA.get(ejecutor(), TEXTO_ESPERA["colab"]))
    if a.get("ultimo") == "error":
        return _sig("cli", f"El asistente fallo en {ejecutor()}: revisa el error", f"python xd.py asistente-importar {s}")
    if a.get("ultimo") == "resultado" and not a.get("aplicada"):
        return _sig("cli", "Revisa el resultado del asistente y aplica la spec",
                    f"python xd.py asistente-importar {s}")
    if s and s.endswith("-ref"):                       # L.5: spec de referencia para comparar, no un proyecto
        return _sig("", "Spec de referencia: solo para comparar (asistente-importar --comparar); no se crea proyecto")
    if t.get("spec_errores"):
        ne = len(t["spec_errores"])
        return _sig("cli", f"Corrige la spec: {ne} error{'es' if ne != 1 else ''} (edita spec.json y vuelve a validar)",
                    f"python xd.py validar {s}")
    if s and not t.get("spec"):
        return _sig("cli", "Describe el caso con el asistente, o parte de la plantilla (sin asistente)",
                    f"python xd.py spec-nueva {s}")
    if not n:
        return _sig("cli", "Proyecto borrado; si lo quieres de nuevo, crealo" if t.get("borrado") else "Crea el proyecto en Label Studio", f"python xd.py crear-proyecto {s}")
    ls, fotos, lo = t.get("ls") or {}, t.get("fotos") or [], t.get("lotes") or {}
    tareas, anot = ls.get("task_number") or 0, ls.get("num_tasks_with_annotations") or 0
    tienes = sum(f["tienes"] for f in fotos)
    if lo.get("en_colab"):
        return _sig(ejecutor(), TEXTO_ESPERA.get(ejecutor(), TEXTO_ESPERA["colab"]))
    if lo.get("sin_importar"):
        return _sig("cli", f"Importa las predicciones de {ejecutor()}", "python xd.py lote-importar --fijar-version")
    if s and fotos and any(f["tienes"] == 0 for f in fotos):
        return _sig("host", "Captura fotos: hay carpetas vacias", f"python capturar.py {s}")
    if s and tienes > tareas:
        return _sig("cli", f"Hay {tienes - tareas} fotos sin tarea: sincroniza", f"python xd.py sincronizar {s}")
    if t.get("runs_sin_registrar"):
        return _sig("cli", f"Registra el modelo entrenado en {ejecutor()}",
                    f"python xd.py registrar {n} --run ultimo --activar")
    if not (t.get("modelos") or {}).get("activo"):
        if anot == 0 and not ls.get("total_predictions_number"):
            return _sig("cli", "Pre-etiqueta una muestra con SAM 3", f"python xd.py preetiquetar {n} --muestra 30")
        if anot == 0:
            return _sig("label_studio", "Revisa la muestra en Label Studio y da Submit")
        if t.get("datasets"):
            return _sig(ejecutor(), f"Entrena en {ejecutor()} con el ultimo dataset (o exporta otro si revisaste mas)",
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
    try:
        return xd._transporte().carpeta("asistente") if drive else None
    except SystemExit:
        return None


def asistente_detalle(slug):
    """Ultimo trabajo del asistente para el slug, listo para mostrar (SOLO LECTURA).
    La spec pasa por buzon.preparar_spec: el mismo camino que asistente-importar."""
    bz = _buzon_dir(_drive())
    ruta = PROYECTOS / slug / "spec.json"
    out = {"slug": slug, "spec_existe": ruta.exists(), "estado": _asistente(vista(), slug) if bz else None,
           "ejecutor": ejecutor()}
    if not bz:
        out["error"] = "No encuentro el buzon del asistente en el transporte (en Drive: ASISTENTE_DRIVE o LOTES_DRIVE)"
        return out
    st = out["estado"] or {}
    if st.get("ultimo") == "error" and (bz / st["trabajo"]).is_file():
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


def ejecutor():
    """'kaggle' si el transporte es Kaggle (P.2.7); si no, EJECUTOR del .env (colab)."""
    try:
        return "kaggle" if xd._transporte().nombre == "kaggle" else EJECUTOR
    except SystemExit:
        return EJECUTOR


TEXTO_ESPERA = {"colab": "Esperando a Colab: abre worker.ipynb y corre la celda 2",
          "kaggle": "En Kaggle: 'Enviar a Kaggle' y, cuando termine, 'Traer de Kaggle' (Pasos externos)"}
# Pasos externos: al desplegar (RunPod/AWS) solo se agrega otra columna aqui; la UI no cambia
PASOS = {
    "asistente": {"colab": "Colab: abre worker.ipynb y corre la celda 2 (la 1 si la sesion es nueva)"},
    "preetiquetado": {"colab": "Colab: abre worker.ipynb y corre la celda 2 (la 1 si la sesion es nueva)"},
    "entrenamiento": {"colab": "Colab: abre worker.ipynb y corre la celda 2 (la 1 si la sesion es nueva); entrena el dataset mas reciente del proyecto con los parametros de xd.py dataset"},
}
KAGGLE = {
    None: "Listo para Kaggle: pulsa 'Enviar a Kaggle' (worker --enviar)",
    "lanzado": "En Kaggle ({envio}): esperando GPU; 'Estado de Kaggle' para ver si ya corre",
    "corriendo": "En Kaggle ({envio}): corriendo; 'Traer de Kaggle' cuando termine",
    "terminado": "En Kaggle ({envio}): terminado; pulsa 'Traer de Kaggle'",
    "fallido": "En Kaggle ({envio}): el kernel fallo; pulsa 'Traer de Kaggle' para ver el log",
    "traido": "En Kaggle ({envio}): traido sin resultado; Reintentar",
}


def _instr(tipo, **kw):
    ej = ejecutor()
    t = (PASOS.get(tipo) or {}).get(ej)
    return t.format(**kw) if t else f"{ej}: sin instrucciones para {tipo}"


def _item(tipo, archivo, estado, texto, n=None, slug=None, accion=None, id=None):
    return {"tipo": tipo, "archivo": archivo, "estado": estado, "texto": texto, "n": n, "slug": slug, "id": id,
            "accion": accion, "protegido": n in PROTEGIDOS,
            "archivable": estado in ("en_espera", "error") and tipo in ("asistente", "preetiquetado", "entrenamiento")}


def _reintentar(t):
    return {"accion": "trabajos", "titulo": "Reintentar", "opciones": {"--reintentar": t["id"]}} if t["id"] is not None else None


def externos():
    """Trabajos que esperan o vuelven del ejecutor externo, segun la cola (SOLO LECTURA)."""
    v = vista()
    ej = ejecutor()
    out = {"ejecutor": ej, "items": [], "avisos": list(v["avisos"]), "sin_guardar": v["sin_guardar"],
           "envio": _ultimo_envio() if ej == "kaggle" else None}
    envios = {}
    if v["sin_guardar"]:
        out["avisos"].append(f"{v['sin_guardar']} cambio(s) de estado vistos en Drive sin guardar en la cola: Reconciliar")
    try:                                               # P.3.7: el aviso del clic (p. ej. foto sin precodificar)
        motivo = ((xd._estado() or {}).get("cache_disco") or {}).get("ultimo_motivo")
        if motivo:
            out["avisos"].append(f"Clic: {motivo}")
    except Exception:
        pass
    it = out["items"]
    ultimo_ds = {}                                   # el cuaderno de entrenamiento toma el ultimo dataset del proyecto
    for t in v["trabajos"]:
        if t["tipo"] == "entrenamiento" and t["estado"] in ESPERA:
            ultimo_ds[t["proyecto"]] = max(ultimo_ds.get(t["proyecto"], ""), t["archivo"])
    # P.4: agrupar trabajos por grupo para mostrar "trozo N de M"
    grupos_info = {}
    for t in v["trabajos"]:
        g = t.get("grupo")
        if g:
            grupos_info.setdefault(g, {"trozos": set(), "estados": {}})
            # numero de trozo segun el nombre del archivo
            if "_t01.zip" in t["archivo"] or "_t01_" in t["archivo"]:
                grupos_info[g]["trozos"].add(1)
            elif "_t02.zip" in t["archivo"] or "_t02_" in t["archivo"]:
                grupos_info[g]["trozos"].add(2)
            grupos_info[g]["estados"][t["archivo"]] = t["estado"]
    for t in sorted(v["trabajos"], key=lambda t: (t["tipo"], t["proyecto"] or 0, t["archivo"])):
        tipo, n, slug, est = t["tipo"], t["proyecto"], t["slug"], t["estado"]
        grupo = t.get("grupo")
        if est in ESPERA:
            if tipo == "entrenamiento" and t["archivo"] != ultimo_ds.get(n):
                out["avisos"].append(f"{t['archivo']}: dataset viejo en espera (Colab entrena el ultimo); archivalo")
                continue
            texto = _instr(tipo, archivo=t["archivo"], n=n)
            if ej == "kaggle":                         # P.2.7b: el estado del envio sale de la cola
                env = t.get("envio")
                if env and env not in envios:
                    envios[env] = (_envio(env) or {}).get("estado")
                texto = KAGGLE.get(envios.get(env) if env else None, KAGGLE[None]).format(envio=env)
            if est == "pendiente":
                texto = "El zip no llego a Drive: repite el comando que lo creo. " + texto
            if grupo and grupo in grupos_info:
                total = len(grupos_info[grupo]["trozos"])
                if "_t01.zip" in t["archivo"] or "_t01_" in t["archivo"]:
                    texto = f"Trozo 1 de {total}: " + texto
                elif "_t02.zip" in t["archivo"] or "_t02_" in t["archivo"]:
                    texto = f"Trozo 2 de {total}: " + texto
            it.append(_item(tipo, t["archivo"], "en_espera", texto, n=n, slug=slug, id=t["id"]))
        elif est == "listo" and tipo == "preetiquetado":
            desc = "Predicciones listas: importalas a Label Studio"
            if grupo and grupo in grupos_info:
                total = len(grupos_info[grupo]["trozos"])
                listos = sum(1 for e in grupos_info[grupo]["estados"].values() if e in ("listo", "importado"))
                desc = f"Trozo {listos}/{total} listo: importa a Label Studio"
            it.append(_item(tipo, t["resultado"], "listo", desc, n=n,
                            id=t["id"], accion={"accion": "lote-importar", "opciones": {"--fijar-version": True}}))
        elif est == "listo" and tipo == "entrenamiento":
            it.append(_item(tipo, t["resultado"], "listo", "Corrida terminada con metricas.json: registrala", n=n,
                            id=t["id"], accion={"accion": "registrar", "n": n,
                                                "opciones": {"--run": t["resultado"], "--activar": True}}))
        elif est == "listo" and tipo == "precodificacion":  # P.4: precodificaciones listas
            desc = "Cache de SAM 3 lista: importa al hub"
            if grupo and grupo in grupos_info:
                total = len(grupos_info[grupo]["trozos"])
                listos = sum(1 for e in grupos_info[grupo]["estados"].values() if e in ("listo", "importado"))
                desc = f"Cache trozo {listos}/{total}: importa al hub"
            it.append(_item(tipo, t["archivo"], "listo", desc, n=n, id=t["id"],
                            accion={"accion": "cache-importar", "opciones": {}}))
        elif est == "error":
            if tipo == "asistente" and _asist_vivos(v, slug)[-1]["archivo"] != t["archivo"]:
                continue                             # ya hay un trabajo mas nuevo del mismo slug
            it.append(_item(tipo, t["archivo"], "error", f"Fallo en {EJECUTOR}: {(t['error'] or '')[-200:]}"
                            " | Reintentar lo vuelve a enviar; Archivar lo descarta", n=n, slug=slug, id=t["id"],
                            accion=_reintentar(t)))
    for tipo in ("asistente", "preetiquetado"):
        k = sum(1 for x in it if x["tipo"] == tipo and x["estado"] == "en_espera")
        if k > 1:
            out["avisos"].append(f"Hay {k} trabajos de {tipo} en espera: el worker los procesa TODOS; archiva los que no quieras")
    return out


def proyectos():
    avisos = []
    lista = _ls("/api/projects?page_size=200")
    if lista is None:
        avisos.append("Label Studio no responde: sin tareas ni anotadas")
    lista = (lista.get("results") if isinstance(lista, dict) else lista) or []
    ls = {p["id"]: p for p in lista if isinstance(p, dict) and "id" in p}
    if not _drive():
        avisos.append("No encuentro la carpeta de lotes del transporte (en Drive: LOTES_DRIVE): sin lotes, runs ni asistente")
    v = vista()
    lts = lotes(v)
    slugs = {d.name for d in PROYECTOS.iterdir() if d.is_dir()} if PROYECTOS.is_dir() else set()
    slugs |= {t["slug"] for t in v["trabajos"] if t["tipo"] == "asistente" and t["slug"]}
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
             "protegido": n in PROTEGIDOS, "asistente": _asistente(v, slug)}
        if ruta.exists() and spec is None:
            t["spec_errores"] = [f"spec.json no es JSON valido: revisalo con  python xd.py validar {slug}"]
        if spec:
            t["spec_errores"], t["spec_avisos"] = xd._validar_spec(spec, slug)
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
            _datos(t, n, _ls(f"/api/projects/{n}"), lts, v)
        t["siguiente"] = siguiente(t)
        tarjetas.append(t)
    for pid, p in sorted(ls.items()):
        if pid not in usados:
            t = {"slug": None, "titulo": p.get("title") or f"Proyecto {pid}", "spec": False, "n": pid,
                 "vinculo": None, "protegido": pid in PROTEGIDOS, "asistente": None}
            _datos(t, pid, _ls(f"/api/projects/{pid}"), lts, v)
            t["siguiente"] = siguiente(t)
            tarjetas.append(t)
    for ruta_c, ss in sorted(compartidas.values()):
        if len(set(ss)) > 1:
            avisos.append(f"Carpeta compartida por {sorted(set(ss))}: {ruta_c} (sus fotos cuentan en todos)")
    tarjetas.sort(key=lambda t: (t["protegido"], t["n"] is None, str(t["titulo"])))
    return {"tarjetas": tarjetas, "avisos": avisos}


if __name__ == "__main__":
    print(json.dumps({"servicios": servicios(), **proyectos()}, indent=1, ensure_ascii=True, default=str))
