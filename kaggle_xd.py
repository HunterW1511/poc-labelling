"""P.2.6: Kaggle desde el hub (CLI oficial `kaggle` por subprocess). Biblioteca estandar.
- Credenciales: API token en ~/.kaggle/access_token (o KAGGLE_API_TOKEN / kaggle.json legacy). Solo se comprueba que
  existan; NUNCA se leen ni se imprimen. Toda salida de la CLI pasa por ocultar() antes de mostrarse.
- Todo dataset es PRIVADO: nunca se pasa -u/--public (lo verifica test_kaggle).
- Una cuenta por persona (D2): el usuario sale de KAGGLE_USUARIO en .env."""
import hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

SLUG_PESOS = "xd-pesos"
TITULO_PESOS = "xd-pesos SAM 3"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")
USUARIO = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SECRETO = re.compile(r"KGAT_[A-Za-z0-9]+|\b[0-9a-f]{32}\b|(\"key\"\s*:\s*\")[^\"]+")


def ocultar(texto):
    """Quita de un texto cualquier cosa con forma de token o clave."""
    return SECRETO.sub(lambda m: (m.group(1) or "") + "***", str(texto or ""))


def dir_config(env=os.environ):
    return Path(env.get("KAGGLE_CONFIG_DIR") or Path.home() / ".kaggle")


def credencial(env=os.environ):
    """Donde esta la credencial (sin leerla): 'KAGGLE_API_TOKEN', 'access_token', 'kaggle.json (legacy)' o None."""
    if env.get("KAGGLE_API_TOKEN"):
        return "KAGGLE_API_TOKEN"
    d = dir_config(env)
    if (d / "access_token").is_file():
        return "access_token"
    if (d / "kaggle.json").is_file():
        return "kaggle.json (legacy)"
    return None


def usuario(env):
    u = (env.get("KAGGLE_USUARIO") or "").strip()
    if not USUARIO.match(u):
        raise SystemExit("Falta KAGGLE_USUARIO en .env (tu nombre de usuario de Kaggle; una cuenta por persona)")
    return u


def comando():
    """Ejecutable de la CLI oficial (pip install kaggle==2.2.5)."""
    k = shutil.which("kaggle")
    if not k:
        raise SystemExit("No encuentro la CLI de Kaggle: pip install -r requirements.txt (kaggle==2.2.5)")
    return [k]


def cli(*args, correr=subprocess.run, timeout=3600):
    """-> (rc, salida sin secretos). Nunca usa --public."""
    if any(a in ("-u", "--public") for a in args):
        raise ValueError("los datasets del proyecto son siempre privados (sin --public)")
    p = correr(comando() + [str(a) for a in args], capture_output=True, text=True, timeout=timeout,
               stdin=subprocess.DEVNULL)
    return p.returncode, ocultar((p.stdout or "") + (p.stderr or ""))


def sha256(ruta, bloque=8 << 20):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(bloque), b""):
            h.update(b)
    return h.hexdigest()


def metadata(usuario_, slug, titulo):
    if not SLUG.match(slug):
        raise ValueError(f"slug {slug!r}: 3-50 caracteres, minusculas, digitos o '-'")
    if not 6 <= len(titulo) <= 50:
        raise ValueError(f"titulo {titulo!r}: 6-50 caracteres")
    return {"title": titulo, "id": f"{usuario_}/{slug}", "licenses": [{"name": "other"}]}


def armar_pesos(pesos, licencia, destino, usuario_, hash_=None):
    """Carpeta lista para subir: sam3.pt (enlace duro si se puede; si no, copia), LICENSE_SAM.txt, pesos.json y
    dataset-metadata.json. -> info (dict)."""
    pesos, licencia, destino = Path(pesos), Path(licencia), Path(destino)
    if not pesos.is_file():
        raise SystemExit(f"No existe {pesos} (pidelo al responsable; no va en Git)")
    if not licencia.is_file():
        raise SystemExit(f"No existe {licencia}: la SAM License debe viajar con los pesos")
    destino.mkdir(parents=True, exist_ok=True)
    dst = destino / pesos.name
    if dst.exists():
        dst.unlink()
    try:
        os.link(pesos, dst)                     # mismo disco: no duplica 3.3 GB
        modo = "enlace"
    except OSError:
        shutil.copy2(pesos, dst)
        modo = "copia"
    shutil.copy2(licencia, destino / "LICENSE_SAM.txt")
    info = {"esquema": 1, "archivo": pesos.name, "bytes": pesos.stat().st_size, "sha256": hash_ or sha256(pesos),
            "licencia": "LICENSE_SAM.txt", "creado": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (destino / "pesos.json").write_text(json.dumps(info, ensure_ascii=True, indent=1), encoding="utf-8")
    meta = metadata(usuario_, SLUG_PESOS, TITULO_PESOS)
    (destino / "dataset-metadata.json").write_text(json.dumps(meta, ensure_ascii=True, indent=1), encoding="utf-8")
    return {**info, "dataset": meta["id"], "modo": modo, "carpeta": str(destino)}


def estado_dataset(dataset, correr=subprocess.run):
    """-> 'ready' | otro estado | None si no existe o no hay acceso."""
    rc, out = cli("datasets", "status", dataset, correr=correr, timeout=120)
    if rc:
        return None
    return (out.strip().splitlines() or [""])[-1].strip().lower() or None


def subir(carpeta, existe, mensaje, correr=subprocess.run):
    """create (privado) o version. -> (rc, salida)."""
    if existe:
        return cli("datasets", "version", "-p", carpeta, "-m", mensaje, "-r", "skip", correr=correr)
    return cli("datasets", "create", "-p", carpeta, "-r", "skip", correr=correr)


def esperar_listo(dataset, limite=3600, cada=20, correr=subprocess.run, dormir=time.sleep, reloj=time.time):
    """Sondea hasta 'ready'. -> segundos que tardo, o None si se agoto el limite."""
    t0 = reloj()
    while reloj() - t0 <= limite:
        if estado_dataset(dataset, correr=correr) == "ready":
            return round(reloj() - t0, 1)
        dormir(cada)
    return None


# ------------------------------------------------------------------ P.2.7: envios y kernel
SLUG_ENVIOS, TITULO_ENVIOS = "xd-envios", "xd-envios trabajos"
SLUG_KERNEL = "xd-worker"                       # el titulo debe "slugificar" al slug: se usa el mismo
ACTIVOS = ("queued", "running", "new_script", "cancel_requested")
TIPO_DE_CARPETA = {"asistente": "asistente", "lotes": "preetiquetado", "datasets": "entrenamiento"}
TIPO_POR_PREFIJO = (("asist_", "asistente"), ("lote_p", "preetiquetado"), ("dataset_p", "entrenamiento"),
                    ("pre_p", "precodificacion"))


def tipo_de(nombre):
    return next((t for p, t in TIPO_POR_PREFIJO if nombre.startswith(p)), None)
EXT_ENVIO = ".xd"     # Kaggle DESCOMPRIME los .zip de un dataset (visto en P.2.7a): viajan como <zip>.xd
CARPETAS_SALIDA = ("asistente", "lotes", "datasets", "runs")


def _enlazar(src, dst):
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def version_dataset(dataset, correr=subprocess.run):
    """Numero de version actual de un dataset (status --format json), o None."""
    rc, out = cli("datasets", "status", dataset, "--format", "json", correr=correr, timeout=120)
    try:
        return int(json.loads(out[out.index("{"):])["current_version_number"]) if rc == 0 else None
    except (ValueError, KeyError, TypeError):
        return None


def armar_envio(zips, destino, usuario_, nombre, operador, pesos=None):
    """zips: [(carpeta, Path)] -> carpeta con los zips + envio.json + dataset-metadata.json. -> envio (dict)."""
    destino = Path(destino)
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    trabajos = []
    for carpeta, zp in zips:
        zp = Path(zp)
        tipo = tipo_de(zp.name)
        if carpeta not in TIPO_DE_CARPETA or tipo is None:
            raise ValueError(f"{zp.name} ({carpeta}): no es un trabajo conocido")
        _enlazar(zp, destino / (zp.name + EXT_ENVIO))
        trabajos.append({"tipo": tipo, "archivo": zp.name, "en_envio": zp.name + EXT_ENVIO,
                         "bytes": zp.stat().st_size})
    if not trabajos:
        raise ValueError("envio vacio")
    envio = {"esquema": 1, "envio": nombre, "operador": operador, "creado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "trabajos": trabajos}
    if pesos:                                     # P.4.R4: {"version": N, "verificar_sha": bool} de xd-pesos
        envio["pesos"] = dict(pesos)
    (destino / "envio.json").write_text(json.dumps(envio, ensure_ascii=True, indent=1), encoding="utf-8")
    meta = metadata(usuario_, SLUG_ENVIOS, TITULO_ENVIOS)
    (destino / "dataset-metadata.json").write_text(json.dumps(meta, ensure_ascii=True, indent=1), encoding="utf-8")
    return envio


def kernel_metadata(usuario_):
    return {"id": f"{usuario_}/{SLUG_KERNEL}", "title": SLUG_KERNEL, "code_file": "lanzador.py", "language": "python",
            "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
            "dataset_sources": [f"{usuario_}/{SLUG_PESOS}", f"{usuario_}/{SLUG_ENVIOS}"],
            "competition_sources": [], "kernel_sources": [], "model_sources": []}


def armar_kernel(lanzador, destino, usuario_):
    destino = Path(destino)
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    shutil.copy2(lanzador, destino / "lanzador.py")
    meta = kernel_metadata(usuario_)
    (destino / "kernel-metadata.json").write_text(json.dumps(meta, ensure_ascii=True, indent=1), encoding="utf-8")
    return meta


def subir_envio(carpeta, existe, nombre, correr=subprocess.run):
    """Una version del dataset privado xd-envios; -d borra las versiones viejas (no se acumulan fotos en Kaggle)."""
    if existe:
        return cli("datasets", "version", "-p", carpeta, "-m", nombre, "-r", "skip", "-d", correr=correr)
    return cli("datasets", "create", "-p", carpeta, "-r", "skip", correr=correr)


def push_kernel(carpeta, limite_s=0, acelerador="NvidiaTeslaT4", correr=subprocess.run):
    args = ["kernels", "push", "-p", carpeta, "--accelerator", acelerador] + (["-t", int(limite_s)] if limite_s else [])
    return cli(*args, correr=correr, timeout=600)


VERSION_PUSH = re.compile(r"Kernel version (\d+) successfully")


def version_push(salida):
    """'Kernel version 6 successfully pushed.' -> 6 (None si la CLI no la dice)."""
    m = VERSION_PUSH.search(salida or "")
    return int(m.group(1)) if m else None


ESTADO = re.compile(r'has status "(?:\w+\.)?(\w+)"')
FALLO = re.compile(r'Failure message: "(.*)"', re.S)


def estado_kernel(kernel, correr=subprocess.run):
    """-> (estado en minusculas o None si no existe/no hay acceso, mensaje de fallo o salida)."""
    rc, out = cli("kernels", "status", kernel, correr=correr, timeout=120)
    m = ESTADO.search(out)
    if rc or not m:
        return None, out.strip()[-300:]
    f = FALLO.search(out)
    return m.group(1).lower(), (f.group(1).strip() if f else "")


# P.4.R6: la salida se baja en dos fases. La CLI (2.2.5) aplica --file-pattern con re.search sobre el nombre de cada
# archivo y los baja de uno en uno: primero todo menos la cache (KB: _pred.json, indices, logs), luego los .pt (MB).
PATRON_SIN_CACHE = r"^(?!.*\.pt$)"
PATRON_CACHE = r"\.pt$"


def bajar_salida(kernel, destino, correr=subprocess.run, patron=None):
    """Baja la salida del kernel a destino (lo vacia antes). patron: solo los archivos cuyo nombre lo cumple."""
    destino = Path(destino)
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    filtro = ["--file-pattern", patron] if patron else []
    return cli("kernels", "output", kernel, "-p", destino, "-o", "-q", *filtro, correr=correr, timeout=3600)


def archivos_salida(salida):
    """Archivos de la salida que van al espejo: [(ruta relativa, Path)] solo bajo asistente/lotes/datasets/runs."""
    salida = Path(salida)
    return sorted((f.relative_to(salida).as_posix(), f) for c in CARPETAS_SALIDA
                  for f in (salida / c).rglob("*") if f.is_file())


def integrar(salida, espejo):
    """Copia la salida del kernel al espejo local (mismos nombres que con Drive). -> rutas relativas copiadas."""
    hechas = []
    for rel, f in archivos_salida(salida):
        dst = Path(espejo) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        shutil.copy2(f, tmp)
        tmp.replace(dst)
        hechas.append(rel)
    return hechas


if __name__ == "__main__":
    print(f"credencial: {credencial() or 'NO HAY'}")
    sys.exit(0)
