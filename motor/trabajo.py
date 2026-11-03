"""Etapa C.4: ejecutor del asistente. VIAJA en el zip y corre en Colab o Kaggle (lo llama worker.py).
procesar(d) lee entrada.json, transcribe el audio (faster-whisper), libera la memoria y genera la spec con el
LLM (Ollama). Usa GPU si hay; si no, CPU (mas lento). Nunca dos modelos pesados cargados a la vez.
Importable en el host (tests) sin GPU."""
import ctypes, gc, glob, json, site, subprocess, time
from pathlib import Path

import asistente
import llm_ollama

URL = "http://127.0.0.1:11434"
SR = 16000
CUDA12 = ("cuda_runtime/lib/libcudart.so.12", "cublas/lib/libcublasLt.so.12", "cublas/lib/libcublas.so.12",
          "cudnn/lib/libcudnn*.so.9")


def precargar_cuda12():
    """ctranslate2 pide CUDA 12 aunque Colab traiga otra: precarga las libs de los paquetes nvidia-*-cu12.
    -> lista de las que no cargaron."""
    pend = []
    for sp in site.getsitepackages():
        for pat in CUDA12:
            pend += sorted(glob.glob(f"{sp}/nvidia/{pat}"))
    for _ in range(3):                                # varias pasadas: algunas dependen de otras
        fallan = []
        for l in pend:
            try:
                ctypes.CDLL(l, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                fallan.append(l)
        pend = fallan
    return pend


def hay_gpu():
    """True si hay una GPU NVIDIA usable (driver presente)."""
    try:
        return subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def leer_audio(ruta, sr=SR):
    """Cualquier formato -> float32 mono a 16 kHz con ffmpeg (sin PyAV, que cambia de API)."""
    import numpy as np
    crudo = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(ruta), "-f", "s16le", "-ac", "1",
                            "-ar", str(sr), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(crudo, np.int16).astype(np.float32) / 32768.0


def transcribir(ruta, modelo, idioma, vocabulario=()):
    gpu = hay_gpu()
    sin_cargar = precargar_cuda12() if gpu else []
    from faster_whisper import WhisperModel
    audio = leer_audio(ruta)
    t = time.time()
    m = WhisperModel(modelo, device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8")
    kw = {"initial_prompt": "Vocabulario: " + ", ".join(vocabulario) + "."} if vocabulario else {}
    segs, _ = m.transcribe(audio, language=idioma, vad_filter=True, beam_size=5, **kw)
    texto = " ".join(s.text.strip() for s in segs)
    info = {"modelo": modelo, "device": "cuda" if gpu else "cpu", "seg": round(time.time() - t, 1),
            "audio_seg": round(len(audio) / SR, 1), "cuda12_sin_cargar": sin_cargar}
    del m
    gc.collect()
    return texto, info


def procesar(d, nombre="", url=URL, llm=None):
    """d: carpeta con entrada.json (+ audio/). llm: inyectable para pruebas (por defecto Ollama en url)."""
    d = Path(d)
    e = json.loads((d / "entrada.json").read_text(encoding="utf-8"))
    texto, stt, voc = (e.get("texto") or "").strip(), None, e.get("vocabulario") or []
    if llm is None and not hay_gpu():
        print("AVISO: sin GPU; transcripcion y LLM en CPU (mucho mas lento)")
    if e.get("audio"):
        if llm is None:
            try:
                llm_ollama.liberar(None, url)   # memoria libre para Whisper
            except OSError:
                pass
        dicho, stt = transcribir(d / e["audio"], e["modelo_stt"], e["idioma"], voc)
        print(f"  stt: {stt['seg']} s en {stt['device']}", flush=True)
        texto = (texto + "\n" + dicho).strip()
    if llm is None:
        llm_ollama.servidor(url)
        llm_ollama.asegurar(e["modelo_llm"], url)
        llm = llm_ollama.cliente(e["modelo_llm"], url)
    t = time.time()
    r = asistente.generar_spec(texto, llm, respuestas=e.get("respuestas") or "", vocabulario=voc,
                               previa=e.get("previa"))
    return {"esquema": 1, "trabajo": e.get("trabajo") or nombre, "slug": e["slug"], "transcripcion": texto,
            "vocabulario": voc, "stt": stt, "llm_seg": round(time.time() - t, 1), "resultado": r,
            "terminado": time.strftime("%Y-%m-%dT%H:%M:%S")}
