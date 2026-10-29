"""Etapa C.4: buzon del asistente en Drive (PURO, solo biblioteca estandar; lo usa xd.py en el host).
armar() -> zip de trabajo (codigo + entrada.json + audio) que procesa el notebook asistente.ipynb.
resultados() / errores() / preparar_spec() leen lo que deja Colab: <trabajo>_resultado.json o _error.txt."""
import copy, json, re, time, zipfile
from pathlib import Path

import spec

ESQUEMA_TRABAJO = 1
PREFIJO = "asist_"
MODULOS = ("spec.py", "perfil.py", "colores.py", "esquema_llm.py", "asistente.py", "llm_ollama.py", "trabajo.py")
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".webm", ".mp4", ".aac", ".opus"}
MODELO_LLM, MODELO_STT, IDIOMA = "qwen2.5:14b", "large-v3-turbo", "es"


def nombre_trabajo(slug, ahora=None):
    return f"{PREFIJO}{slug}_{time.strftime('%Y%m%d-%H%M%S', time.localtime(ahora))}"


def armar(motor, destino, slug, texto="", audio=None, vocabulario=(), respuestas="", previa=None,
          modelo_llm=MODELO_LLM, modelo_stt=MODELO_STT, idioma=IDIOMA, ahora=None):
    """-> (ruta del zip, entrada). ValueError si falta algo."""
    motor, destino = Path(motor), Path(destino)
    if not spec.SLUG.match(str(slug)):
        raise ValueError(f"slug={slug!r}: solo minusculas, digitos, _ o -")
    if not (str(texto).strip() or audio):
        raise ValueError("se necesita --audio o --texto")
    if audio:
        audio = Path(audio)
        if not audio.is_file():
            raise ValueError(f"no existe el audio {audio}")
        if audio.suffix.lower() not in AUDIO_EXT:
            raise ValueError(f"formato de audio {audio.suffix!r} no soportado: {sorted(AUDIO_EXT)}")
    faltan = [m for m in MODULOS if not (motor / m).is_file()]
    if faltan:
        raise ValueError(f"faltan modulos en {motor}: {faltan}")
    nombre = nombre_trabajo(slug, ahora)
    entrada = {"esquema": ESQUEMA_TRABAJO, "trabajo": nombre, "slug": slug, "texto": str(texto or "").strip(),
               "audio": f"audio/entrada{audio.suffix.lower()}" if audio else None,
               "vocabulario": [str(v).strip() for v in vocabulario if str(v).strip()],
               "respuestas": str(respuestas or "").strip(), "previa": previa,
               "modelo_llm": modelo_llm, "modelo_stt": modelo_stt, "idioma": idioma,
               "creado": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ahora))}
    destino.mkdir(parents=True, exist_ok=True)
    zp, tmp = destino / f"{nombre}.zip", destino / f"{nombre}.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for m in MODULOS:
            z.write(motor / m, f"codigo/{m}")
        z.writestr("entrada.json", json.dumps(entrada, ensure_ascii=True, indent=1))
        if audio:
            z.write(audio, entrada["audio"])
    tmp.replace(zp)                                  # el notebook nunca ve un zip a medias
    return zp, entrada


def _de(destino, slug, sufijo):
    pat = re.compile(rf"^{PREFIJO}{re.escape(slug) if slug else '.+'}_\d{{8}}-\d{{6}}{re.escape(sufijo)}$")
    return sorted((f for f in Path(destino).glob(f"{PREFIJO}*{sufijo}") if pat.match(f.name)),
                  key=lambda f: f.name[-(15 + len(sufijo)):])


def resultados(destino, slug=""):
    """Archivos <trabajo>_resultado.json del slug (o de todos), del mas viejo al mas nuevo."""
    return _de(destino, slug, "_resultado.json")


def errores(destino, slug=""):
    return _de(destino, slug, "_error.txt")


def pendientes(destino):
    d = Path(destino)
    return sorted(z for z in d.glob(f"{PREFIJO}*.zip")
                  if not (d / f"{z.stem}_resultado.json").exists() and not (d / f"{z.stem}_error.txt").exists())


def preparar_spec(res, slug):
    """Spec del resultado con el slug que pidio el usuario (no el que invento el LLM), revalidada.
    -> (spec o None, errores, avisos)"""
    r = res.get("resultado") or {}
    s = copy.deepcopy(r.get("spec"))
    if not isinstance(s, dict):
        return None, ["el trabajo no produjo una spec"], []
    if isinstance(s.get("proyecto"), dict):
        s["proyecto"]["slug"] = slug
    s["imagenes"] = {"raiz": f"mis_imagenes/{slug}"}         # carpeta propia por proyecto (no compartir Fondo)
    e, a = spec.validar(s)
    return s, e + [f"asistente: {p}" for p in (r.get("problemas") or []) if p not in e], a
