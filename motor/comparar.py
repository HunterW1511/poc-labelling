"""Etapa C.5: compara una spec GENERADA por el asistente con una de REFERENCIA hecha a mano (PURO).
Solo informa: cuenta aciertos en lo que el asistente debe decidir (clases, maximos, importancia, carpetas)
y lista aparte lo que es ajuste EXPERTO (no lo propone el LLM) y lo informativo (prompts, colores).
Uso: python comparar.py generada.json referencia.json"""
import difflib, re, unicodedata

import esquema_llm as E

CORTE = 0.6


def _n(s):
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def _clases(s):
    return {c["nombre"]: c for c in s.get("clases") or [] if isinstance(c, dict) and c.get("nombre")}


def emparejar(gen, ref):
    """{clase_ref: clase_gen o None}: igual normalizado, luego parecido (difflib)."""
    libres, out = {_n(g): g for g in _clases(gen)}, {}
    for r in _clases(ref):
        m = libres.pop(_n(r), None)
        if m is None:
            cand = difflib.get_close_matches(_n(r), list(libres), n=1, cutoff=CORTE)
            m = libres.pop(cand[0]) if cand else None
        out[r] = m
    return out


def _imp(c):
    return (c or {}).get("importancia") or "media"          # plan.py trata None como media


def comparar(gen, ref):
    """-> {"aciertos", "total", "lineas"}"""
    par, cg, cr = emparejar(gen, ref), _clases(gen), _clases(ref)
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
    firmas_g = {(k.get("tipo"), frozenset(k.get("clases") or [])): k.get("nombre")
                for k in gen.get("carpetas") or [] if isinstance(k, dict)}
    for k in ref.get("carpetas") or []:
        f = (k.get("tipo"), frozenset(mapa.get(x, f"?{x}") for x in k.get("clases") or []))
        g = firmas_g.get(f)
        punto(g is not None, f"{k.get('nombre')} ({k.get('tipo')}, {len(k.get('clases') or [])} clases): "
                             + (f"generada como '{g}'" if g else "sin equivalente"))
    for (t, cl), n in firmas_g.items():
        if not any((k.get("tipo"), frozenset(mapa.get(x, f"?{x}") for x in k.get("clases") or [])) == (t, cl)
                   for k in ref.get("carpetas") or []):
            punto(False, f"carpeta '{n}' ({t}) sobra")

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
    import sys
    from spec import cargar
    print("\n".join(comparar(cargar(sys.argv[1]), cargar(sys.argv[2]))["lineas"]))
