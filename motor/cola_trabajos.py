"""P.1: cola persistente de trabajos del hub (solo biblioteca estandar: sqlite3, sin red; solo lo usa el host).
Diseno en docs/cola_trabajos.md. La base vive en el disco local del hub (nunca en Drive); Drive solo transporta.
Uso: con = abrir(ruta); t = crear(con, "preetiquetado", "lote_p3_x.zip", proyecto=3); mover(con, t["id"], "enviado")."""
import sqlite3, time
from pathlib import Path

ESQUEMA = 1
TIPOS = ("asistente", "preetiquetado", "entrenamiento", "precodificacion")
ESTADOS = ("pendiente", "enviado", "en_proceso", "listo", "importado", "error", "archivado")
TRANSICIONES = {
    "pendiente": ("enviado", "error", "archivado"),
    "enviado": ("en_proceso", "listo", "error", "archivado"),
    "en_proceso": ("listo", "error"),
    "listo": ("importado", "archivado"),
    "error": ("pendiente", "archivado"),
    "importado": (),
    "archivado": (),
}
FINALES = tuple(e for e, sig in TRANSICIONES.items() if not sig)
INICIALES = ("pendiente", "enviado")      # asistente se arma directo en Drive: nace enviado
MAX_ERROR = 2000                          # se guarda la cola del mensaje (lo ultimo suele ser lo util)

_DDL = """
CREATE TABLE trabajos (
  id INTEGER PRIMARY KEY, tipo TEXT NOT NULL, proyecto INTEGER, slug TEXT, estado TEXT NOT NULL,
  archivo TEXT NOT NULL, resultado TEXT, creado TEXT NOT NULL, actualizado TEXT NOT NULL,
  intentos INTEGER NOT NULL DEFAULT 0, error TEXT, UNIQUE (tipo, archivo));
CREATE TABLE eventos (
  id INTEGER PRIMARY KEY, trabajo INTEGER NOT NULL REFERENCES trabajos(id), de TEXT, a TEXT NOT NULL,
  fecha TEXT NOT NULL, detalle TEXT);
CREATE INDEX trabajos_estado ON trabajos (estado, tipo);
CREATE INDEX eventos_trabajo ON eventos (trabajo, id);
"""


class Conflicto(ValueError):
    """Otro proceso cambio el estado del trabajo entre la lectura y la escritura."""


def _ahora(ahora=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ahora))


def _nombre(valor, que):
    v = str(valor or "")
    if not v.strip() or "/" in v or "\\" in v or v in (".", ".."):
        raise ValueError(f"{que}={valor!r}: solo un nombre, sin carpeta")
    return v


def _recortar(texto):
    t = str(texto or "").strip()
    return t[-MAX_ERROR:] if t else None


def abrir(ruta, timeout=10.0):
    """Abre (o crea) la base y aplica las migraciones pendientes. -> sqlite3.Connection (filas como dict)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(ruta), timeout=timeout)
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    con.execute("PRAGMA journal_mode = WAL")       # la UI lee mientras un comando de xd.py escribe
    con.execute("PRAGMA foreign_keys = ON")
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    if ver > ESQUEMA:
        con.close()
        raise RuntimeError(f"{ruta}: esquema {ver} mas nuevo que el del codigo ({ESQUEMA}); actualiza el repo")
    if ver < 1:
        with con:
            con.executescript(_DDL)
            con.execute(f"PRAGMA user_version = {ESQUEMA}")
    return con


def _fila(r):
    return dict(r) if r is not None else None


def _evento(con, trabajo, de, a, fecha, detalle=None):
    con.execute("INSERT INTO eventos (trabajo, de, a, fecha, detalle) VALUES (?, ?, ?, ?, ?)",
                (trabajo, de, a, fecha, _recortar(detalle)))


def obtener(con, id):
    return _fila(con.execute("SELECT * FROM trabajos WHERE id = ?", (id,)).fetchone())


def buscar(con, tipo, archivo):
    return _fila(con.execute("SELECT * FROM trabajos WHERE tipo = ? AND archivo = ?", (tipo, archivo)).fetchone())


def listar(con, tipo=None, estado=None, proyecto=None, slug=None, activos=False):
    """Filtros opcionales; estado puede ser un texto o una tupla. activos=True excluye los finales."""
    where, args = [], []
    for col, v in (("tipo", tipo), ("proyecto", proyecto), ("slug", slug)):
        if v is not None:
            where.append(f"{col} = ?")
            args.append(v)
    if estado is not None:
        est = (estado,) if isinstance(estado, str) else tuple(estado)
        where.append(f"estado IN ({','.join('?' * len(est))})")
        args += est
    if activos:
        where.append(f"estado NOT IN ({','.join('?' * len(FINALES))})")
        args += FINALES
    sql = "SELECT * FROM trabajos" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
    return [dict(r) for r in con.execute(sql, args)]


def eventos(con, id):
    return [dict(r) for r in con.execute("SELECT * FROM eventos WHERE trabajo = ? ORDER BY id", (id,))]


def crear(con, tipo, archivo, proyecto=None, slug=None, estado="pendiente", detalle=None, ahora=None):
    """Registra un trabajo. Idempotente por (tipo, archivo): si ya existe lo devuelve sin tocarlo.
    -> (trabajo, nuevo)"""
    if tipo not in TIPOS:
        raise ValueError(f"tipo={tipo!r}: debe ser uno de {TIPOS}")
    if estado not in INICIALES:
        raise ValueError(f"estado inicial {estado!r}: debe ser uno de {INICIALES}")
    archivo = _nombre(archivo, "archivo")
    if proyecto is not None:
        proyecto = int(proyecto)
    f = _ahora(ahora)
    with con:
        cur = con.execute("INSERT OR IGNORE INTO trabajos (tipo, proyecto, slug, estado, archivo, creado, actualizado)"
                          " VALUES (?, ?, ?, ?, ?, ?, ?)", (tipo, proyecto, slug, estado, archivo, f, f))
        if cur.rowcount == 0:
            return buscar(con, tipo, archivo), False
        _evento(con, cur.lastrowid, None, estado, f, detalle)
    return obtener(con, cur.lastrowid), True


def mover(con, id, a, desde=None, resultado=None, detalle=None, ahora=None):
    """Transicion validada. desde = estado que el llamador espera (Conflicto si ya no es ese).
    a='error' guarda detalle en error; a='pendiente' (reintento) suma un intento y limpia el error."""
    if a not in ESTADOS:
        raise ValueError(f"estado {a!r} desconocido: {ESTADOS}")
    t = obtener(con, id)
    if t is None:
        raise KeyError(f"no existe el trabajo {id}")
    actual = t["estado"]
    if desde is not None and actual != desde:
        raise Conflicto(f"trabajo {id}: se esperaba {desde!r} y esta en {actual!r}")
    if a not in TRANSICIONES[actual]:
        raise ValueError(f"trabajo {id}: transicion {actual} -> {a} no permitida "
                         f"(desde {actual}: {TRANSICIONES[actual] or 'ninguna, es final'})")
    if resultado is not None:
        resultado = _nombre(resultado, "resultado")
    f = _ahora(ahora)
    error = _recortar(detalle) if a == "error" else (None if a == "pendiente" else t["error"])
    with con:
        cur = con.execute("UPDATE trabajos SET estado = ?, actualizado = ?, error = ?, resultado = COALESCE(?, resultado),"
                          " intentos = intentos + ? WHERE id = ? AND estado = ?",
                          (a, f, error, resultado, 1 if a == "pendiente" else 0, id, actual))
        if cur.rowcount == 0:
            raise Conflicto(f"trabajo {id}: otro proceso lo movio desde {actual!r}")
        _evento(con, id, actual, a, f, detalle)
    return obtener(con, id)


def fallo(con, id, detalle, ahora=None):
    """Fallo del lado del hub (por ejemplo al importar): el estado NO cambia; suma un intento y guarda el error."""
    t = obtener(con, id)
    if t is None:
        raise KeyError(f"no existe el trabajo {id}")
    f = _ahora(ahora)
    with con:
        cur = con.execute("UPDATE trabajos SET actualizado = ?, error = ?, intentos = intentos + 1"
                          " WHERE id = ? AND estado = ?", (f, _recortar(detalle), id, t["estado"]))
        if cur.rowcount == 0:
            raise Conflicto(f"trabajo {id}: otro proceso lo movio desde {t['estado']!r}")
        _evento(con, id, t["estado"], t["estado"], f, f"fallo: {detalle}")
    return obtener(con, id)
