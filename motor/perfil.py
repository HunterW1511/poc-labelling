"""Perfil de proyecto leido del XML de Label Studio. Generico: nada fijo por caso."""
import xml.etree.ElementTree as ET

CONTROLES = ("PolygonLabels", "RectangleLabels", "BrushLabels")
GLOBALES = {"imgsz": 644, "conf_base": 0.15, "iou_duplicado": 0.6, "contencion": 0.85,
            "simplificar": 0.004, "cobertura_negativo": 0.5, "conf_negativo": 0.3}


def _num(v):
    return float(v) if v not in (None, "") else None


def leer_perfil(label_config):
    root = ET.fromstring(label_config)
    ctrl = next((t for t in root.iter() if t.tag in CONTROLES), None)
    if ctrl is None:
        raise ValueError(f"El XML no tiene ningun control {CONTROLES}")
    a = ctrl.attrib
    g = {k: type(v)(float(a[k])) if a.get(k) else v for k, v in GLOBALES.items()}
    to_name = a["toName"].split(",")[0]
    img = next((t for t in root.iter() if t.attrib.get("name") == to_name), None)

    perfil = {"from_name": a["name"], "to_name": to_name, "tipo": ctrl.tag,
              "campo_imagen": img.attrib["value"].lstrip("$") if img is not None else None,
              **g, "clases": [], "sin_prompt": [], "negativos": []}
    perfil["negativos"] = [{"texto": n.strip(), "conf": g["conf_negativo"]}
                           for n in (a.get("negativos") or "").split(";") if n.strip()]

    prompts = {}
    for lab in ctrl.iter("Label"):
        la, clase = lab.attrib, lab.attrib["value"]
        perfil["clases"].append(clase)
        crudos = [p.strip() for p in (la.get("prompts") or "").split(";") if p.strip()]
        if not crudos:
            perfil["sin_prompt"].append(clase)          # solo etiquetado manual
        for crudo in crudos:
            texto, _, conf_p = (s.strip() for s in crudo.partition("@"))
            p = prompts.setdefault(texto, {"texto": texto, "clases": [], "_conf": [],
                                           "_amin": [], "_amax": [], "_max": [], "_cont": []})
            p["clases"].append(clase)
            p["_conf"].append(_num(conf_p) or _num(la.get("conf")) or g["conf_base"])
            p["_amin"].append(_num(la.get("area_min")) or 0.0)
            p["_amax"].append(_num(la.get("area_max")) or 1.0)
            p["_max"].append(_num(la.get("max")))
            p["_cont"].append(_num(la.get("contencion")) or g["contencion"])

    # Fusion de un prompt compartido por varias clases: siempre la opcion mas permisiva
    perfil["prompts"] = [{
        "texto": p["texto"], "clases": p["clases"],
        "conf": min(p["_conf"]), "area_min": min(p["_amin"]), "area_max": max(p["_amax"]),
        "max_por_imagen": int(sum(p["_max"])) if all(m is not None for m in p["_max"]) else None,
        "contencion": max(p["_cont"]),
    } for p in prompts.values()]
    return perfil

def limites_por_clase(label_config):
    """{clase: {"max", "area_min", "area_max"}} leidos por CLASE (sin la fusion de prompts de leer_perfil)."""
    root = ET.fromstring(label_config)
    ctrl = next((t for t in root.iter() if t.tag in CONTROLES), None)
    if ctrl is None:
        raise ValueError(f"El XML no tiene ningun control {CONTROLES}")
    out = {}
    for lab in ctrl.iter("Label"):
        la = lab.attrib
        mx = _num(la.get("max"))
        out[la["value"]] = {"max": int(mx) if mx else None, "area_min": _num(la.get("area_min")),
                            "area_max": _num(la.get("area_max"))}
    return out
