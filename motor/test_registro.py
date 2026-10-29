"""Prueba de registro.py (host): python motor\test_registro.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registro import activar, agregar, mejor, normalizar, tabla, vacio

V1 = {"proyecto": 2, "tarea": "det", "arquitectura": "yolo11n", "imgsz": 960, "entrenado": "2026-10-13",
      "dataset": "dataset_p2_det_20261013-2210", "metricas_val": {"mAP50": 0.945, "mAP50_95": 0.818},
      "conteo_val": {"conf": 0.25, "exacto": 8, "imagenes": 29, "error_abs": {"Tornillos": 12}}}
V2 = {"esquema": 1, "creado": "2026-10-15T06:00:00", "dataset": "dataset_p2_det_20261015-0533.zip",
      "formato": "det", "modelo_base": "yolo11n.pt", "params": {"imgsz": 960},
      "conteo": {"exactas": 7, "imagenes": 33, "tasa": 0.212}, "map50": 0.928, "map50_95": 0.816,
      "por_clase": {"Tornillos": {"ap50": 0.957, "error_abs": 30}, "Base": {"error_abs": 1}}}


def falla(f, exc):
    try:
        f()
    except exc:
        return True
    raise AssertionError(f"debio lanzar {exc.__name__}")


def main():
    r1, r2 = normalizar(V1), normalizar(V2)
    assert r1["conteo_tasa"] == 0.276 and r1["base"] == "yolo11n" and r1["error_abs"]["Tornillos"] == 12
    assert r2["conteo_tasa"] == 0.212 and r2["imgsz"] == 960 and r2["error_abs"] == {"Tornillos": 30, "Base": 1}
    falla(lambda: normalizar({"map50": 0.99}), ValueError)
    falla(lambda: normalizar({"conteo": {"exactas": 1, "imagenes": 0}}), ValueError)

    reg = vacio(2)
    assert mejor(reg) is None
    reg = agregar(reg, "v1", V1, "p2/v1/best.pt", "manual", "2026-10-13")
    reg2 = agregar(reg, "v2", V2, "p2/v2/best.pt", "runs/x", "2026-10-15")
    assert len(reg["modelos"]) == 1, "agregar no debe mutar el original"
    falla(lambda: agregar(reg2, "v2", V2, "x", "y", "z"), ValueError)
    assert mejor(reg2) == "v1", "v1 cuenta mejor (28% vs 21%)"

    # mas mAP pero peor conteo NO gana
    alto_map = dict(V2, map50=0.999, conteo={"exactas": 1, "imagenes": 33})
    reg3 = agregar(reg2, "v3", alto_map, "p2/v3/best.pt", "runs/y", "2026-10-16")
    assert mejor(reg3) == "v1"
    # empate de conteo -> gana el de mas mAP50
    emp = dict(V2, map50=0.99, conteo={"exactas": 8, "imagenes": 29})
    assert mejor(agregar(reg3, "v4", emp, "p", "o", "2026-10-17")) == "v4"

    assert reg3["activo"] is None
    act = activar(reg3, "v2")
    assert act["activo"] == "v2" and reg3["activo"] is None
    falla(lambda: activar(reg3, "nope"), KeyError)
    t = tabla(act)
    assert any(l.startswith("*") and "v2" in l for l in t) and any(l.startswith(" +") and "v1" in l for l in t)
    print("test_registro OK")
    print("\n".join(t))


if __name__ == "__main__":
    main()
