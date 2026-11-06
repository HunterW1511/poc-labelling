"""P.7.1: el siguiente paso de un proyecto, estructurado para el modo guiado (modulo puro: sin red ni disco).
Recibe la tarjeta que arma tablero.proyectos() y devuelve en que paso del flujo esta, quien lo hace y, si la UI puede
hacerlo, la accion lista para /api/accion (misma lista blanca ACCIONES de ui.py). tablero.siguiente() lo usa; la CLI
lo muestra con  python xd.py guia [N|slug].

Paso -> {"paso": 1-9 | None, "fase": nombre, "quien": QUIEN, "texto": ..., "accion": {...} | None,
         "donde": compat con la UI de E.5 (cli, host, label_studio, colab, kaggle o ""), "cmd": comando equivalente}"""

FASES = ("Caso", "Proyecto", "Fotos", "Pre-etiquetado", "Revision", "Modelo", "Mas tareas", "Validacion", "En vivo")
# ui = la UI lo corre (reporte y luego --aplicar si aplica); host = la UI lo lanza pero abre una ventana en el escritorio
# (camara); label_studio = trabajo humano en Label Studio; editar = editar un archivo a mano; espera = lo hace el worker
# (o el daemon); nada = no hay paso (protegido, spec de referencia)
QUIEN = ("ui", "host", "label_studio", "editar", "espera", "nada")
TEXTO_ESPERA = {"colab": "Esperando a Colab: abre worker.ipynb y corre la celda 2",
                "kaggle": "En Kaggle: 'Enviar a Kaggle' y, cuando termine, 'Traer de Kaggle' (Pasos externos)"}
MUESTRA = 30                                    # tamano de muestra sugerido para pre-etiquetar (20-50)


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
        return _paso(1, "espera", espera, donde=ejecutor)
    if a.get("ultimo") == "error":
        return _paso(1, "ui", f"El asistente fallo en {ejecutor}: revisa el error", accion("asistente-importar", slug=s))
    if a.get("ultimo") == "resultado" and not a.get("aplicada"):
        return _paso(1, "ui", "Revisa el resultado del asistente y aplica la spec", accion("asistente-importar", slug=s))
    if s and s.endswith("-ref"):                       # L.5: spec de referencia para comparar, no un proyecto
        return _paso(None, "nada", "Spec de referencia: solo para comparar (asistente-importar --comparar); no se crea proyecto")
    if t.get("spec_errores"):
        ne = len(t["spec_errores"])
        return _paso(1, "editar", f"Corrige la spec: {ne} error{'es' if ne != 1 else ''} (edita spec.json y vuelve a validar)",
                     accion("validar", slug=s))
    if s and not t.get("spec"):
        return _paso(1, "ui", "Describe el caso con el asistente, o parte de la plantilla (sin asistente)",
                     accion("spec-nueva", slug=s))
    if not n:
        return _paso(2, "ui", "Proyecto borrado; si lo quieres de nuevo, crealo" if t.get("borrado") else
                     "Crea el proyecto en Label Studio", accion("crear-proyecto", slug=s))
    ls, fotos, lo = t.get("ls") or {}, t.get("fotos") or [], t.get("lotes") or {}
    tareas, anot = ls.get("task_number") or 0, ls.get("num_tasks_with_annotations") or 0
    tienes = sum(f["tienes"] for f in fotos)
    if lo.get("en_colab"):
        return _paso(4, "espera", espera, donde=ejecutor)
    if lo.get("sin_importar"):
        return _paso(4, "ui", f"Importa las predicciones de {ejecutor}", accion("lote-importar", fijar_version=True))
    if s and fotos and any(f["tienes"] == 0 for f in fotos):
        return _paso(3, "host", "Captura fotos: hay carpetas vacias", accion("capturar", slug=s))
    if s and tienes > tareas:
        return _paso(3, "ui", f"Hay {tienes - tareas} fotos sin tarea: sincroniza", accion("sincronizar", slug=s))
    if t.get("runs_sin_registrar"):
        return _paso(6, "ui", f"Registra el modelo entrenado en {ejecutor}",
                     accion("registrar", n=n, run="ultimo", activar=True))
    if not (t.get("modelos") or {}).get("activo"):
        if anot == 0 and not ls.get("total_predictions_number"):
            return _paso(4, "ui", "Pre-etiqueta una muestra con SAM 3", accion("preetiquetar", n=n, muestra=MUESTRA))
        if anot == 0:
            return _paso(5, "label_studio", "Revisa la muestra en Label Studio y da Submit")
        if t.get("datasets"):
            return _paso(6, "ui", f"Entrena en {ejecutor} con el ultimo dataset (o exporta otro si revisaste mas)",
                         accion("dataset", n=n, drive=True), donde=ejecutor)
        return _paso(6, "ui", "Exporta el dataset para entrenar", accion("dataset", n=n, drive=True))
    if tareas > anot:
        return _paso(7, "ui", f"{tareas - anot} tareas sin anotar: pre-etiqueta con el hijo",
                     accion("preetiquetar", n=n, muestra=MUESTRA))
    return _paso(8, "ui", "Valida el modelo: aceptacion y prueba en vivo", accion("aceptacion", n=n))
