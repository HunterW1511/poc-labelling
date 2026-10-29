"""Etapa C.2: lo que el LLM sabe de la spec, DERIVADO de spec.py. PURO, solo biblioteca estandar
(corre en el host y viaja en el trabajo de Colab). Nada fijo por caso.
  esquema_json()  -> JSON schema para el parametro 'format' de Ollama
  instrucciones() -> prompt de sistema (campos + reglas + ejemplo)
  completar(p)    -> spec completa a partir de la parte que propone el LLM
Uso: python esquema_llm.py   (imprime las instrucciones y su tamano aproximado)"""
import copy, json

import spec
from colores import COLORES
from perfil import GLOBALES

_IMP = sorted(x for x in spec.IMPORTANCIA if x)
# Cada clave de spec.CLAVES esta en exactamente un grupo (lo verifica test_esquema_llm.py):
#   LLM: la propone el LLM | FIJO: la pone completar() | EXPERTO: ajuste fino a mano, el LLM no la toca
LLM = {
    "raiz": {
        "proyecto": "objeto con titulo, slug y descripcion",
        "tipo": f"forma de la etiqueta: {' o '.join(sorted(spec.TIPOS))}",
        "negativos": "lista de textos en ingles de cosas visibles que NO son objetos y se confunden con ellos "
                     "(ej. shadow); puede ir vacia",
        "clases": "lista de clases a detectar",
        "carpetas": "lista de carpetas de fotos"},
    "proyecto": {
        "titulo": "titulo corto en espanol",
        "slug": f"identificador del proyecto, regex {spec.SLUG.pattern}",
        "descripcion": "una frase que resume el caso"},
    "clase": {
        "nombre": f"identificador, regex {spec.NOMBRE.pattern}",
        "prompts": "1 a 3 frases nominales cortas en ingles que describen la apariencia del objeto",
        "descripcion": "lo que dijo el usuario de esta clase, en una frase",
        "color": f"color para la interfaz, uno de: {', '.join(COLORES)}",
        "max_por_imagen": "entero >= 1 si el usuario dijo cuantos caben como maximo en una foto; si no, null",
        "importancia": f"{' o '.join(_IMP)} si el usuario la recalco; si no, null"},
    "carpeta": {
        "nombre": f"identificador, regex {spec.CARPETA.pattern}",
        "tipo": f"{', '.join(sorted(spec.TIPOS_CARPETA))}",
        "clases": "nombres de las clases que aparecen en sus fotos ([] si es negativo)",
        "descripcion": "que fotos van en la carpeta"},
}
FIJO = {"esquema": spec.ESQUEMA, "imagenes": {"raiz": "mis_imagenes"},
        "motor": {"url": "http://motor:9090", "interactivo": True}}
EXPERTO = {"raiz": {"imgsz", "ajustes"},
           "clase": {"area_min", "area_max", "conf", "clic", "dentro_de", "contencion"}}
ORDEN = ("esquema", "proyecto", "tipo", "negativos", "clases", "carpetas", "imagenes", "motor")

REGLAS = [
    "Usa solo lo que dijo el usuario. Todo valor que decidas tu sin que lo haya dicho va tambien en "
    "'supuestos', una frase cada uno.",
    "La transcripcion viene de reconocimiento de voz: puede tener errores y muletillas. Interpreta la intencion.",
    "Una clase por cada tipo de objeto que el usuario quiere detectar o contar. Conserva los nombres que dijo, "
    "sin acentos ni espacios (usa _). Si se dan NOMBRES CORRECTOS, usalos tal cual en vez de la transcripcion.",
    "Los prompts describen la APARIENCIA visible SIEMPRE en ingles, nunca en espanol (color, material, forma, "
    "tamano). Usa nombres comunes (apple, box) pero nunca marcas ni nombres propios: el detector no los conoce.",
    "Nunca repitas el mismo texto de prompt en dos clases: dos clases con el mismo prompt se confunden. "
    "Si dos clases se parecen, usa el rasgo visible que las distingue.",
    "Un estado o defecto de un objeto (roto, abierto, vacio) solo es clase aparte si el usuario lo pidio. "
    "Si no queda claro, pregunta.",
    "max_por_imagen: el numero que dijo el usuario de cuantos objetos de esa clase puede haber en una foto o en "
    "el conjunto (ej. 'lleva 10 tornillos' -> 10). Si no dijo ningun numero para esa clase: null y pregunta. "
    "No inventes 1.",
    "importancia: 'alta' solo para lo que el usuario recalca como critico, pequeno o dificil de ver; "
    "'baja' si dice que importa poco; en cualquier otro caso null.",
    "Cada clase con un color distinto; si el usuario menciono el color del objeto, usa ese.",
    "carpetas: sigue la organizacion de fotos que describio el usuario. 'pieza' = fotos de una sola clase; "
    "'mezcla' = varias clases juntas; 'negativo' = fondo sin objetos, con clases []. "
    "Cada clase debe aparecer en alguna carpeta.",
    "Si el usuario no menciono fotos de fondo vacio, agrega una carpeta 'negativo' llamada Fondo y anotalo "
    "como supuesto.",
    "conteos: anota cada numero de clases o de carpetas que el usuario dijo explicitamente, con la cita "
    "textual; el sistema verifica que tu spec tenga esa cantidad. Si enumera carpetas por tipo ('7 individuales, "
    "una de ensamble y una de fondo'), anota cada tipo por separado (carpetas_pieza, carpetas_mezcla, "
    "carpetas_negativo). Si dice que dos objetos son piezas distintas, son dos clases aunque se parezcan o "
    "compartan color. Lista vacia si no dijo numeros.",
    f"Si dos clases distintas pueden ocupar casi la misma zona de la imagen (traslape mayor a "
    f"{GLOBALES['iou_duplicado']:.0%}), el sistema se queda solo con una: anotalo en supuestos.",
    "tipo 'poligonos' salvo que el usuario pida rectangulos o cajas.",
    "supuestos y preguntas en espanol. preguntas: maximo 5, concretas, sobre lo que falta para fotografiar "
    "y etiquetar; junta en una sola las preguntas que se repiten para varias clases; lista vacia si no falta nada.",
]

EJEMPLO_TEXTO = ("Quiero contar dos frutas, manzanas y platanos, sobre una mesa de madera. A veces hay hasta cinco "
                 "manzanas. Los platanos chicos son dificiles de ver. Voy a hacer 4 carpetas: una por cada fruta, "
                 "otra con las dos juntas y otra de la mesa vacia.")
EJEMPLO = {
    "spec": {
        "proyecto": {"titulo": "Conteo de frutas", "slug": "frutas",
                     "descripcion": "Manzanas y platanos sobre una mesa de madera"},
        "tipo": "poligonos", "negativos": [],
        "clases": [
            {"nombre": "Manzana", "prompts": ["red apple", "round red fruit"],
             "descripcion": "Manzana sobre la mesa", "color": "rojo", "max_por_imagen": 5, "importancia": None},
            {"nombre": "Platano", "prompts": ["yellow banana", "curved yellow fruit"],
             "descripcion": "Platano sobre la mesa; los chicos son dificiles de ver", "color": "amarillo",
             "max_por_imagen": None, "importancia": "alta"}],
        "carpetas": [
            {"nombre": "Manzana", "tipo": "pieza", "clases": ["Manzana"], "descripcion": "Solo manzanas"},
            {"nombre": "Platano", "tipo": "pieza", "clases": ["Platano"], "descripcion": "Solo platanos"},
            {"nombre": "Mezcla", "tipo": "mezcla", "clases": ["Manzana", "Platano"],
             "descripcion": "Las dos frutas juntas"},
            {"nombre": "Fondo", "tipo": "negativo", "clases": [], "descripcion": "Mesa sin frutas"}]},
    "conteos": [{"objeto": "clases", "numero": 2, "cita": "dos frutas"},
                {"objeto": "carpetas", "numero": 4, "cita": "4 carpetas"},
                {"objeto": "carpetas_pieza", "numero": 2, "cita": "una por cada fruta"}],
    "supuestos": ["Colores rojo y amarillo: el usuario no dijo colores para la interfaz",
                  "Prompts de manzana roja: el usuario no dijo el color de las manzanas"],
    "preguntas": ["Cuantos platanos puede haber como maximo en una foto?",
                  "Las manzanas pueden ser verdes ademas de rojas?"]}


def fijas(sec):
    """Claves FIJO de una seccion de spec.CLAVES."""
    return set(FIJO) if sec == "raiz" else set(FIJO.get(sec) or {})


def _p(sec, k, **kw):
    return {"description": LLM[sec][k], **kw}


NULO = {"type": "null"}
# conteos que el LLM puede citar y el sistema verifica (asistente.verificar_conteos)
CONTEOS = ("clases", "carpetas", "carpetas_pieza", "carpetas_mezcla", "carpetas_negativo")


def esquema_json():
    txt, lista = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
    proyecto = {"type": "object", "properties": {k: _p("proyecto", k, **txt) for k in LLM["proyecto"]},
                "required": sorted(LLM["proyecto"])}
    clase = {"type": "object", "required": ["nombre", "prompts", "descripcion", "max_por_imagen", "importancia"],
             "properties": {
        "nombre": _p("clase", "nombre", **txt),
        "prompts": _p("clase", "prompts", type="array", items=txt, minItems=1, maxItems=3),
        "descripcion": _p("clase", "descripcion", **txt),
        "color": _p("clase", "color", type="string", enum=list(COLORES)),
        "max_por_imagen": _p("clase", "max_por_imagen", anyOf=[{"type": "integer", "minimum": 1}, NULO]),
        "importancia": _p("clase", "importancia", anyOf=[{"type": "string", "enum": _IMP}, NULO])}}
    carpeta = {"type": "object", "required": ["nombre", "tipo", "clases"], "properties": {
        "nombre": _p("carpeta", "nombre", **txt),
        "tipo": _p("carpeta", "tipo", type="string", enum=sorted(spec.TIPOS_CARPETA)),
        "clases": _p("carpeta", "clases", **lista),
        "descripcion": _p("carpeta", "descripcion", **txt)}}
    raiz = {"type": "object", "required": sorted(LLM["raiz"]), "properties": {
        "proyecto": _p("raiz", "proyecto", **proyecto),
        "tipo": _p("raiz", "tipo", type="string", enum=sorted(spec.TIPOS)),
        "negativos": _p("raiz", "negativos", **lista),
        "clases": _p("raiz", "clases", type="array", items=clase, minItems=1),
        "carpetas": _p("raiz", "carpetas", type="array", items=carpeta, minItems=1)}}
    conteo = {"type": "object", "required": ["objeto", "numero", "cita"], "properties": {
        "objeto": {"type": "string", "enum": list(CONTEOS)}, "numero": {"type": "integer", "minimum": 0},
        "cita": {"type": "string"}}}
    return {"type": "object", "required": ["spec", "conteos", "supuestos", "preguntas"],
            "properties": {"spec": raiz, "conteos": {"type": "array", "items": conteo},
                           "supuestos": lista, "preguntas": lista}}


def instrucciones():
    l = ["Convierte la descripcion hablada de un caso de vision artificial en una especificacion JSON "
         "para pre-etiquetar fotos. Responde solo con el JSON.", "", "CAMPOS:"]
    for sec in ("raiz", "proyecto", "clase", "carpeta"):
        l += [f"- {sec}.{k}: {d}" for k, d in LLM[sec].items()]
    l += [f"- conteos: lista de {{objeto, numero, cita}}; objeto es uno de: {', '.join(CONTEOS)}"]
    l += ["", "REGLAS:"] + [f"{i}. {r}" for i, r in enumerate(REGLAS, 1)]
    l += ["", "EJEMPLO", "Usuario: " + EJEMPLO_TEXTO, "Respuesta: " + json.dumps(EJEMPLO, ensure_ascii=False)]
    return "\n".join(l)


def _limpio(d):
    return {k: v for k, v in d.items() if v is not None and v != ""}


def completar(parcial):
    """Parte del LLM -> spec completa: limpia nulos, agrega FIJO (que el LLM no puede pisar) y ordena."""
    p = _limpio(copy.deepcopy(parcial or {}))
    for sec in ("clases", "carpetas"):
        if isinstance(p.get(sec), list):
            p[sec] = [_limpio(x) if isinstance(x, dict) else x for x in p[sec]]
    out = {**p, **copy.deepcopy(FIJO)}
    return {**{k: out[k] for k in ORDEN if k in out}, **{k: v for k, v in out.items() if k not in ORDEN}}


if __name__ == "__main__":
    t = instrucciones()
    print(t)
    print(f"\n~{len(t) // 4} tokens de instrucciones | esquema {len(json.dumps(esquema_json())) // 4} tokens")
