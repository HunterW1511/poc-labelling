"""Prueba de plan.py (solo biblioteca estandar). Uso: python motor/test_plan.py"""
import copy
from pathlib import Path

from plan import MINIMOS, plan_captura
from spec import cargar

SPEC = cargar(Path(__file__).resolve().parent / "fixtures" / "spec_ensamble.json")


def main():
    filas = plan_captura(SPEC)
    f = {x["carpeta"]: x for x in filas}
    for x in filas:
        print(f"  {x['carpeta']:<14} {x['tipo']:<9} {x['fotos']:>4}  {x['motivo']}")
    assert f["Tornillos"]["fotos"] == 60 and f["Base"]["fotos"] == 40, f
    assert f["Ensamble"]["fotos"] == 125, f["Ensamble"]                # max(50, 15*7) + 20
    assert f["Fondo"]["fotos"] == 58, f["Fondo"]                       # ceil(0.12 * 425 / 0.88)
    v = f["Ensamble"]["variaciones"]
    assert any("Tornillos: variar la cantidad de 1 a 10" in x for x in v), v
    assert any("Eje_Externo y Eje_Interno juntas" in x for x in v), v
    print(f"base OK | total {sum(x['fotos'] for x in filas)}")

    esc = plan_captura(SPEC, total=200)
    assert all(x["fotos"] >= MINIMOS[x["tipo"]] for x in esc)
    assert abs(sum(x["fotos"] for x in esc) - 200) <= len(esc), sum(x["fotos"] for x in esc)
    print(f"escalado OK | total pedido 200 -> {sum(x['fotos'] for x in esc)}")

    s = copy.deepcopy(SPEC)
    s["carpetas"] = [k for k in s["carpetas"] if k["tipo"] != "negativo"]
    assert all(x["tipo"] != "negativo" for x in plan_captura(s))
    print("sin negativos OK")
    print("TEST PLAN OK")


if __name__ == "__main__":
    main()
