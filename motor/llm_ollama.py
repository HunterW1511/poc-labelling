"""Adaptador Ollama para asistente.py (solo biblioteca estandar).
cliente(...) -> llm(mensajes, esquema) -> (texto, info). servidor() lo levanta si no responde,
asegurar() descarga un modelo que falte, liberar() suelta la memoria de los modelos YA cargados."""
import json, time, urllib.request


def _post(url, cuerpo, timeout):
    req = urllib.request.Request(url, json.dumps(cuerpo).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def cliente(modelo="qwen2.5:14b", url="http://127.0.0.1:11434", num_ctx=8192, temperatura=0.0, timeout=900,
            num_predict=3000, avisar=print, temperatura_reparar=0.4):
    """num_predict corta una respuesta en bucle (done_reason 'length'); avisar muestra el avance (None = callar).
    Si los mensajes ya traen una respuesta previa (reparacion), usa temperatura_reparar: con 0 el modelo
    repetiria exactamente la misma salida."""
    def llm(mensajes, esquema):
        t = time.time()
        temp = temperatura_reparar if any(m.get("role") == "assistant" for m in mensajes) else temperatura
        d = _post(url.rstrip("/") + "/api/chat", {
            "model": modelo, "stream": False, "format": esquema, "messages": mensajes,
            "options": {"temperature": temp, "num_ctx": num_ctx, "num_predict": num_predict}}, timeout)
        info = {"modelo": modelo, "seg": round(time.time() - t, 1), "entrada": d.get("prompt_eval_count"),
                "salida": d.get("eval_count"), "fin": d.get("done_reason"), "temp": temp}
        if avisar:
            avisar(f"    llm {modelo}: {info['seg']} s | temp {temp} | entrada {info['entrada']} | salida {info['salida']}"
                   + (" | CORTADA: llego a num_predict" if info["fin"] == "length" else ""))
        return d["message"]["content"], info
    return llm


def liberar(modelo=None, url="http://127.0.0.1:11434"):
    """Descarga de la memoria los modelos cargados (todos, o solo 'modelo'). Consulta /api/ps primero:
    una peticion a un modelo NO cargado lo cargaria. -> lista de los que descargo."""
    cargados = [m.get("name") or m.get("model") for m in _get(url.rstrip("/") + "/api/ps").get("models", [])]
    fuera = [m for m in cargados if m and modelo in (None, m)]
    for m in fuera:
        _post(url.rstrip("/") + "/api/generate", {"model": m, "keep_alive": 0}, 120)
    return fuera


def asegurar(modelo, url="http://127.0.0.1:11434"):
    """Descarga el modelo si Ollama no lo tiene. -> True si lo descargo."""
    tags = _get(url.rstrip("/") + "/api/tags")
    if any(modelo in (m.get("name"), m.get("model")) for m in tags.get("models", [])):
        return False
    _post(url.rstrip("/") + "/api/pull", {"model": modelo, "stream": False}, 3600)
    return True


def servidor(url="http://127.0.0.1:11434", espera=60):
    """Levanta 'ollama serve' si no responde (Colab lo pierde al reiniciar). -> True si ya estaba vivo."""
    import shutil, subprocess

    def vivo():
        try:
            urllib.request.urlopen(url.rstrip("/") + "/api/version", timeout=3).close()
            return True
        except OSError:
            return False
    if vivo():
        return True
    if not shutil.which("ollama"):
        raise RuntimeError("ollama no esta instalado: corre la celda 1 del notebook")
    subprocess.Popen(["ollama", "serve"], stdout=open("/tmp/ollama_serve.log", "a"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    for _ in range(espera):
        if vivo():
            return False
        time.sleep(1)
    raise RuntimeError(f"ollama no respondio en {espera} s (revisa /tmp/ollama_serve.log)")
