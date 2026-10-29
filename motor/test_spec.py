"""Prueba de spec.py. Uso: python /app/test_spec.py"""
import copy

from spec import cargar, validar

BASE = cargar("/app/fixtures/spec_ensamble.json")


def romper(f):
    s = copy.deepcopy(BASE)
    f(s)
    return validar(s)[0]


def clase(s, n):
    return next(c for c in s["clases"] if c["nombre"] == n)


CASOS = [
    ("clave con typo", lambda s: clase(s, "Base").update(max=1), "clave desconocida 'max'"),
    ("dentro_de inexistente", lambda s: clase(s, "Eje_Interno").update(dentro_de="Eje_X"), "dentro_de='Eje_X'"),
    ("ciclo dentro_de", lambda s: (clase(s, "Eje_Interno").update(dentro_de="Eje_Externo"),
                                   clase(s, "Eje_Externo").update(dentro_de="Eje_Interno")), "ciclo"),
    ("area invertida", lambda s: clase(s, "Base").update(area_max=0.005), "area_min (0.01) debe ser menor"),
    ("carpeta clase inexistente", lambda s: s["carpetas"][0]["clases"].append("Rueda"), "clase inexistente 'Rueda'"),
    ("negativo con clases", lambda s: s["carpetas"][-1]["clases"].append("Base"), "negativo no lleva clases"),
    ("clic invalido", lambda s: clase(s, "Base").update(clic="medio"), "clic='medio'"),
    ("nombre duplicado", lambda s: s["clases"].append(copy.deepcopy(clase(s, "Base"))), "duplicado 'Base'"),
    ("ajuste desconocido", lambda s: s["ajustes"].update(iou=0.5), "ajustes: clave desconocida 'iou'"),
    ("slug invalido", lambda s: s["proyecto"].update(slug="Mi Proyecto"), "proyecto.slug"),
]


def main():
    e, a = validar(BASE)
    assert not e, e
    assert any("yellow plastic part" in x and "area_max" in x for x in a), a
    print(f"spec real OK: 0 errores, {len(a)} avisos")
    for x in a:
        print("   AVISO:", x)
    for nombre, f, esperado in CASOS:
        errs = romper(f)
        assert any(esperado in x for x in errs), (nombre, errs)
        print(f"   rota OK  {nombre:<26} -> {next(x for x in errs if esperado in x)[:70]}")
    print(f"TEST SPEC OK ({len(CASOS)} casos rotos detectados)")


if __name__ == "__main__":
    main()
