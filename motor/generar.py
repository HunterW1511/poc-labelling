"""Generador DETERMINISTA del XML de Label Studio a partir de la especificacion (B.3).
Misma spec -> mismo XML. Un LLM nunca escribe el XML. Cadena: validar -> XML -> leer_perfil -> revisar_perfil.
Uso: python /app/generar.py <spec.json> [--salida archivo.xml]"""
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import reglas
from perfil import GLOBALES, leer_perfil
from spec import cargar, validar
from version import huella_perfil, version_modelo

CONTROL = {"poligonos": "PolygonLabels", "cajas": "RectangleLabels"}
from colores import COLORES
PALETA = list(COLORES.values())
ANIDAR = 1.01          # contencion > 1: la regla de fragmentos nunca dispara dentro del grupo (dentro_de)


def _f(v):
    """Numero -> texto que perfil.py vuelve a leer como el MISMO valor."""
    v = float(v)
    return str(int(v)) if v.is_integer() and abs(v) >= 1 else repr(v)


def _color(c, i):
    col = str(c.get("color") or "").strip()
    if not col:
        return None
    if col.startswith("#") and len(col) in (4, 7):
        return col
    return COLORES.get(col.lower(), PALETA[i % len(PALETA)])


def generar_xml(spec):
    err, _ = validar(spec)
    if err:
        raise ValueError("especificacion invalida:\n  " + "\n  ".join(err))
    clases = spec["clases"]
    anidar = set()
    for c in clases:
        if c.get("dentro_de"):
            anidar.update((c["nombre"], c["dentro_de"]))

    raiz = ET.Element("View")
    ET.SubElement(raiz, "Image", {"name": "image", "value": "$image", "zoom": "true"})
    attrs = {"name": "label", "toName": "image", "strokeWidth": "2", "opacity": "0.4",
             "imgsz": _f(spec.get("imgsz", GLOBALES["imgsz"]))}
    if spec.get("negativos"):
        attrs["negativos"] = ";".join(n.strip() for n in spec["negativos"])
    for k, v in sorted((spec.get("ajustes") or {}).items()):
        attrs[k] = _f(v)
    ctrl = ET.SubElement(raiz, CONTROL[spec.get("tipo", "poligonos")], attrs)

    for i, c in enumerate(clases):
        a = {"value": c["nombre"]}
        col = _color(c, i)
        if col:
            a["background"] = col
        if c.get("prompts"):
            a["prompts"] = ";".join(p.strip() for p in c["prompts"])
        cont = c.get("contencion")
        if cont is None and c["nombre"] in anidar:
            cont = ANIDAR
        for clave, valor in (("conf", c.get("conf")), ("area_min", c.get("area_min")),
                             ("area_max", c.get("area_max")), ("max", c.get("max_por_imagen")),
                             ("contencion", cont)):
            if valor is not None:
                a[clave] = _f(valor)
        if c.get("clic"):
            a["clic"] = c["clic"]
        ET.SubElement(ctrl, "Label", a)

    if (spec.get("motor") or {}).get("interactivo", True):
        kp = ET.SubElement(raiz, "KeyPointLabels", {"name": "clic", "toName": "image", "smart": "true"})
        for c in clases:
            ET.SubElement(kp, "Label", {"value": c["nombre"]})
    ET.indent(raiz, space="  ")
    return ET.tostring(raiz, encoding="unicode")


def verificar(spec):
    """-> (xml, perfil, version). Falla en voz alta si algo de la cadena no cuadra."""
    xml = generar_xml(spec)
    p = leer_perfil(xml)
    reglas.revisar_perfil(p)
    return xml, p, version_modelo(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--salida", default="")
    a = ap.parse_args()
    spec = cargar(a.spec)
    _, avisos = validar(spec)
    for x in avisos:
        print("AVISO:", x)
    xml, p, ver = verificar(spec)
    print(f"clases {len(p['clases'])} | prompts {[x['texto'] for x in p['prompts']]}")
    print(f"perfil {huella_perfil(p)} | version {ver}")
    if a.salida:
        Path(a.salida).write_text(xml + "\n", encoding="utf-8")
        print("XML ->", a.salida)


if __name__ == "__main__":
    main()
