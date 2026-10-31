import logging

from label_studio_ml.model import LabelStudioMLBase
from label_studio_ml.response import ModelResponse

import cola
import interactivo
import version
from perfil import leer_perfil

log = logging.getLogger("motor")


class MotorPreetiquetado(LabelStudioMLBase):
    """Motor generico multiproyecto: el comportamiento sale del perfil en el XML."""

    def _version(self):
        try:
            p = leer_perfil(self.label_config)
        except Exception:
            return "motor-sin-perfil"
        return version.version_modelo(p)

    def setup(self):
        self.set("model_version", self._version())

    def predict(self, tasks, context=None, **kwargs):
        perfil = leer_perfil(self.label_config)
        if context:                                   # Etapa 3: clic -> poligono (sincrono)
            if not tasks:
                return ModelResponse(predictions=[])
            preds = interactivo.responder(tasks[0], context, perfil, "clic-" + self._version(), self.label_config, self.project_id)
            return ModelResponse(predictions=preds)
        if len(tasks) == 1:        # L.10: una tarea = alguien la abrio para etiquetar; un lote no despierta al interactivo
            interactivo.precalentar(perfil["imgsz"], perfil, self.project_id)     # el primer clic no espera la carga
        if not perfil["prompts"]:
            log.warning("proyecto %s sin prompts en el XML; nada que hacer", self.project_id)
            return ModelResponse(predictions=[])
        cola.encolar(tasks, perfil, self._version())
        return ModelResponse(predictions=[])        # las predicciones llegan despues por la API

    def fit(self, event, data, **kwargs):
        log.info("fit | proyecto=%s | evento=%s", self.project_id, event)




