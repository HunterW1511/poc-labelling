"""Ejecutor de lotes en Colab. Viaja en el zip (codigo/): el notebook solo llama procesar(),
asi un modo nuevo no obliga a cambiar el notebook. Nunca hay dos SAM 3 cargados a la vez."""
import gc, json, time
from pathlib import Path


def _liberar(cache):
    cache.clear()
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


def _obtener(cache, clave, crear):
    if clave not in cache:
        _liberar(cache)
        cache[clave] = crear()
    return cache[clave]


def _ov(sam3_pt, imgsz, device, **extra):
    return {"model": sam3_pt, "imgsz": imgsz, "task": "segment", "mode": "predict", "verbose": False,
            "save": False, "device": device, **extra}


def procesar(d, cache, nombre_zip, sam3_pt="/content/sam3.pt", device=0):
    """d = carpeta del zip extraido; cache = dict del notebook (persiste entre lotes)."""
    d = Path(d)
    man = json.load(open(d / "manifiesto.json"))
    perfil, ver, modo = man["perfil"], man["version"], man.get("modo", "sam3")
    import pipeline
    if modo == "sam3":
        from ultralytics.models.sam import SAM3SemanticPredictor
        pred = _obtener(cache, ("sem", perfil["imgsz"]),
                        lambda: SAM3SemanticPredictor(overrides=_ov(sam3_pt, perfil["imgsz"], device, conf=0.05)))
        inferir = lambda ruta: pipeline.inferir(pred, ruta, perfil)
    elif modo == "hijo":
        import hijo
        from ultralytics import YOLO
        from ultralytics.models.sam import SAM3Predictor
        h = man["hijo"]
        sam = _obtener(cache, ("int", perfil["imgsz"]),
                       lambda: SAM3Predictor(overrides=_ov(sam3_pt, perfil["imgsz"], device)))
        yolo = YOLO(str(d / h["archivo"]))
        hijo.validar_clases(yolo.names, perfil["clases"])
        inferir = lambda ruta: hijo.inferir_hijo(yolo, sam, ruta, perfil, man["limites"], h["conf"], h["imgsz"])
    else:
        raise ValueError(f"modo desconocido: {modo}")
    print(f"{nombre_zip}: modo {modo} | version {ver} | {len(man['tareas'])} tareas")
    preds, t0 = [], time.time()
    for i, t in enumerate(man["tareas"], 1):
        ti = time.time()
        res, score, info = inferir(str(d / t["foto"]))
        preds.append({"task": t["id"], "model_version": ver, "score": score, "result": res})
        extra = f" | sam {info['sam_mascaras']}" if "sam_mascaras" in info else ""
        print(f"[{i}/{len(man['tareas'])}] tarea {t['id']} | crudas {info['crudas']} -> finales "
              f"{info['finales']} | {info['descartes']}{extra} | {time.time() - ti:.1f}s")
    print(f"OK {nombre_zip}: {len(preds)} tareas en {time.time() - t0:.0f}s")
    return {"lote": nombre_zip, "proyecto": man["proyecto"], "version": ver, "modo": modo, "predicciones": preds}
