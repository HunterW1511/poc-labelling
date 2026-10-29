"""D.1: muestra estratificada por carpeta. PURO (solo biblioteca estandar): corre en el host y en el motor.
La carpeta sale de la ruta de la tarea: /data/local-files/?d=mis_imagenes/<carpeta>/x.jpg"""
import hashlib
from pathlib import PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse

SIN_RUTA = "(sin ruta)"
RAIZ = "(raiz)"


def carpeta_de(valor):
    """Directorio padre inmediato de la imagen."""
    if not valor:
        return SIN_RUTA
    u = urlparse(str(valor))
    q = parse_qs(u.query).get("d")
    ruta = q[0] if q else unquote(u.path)
    return PurePosixPath(ruta).parent.name or RAIZ


def _orden(tid, semilla):
    return hashlib.sha1(f"{semilla}:{tid}".encode()).hexdigest()


def repartir(tamanos, n, minimo=1):
    """{carpeta: tamano} -> {carpeta: cupo}. Suma = min(n, total). Cada carpeta recibe al menos
    min(minimo, tamano) mientras alcance n (primero las mas grandes); el resto, proporcional al tamano."""
    if n < 0 or minimo < 0:
        raise ValueError("n y minimo deben ser >= 0")
    cupo = {c: 0 for c in tamanos}
    restante = min(n, sum(tamanos.values()))
    for c in sorted(tamanos, key=lambda c: (-tamanos[c], c)):
        k = min(minimo, tamanos[c], restante)
        cupo[c] = k
        restante -= k
    while restante:
        c = min((c for c in tamanos if cupo[c] < tamanos[c]),
                key=lambda c: (cupo[c] / tamanos[c], -tamanos[c], c))
        cupo[c] += 1
        restante -= 1
    return cupo


def muestra_estratificada(tareas, n, campo="image", semilla=0, minimo=1, prioridad=None):
    """tareas: [{"id", "data": {campo: ruta}}] -> ids elegidos (ordenados). Determinista por semilla.`r`n    prioridad: ids que entran primero dentro del cupo de su carpeta (no cambia los cupos)."""
    grupos = {}
    for t in tareas:
        grupos.setdefault(carpeta_de((t.get("data") or {}).get(campo)), []).append(t["id"])
    cupo = repartir({c: len(v) for c, v in grupos.items()}, n, minimo)
    prio = set(prioridad or ())
    ids = []
    for c, v in grupos.items():
        ids += sorted(v, key=lambda i: (i not in prio, _orden(i, semilla)))[:cupo[c]]
    return sorted(ids)
