"""Reglas de post-proceso (2.4). Funciones PURAS: sin SAM 3, sin Label Studio, sin disco.
Entrada : detecciones crudas [{"mask": bool HxW, "prompt": str, "conf": float}] (incluye negativos) + perfil.
Salida  : (instancias, descartes: Counter, conflictos: int)."""
from collections import Counter

import numpy as np

GLOBALES = ("iou_duplicado", "contencion", "cobertura_negativo", "conf_negativo", "negativos")
POR_PROMPT = ("texto", "clases", "conf", "area_min", "area_max", "max_por_imagen", "contencion")


def negativos(perfil):
    """{texto: conf}. Acepta lista de dicts {"texto", "conf"}, lista de str o str separado por ';'."""
    n = perfil["negativos"] or []
    if isinstance(n, str):
        n = n.split(";")
    out = {}
    for x in n:
        if isinstance(x, dict):
            if "texto" not in x:
                raise KeyError(f"negativo sin 'texto': {x}")
            t, c = x["texto"], x.get("conf")
        else:
            t, c = x, None
        t = str(t).strip()
        if t:
            out[t] = float(c if c is not None else perfil["conf_negativo"])
    return out


def revisar_perfil(perfil):
    """Falla en voz alta si el perfil usa otros nombres de clave (evita defaults silenciosos)."""
    faltan = [k for k in GLOBALES if k not in perfil]
    for p in perfil["prompts"]:
        faltan += [f"{p.get('texto')}.{k}" for k in POR_PROMPT if k not in p]
    if faltan:
        raise KeyError("perfil sin claves: " + ", ".join(faltan))
    negativos(perfil)


def _iou(a, b):
    u = np.logical_or(a, b).sum()
    return np.logical_and(a, b).sum() / u if u else 0.0


def _contenida(a, b):
    """Fraccion de a que cae dentro de b."""
    return np.logical_and(a, b).sum() / max(1, a.sum())


def _candidatos(detecciones, perfil, desc):
    """Separa negativos (union de mascaras) y filtra positivos por confianza y area."""
    por_texto = {p["texto"]: p for p in perfil["prompts"]}
    negs = negativos(perfil)
    cands, sombra = [], None
    for d in detecciones:
        m = d["mask"]
        if d["prompt"] in negs:
            if d["conf"] >= negs[d["prompt"]]:
                sombra = m.copy() if sombra is None else (sombra | m)
            continue
        p = por_texto.get(d["prompt"])
        if p is None:
            continue
        if d["conf"] < p["conf"]:
            desc["conf"] += 1
            continue
        area = m.sum() / m.size
        if not p["area_min"] <= area <= p["area_max"]:
            desc["area"] += 1
            continue
        cont = p["contencion"] if p["contencion"] is not None else perfil["contencion"]
        cands.append({"mask": m, "prompt": d["prompt"], "conf": float(d["conf"]), "area": float(area),
                      "clases": list(p["clases"]), "max": p["max_por_imagen"], "cont": cont,
                      "alternativas": []})
    return cands, sombra


def _sin_sombras(cands, sombra, cobertura, desc):
    if sombra is None or not sombra.any():
        return cands
    out = []
    for c in cands:
        if _contenida(c["mask"], sombra) > cobertura:
            desc["sombra"] += 1
        else:
            out.append(c)
    return out


def _sin_duplicados(cands, iou_dup, desc):
    """Gana la de mayor confianza. Duplicado = IoU alto; fragmento = mismas clases y contenido > cont."""
    kept, conflictos = [], 0
    for c in sorted(cands, key=lambda d: -d["conf"]):
        dup = next((k for k in kept if _iou(c["mask"], k["mask"]) > iou_dup), None)
        if dup is not None:
            if set(dup["clases"]) != set(c["clases"]):
                conflictos += 1
                dup["alternativas"].append(c["prompt"])
            desc["duplicado"] += 1
            continue
        if any(set(k["clases"]) == set(c["clases"]) and max(_contenida(c["mask"], k["mask"]), _contenida(k["mask"], c["mask"])) > c["cont"]
               for k in kept):
            desc["fragmento"] += 1
            continue
        kept.append(c)
    return kept, conflictos


def _maximo(cands, desc):
    vistos, out = Counter(), []
    for c in cands:                                   # ya vienen ordenadas por confianza
        g = tuple(sorted(c["clases"]))
        vistos[g] += 1
        if c["max"] and vistos[g] > c["max"]:
            desc["maximo"] += 1
        else:
            out.append(c)
    return out


def aplicar(detecciones, perfil):
    desc = Counter()
    if not detecciones:
        return [], desc, 0
    cands, sombra = _candidatos(detecciones, perfil, desc)
    cands = _sin_sombras(cands, sombra, perfil["cobertura_negativo"], desc)
    cands, conflictos = _sin_duplicados(cands, perfil["iou_duplicado"], desc)
    final = _maximo(cands, desc)
    for c in final:
        c.pop("max"); c.pop("cont")
        c["ambigua"] = len(c["clases"]) > 1
    return final, desc, conflictos

