"""Prueba de generar.py contra el perfil fijo del proyecto 2 (fixtures/label_config_p2.xml).
Uso: python /app/test_generar.py  (no depende de Label Studio)"""
import copy
from pathlib import Path

from generar import generar_xml, verificar
from perfil import leer_perfil
from spec import cargar
from version import huella_perfil

FIX = Path(__file__).resolve().parent / "fixtures"
SPEC = cargar(FIX / "spec_ensamble.json")
XML_REAL = (FIX / "label_config_p2.xml").read_text(encoding="utf-8")


def diff(a, b, ruta=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from diff(a.get(k), b.get(k), f"{ruta}.{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from diff(x, y, f"{ruta}[{i}]")
    elif a != b:
        yield f"{ruta}: generado={a!r} | real={b!r}"


def main():
    xml, p, ver = verificar(SPEC)
    assert generar_xml(SPEC) == xml, "el generador no es determinista"
    real = leer_perfil(XML_REAL)
    d = list(diff(p, real))
    for x in d:
        print("  DIFF", x)
    print("huella generada:", huella_perfil(p), "| fixture p2:", huella_perfil(real), "| version:", ver)
    assert not d and huella_perfil(p) == "bff21077"
    print("ACEPTACION OK: el XML generado reproduce el perfil fijo del proyecto 2")

    s = copy.deepcopy(SPEC)
    for c in s["clases"]:
        if c["nombre"] in ("Eje_Externo", "Eje_Interno"):
            c.pop("contencion")
    next(c for c in s["clases"] if c["nombre"] == "Eje_Interno")["dentro_de"] = "Eje_Externo"
    _, p2, _ = verificar(s)
    am = next(x for x in p2["prompts"] if x["texto"] == "yellow plastic part")
    assert am["contencion"] == 1.01 and huella_perfil(p2) == "bff21077", am
    print("dentro_de OK: genera contencion 1.01 en el grupo (mismo perfil)")

    s = copy.deepcopy(SPEC)
    s["clases"][0]["max"] = 3
    try:
        generar_xml(s)
        raise AssertionError("una spec invalida debio fallar")
    except ValueError as e:
        print("spec invalida rechazada OK:", str(e).splitlines()[1].strip()[:70])
    print("TEST GENERAR OK")


if __name__ == "__main__":
    main()
