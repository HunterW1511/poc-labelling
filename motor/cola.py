"""Cola en segundo plano: predict responde al instante; SAM 3 (CPU local) procesa y sube por la API."""
import logging, os, queue, threading, time

import numpy as np
import requests
try:                                    # SDK actual: la funcion vive dentro de label_studio_sdk
    from label_studio_sdk._extensions.label_studio_tools.core.utils.io import get_local_path
except ImportError:                     # SDK antiguo: paquete separado
    from label_studio_tools.core.utils.io import get_local_path

import pipeline

log = logging.getLogger("motor.cola")
from config import HEADERS, LS_URL, SAM3_MODEL, dispositivo   # re-exportados: otros scripts los importan de cola

_cola, _pendientes, _lock = queue.Queue(), set(), threading.Lock()
_hilo = None
CARGA = threading.Lock()   # una carga de modelo a la vez (evita OOM)
_sam = {"pred": None, "imgsz": None, "cargando": False, "esperando_carga": False}
al_vaciar = []             # L.10: callbacks cuando la cola semantica queda vacia (el interactivo reanuda la precodificacion)


def overrides_sam3(imgsz, conf):
    """Overrides UNICOS para todo SAM 3 del motor. Todos los predictores deben compartir device y quantize:
    setup_model hace model.to(device) y half()/float() incluso sobre un modelo compartido."""
    return {"model": SAM3_MODEL, "imgsz": imgsz, "conf": conf, "task": "segment", "mode": "predict",
            "verbose": False, "save": False, "device": dispositivo()}


def encolar(tareas, perfil, version):
    """Llamado desde predict. El hilo se arranca aqui (no en el import) por el --preload de gunicorn."""
    global _hilo
    n = 0
    with _lock:
        if _hilo is None or not _hilo.is_alive():
            _hilo = threading.Thread(target=_trabajar, daemon=True, name="sam3")
            _hilo.start()
        for t in tareas:
            if t["id"] not in _pendientes:
                _pendientes.add(t["id"])
                _cola.put((t, perfil, version))
                n += 1
    log.info("encoladas %d | en cola %d", n, _cola.qsize())


def ocupada():
    """Hay trabajo semantico pendiente o en curso (L.10: la precodificacion interactiva cede la CPU)."""
    return _cola.unfinished_tasks > 0


def _terminar(tid):
    with _lock:
        _pendientes.discard(tid)
    _cola.task_done()
    if not ocupada():
        for f in list(al_vaciar):
            try:
                f()
            except Exception:
                log.exception("al_vaciar fallo")


def _ya_tiene(task_id, version):
    r = requests.get(f"{LS_URL}/api/predictions", params={"task": task_id}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return any(p.get("model_version") == version for p in r.json())


def _predictor(imgsz):
    if _sam["pred"] is not None and _sam["imgsz"] == imgsz:
        return _sam["pred"]                      # ya cargado: sin esperar el candado
    _sam["esperando_carga"] = True                 # L.10: visible en /estado (explica una cola quieta)
    try:
        with CARGA:
            _sam["esperando_carga"] = False
            return _predictor_sin_candado(imgsz)
    finally:
        _sam["esperando_carga"] = False


def _predictor_sin_candado(imgsz):
    if _sam["pred"] is None or _sam["imgsz"] != imgsz:
        from ultralytics.models.sam import SAM3SemanticPredictor
        t0 = time.time()
        _sam["pred"], _sam["cargando"] = None, True          # libera el anterior antes de cargar otro
        try:
            p = SAM3SemanticPredictor(overrides=overrides_sam3(imgsz, 0.05))
            p.set_image(np.zeros((imgsz, imgsz, 3), np.uint8))   # fuerza la carga dentro del candado
            _sam["pred"], _sam["imgsz"] = p, imgsz             # L.10: visible solo cuando ya esta listo
        finally:
            _sam["cargando"] = False
        log.info("SAM 3 listo (imgsz=%d, device=%s) en %.0fs", imgsz, dispositivo(), time.time() - t0)
    return _sam["pred"]


def _trabajar():
    while True:
        t, perfil, version = _cola.get()
        tid = t["id"]
        try:
            if _ya_tiene(tid, version):
                log.info("tarea %s ya tiene %s, omito", tid, version)
                continue
            ruta = get_local_path(t["data"][perfil["campo_imagen"]], task_id=tid)
            t0 = time.time()
            res, score, info = pipeline.inferir(_predictor(perfil["imgsz"]), ruta, perfil)
            log.info("crudas %d -> finales %d | descartes %s | conflictos %d",
                     info["crudas"], info["finales"], info["descartes"], info["conflictos"])
            requests.post(f"{LS_URL}/api/predictions", headers=HEADERS, timeout=60, json={
                "task": tid, "model_version": version, "score": score, "result": res}).raise_for_status()
            log.info("tarea %s | %d regiones | %.0fs | quedan %d", tid, len(res), time.time() - t0, _cola.qsize())
        except Exception:
            log.exception("tarea %s fallo", tid)
        finally:
            _terminar(tid)




