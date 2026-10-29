"""Especificacion de proyecto (B.2): describe el caso FISICO; el generador (B.3) la traduce al XML.
validar(spec) -> (errores, avisos). PURO: sin red ni Label Studio.
Uso: python /app/spec.py <spec.json>   (codigo de salida 1 si hay errores)"""
import json, re, sys
from pathlib import Path

from perfil import GLOBALES

ESQUEMA = 1
NOMBRE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
CARPETA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PROMPT = re.compile(r"^[^@;]+(@(0(\.\d+)?|1(\.0+)?))?$")      # "texto" o "texto@0.20"
CLAVES = {
    "raiz": {"esquema", "proyecto", "tipo", "imgsz", "negativos", "ajustes", "clases", "carpetas",
             "imagenes", "motor"},
    "proyecto": {"titulo", "slug", "descripcion"},
    "clase": {"nombre", "prompts", "descripcion", "color", "max_por_imagen", "area_min", "area_max", "conf",
              "clic", "importancia", "dentro_de", "contencion"},
    "carpeta": {"nombre", "tipo", "clases", "descripcion"},
    "imagenes": {"raiz"},
    "motor": {"url", "interactivo"}}
TIPOS, TIPOS_CARPETA = {"poligonos", "cajas"}, {"pieza", "mezcla", "negativo"}
CLIC, IMPORTANCIA = {None, "", "grande", "chico"}, {None, "alta", "media", "baja"}
AJUSTES = set(GLOBALES) - {"imgsz"}


def cargar(ruta):
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _extra(d, permitidas, donde, err):
    if not isinstance(d, dict):
        err.append(f"{donde}: debe ser un objeto")
        return
    for k in sorted(set(d) - permitidas):
        err.append(f"{donde}: clave desconocida '{k}' (permitidas: {', '.join(sorted(permitidas))})")


def _num(v, donde, campo, err, lo=0.0, hi=1.0):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        err.append(f"{donde}.{campo}={v!r}: debe ser un numero entre {lo} y {hi}")
        return None
    return float(v)


def _base(p):
    return p.split("@")[0].strip()


def validar(spec):
    err, av = [], []
    if not isinstance(spec, dict):
        return ["la especificacion debe ser un objeto JSON"], av
    _extra(spec, CLAVES["raiz"], "raiz", err)
    if spec.get("esquema") != ESQUEMA:
        err.append(f"esquema={spec.get('esquema')!r}: se espera {ESQUEMA}")

    pr = spec.get("proyecto") or {}
    _extra(pr, CLAVES["proyecto"], "proyecto", err)
    if isinstance(pr, dict):
        if not str(pr.get("titulo") or "").strip():
            err.append("proyecto.titulo vacio")
        if not SLUG.match(str(pr.get("slug") or "")):
            err.append(f"proyecto.slug={pr.get('slug')!r}: solo minusculas, digitos, _ o -")
    if spec.get("tipo", "poligonos") not in TIPOS:
        err.append(f"tipo={spec.get('tipo')!r}: debe ser {sorted(TIPOS)}")
    imgsz = spec.get("imgsz", GLOBALES["imgsz"])
    if isinstance(imgsz, bool) or not isinstance(imgsz, int) or not 256 <= imgsz <= 2048:
        err.append(f"imgsz={imgsz!r}: entero entre 256 y 2048")

    aj = spec.get("ajustes") or {}
    if isinstance(aj, dict):
        for k, v in aj.items():
            if k not in AJUSTES:
                err.append(f"ajustes: clave desconocida '{k}' (permitidas: {', '.join(sorted(AJUSTES))})")
            else:
                _num(v, "ajustes", k, err, 0.0, 2.0)
    else:
        err.append("ajustes: debe ser un objeto")

    negs = spec.get("negativos") or []
    if not isinstance(negs, list) or any(not isinstance(n, str) or not n.strip() or "@" in n or ";" in n for n in negs):
        err.append("negativos: lista de textos sin '@' ni ';' (su confianza va en ajustes.conf_negativo)")

    # ------------------------------------------------------------- clases
    clases = spec.get("clases") or []
    if not isinstance(clases, list) or not clases:
        err.append("clases: se necesita al menos una")
        clases = []
    clases = [c for c in clases if isinstance(c, dict)] if clases else []
    nombres = [c.get("nombre") for c in clases]
    for n in sorted({str(n) for n in nombres if nombres.count(n) > 1}):
        err.append(f"clases: nombre duplicado '{n}'")
    por_nombre = {c.get("nombre"): c for c in clases}
    grupos = {}                                            # prompt base -> [nombres de clase]
    for i, c in enumerate(clases):
        n = c.get("nombre")
        donde = f"clases[{n or i}]"
        _extra(c, CLAVES["clase"], donde, err)
        if not NOMBRE.match(str(n or "")):
            err.append(f"{donde}.nombre: letra inicial y luego letras, digitos o _")
        ps = c.get("prompts") or []
        if not isinstance(ps, list):
            err.append(f"{donde}.prompts: debe ser una lista")
            ps = []
        for p in ps:
            if not isinstance(p, str) or not PROMPT.match(p.strip()):
                err.append(f"{donde}: prompt invalido {p!r} ('texto' o 'texto@0.20', sin ';')")
            else:
                if not p.isascii():
                    av.append(f"{donde}: prompt '{p}' no es ASCII; SAM 3 entiende ingles")
                grupos.setdefault(_base(p), []).append(n)
        if not ps:
            av.append(f"{donde}: sin prompts -> solo etiquetado manual")
        amin = _num(c.get("area_min"), donde, "area_min", err)
        amax = _num(c.get("area_max"), donde, "area_max", err)
        if amin is not None and amax is not None and amin >= amax:
            err.append(f"{donde}: area_min ({amin}) debe ser menor que area_max ({amax})")
        mx = c.get("max_por_imagen")
        if mx is not None and (isinstance(mx, bool) or not isinstance(mx, int) or mx < 1):
            err.append(f"{donde}.max_por_imagen={mx!r}: entero >= 1")
        _num(c.get("conf"), donde, "conf", err)
        _num(c.get("contencion"), donde, "contencion", err, 0.0, 2.0)
        if c.get("clic") not in CLIC:
            err.append(f"{donde}.clic={c.get('clic')!r}: 'grande', 'chico' o vacio")
        if c.get("importancia") not in IMPORTANCIA:
            err.append(f"{donde}.importancia={c.get('importancia')!r}: 'alta', 'media' o 'baja'")

    for c in clases:                                       # dentro_de
        n, d = c.get("nombre"), c.get("dentro_de")
        if d is None:
            continue
        if d not in por_nombre or d == n:
            err.append(f"clases[{n}].dentro_de={d!r}: debe ser otra clase existente")
            continue
        visto, x = set(), n
        while x is not None:
            if x in visto:
                err.append(f"clases[{n}].dentro_de forma un ciclo")
                break
            visto.add(x)
            x = (por_nombre.get(x) or {}).get("dentro_de")
        if not any(n in g and d in g for g in grupos.values()):
            av.append(f"clases[{n}].dentro_de: no comparte prompt con '{d}', no tiene efecto")

    for t, g in grupos.items():                            # fusion de prompts compartidos
        if len(set(g)) < 2:
            continue
        for campo in ("area_min", "area_max", "conf", "contencion", "max_por_imagen"):
            vals = {repr((por_nombre.get(x) or {}).get(campo)) for x in set(g)}
            if len(vals) > 1:
                av.append(f"prompt '{t}' compartido por {sorted(set(g))}: {campo} distinto {sorted(vals)}; "
                          f"perfil.py fusiona y usa el valor mas permisivo")

    # ------------------------------------------------------------- carpetas
    carpetas = spec.get("carpetas") or []
    if not isinstance(carpetas, list) or not carpetas:
        err.append("carpetas: se necesita al menos una")
        carpetas = []
    carpetas = [k for k in carpetas if isinstance(k, dict)]
    nc = [k.get("nombre") for k in carpetas]
    for n in sorted({str(n) for n in nc if nc.count(n) > 1}):
        err.append(f"carpetas: nombre duplicado '{n}'")
    cubiertas = set()
    for i, k in enumerate(carpetas):
        donde = f"carpetas[{k.get('nombre') or i}]"
        _extra(k, CLAVES["carpeta"], donde, err)
        if not CARPETA.match(str(k.get("nombre") or "")):
            err.append(f"{donde}.nombre: letras, digitos, _ o -")
        tipo, cl = k.get("tipo"), k.get("clases") or []
        if tipo not in TIPOS_CARPETA:
            err.append(f"{donde}.tipo={tipo!r}: debe ser {sorted(TIPOS_CARPETA)}")
        for x in cl:
            if x not in por_nombre:
                err.append(f"{donde}: clase inexistente '{x}'")
        cubiertas.update(cl)
        if tipo == "negativo" and cl:
            err.append(f"{donde}: una carpeta negativo no lleva clases")
        if tipo in ("pieza", "mezcla") and not cl:
            err.append(f"{donde}: una carpeta {tipo} necesita clases")
        if tipo == "pieza" and len(cl) > 1:
            av.append(f"{donde}: tipo pieza con varias clases; quiza es 'mezcla'")
    if carpetas and not any(k.get("tipo") == "negativo" for k in carpetas):
        av.append("carpetas: no hay carpeta 'negativo' (fondo sin piezas); ayuda a evitar falsos positivos")
    for n in nombres:
        if n not in cubiertas:
            av.append(f"clases[{n}]: no aparece en ninguna carpeta")

    im = spec.get("imagenes") or {}
    _extra(im, CLAVES["imagenes"], "imagenes", err)
    raiz = str((im or {}).get("raiz") or "")
    if raiz and (raiz.startswith(("/", "\\")) or ".." in raiz.replace("\\", "/").split("/")):
        err.append(f"imagenes.raiz={raiz!r}: ruta relativa a /label-studio/files, sin '..'")
    mo = spec.get("motor") or {}
    _extra(mo, CLAVES["motor"], "motor", err)
    if isinstance(mo, dict):
        if mo.get("url") is not None and not str(mo["url"]).startswith(("http://", "https://")):
            err.append(f"motor.url={mo['url']!r}: debe empezar con http:// o https://")
        if mo.get("interactivo") is not None and not isinstance(mo["interactivo"], bool):
            err.append("motor.interactivo: true o false")
    return list(dict.fromkeys(err)), list(dict.fromkeys(av))


if __name__ == "__main__":
    e, a = validar(cargar(sys.argv[1]))
    for x in e:
        print("ERROR:", x)
    for x in a:
        print("AVISO:", x)
    print(f"{len(e)} errores, {len(a)} avisos")
    sys.exit(1 if e else 0)

