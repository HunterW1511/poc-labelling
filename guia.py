"""P.7: el siguiente paso de un proyecto, estructurado para el modo guiado (modulo puro: sin red ni disco).
Recibe la tarjeta que arma tablero.proyectos() y devuelve en que paso del flujo esta, quien lo hace y, si la UI puede
hacerlo, la accion lista para /api/accion (misma lista blanca ACCIONES de ui.py). tablero.siguiente() lo usa; la CLI
lo muestra con  python xd.py guia [N|slug].

Flujo (P.7.4, el de la persona): Crear proyecto -> Describir (grabar o escribir) -> Fotos -> Pre-etiquetar ->
Verificar -> Modelo hijo -> Pre-etiquetar final (con el hijo) -> Verificar final -> Modelo final -> Probar en vivo.

Paso -> {"paso": 1-10 | None, "fase": nombre, "quien": QUIEN, "texto": ..., "accion": {...} | None,
         "donde": compat con la vista avanzada (cli, host, label_studio, colab, kaggle o ""), "cmd": comando}"""

FASES = ("Crear proyecto", "Describir el caso", "Fotos", "Pre-etiquetar", "Verificar", "Modelo hijo",
         "Pre-etiquetar final", "Verificar final", "Modelo final", "Probar en vivo")
# ui = la UI lo corre (reporte y luego --aplicar si aplica); host = la UI lo lanza pero abre una ventana en el escritorio
# (camara); label_studio = trabajo humano en Label Studio (puede traer una accion para "ya termine"); editar = editar
# un archivo a mano; espera = lo hace el worker (o el automatico); nada = no hay paso (protegido, spec de referencia)
QUIEN = ("ui", "host", "label_studio", "editar", "espera", "nada")
TEXTO_ESPERA = {"colab": "Esperando a Colab: abre worker.ipynb y corre la celda 2",
                "kaggle": "En Kaggle: 'Enviar a Kaggle' y, cuando termine, 'Traer de Kaggle' (Pasos externos)"}
# P.7 bloque 2.2: minimo de fotos revisadas para entrenar (con 19 el hijo de la prueba P.7 no aprendio nada); si el
# proyecto tiene menos tareas, basta con revisarlas todas. La muestra inicial coincide con el minimo.
MIN_REVISADAS = 50
MUESTRA = MIN_REVISADAS                         # tamano de muestra sugerido para el primer pre-etiquetado


def faltan_para_entrenar(anot, tareas):
    """Fotos revisadas que faltan para poder entrenar (0 = ya se puede)."""
    return max(0, max(1, min(MIN_REVISADAS, tareas)) - anot)


def accion(nombre, slug=None, n=None, **opciones):
    """Accion para /api/accion. opciones: {"--muestra": 30, "--fijar-version": True, ...} (por nombre con _ -> -)."""
    a = {"accion": nombre, "opciones": {"--" + k.replace("_", "-"): v for k, v in opciones.items()}}
    if slug is not None:
        a["slug"] = slug
    if n is not None:
        a["n"] = n
    return a


def comando(a):
    """Comando de CLI equivalente a una accion (lo que la UI correria, en modo reporte)."""
    if not a:
        return ""
    prog = "python capturar.py" if a["accion"] == "capturar" else f"python xd.py {a['accion']}"
    partes = [prog] + [str(a[k]) for k in ("slug", "n") if a.get(k) is not None]
    for k, v in a.get("opciones", {}).items():
        if v is True:
            partes.append(k)
        elif v not in (False, None, ""):
            partes += [k, str(v)]
    return " ".join(partes)


def _paso(paso, quien, texto, a=None, donde=None):
    if quien not in QUIEN:
        raise ValueError(f"quien {quien!r}: {QUIEN}")
    return {"paso": paso, "fase": FASES[paso - 1] if paso else "", "quien": quien, "texto": texto, "accion": a,
            "donde": donde if donde is not None else {"ui": "cli", "espera": "", "nada": "", "editar": "cli"}.get(quien, quien),
            "cmd": comando(a)}


def siguiente(t, ejecutor="colab"):
    """Siguiente paso de la tarjeta t (ver tablero.proyectos). ejecutor: 'colab' o 'kaggle'."""
    s, n = t.get("slug"), t.get("n")
    espera = TEXTO_ESPERA.get(ejecutor, TEXTO_ESPERA["colab"])
    if t.get("protegido"):
        return _paso(None, "nada", "Proyecto protegido: solo lectura")
    a = t.get("asistente") or {}
    if a.get("ultimo") == "pendiente":
        return _paso(2, "espera", "El asistente esta leyendo tu descripcion en " + ejecutor, donde=ejecutor)
    if a.get("ultimo") == "error":
        return _paso(2, "ui", f"El asistente fallo en {ejecutor}: revisa el error y vuelve a describirlo",
                     accion("asistente-importar", slug=s))
    if a.get("ultimo") == "resultado" and not a.get("aplicada"):
        return _paso(2, "ui", "Revisa lo que entendio el asistente y aplicalo", accion("asistente-importar", slug=s))
    if s and s.endswith("-ref"):                       # L.5: spec de referencia para comparar, no un proyecto
        return _paso(None, "nada", "Spec de referencia: solo para comparar (asistente-importar --comparar); no se crea proyecto")
    if t.get("spec_errores"):
        ne = len(t["spec_errores"])
        return _paso(2, "editar", f"Corrige la spec: {ne} error{'es' if ne != 1 else ''} (edita spec.json y vuelve a validar)",
                     accion("validar", slug=s))
    if s and not t.get("spec"):
        return _paso(2, "ui", "Describe el caso: graba o escribe que quieres contar", accion("spec-nueva", slug=s))
    if not n:
        return _paso(2, "ui", "Proyecto borrado; si lo quieres de nuevo, crealo" if t.get("borrado") else
                     "Descripcion lista: crea el proyecto en Label Studio", accion("crear-proyecto", slug=s))
    ls, fotos, lo = t.get("ls") or {}, t.get("fotos") or [], t.get("lotes") or {}
    tareas, anot = ls.get("task_number") or 0, ls.get("num_tasks_with_annotations") or 0
    tienes = sum(f["tienes"] for f in fotos)
    ee = t.get("en_espera") or {}
    mod = t.get("modelos") or {}
    hijo = bool(mod.get("activo"))
    if s and fotos and any(f["tienes"] == 0 for f in fotos):
        return _paso(3, "host", "Toma las fotos: hay carpetas vacias", accion("capturar", slug=s))
    if s and tienes > tareas:
        return _paso(3, "ui", f"Hay {tienes - tareas} fotos nuevas: subelas a Label Studio", accion("sincronizar", slug=s))
    pre, ver, ent = (7, 8, 9) if hijo else (4, 5, 6)
    if ee.get("entrenamiento"):
        return _paso(ent, "espera", f"Entrenando el modelo en {ejecutor}", donde=ejecutor)
    if t.get("runs_sin_registrar"):
        return _paso(ent, "ui", "Modelo entrenado: registralo y activalo", accion("registrar", n=n, run="ultimo", activar=True))
    if hijo and (mod.get("n") or 0) >= 2:
        return _paso(10, "host", "Prueba el modelo final con la camara", accion("ver", n=n))
    if lo.get("en_colab") or ee.get("preetiquetado"):
        return _paso(pre, "espera", ("Pre-etiquetando con el modelo hijo en " if hijo else "Pre-etiquetando con SAM 3 en ")
                     + ejecutor, donde=ejecutor)
    if lo.get("sin_importar"):
        return _paso(pre, "ui", "Predicciones listas: subelas a Label Studio", accion("lote-importar", fijar_version=True))
    faltan = faltan_para_entrenar(anot, tareas)
    entrenar = accion("dataset", n=n, drive=True) if not faltan else None
    minimo = f" Para entrenar faltan {faltan} (minimo {min(MIN_REVISADAS, tareas)} revisadas)." if faltan else ""
    if not hijo:
        if anot == 0 and not ls.get("total_predictions_number"):
            return _paso(4, "ui", "Pre-etiqueta una muestra de fotos con SAM 3", accion("preetiquetar", n=n, muestra=MUESTRA))
        return _paso(5, "label_studio", f"Corrige y da Submit en Label Studio ({anot} de {tareas} revisadas)."
                     + (minimo or " Cuando termines la muestra, entrena el modelo hijo"), entrenar)
    if str(ls.get("model_version") or "").startswith("hijo-"):
        return _paso(8, "label_studio", f"Corrige lo que el hijo dejo mal ({anot} de {tareas} revisadas)."
                     + (minimo or " Cuando termines, entrena el modelo final"), entrenar)
    if tareas > anot:
        return _paso(7, "ui", f"Pre-etiqueta las {tareas - anot} fotos que faltan con el modelo hijo",
                     accion("preetiquetar", n=n, muestra=tareas - anot, modo="hijo"))
    return _paso(9, "ui", "Todas las fotos revisadas: entrena el modelo final", entrenar)
