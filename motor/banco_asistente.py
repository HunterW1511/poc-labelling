"""L.6: banco fijo de casos para comparar LLMs del asistente (texto fijo, sin STT). PURO, biblioteca estandar.
Cada caso trae una trampa: adjetivos que no son clase, un estado no pedido, unidades que hay que escalar.
evaluar(resultado_de_generar_spec, caso) -> lista de fallos (vacia = pasa). Lo corre Colab (L.6.2)."""
import unicodedata

CASOS = [
    {"id": "tazas", "trampa": "colores no son clases; cada taza trae su cuchara (escalar)",
     "texto": "Quiero contar tazas y cucharas en la mesa de la oficina. En una foto puede haber hasta cuatro "
              "tazas y cada taza trae su cuchara. Hay tazas blancas y negras, pero para mi todas son taza, no me "
              "importa el color. Voy a tomar fotos de solo tazas, solo cucharas, las dos juntas y la mesa vacia.",
     "clases": {"Taza": 4, "Cuchara": (4, "o_pregunta")}},   # 'su cuchara' = 1 por taza: 4, o null si lo pregunta
    {"id": "botellas", "trampa": "'sin tapa' es un estado no pedido: no es clase",
     "texto": "Necesito detectar botellas de plastico transparente en una banda transportadora. En cada foto pasan "
              "como maximo seis botellas. A veces una botella viene sin tapa, pero eso no me importa, solo quiero "
              "contarlas.",
     "clases": {"Botella": 6}},
    {"id": "cajas", "trampa": "2 tarimas x 8 cajas = 16; una etiqueta por caja = 16; la tarima no es clase",
     "texto": "Quiero contar cajas de carton y sus etiquetas en un almacen. En cada foto salen hasta dos tarimas y "
              "cada tarima lleva ocho cajas; cada caja tiene una etiqueta blanca pegada. La tarima no me interesa "
              "detectarla.",
     "clases": {"Caja": 16, "Etiqueta": 16}},
]


def _norm(s):
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip("_ ")
    return t[:-1] if t.endswith("s") else t                  # Tazas -> taza


def evaluar(r, caso):
    f = []
    if not r.get("ok"):
        f.append(f"no valido tras {r.get('intentos')} intentos: {(r.get('problemas') or [])[:2]}")
    clases = [c for c in ((r.get("spec") or {}).get("clases") or []) if isinstance(c, dict)]
    hay = {_norm(c.get("nombre")): c for c in clases}
    esp = {_norm(k): (k, mx) for k, mx in caso["clases"].items()}
    preg = [unicodedata.normalize("NFKD", str(p)).encode("ascii", "ignore").decode().lower()
            for p in r.get("preguntas") or []]
    for nk, (k, mx) in esp.items():
        mx, tolera = mx if isinstance(mx, tuple) else (mx, None)
        c = hay.get(nk)
        if c is None:
            f.append(f"falta la clase {k}")
        elif mx is not None and c.get("max_por_imagen") != mx:
            pregunto = any("cuant" in q and nk in q for q in preg)
            if not (tolera and c.get("max_por_imagen") is None and pregunto):
                f.append(f"{k}: max_por_imagen={c.get('max_por_imagen')} (esperado {mx}"
                         + (" o null preguntando" if tolera else "") + ")")
    for p in r.get("preguntas") or []:                       # preguntar lo que ya se dijo resta credibilidad
        q = unicodedata.normalize("NFKD", str(p)).encode("ascii", "ignore").decode().lower()
        if "cuant" in q:
            for nk, c in hay.items():
                if c.get("max_por_imagen") is not None and nk and nk in q:
                    f.append(f"pregunta redundante (ya tiene max_por_imagen={c.get('max_por_imagen')}): {p}")
                    break
    sobran = [c.get("nombre") for nk, c in hay.items() if nk not in esp]
    if sobran:
        f.append(f"clases que el usuario no pidio: {sobran}")
    return f


if __name__ == "__main__":                                   # autoprueba del evaluador (sin LLM)
    bien = {"ok": True, "spec": {"clases": [{"nombre": "Tazas", "max_por_imagen": 4},
                                            {"nombre": "Cuchara", "max_por_imagen": 4}]}}
    mal = {"ok": True, "spec": {"clases": [{"nombre": "Taza", "max_por_imagen": 1},
                                           {"nombre": "Taza_Negra", "max_por_imagen": 4}]}}
    assert evaluar(bien, CASOS[0]) == [], evaluar(bien, CASOS[0])
    assert len(evaluar(mal, CASOS[0])) == 3, evaluar(mal, CASOS[0])
    print("banco OK:", len(CASOS), "casos |", evaluar(mal, CASOS[0]))
