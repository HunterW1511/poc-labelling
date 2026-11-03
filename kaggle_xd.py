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


if __name__ == "__main__":
    print(f"credencial: {credencial() or 'NO HAY'}")
    sys.exit(0)
