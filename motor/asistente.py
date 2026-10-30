"""Etapa C.3: descripcion (texto) -> spec validada, con un LLM inyectado. PURO: el LLM es una funcion
llm(mensajes, esquema) -> (texto, info); sin red ni disco. Corre en el host (tests) y en Colab (trabajo).
Cadena: mensajes -> LLM -> JSON -> normalizar -> completar -> validar + exigencias -> reparar (max INTENTOS).
Uso de prueba: python asistente.py descripcion.txt [--modelo qwen2.5:3b] [--url http://127.0.0.1:11434]"""
import difflib, json, re, unicodedata

import esquema_llm as E
import spec
from colores import COLORES

INTENTOS = 3
CORTE_VOCABULARIO = 0.75        # similitud minima (difflib) para corregir un nombre con el vocabulario


def _ident(s):
    """Texto -> identificador ASCII: sin acentos, espacios y simbolos a '_', letra inicial."""
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9_]+", "_", t.strip()).strip("_")
    return t if t[:1].isalpha() else "C_" + t


def normalizar(p):
    """Arreglos DETERMINISTAS (no gastan un intento del LLM). -> (parcial, correcciones)."""
    cor = []
    if not isinstance(p, dict):
        return p, cor
    clases = [c for c in p.get("clases") or [] if isinstance(c, dict)]
    carpetas = [k for k in p.get("carpetas") or [] if isinstance(k, dict)]
    mapa = {}
    for c in clases:
        if isinstance(c.get("nombre"), str) and c["nombre"].strip():
            n = _ident(c["nombre"])
            if n != c["nombre"]:
                cor.append(f"nombre de clase '{c['nombre']}' -> '{n}'")
                mapa[c["nombre"]] = n
                c["nombre"] = n
        if isinstance(c.get("prompts"), list):
            c["prompts"] = [x.strip() for x in c["prompts"] if isinstance(x, str) and x.strip()]
    for k in carpetas:
        if isinstance(k.get("nombre"), str) and k["nombre"].strip():
            n = _ident(k["nombre"])
            if n != k["nombre"]:
                cor.append(f"nombre de carpeta '{k['nombre']}' -> '{n}'")
                k["nombre"] = n
        if isinstance(k.get("clases"), list):
            k["clases"] = [mapa.get(x) or _ident(x) if isinstance(x, str) else x for x in k["clases"]]
        if k.get("tipo") == "mezcla" and isinstance(k.get("clases"), list) and len(set(k["clases"])) == 1:
            cor.append(f"carpeta '{k.get('nombre')}' tiene una sola clase: mezcla -> pieza")
            k["tipo"] = "pieza"
    pr = p.get("proyecto")
    if isinstance(pr, dict) and isinstance(pr.get("slug"), str) and pr["slug"].strip():
        s = _ident(pr["slug"]).lower()
        if s != pr["slug"]:
            cor.append(f"slug '{pr['slug']}' -> '{s}'")
            pr["slug"] = s
    usados = set()
    for c in clases:                                   # colores repetidos -> el siguiente libre
        col = c.get("color")
        if col and col in usados:
            libre = next((x for x in COLORES if x not in usados), None)
            if libre:
                cor.append(f"color repetido '{col}' en {c.get('nombre')} -> '{libre}'")
                c["color"] = libre
        if c.get("color"):
            usados.add(c["color"])
    if carpetas and not any(k.get("tipo") == "negativo" for k in carpetas):
        nombres = {k.get("nombre") for k in carpetas}
        n = next(x for x in ["Fondo"] + [f"Fondo_{i}" for i in range(2, 99)] if x not in nombres)
        p["carpetas"].append({"nombre": n, "tipo": "negativo", "clases": [], "descripcion": "Fondo sin objetos"})
        cor.append(f"carpeta negativo '{n}' agregada (ayuda a evitar falsos positivos)")
    return p, cor


def aplicar_vocabulario(p, vocabulario):
    """Nombres de clase parecidos a un termino del vocabulario -> el termino (DETERMINISTA, difflib).
    Renombra tambien las referencias y las carpetas con el mismo nombre. -> (parcial, correcciones)."""
    cor, voc = [], {_ident(v).lower(): _ident(v) for v in vocabulario or () if str(v).strip()}
    if not voc or not isinstance(p, dict):
        return p, cor
    mapa = {}
    for c in p.get("clases") or []:
        n = c.get("nombre") if isinstance(c, dict) else None
        if not isinstance(n, str):
            continue
        m = difflib.get_close_matches(n.lower(), list(voc), n=1, cutoff=CORTE_VOCABULARIO)
        if m and voc[m[0]] != n:
            mapa[n] = voc[m[0]]
            cor.append(f"nombre de clase '{n}' -> '{voc[m[0]]}' (vocabulario)")
            c["nombre"] = voc[m[0]]
    for k in p.get("carpetas") or []:
        if isinstance(k, dict):
            k["nombre"] = mapa.get(k.get("nombre"), k.get("nombre"))
            if isinstance(k.get("clases"), list):
                k["clases"] = [mapa.get(x, x) for x in k["clases"]]
    return p, cor


def exigencias(s):
    """Reglas del asistente mas estrictas que validar() y que solo el LLM puede arreglar."""
    out, usos = [], {}
    clases = [c for c in s.get("clases") or [] if isinstance(c, dict)]
    for c in clases:
        for p in c.get("prompts") or []:
            if isinstance(p, str):
                usos.setdefault(p.split("@")[0].strip().lower(), set()).add(c.get("nombre"))
                if not p.isascii():
                    out.append(f"clase '{c.get('nombre')}': el prompt '{p}' debe estar en ingles y sin acentos")
    for t, ns in usos.items():
        if len(ns) > 1:
            out.append(f"el prompt '{t}' esta repetido en {sorted(map(str, ns))}: cada clase necesita prompts "
                       f"distintos que describan el rasgo visible que la distingue")
    cubiertas = {x for k in s.get("carpetas") or [] if isinstance(k, dict) for x in k.get("clases") or []}
    for c in clases:
        if c.get("nombre") not in cubiertas:
            out.append(f"la clase '{c.get('nombre')}' no aparece en ninguna carpeta")
    return out


def verificar_conteos(s, conteos):
    """Los numeros que el usuario dijo (citados por el LLM) contra lo que tiene la spec. DETERMINISTA."""
    carpetas = [k for k in s.get("carpetas") or [] if isinstance(k, dict)]
    real = {"clases": len(s.get("clases") or []), "carpetas": len(carpetas)}
    for t in ("pieza", "mezcla", "negativo"):
        real[f"carpetas_{t}"] = sum(k.get("tipo") == t for k in carpetas)
    out = []
    for c in conteos or []:
        if not isinstance(c, dict) or c.get("objeto") not in real or not isinstance(c.get("numero"), int):
            continue
        if c["numero"] != real[c["objeto"]]:
            tiene = (s.get("clases") or []) if c["objeto"] == "clases" else \
                [k for k in carpetas if c["objeto"] == "carpetas" or k.get("tipo") == c["objeto"][9:]]
            nombres = [x.get("nombre") for x in tiene if isinstance(x, dict)]
            out.append(f"el usuario dijo '{c.get('cita')}' ({c['numero']} {c['objeto']}) pero la spec tiene "
                       f"{real[c['objeto']]}: {nombres}. Revisa si juntaste dos en una (por ejemplo dos piezas "
                       f"parecidas o del mismo color), te falto alguna o sobra alguna; si tu conteo estaba mal "
                       f"citado, corrige el conteo")
    return out

def filtrar_preguntas(preguntas, s):
    """Quita las preguntas de cantidad sobre clases que ya tienen max_por_imagen. DETERMINISTA.
    -> (preguntas, correcciones)"""
    ya = [str(c.get("nombre")).replace("_", " ").lower() for c in ((s or {}).get("clases") or [])
          if isinstance(c, dict) and c.get("max_por_imagen") is not None and c.get("nombre")]
    out, cor = [], []
    for p in preguntas:
        q = unicodedata.normalize("NFKD", str(p)).encode("ascii", "ignore").decode().lower()
        n = next((x for x in ya if "cuant" in q and x in q), None)
        if n:
            cor.append(f"pregunta quitada (ya hay max_por_imagen de {n}): {p}")
        else:
            out.append(p)
    return out, cor


def mensaje_usuario(texto, respuestas="", vocabulario=(), previa=None):
    partes = ["DESCRIPCION DEL USUARIO:", str(texto).strip()]
    if vocabulario:
        partes += ["", "NOMBRES CORRECTOS (la transcripcion puede escribirlos mal): " + ", ".join(vocabulario)]
    if previa:
        partes += ["", "ESPECIFICACION ANTERIOR (actualizala, no empieces de cero):",
                   json.dumps(previa, ensure_ascii=False)]
    if respuestas:
        partes += ["", "RESPUESTAS DEL USUARIO A TUS PREGUNTAS:", str(respuestas).strip()]
    return "\n".join(partes)


def generar_spec(texto, llm, respuestas="", vocabulario=(), previa=None, intentos=INTENTOS):
    """-> {"ok", "spec", "supuestos", "preguntas", "correcciones", "avisos", "problemas", "intentos", "historial"}"""
    msgs = [{"role": "system", "content": E.instrucciones()},
            {"role": "user", "content": mensaje_usuario(texto, respuestas, vocabulario, previa)}]
    esquema, historial, res = E.esquema_json(), [], None
    for i in range(1, intentos + 1):
        crudo, info = llm(msgs, esquema)
        obj, s, cor, avisos = None, None, [], []
        try:
            obj = json.loads(crudo)
            if not isinstance(obj, dict) or not isinstance(obj.get("spec"), dict):
                obj, problemas = None, ["la respuesta debe ser un objeto con 'spec', 'supuestos' y 'preguntas'"]
        except ValueError as e:
            problemas = [f"la respuesta no es JSON valido ({e})"]
        if obj is not None:
            parcial, cor = normalizar(obj["spec"])
            parcial, cor_voc = aplicar_vocabulario(parcial, vocabulario)
            cor += cor_voc
            s = E.completar(parcial)
            errores, avisos = spec.validar(s)
            problemas = errores + exigencias(s) + verificar_conteos(s, obj.get("conteos"))
        historial.append({"intento": i, "problemas": problemas, "info": info})
        preg, quitadas = filtrar_preguntas(list((obj or {}).get("preguntas") or []), s)
        cor += quitadas
        res = {"ok": not problemas, "spec": s, "supuestos": list((obj or {}).get("supuestos") or []),
               "preguntas": preg, "conteos": list((obj or {}).get("conteos") or []), "correcciones": cor, "avisos": avisos,
               "problemas": problemas, "intentos": i, "historial": historial}
        if not problemas:
            break
        msgs += [{"role": "assistant", "content": crudo},
                 {"role": "user", "content": "Tu respuesta tiene estos problemas:\n- " + "\n- ".join(problemas)
                  + "\nCorrigelos y responde de nuevo el JSON completo."}]
    return res


def resumen(r):
    """Texto legible del resultado (lo usan el CLI del host y el notebook)."""
    l = [f"{'OK' if r['ok'] else 'CON PROBLEMAS'} en {r['intentos']} intento(s)"]
    for h in r["historial"]:
        l.append(f"  intento {h['intento']}: {len(h['problemas'])} problemas | {h.get('info') or ''}")
    s = r["spec"] or {}
    for c in s.get("clases") or []:
        l.append(f"  clase {c.get('nombre')}: {c.get('prompts')} max={c.get('max_por_imagen')} "
                 f"imp={c.get('importancia')} color={c.get('color')}")
    for k in s.get("carpetas") or []:
        l.append(f"  carpeta {k.get('nombre')} ({k.get('tipo')}): {k.get('clases')}")
    for titulo, campo in (("SUPUESTOS", "supuestos"), ("PREGUNTAS", "preguntas"), ("CORRECCIONES", "correcciones"),
                          ("AVISOS", "avisos"), ("PROBLEMAS", "problemas")):
        if r[campo]:
            l.append(titulo + ":")
            l += [f"  - {x}" for x in r[campo]]
    return "\n".join(l)


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    import llm_ollama
    ap = argparse.ArgumentParser()
    ap.add_argument("texto")
    ap.add_argument("--modelo", default="qwen2.5:14b")
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    a = ap.parse_args()
    r = generar_spec(Path(a.texto).read_text(encoding="utf-8"), llm_ollama.cliente(a.modelo, a.url))
    print(resumen(r))
    print(json.dumps(r["spec"], indent=1, ensure_ascii=False))
