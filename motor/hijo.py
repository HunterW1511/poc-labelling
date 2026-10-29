"""D.6: fusion modelo hijo (clase + caja) + SAM 3 por caja (poligono). Funciones PURAS (numpy, sin disco).
dets   : [{"clase", "conf", "caja": [x1, y1, x2, y2] en pixeles}]   (salida del YOLO hijo)
masks  : lista alineada con dets: bool HxW o None (SAM 3 con prompt de caja)
limites: {clase: {"max", "area_min", "area_max"}}  (por CLASE, sin fusion de prompts)"""
from collections import Counter

import numpy as np

OPCIONES = {"margen": 0.10, "min_dentro": 0.5, "min_relleno": 0.15, "usar_area": False}


def _caja_px(caja, h, w, margen=0.0):
    x1, y1, x2, y2 = caja
    mx, my = (x2 - x1) * margen, (y2 - y1) * margen
    return (max(0, int(np.floor(x1 - mx))), max(0, int(np.floor(y1 - my))),
            min(w, int(np.ceil(x2 + mx))), min(h, int(np.ceil(y2 + my))))


def caja_a_mascara(caja, h, w, margen=0.0):
    m = np.zeros((h, w), dtype=bool)
    x1, y1, x2, y2 = _caja_px(caja, h, w, margen)
    m[y1:y2, x1:x2] = True
    return m


def elegir_mascara(mask, caja, h, w, op=OPCIONES):
    """-> (mascara, fuente). Usa la de SAM 3 si es razonable para la caja; si no, la caja."""
    caja_m = caja_a_mascara(caja, h, w)
    if mask is None or mask.shape != (h, w) or not mask.any():
        return caja_m, "caja"
    ampliada = caja_a_mascara(caja, h, w, op["margen"])
    dentro = np.logical_and(mask, ampliada).sum() / mask.sum()
    recortada = np.logical_and(mask, ampliada)
    relleno = recortada.sum() / max(1, caja_m.sum())
    if dentro < op["min_dentro"] or relleno < op["min_relleno"]:
        return caja_m, "caja"
    return recortada, "sam"


def fusionar(dets, masks, limites, h, w, op=OPCIONES):
    """-> (instancias [{"clases": [c], "conf", "mask", "fuente"}], descartes Counter)."""
    if len(masks) != len(dets):
        raise ValueError(f"{len(dets)} detecciones pero {len(masks)} mascaras")
    desc, por_clase, out = Counter(), Counter(), []
    orden = sorted(range(len(dets)), key=lambda i: -dets[i]["conf"])
    for i in orden:
        d = dets[i]
        lim = limites.get(d["clase"])
        if lim is None:
            desc["clase_desconocida"] += 1
            continue
        m, fuente = elegir_mascara(masks[i], d["caja"], h, w, op)
        area = m.sum() / (h * w)
        if op.get("usar_area") and ((lim.get("area_min") and area < lim["area_min"]) or (lim.get("area_max") and area > lim["area_max"])):
            desc["area"] += 1
            continue
        if lim.get("max") and por_clase[d["clase"]] >= lim["max"]:
            desc["maximo"] += 1
            continue
        por_clase[d["clase"]] += 1
        desc[f"fuente_{fuente}"] += 0              # deja constancia de la clave aunque sea 0
        out.append({"clases": [d["clase"]], "conf": float(d["conf"]), "mask": m, "fuente": fuente})
    desc.update(Counter(f"fuente_{x['fuente']}" for x in out))
    return out, desc

def validar_clases(names, clases):
    """El hijo solo puede predecir clases que existan en el proyecto (si cambiaron las clases, reentrenar)."""
    nombres = set(names.values() if isinstance(names, dict) else names)
    extra = sorted(nombres - set(clases))
    if extra:
        raise ValueError(f"El modelo hijo tiene clases que no existen en el proyecto: {extra}")


def inferir_hijo(yolo, sam, ruta, perfil, limites, conf=0.25, imgsz=960, op=OPCIONES):
    """yolo = YOLO(best.pt); sam = SAM3Predictor (prompt de cajas). -> (result_ls, score, info)."""
    import cv2
    import pipeline
    r = yolo.predict(ruta, imgsz=imgsz, conf=conf, verbose=False)[0]
    h, w = r.orig_shape
    names = r.names
    dets = [{"clase": names[int(c)], "conf": float(s), "caja": [float(v) for v in b]}
            for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())]
    info = {"w": w, "h": h, "crudas": len(dets), "finales": 0, "descartes": {}, "sam_mascaras": 0}
    masks = [None] * len(dets)
    if dets:
        sam.set_image(ruta)
        rs = sam(bboxes=[d["caja"] for d in dets])
        rs = rs[0] if isinstance(rs, list) else rs
        if rs.masks is not None:
            mm = rs.masks.data.cpu().numpy() > 0.5
            if mm.shape[1:] != (h, w):
                mm = np.stack([cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
                               for m in mm])
            info["sam_mascaras"] = len(mm)
            if len(mm) == len(dets):                 # si no cuadra, todas caen a caja (queda en info)
                masks = list(mm)
    inst, desc = fusionar(dets, masks, limites, h, w, op)
    res, confs = [], []
    for i in inst:
        poly = pipeline.poligono(i["mask"], perfil["simplificar"])
        if poly:
            res.append(pipeline.a_ls({"clases": i["clases"], "conf": i["conf"], "poligono": poly}, perfil, w, h))
            confs.append(i["conf"])
    info.update(finales=len(res), descartes=dict(desc))
    return res, (sum(confs) / len(confs) if confs else 0.0), info
