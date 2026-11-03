"""Etapa C.5 + L.5: compara una spec GENERADA por el asistente con una de REFERENCIA hecha a mano (PURO).
Solo informa: cuenta aciertos en lo que el asistente debe decidir (clases, maximos, importancia, carpetas)
y lista aparte lo que es ajuste EXPERTO (no lo propone el LLM) y lo informativo (prompts, colores).
Sinonimos: los declara quien compara (nada fijo por caso): "Pelo=Cabello,Ojo=Ojos".
Uso: python comparar.py generada.json referencia.json [--sinonimos "A=B,C=D"]"""
import difflib, re, unicodedata

import esquema_llm as E

CORTE = 0.6


def _n(s):
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]", "", t)
    return t[:-1] if len(t) > 3 and t.endswith("s") else t        # plural simple: Tazas = Taza


def _clases(s):
    return {c["nombre"]: c for c in s.get("clases") or [] if isinstance(c, dict) and c.get("nombre")}


def _grupos(sinonimos):
    """'Pelo=Cabello,Ojo=Ojos' o [['Pelo', 'Cabello']] -> {nombre normalizado: grupo}."""
    if isinstance(sinonimos, str):
        sinonimos = [g.split("=") for g in sinonimos.split(",") if g.strip()]
    out = {}
    for i, g in enumerate(sinonimos or ()):
        for x in g:
            if str(x).strip():
                out[_n(x)] = i
    return out


def emparejar(gen, ref, sinonimos=()):
    """{clase_ref: clase_gen o None}: igual normalizado, sinonimo declarado y luego parecido (difflib)."""
    libres, out, grp = {_n(g): g for g in _clases(gen)}, {}, _grupos(sinonimos)
    for r in _clases(ref):
        nr = _n(r)
        m = libres.pop(nr, None)
        if m is None and nr in grp:
            k = next((x for x in libres if grp.get(x) == grp[nr]), None)
            m = libres.pop(k) if k else None
        if m is None:
            cand = difflib.get_close_matches(nr, list(libres), n=1, cutoff=CORTE)
            m = libres.pop(cand[0]) if cand else None
        out[r] = m
    return out


def _imp(c):
    return (c or {}).get("importancia") or "media"          # plan.py trata None como media


def comparar(gen, ref, sinonimos=()):
    """-> {"aciertos", "total", "lineas"}"""
    par, cg, cr = emparejar(gen, ref, sinonimos), _clases(gen), _clases(ref)
    ok, tot, l = 0, 0, []

    def punto(bien, txt):
        nonlocal ok, tot
        tot += 1
        ok += bool(bien)
        l.append(f"  [{'OK' if bien else '--'}] {txt}")

    l.append("CLASES")
    for r, g in par.items():
        punto(g is not None, f"{r}: " + (f"generada como '{g}'" if g else "FALTA en la generada"))
        if g is None:
            continue
        a, b = cr[r].get("max_por_imagen"), cg[g].get("max_por_imagen")
        punto(a == b, f"{r}.max_por_imagen: referencia {a} | generada {b}")
        punto(_imp(cr[r]) == _imp(cg[g]), f"{r}.importancia: referencia {_imp(cr[r])} | generada {_imp(cg[g])}")
    for g in sorted(set(cg) - {x for x in par.values() if x}):
        punto(False, f"'{g}' sobra (no esta en la referencia)")

    l.append("CARPETAS (por tipo y clases)")
    mapa = {r: g for r, g in par.items() if g}
    gens = [k for k in gen.get("carpetas") or [] if isinstance(k, dict)]
    usadas = set()
    for k in ref.get("carpetas") or []:
        if not isinstance(k, dict):
            continue
        quiero = {mapa.get(x, f"?{x}") for x in k.get("clases") or []}
        mejor, puntaje = None, 0.0
        for i, kg in enumerate(gens):                  # mismo tipo y la mayor coincidencia de clases
            if i in usadas or kg.get("tipo") != k.get("tipo"):
                continue
            tiene = set(kg.get("clases") or [])
            p = len(quiero & tiene) / len(quiero | tiene) if quiero | tiene else 1.0
            p += 0.01 * (_n(kg.get("nombre")) == _n(k.get("nombre")))          # desempate por nombre
            if p > puntaje:
                mejor, puntaje = i, p
        desc = f"{k.get('nombre')} ({k.get('tipo')}, {len(quiero)} clases)"
        if mejor is None:
            punto(False, f"{desc}: sin equivalente")
            continue
        usadas.add(mejor)
        kg = gens[mejor]
        tiene = set(kg.get("clases") or [])
        if tiene == quiero:
            punto(True, f"{desc}: generada como '{kg.get('nombre')}'")
        else:
            punto(False, f"{desc}: generada como '{kg.get('nombre')}' con otras clases | "
                         f"faltan {sorted(quiero - tiene)} | sobran {sorted(tiene - quiero)}")
    for i, kg in enumerate(gens):
        if i not in usadas:
            punto(False, f"carpeta '{kg.get('nombre')}' ({kg.get('tipo')}) sobra")

    l.append("INFORMATIVO (no cuenta)")
    for r, g in par.items():
        if g:
            l.append(f"  {r}: prompts ref {cr[r].get('prompts')} | gen {cg[g].get('prompts')}")
    l.append(f"  negativos: ref {ref.get('negativos') or []} | gen {gen.get('negativos') or []}")
    grupos = {}
    for c in cr.values():
        for p in c.get("prompts") or []:
            grupos.setdefault(p.split("@")[0].strip(), []).append(c["nombre"])
    for p, ns in grupos.items():
        if len(ns) > 1:
            l.append(f"  la referencia comparte '{p}' entre {ns}; el asistente exige prompts distintos (esperado)")
    expertos = sorted({f"{n}.{k}" for n, c in cr.items() for k in c if k in E.EXPERTO["clase"]} |
                      {k for k in ref if k in E.EXPERTO["raiz"]})
    if expertos:
        l.append(f"  ajuste EXPERTO de la referencia (a mano despues): {', '.join(expertos)}")
    l.insert(0, f"ACIERTOS {ok}/{tot} ({ok / max(1, tot):.0%})")
    return {"aciertos": ok, "total": tot, "lineas": l}


if __name__ == "__main__":
    import argparse
    from spec import cargar
    ap = argparse.ArgumentParser()
    ap.add_argument("generada")
    ap.add_argument("referencia")
    ap.add_argument("--sinonimos", default="", help='"Pelo=Cabello,Ojo=Ojos"')
    a = ap.parse_args()
    print("\n".join(comparar(cargar(a.generada), cargar(a.referencia), a.sinonimos)["lineas"]))