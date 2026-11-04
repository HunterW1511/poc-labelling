"""P.2.5 (D5): adaptador de transporte. Para el hub, todo transporte son CARPETAS LOCALES por tipo
(asistente, lotes, datasets, runs) + enviar / traer / archivar. Los comandos y la reconciliacion leen nombres de
archivo en esas carpetas y no saben de que proveedor vienen.
- Drive: las carpetas de Google Drive para escritorio (la app sincroniza; traer no hace nada).
- Espejo: carpetas locales (base del transporte de Kaggle en P.2.7, que sube en enviar y descarga en traer; y tests).
Biblioteca estandar; solo lo usa el host."""
import shutil
from pathlib import Path

CARPETAS = ("asistente", "lotes", "datasets", "runs")
PREFIJO = (("asist_", "asistente"), ("lote_p", "lotes"), ("dataset_p", "datasets"), ("pre_p", "lotes"))


def carpeta_de(nombre):
    """Carpeta que corresponde a un archivo de trabajo por su nombre (asist_*, lote_p*, dataset_p*), o None."""
    return next((c for p, c in PREFIJO if nombre.startswith(p)), None)


class Transporte:
    nombre = "base"

    def carpeta(self, c, crear=False):
        """Ruta local de la carpeta c, o None si no esta disponible."""
        raise NotImplementedError

    def falta(self, c):
        return f"{self.nombre}: no encuentro la carpeta '{c}'"

    def requerir(self, c, crear=False):
        p = self.carpeta(c, crear=crear)
        if p is None:
            raise SystemExit(self.falta(c))
        return p

    def carpetas(self):
        return {c: self.carpeta(c) for c in CARPETAS}

    def enviar(self, c, archivo):
        """Deja una copia de archivo en la carpeta c (atomica: el worker nunca ve un zip a medias). -> destino."""
        d = self.requerir(c, crear=True)
        archivo = Path(archivo)
        destino, tmp = d / archivo.name, d / f"{archivo.name}.tmp"
        shutil.copy2(archivo, tmp)
        tmp.replace(destino)
        return destino

    def traer(self):
        """Trae resultados del proveedor a las carpetas locales. -> nombres nuevos. Drive: la app ya sincroniza."""
        return []

    def archivar(self, c, nombre, nuevo=None):
        """Mueve carpeta(c)/nombre a carpeta(c)/_archivo/(nuevo o nombre). No borra nada. -> destino."""
        d = self.requerir(c)
        origen, destino = d / nombre, d / "_archivo" / (nuevo or nombre)
        if not origen.exists():
            raise FileNotFoundError(f"no existe {origen}")
        destino.parent.mkdir(exist_ok=True)
        shutil.move(str(origen), str(destino))
        return destino

    def __repr__(self):
        return f"{self.nombre}: " + ", ".join(f"{c}={p}" for c, p in self.carpetas().items())


class Drive(Transporte):
    """LOTES_DRIVE (obligatoria) y, por defecto junto a ella, asistente, datasets y runs (o *_DRIVE en el .env)."""
    nombre = "drive"
    VAR = {"asistente": "ASISTENTE_DRIVE", "lotes": "LOTES_DRIVE", "datasets": "DATASETS_DRIVE", "runs": "RUNS_DRIVE"}

    def __init__(self, env):
        self.env = env

    def _lotes(self):
        d = self.env.get("LOTES_DRIVE")
        return Path(d) if d and Path(d).is_dir() else None

    def carpeta(self, c, crear=False):
        if c not in CARPETAS:
            raise ValueError(f"carpeta {c!r}: debe ser una de {CARPETAS}")
        lotes = self._lotes()
        if c == "lotes":
            return lotes                              # nunca se crea: si no esta, Drive no esta montado
        v = self.env.get(self.VAR[c])
        p = Path(v) if v else (lotes.parent / c if lotes else None)
        if p is None:
            return None
        if crear and lotes:
            p.mkdir(parents=True, exist_ok=True)
        return p if p.is_dir() else None

    def falta(self, c):
        if c == "lotes" or not self._lotes():
            d = self.env.get("LOTES_DRIVE")
            return (f"No encuentro {d} (revisa Google Drive para escritorio)" if d else
                    "Falta LOTES_DRIVE en .env (carpeta de lotes sincronizada con Drive)")
        return f"No encuentro la carpeta {c} de Drive ({self.VAR[c]} o junto a LOTES_DRIVE)"


class Espejo(Transporte):
    """Carpetas locales bajo una raiz (las crea al pedirlas)."""
    nombre = "espejo"

    def __init__(self, raiz):
        self.raiz = Path(raiz)

    def carpeta(self, c, crear=False):
        if c not in CARPETAS:
            raise ValueError(f"carpeta {c!r}: debe ser una de {CARPETAS}")
        p = self.raiz / c
        if crear:
            p.mkdir(parents=True, exist_ok=True)
        return p if p.is_dir() else None


class Kaggle(Espejo):
    """P.2.7: espejo local (datos/kaggle/espejo). enviar deja el zip en el espejo; `xd.py worker --enviar` lo sube
    (dataset privado xd-envios) y lanza el kernel; `worker --traer` baja la salida al espejo. Asi la reconciliacion,
    lote-importar, asistente-importar y registrar leen los mismos nombres que con Drive."""
    nombre = "kaggle"

    def __init__(self, raiz, env):
        super().__init__(raiz)
        self.env = env

    def carpeta(self, c, crear=False):
        """Espejo local: siempre hay ruta (una carpeta que aun no existe se lee como vacia); solo se crea al escribir."""
        super().carpeta(c, crear=crear)
        return self.raiz / c


def elegir(env, raiz):
    """Transporte segun TRANSPORTE del .env (defecto drive)."""
    t = (env.get("TRANSPORTE") or "drive").strip().lower()
    if t == "drive":
        return Drive(env)
    if t == "kaggle":
        return Kaggle(Path(raiz) / "datos" / "kaggle" / "espejo", env)
    raise SystemExit(f"TRANSPORTE={t!r}: debe ser drive o kaggle")
