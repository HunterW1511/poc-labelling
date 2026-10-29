import logging, time

from flask import jsonify
from label_studio_ml.api import init_app

import cola, config, interactivo
from model import MotorPreetiquetado

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = init_app(model_class=MotorPreetiquetado)
_INICIO = time.time()


@app.route("/estado", methods=["GET"])
def estado():
    """Readiness (A.4): /health solo dice que gunicorn responde; esto dice si SAM 3 esta listo.
    Solo lee estado (sin candados): responde al instante aunque el modelo este cargando."""
    e = interactivo._est
    return jsonify({
        "listo": e["pred"] is not None and not e["calentando"],
        "calentando": e["calentando"], "imgsz": e["imgsz"], "device": config.dispositivo(),
        "cache": len(interactivo._cache), "cache_max": config.CACHE_MAX,
        "precodificando": len(interactivo._en_proceso),
        "cola": cola._cola.qsize(), "cola_pendientes": len(cola._pendientes),
        "semantico_cargado": cola._sam["pred"] is not None,
        "uptime_s": round(time.time() - _INICIO)})
