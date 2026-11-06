"""model.predict: precalienta SOLO con la senal explicita de xd.py (params precalentar) o al abrir UNA tarea (L.10);
un /predict vacio o un lote no despiertan al interactivo. Sin SAM 3 (stubs). Uso: python test_precalentar.py"""
from pathlib import Path

import cola
import interactivo
import model

XML = (Path(__file__).resolve().parent / "fixtures" / "label_config_p2.xml").read_text(encoding="utf-8")


def test_precalentar_solo_con_senal_o_una_tarea():
    llamadas, encoladas = [], []
    viejo = (interactivo.precalentar, cola.encolar)
    try:
        interactivo.precalentar = lambda imgsz, perfil=None, proyecto=None: llamadas.append(proyecto)
        cola.encolar = lambda tareas, perfil, version: encoladas.append(len(tareas))
        m = model.MotorPreetiquetado(project_id="7", label_config=XML)
        assert m.predict([], precalentar=True).predictions == []            # xd.py precalentar
        assert llamadas == ["7"] and encoladas == [], (llamadas, encoladas)  # carga sin encolar nada
        m.predict([])                                                        # /predict vacio: no carga
        assert llamadas == ["7"], llamadas
        m.predict([{"id": 1, "data": {}}, {"id": 2, "data": {}}])             # un lote: no carga
        assert llamadas == ["7"], llamadas
        m.predict([{"id": 3, "data": {}}])                                   # abrir UNA tarea: carga
        assert llamadas == ["7", "7"], llamadas
    finally:
        interactivo.precalentar, cola.encolar = viejo


if __name__ == "__main__":
    test_precalentar_solo_con_senal_o_una_tarea()
    print("TEST PRECALENTAR OK: senal explicita o una tarea; un /predict vacio o un lote no cargan SAM 3")
