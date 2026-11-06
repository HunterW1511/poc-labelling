"""P.1: cola persistente de trabajos del hub (solo biblioteca estandar: sqlite3, sin red; solo lo usa el host).
Diseno en docs/cola_trabajos.md. La base vive en el disco local del hub (nunca en Drive); Drive solo transporta.
Uso: con = abrir(ruta); t = crear(con, "preetiquetado", "lote_p3_x.zip", proyecto=3); mover(con, t["id"], "enviado")."""
import re, sqlite3, time
from pathlib import Path

ESQUEMA = 4          # 1: P.1 | 2: P.2.7b (operador, envio, tabla envios) | 3: P.4.3 (grupo) | 4: P.4.R1 (envios.version)
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
# P.2.7b: un envio agrupa trabajos que viajan juntos a un worker remoto (Kaggle); el operador es quien lo lanza (D2)
_DDL_2 = """
ALTER TABLE trabajos ADD COLUMN operador TEXT;
ALTER TABLE trabajos ADD COLUMN envio TEXT;
CREATE TABLE envios (
  id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, proveedor TEXT NOT NULL, operador TEXT, estado TEXT NOT NULL,
  creado TEXT NOT NULL, actualizado TEXT NOT NULL, detalle TEXT);
CREATE INDEX trabajos_envio ON trabajos (envio);
"""
# P.4.R6: parcial = predicciones e indices traidos, falta bajar la cache (.pt); sigue pendiente hasta traido
ESTADOS_ENVIO = ("lanzado", "corriendo", "terminado", "fallido", "parcial", "traido")
# P.4.3: campo grupo (varios trabajos de un mismo lote original, por ejemplo lote_p13_..._t01 y _t02)
_DDL_3 = """
ALTER TABLE trabajos ADD COLUMN grupo TEXT;
"""
# P.4.R1: version del kernel de Kaggle de cada envio (status y output se piden por version: el kernel es uno solo)
_DDL_4 = """
ALTER TABLE envios ADD COLUMN version INTEGER;
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
            con.execute("PRAGMA user_version = 1")
        ver = 1
    if ver < 2:                                    # migracion 1 -> 2: conserva todos los trabajos
        with con:
            con.executescript(_DDL_2)
            con.execute("PRAGMA user_version = 2")
        ver = 2
    if ver < 3:                                    # migracion 2 -> 3: agrega campo grupo
        with con:
            con.executescript(_DDL_3)
            con.execute("PRAGMA user_version = 3")
        ver = 3
    if ver < 4:                                    # migracion 3 -> 4: version del kernel por envio
        with con:
            con.executescript(_DDL_4)
            con.execute("PRAGMA user_version = 4")
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


def crear(con, tipo, archivo, proyecto=None, slug=None, estado="pendiente", grupo=None, detalle=None, ahora=None):
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
        cur = con.execute("INSERT OR IGNORE INTO trabajos (tipo, proyecto, slug, estado, archivo, grupo, creado, actualizado)"
                          " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (tipo, proyecto, slug, estado, archivo, grupo, f, f))
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
                          " intentos = intentos + ?, envio = CASE WHEN ? THEN NULL ELSE envio END"
                          " WHERE id = ? AND estado = ?",
                          (a, f, error, resultado, 1 if a == "pendiente" else 0, a == "pendiente", id, actual))
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


# --- Envios (P.2.7b): trabajos que viajan juntos a un worker remoto
def por_enviar(con):
    """Trabajos en 'enviado' que aun no van en ningun envio (en Kaggle: el zip esta en el espejo local)."""
    return [dict(r) for r in con.execute("SELECT * FROM trabajos WHERE estado = 'enviado' AND envio IS NULL ORDER BY id")]


def crear_envio(con, nombre, proveedor, operador, ids, ahora=None, version=None):
    """Registra el envio y le asigna los trabajos (solo si siguen en 'enviado' sin envio). -> envio (dict)."""
    nombre = _nombre(nombre, "envio")
    f = _ahora(ahora)
    with con:
        con.execute("INSERT INTO envios (nombre, proveedor, operador, estado, creado, actualizado, version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (nombre, proveedor, operador, "lanzado", f, f, version))
        for i in ids:
            cur = con.execute("UPDATE trabajos SET envio = ?, operador = ?, actualizado = ? "
                              "WHERE id = ? AND estado = 'enviado' AND envio IS NULL", (nombre, operador, f, i))
            if cur.rowcount == 0:
                raise Conflicto(f"trabajo {i}: ya no esta en 'enviado' sin envio")
            _evento(con, i, "enviado", "enviado", f, f"en envio {nombre} ({proveedor}, {operador})")
    return envio(con, nombre)


def envio(con, nombre):
    return _fila(con.execute("SELECT * FROM envios WHERE nombre = ?", (nombre,)).fetchone())


def ultimo_envio(con, proveedor=None):
    sql = "SELECT * FROM envios" + (" WHERE proveedor = ?" if proveedor else "") + " ORDER BY id DESC LIMIT 1"
    return _fila(con.execute(sql, (proveedor,) if proveedor else ()).fetchone())


def envios_pendientes(con, proveedor):
    """Envios aun no traidos (del mas viejo al mas nuevo): los que hay que consultar o traer."""
    return [dict(r) for r in con.execute("SELECT * FROM envios WHERE proveedor = ? AND estado != 'traido' ORDER BY id",
                                         (proveedor,))]


def trabajos_de(con, nombre):
    return [dict(r) for r in con.execute("SELECT * FROM trabajos WHERE envio = ? ORDER BY id", (nombre,))]


def marcar_envio(con, nombre, estado, detalle=None, ahora=None):
    """Cambia el estado del envio; 'corriendo' pasa sus trabajos de enviado a en_proceso. -> envio."""
    if estado not in ESTADOS_ENVIO:
        raise ValueError(f"estado de envio {estado!r}: {ESTADOS_ENVIO}")
    f = _ahora(ahora)
    with con:
        cur = con.execute("UPDATE envios SET estado = ?, actualizado = ?, detalle = COALESCE(?, detalle) WHERE nombre = ?",
                          (estado, f, _recortar(detalle), nombre))
        if cur.rowcount == 0:
            raise KeyError(f"no existe el envio {nombre}")
    if estado == "corriendo":
        for t in trabajos_de(con, nombre):
            if t["estado"] == "enviado":
                mover(con, t["id"], "en_proceso", desde="enviado", detalle=f"el worker corre el envio {nombre}", ahora=ahora)
    return envio(con, nombre)


def sin_salida(con, nombre, detalle, ahora=None):
    """Tras traer un envio terminado: sus trabajos que siguen sin resultado pasan a error (asi se pueden reintentar)."""
    hechos = []
    for t in trabajos_de(con, nombre):
        if t["estado"] in ("enviado", "en_proceso"):
            hechos.append(mover(con, t["id"], "error", detalle=detalle, ahora=ahora))
    return hechos


# --- Reconciliacion (P.1.3): lo UNICO que mira archivos del transporte. Puro: recibe nombres, no lee disco. ---
ASIST_ZIP = re.compile(r"^asist_(.+)_(\d{8}-\d{6})\.zip$")
LOTE_ZIP = re.compile(r"^lote_p(\d+)_.+\.zip$")
LOTE_PRED = re.compile(r"^(lote_p(\d+)_.+)_pred\.json$")
DATASET_ZIP = re.compile(r"^dataset_p(\d+)_.+\.zip$")
CARPETA = {"asistente": "asistente", "preetiquetado": "lotes", "entrenamiento": "datasets", "precodificacion": "lotes"}
PRE_ZIP = re.compile(r"^pre_p(\d+)_.+\.zip$")


def _stem(archivo):
    return archivo[:-4] if archivo.endswith(".zip") else archivo


def detectar(tipo, archivo, a):
    """Que dicen los archivos de un trabajo. a = {carpeta: {nombre: mtime} | set | None (no disponible)}.
    -> (estado, resultado) con estado en listo|importado|error|archivado|enviado|desaparecido, o None si no se sabe."""
    s = _stem(archivo)
    dr = a.get(CARPETA.get(tipo, ""))
    if dr is None:
        return None
    archivados = a.get(f"{CARPETA[tipo]}_archivo") or ()
    if tipo == "asistente":
        res, err = f"{s}_resultado.json", f"{s}_error.txt"
        if res in dr:
            m = ASIST_ZIP.match(archivo)
            spec = (a.get("specs") or {}).get(m.group(1)) if m else None
            aplicada = spec is not None and isinstance(dr, dict) and spec >= dr[res]   # regla vieja del tablero
            return ("importado" if aplicada else "listo"), res
        if err in dr:
            return "error", err
    elif tipo == "preetiquetado":
        pred = f"{s}_pred.json"
        if pred in dr:
            return ("importado" if pred in (a.get("lotes_local") or ()) else "listo"), pred
        if f"{s}_error.txt" in dr:                                      # P.2.4: el worker deja error para todos
            return "error", f"{s}_error.txt"
    elif tipo == "precodificacion":                                  # P.3.3: importado lo marca cache-importar
        res = f"{s}_cache.json"
        if res in dr:
            return "listo", res
        if f"{s}_error.txt" in dr:
            return "error", f"{s}_error.txt"
    elif tipo == "entrenamiento":
        runs = a.get("runs")
        if runs is None:
            return None
        hechos = sorted(r for r in runs if r == s or r.startswith(s + "_"))      # el cuaderno usa stem[_formato]
        if hechos:
            reg = a.get("registrados") or ()
            return ("importado" if any(f"runs/{r}" in reg for r in hechos) else "listo"), hechos[-1]
        if f"{s}_error.txt" in dr:
            return "error", f"{s}_error.txt"
    else:
        return None
    if archivo in archivados:
        return "archivado", None
    return ("enviado" if archivo in dr else "desaparecido"), None


def _edad_horas(fecha, ahora):
    try:
        return ((time.time() if ahora is None else ahora) - time.mktime(time.strptime(fecha, "%Y-%m-%dT%H:%M:%S"))) / 3600
    except (TypeError, ValueError):
        return 0.0


def _candidatos(a):
    """Trabajos que se ven en el transporte -> {(tipo, archivo): (proyecto, slug)}."""
    out = {}
    for n in a.get("asistente") or ():
        m = ASIST_ZIP.match(n)
        if m:
            out[("asistente", n)] = (None, m.group(1))
    for n in a.get("lotes") or ():
        m, p, q = LOTE_ZIP.match(n), LOTE_PRED.match(n), PRE_ZIP.match(n)
        if q:
            out[("precodificacion", n)] = (int(q.group(1)), None)
        elif m:
            out[("preetiquetado", n)] = (int(m.group(1)), None)
        elif p:                                                         # _pred.json sin su zip
            out[("preetiquetado", p.group(1) + ".zip")] = (int(p.group(2)), None)
    for n in a.get("datasets") or ():
        m = DATASET_ZIP.match(n)
        if m:
            out[("entrenamiento", n)] = (int(m.group(1)), None)
    return out


def reconciliar(trabajos, a, horas=24, ahora=None):
    """Compara la cola con el transporte. NO escribe. -> {"acciones": [...], "avisos": [...]}
    accion mover:   {"op": "mover", "id", "archivo", "de", "a", "resultado", "error_de"}
    accion adoptar: {"op": "adoptar", "tipo", "archivo", "proyecto", "slug", "estado", "resultado", "error_de"}"""
    acciones, avisos = [], []
    for tipo, c in CARPETA.items():
        if tipo == "precodificacion":
            continue                                                   # comparte carpeta con preetiquetado
        if a.get(c) is None:
            avisos.append(f"{tipo}: no encuentro la carpeta '{c}' del transporte; no se reconcilia")
    for t in trabajos:
        if t["estado"] not in ("enviado", "en_proceso"):
            continue
        d = detectar(t["tipo"], t["archivo"], a)
        if d is None:
            continue
        est, res = d
        base = {"op": "mover", "id": t["id"], "archivo": t["archivo"], "de": t["estado"], "resultado": None, "error_de": None}
        if est in ("listo", "importado"):           # importado lo marca quien importa (P.1.4), no la reconciliacion
            acciones.append({**base, "a": "listo", "resultado": res})
        elif est == "error":
            acciones.append({**base, "a": "error", "error_de": res})
        elif est == "archivado":
            if "archivado" in TRANSICIONES[t["estado"]]:
                acciones.append({**base, "a": "archivado"})
            else:
                avisos.append(f"trabajo {t['id']} ({t['archivo']}): esta en _archivo pero el worker lo tiene en proceso")
        elif est == "desaparecido":
            avisos.append(f"trabajo {t['id']} ({t['archivo']}): el zip ya no esta en el transporte y no hay resultado")
        elif _edad_horas(t["actualizado"], ahora) > horas:
            avisos.append(f"trabajo {t['id']} ({t['archivo']}): lleva {_edad_horas(t['actualizado'], ahora):.0f} h "
                          f"en {t['estado']} (mas de {horas} h)")
    conocidos = {(t["tipo"], t["archivo"]) for t in trabajos}
    ultimo_ds = {}
    for (tipo, archivo), (n, _) in _candidatos(a).items():
        if tipo == "entrenamiento":
            ultimo_ds[n] = max(ultimo_ds.get(n, ""), archivo)
    for (tipo, archivo), (n, slug) in sorted(_candidatos(a).items()):
        if (tipo, archivo) in conocidos:
            continue
        est, res = detectar(tipo, archivo, a) or (None, None)
        if est in (None, "archivado", "desaparecido"):
            continue
        if tipo == "entrenamiento" and est == "enviado" and archivo != ultimo_ds[n]:
            avisos.append(f"{archivo}: dataset viejo sin run; no se adopta (el cuaderno entrena el ultimo)")
            continue
        acciones.append({"op": "adoptar", "tipo": tipo, "archivo": archivo, "proyecto": n, "slug": slug,
                         "estado": est, "resultado": res if est != "error" else None,
                         "error_de": res if est == "error" else None})
    return {"acciones": acciones, "avisos": avisos}


CAMINO = {"enviado": (), "listo": ("listo",), "importado": ("listo", "importado"), "error": ("error",)}


def aplicar(con, acciones, leer_error=lambda nombre: nombre, ahora=None):
    """Ejecuta las acciones de reconciliar(). leer_error(nombre) -> texto del _error.txt.
    Las adopciones entran como enviado y recorren la maquina de estados (queda en eventos). -> (hechas, avisos)"""
    hechas, avisos = 0, []
    for x in acciones:
        try:
            err = leer_error(x["error_de"]) if x.get("error_de") else None
            if x["op"] == "mover":
                mover(con, x["id"], x["a"], desde=x["de"], resultado=x["resultado"], detalle=err, ahora=ahora)
            else:
                t, nuevo = crear(con, x["tipo"], x["archivo"], proyecto=x["proyecto"], slug=x["slug"], estado="enviado",
                                 detalle="adoptado por reconciliacion", ahora=ahora)
                if not nuevo:
                    avisos.append(f"{x['archivo']}: ya estaba registrado; se omite")
                    continue
                for paso in CAMINO[x["estado"]]:
                    mover(con, t["id"], paso, resultado=x["resultado"] if paso == "listo" else None,
                          detalle=err if paso == "error" else "adoptado por reconciliacion", ahora=ahora)
            hechas += 1
        except (Conflicto, ValueError, KeyError) as e:
            avisos.append(f"{x['archivo']}: {e}")
    return hechas, avisos


def proyectar(trabajos, acciones):
    """Aplica EN MEMORIA las acciones de reconciliar(): la vista que tendria la cola tras --aplicar.
    Para lectores de solo lectura (tablero). Los adoptados llevan id None. No escribe."""
    out = {t["id"]: dict(t) for t in trabajos}
    nuevos = []
    for x in acciones:
        if x["op"] == "mover":
            t = out.get(x["id"])
            if t is None:
                continue
            t["estado"] = x["a"]
            if x.get("resultado"):
                t["resultado"] = x["resultado"]
            if x["a"] == "error":
                t["error"] = x.get("error_de")
        else:
            nuevos.append({"id": None, "tipo": x["tipo"], "proyecto": x["proyecto"], "slug": x["slug"],
                           "estado": x["estado"], "archivo": x["archivo"], "resultado": x["resultado"],
                           "creado": None, "actualizado": None, "intentos": 0, "error": x.get("error_de")})
    return list(out.values()) + nuevos
