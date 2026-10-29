"""Pipeline semantico PURO (sin Label Studio, sin red, sin disco salvo la imagen).
Lo usan la cola local (CPU) y el lote en Colab (GPU): mismo codigo = mismo resultado."""
import uuid

import cv2
import numpy as np

import reglas


def textos(perfil):
    t = [p["texto"] for p in perfil["prompts"]]
    return t + [n for n in sorted(reglas.negativos(perfil)) if n not in t]


def conf_minima(perfil):
    return min([p["conf"] for p in perfil["prompts"]] + list(reglas.negativos(perfil).values()) + [1.0])


def nombre(names, idx, tx):
    if isinstance(names, dict):
        return names.get(idx, tx[idx] if idx < len(tx) else str(idx))
    return names[idx] if idx < len(names) else (tx[idx] if idx < len(tx) else str(idx))


def poligono(m, eps_rel):
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    p = cv2.approxPolyDP(c, eps_rel * cv2.arcLength(c, True), True).reshape(-1, 2)
    return p.tolist() if len(p) >= 3 else None


def a_ls(inst, perfil, w, h):
    base = {"id": uuid.uuid4().hex[:10], "from_name": perfil["from_name"], "to_name": perfil["to_name"],
            "original_width": w, "original_height": h, "image_rotation": 0, "score": inst["conf"]}
    clase = inst["clases"][0]                         # ambiguedad: pendiente (clasificador posterior)
    if perfil["tipo"] == "PolygonLabels":
        return {**base, "type": "polygonlabels", "value": {
            "points": [[x / w * 100, y / h * 100] for x, y in inst["poligono"]],
            "closed": True, "polygonlabels": [clase]}}
    xs, ys = [p[0] for p in inst["poligono"]], [p[1] for p in inst["poligono"]]   # caja derivada
    return {**base, "type": "rectanglelabels", "value": {
        "x": min(xs) / w * 100, "y": min(ys) / h * 100, "width": (max(xs) - min(xs)) / w * 100,
        "height": (max(ys) - min(ys)) / h * 100, "rotation": 0, "rectanglelabels": [clase]}}


def inferir(pred, ruta, perfil):
    """pred = SAM3SemanticPredictor ya creado (CPU o GPU). -> (result_ls, score, info)."""
    reglas.revisar_perfil(perfil)
    tx = textos(perfil)
    pred.args.conf = conf_minima(perfil)
    pred.set_image(ruta)
    r = pred(text=tx)
    r = r[0] if isinstance(r, list) else r
    h, w = r.orig_shape
    info = {"w": w, "h": h, "crudas": 0, "finales": 0, "descartes": {}, "conflictos": 0}
    if r.masks is None or r.boxes is None or len(r.boxes) == 0:
        return [], 0.0, info
    masks = r.masks.data.cpu().numpy() > 0.5
    if masks.shape[1:] != (h, w):
        masks = np.stack([cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
                          for m in masks])
    det = [{"mask": m, "prompt": nombre(r.names, c, tx), "conf": float(s)}
           for m, c, s in zip(masks, r.boxes.cls.int().tolist(), r.boxes.conf.tolist())]
    inst, desc, confl = reglas.aplicar(det, perfil)
    res, confs = [], []
    for i in inst:
        poly = poligono(i["mask"], perfil["simplificar"])
        if poly:
            res.append(a_ls({"clases": i["clases"], "conf": i["conf"], "poligono": poly}, perfil, w, h))
            confs.append(i["conf"])
    info.update(crudas=len(det), finales=len(res), descartes=dict(desc), conflictos=confl)
    return res, (sum(confs) / len(confs) if confs else 0.0), info
