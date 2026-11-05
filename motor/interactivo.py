"""Modo interactivo: clic en Label Studio -> SAM3Predictor por punto -> poligono.
- SAM 3 da 3 mascaras alternativas; se elige con el atributo clic del <Label>: grande | chico | (mayor conf).
- Pre-codificacion CONTINUA: un hilo mantiene codificadas las siguientes PREVIAS tareas sin anotar (orden
  por id) con un segundo predictor que COMPARTE el modelo; cache en RAM (features + dataset).
- P.3.4: antes de codificar se busca la cache de DISCO (motor/cache_sam3, precodificada por el worker en GPU):
  setup_source(foto) + p.features. Orden: RAM -> disco -> codificar. docs/cache_sam3.md"""
import logging, threading, time
import xml.etree.ElementTree as ET
from collections import OrderedDict

import cv2
import numpy as np
import requests

import cache_sam3
import cola
import pipeline

log = logging.getLogger("motor.interactivo")
_lock = threading.Lock()          # predictor principal (clics)
_pre_lock = threading.Lock()      # predictor de pre-codificacion
_cache_lock = threading.Lock()
_ev = threading.Event()           # despierta al hilo de pre-codificacion
_est = {"pred": None, "imgsz": None, "ruta": None, "calentando": False, "pre": None, "hilo_pre": None, "origen": None}
_obj = {"proyecto": None, "tid": 0, "perfil": None}
_cache = OrderedDict()            # ruta -> (features, dataset)
_en_proceso = set()
_lista = {"t": 0.0, "proyecto": None, "tareas": []}
cola.al_vaciar.append(_ev.set)    # L.10: al vaciarse la cola semantica, reanudar la precodificacion
PISO_REL = 0.1                    # una alternativa cuenta si su conf >= 10% de la mejor (el area filtra el resto)
MIN_PIX = 20                      # en clic se ignora area_min del perfil; solo se descartan mascaras < 20 px
from config import CACHE_MAX, CACHE_SAM3, INTERACTIVO, PREVIAS, SAM3_MODEL   # (.env)
_origen = {"actual": 0, "cache": 0, "disco": 0, "codificada": 0, "sin_cache": 0}   # de donde salio cada clic (/estado)
SIN_CACHE = "foto sin precodificar: python xd.py precodificar {p} --aplicar y Enviar a Kaggle (o MOTOR_INTERACTIVO=completo)"
_disco = {"sha": None, "calculando": False, "version": None, "ultimo_motivo": None}


def _version_ul():
    if _disco["version"] is None:
        from importlib.metadata import version
        _disco["version"] = version("ultralytics")
    return _disco["version"]


def _sha_modelo():
    """sha de sam3.pt para la clave de la cache. Si no esta memorizado se calcula en segundo plano (~50 s en la
    laptop) y mientras tanto el clic sigue como siempre (codifica)."""
    if _disco["sha"] is None:
        _disco["sha"] = cache_sam3.sha_memorizado(SAM3_MODEL, CACHE_SAM3 / "modelo.json")
    if _disco["sha"] is None and not _disco["calculando"]:
        _disco["calculando"] = True

        def _f():
            try:
                _disco["sha"] = cache_sam3.sha_modelo(SAM3_MODEL, CACHE_SAM3 / "modelo.json")
                log.info("sha de sam3.pt calculado: %s", _disco["sha"][:12])
            except Exception:
                log.exception("no pude calcular el sha de sam3.pt: sin cache de disco")
            finally:
                _disco["calculando"] = False
        threading.Thread(target=_f, daemon=True, name="sam3-sha").start()
    return _disco["sha"]


def _de_disco(p, ruta):
    """Pone en p la cache de disco de la foto si hay una valida. -> True si la uso."""
    sha = _sha_modelo()
    if not sha or not CACHE_SAM3.is_dir():
        return False
    p.setup_source(ruta)                                 # dataset local (src_shape) y _bb_feat_sizes de esta foto
    feats, motivo = cache_sam3.buscar(CACHE_SAM3, ruta, _est["imgsz"], sha, _version_ul(),
                                      espacial=cache_sam3.espacial_de(p._bb_feat_sizes), device=p.device)
    if feats is None:
        if motivo != "sin cache":
            _disco["ultimo_motivo"] = motivo
            log.warning("%s: %s; se codifica", ruta, motivo)
        return False
    p.features = feats
    return True


def _hay_en_disco(ruta):
    sha = _disco["sha"]
    return bool(sha) and cache_sam3.hay(CACHE_SAM3, ruta, _est["imgsz"], sha, _version_ul())


# ----------------------------------------------------------------- modelos
def _predictor(imgsz):
    if _est["pred"] is not None and _est["imgsz"] == imgsz:
        return _est["pred"]                      # ya cargado: sin esperar el candado
    with cola.CARGA:
        return _predictor_sin_candado(imgsz)


def _predictor_sin_candado(imgsz):
    if _est["pred"] is None or _est["imgsz"] != imgsz:
        from ultralytics.models.sam import SAM3Predictor
        t0 = time.time()
        _est["pred"], _est["ruta"], _est["pre"] = None, None, None
        with _cache_lock:
            _cache.clear()
        if INTERACTIVO == "liviano":                    # P.3.5: sin image encoder; pesos del checkpoint propio
            import sam3_ligero
            p = sam3_ligero.predictor_liviano()(overrides=cola.overrides_sam3(imgsz, 0.01))
            p.setup_model(verbose=False)
            origen = type(p).origen
        else:
            p = SAM3Predictor(overrides=cola.overrides_sam3(imgsz, 0.01))
            p.set_image(np.zeros((imgsz, imgsz, 3), np.uint8))       # fuerza la carga de pesos
            origen = "sam3.pt completo"
        _est["pred"], _est["imgsz"], _est["origen"] = p, imgsz, origen
        log.info("SAM 3 interactivo %s listo (imgsz=%d, device=%s, %s) en %.0fs", INTERACTIVO, imgsz,
                 cola.dispositivo(), origen, time.time() - t0)
    return _est["pred"]


def _pre_predictor():
    """Segundo predictor que comparte el modelo del principal (no duplica RAM)."""
    if _est["pre"] is None:
        from ultralytics.models.sam import SAM3Predictor
        p2 = SAM3Predictor(overrides=cola.overrides_sam3(_est["imgsz"], 0.01))  # mismo device/quantize que el principal
        p2.setup_model(_est["pred"].model, verbose=False)
        _est["pre"] = p2
    return _est["pre"]


def precalentar(imgsz, perfil=None, proyecto=None):
    """Carga el modelo en segundo plano y, al terminar, empieza a pre-codificar las primeras pendientes."""
    if _est["pred"] is not None or _est["calentando"]:
        return
    _est["calentando"] = True

    def _f():
        try:
            with _lock:
                _predictor(imgsz)
        except Exception:
            log.exception("precalentar fallo")
        finally:
            _est["calentando"] = False
        if perfil is not None:
            _apuntar(proyecto, 0, perfil)
    threading.Thread(target=_f, daemon=True, name="sam3-int").start()


# ----------------------------------------------------------------- cache de codificaciones
def _guardar(ruta, feats, ds):
    with _cache_lock:
        _cache[ruta] = (feats, ds)
        _cache.move_to_end(ruta)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


def _en_cache(ruta):
    with _cache_lock:
        v = _cache.get(ruta)
        if v is not None:
            _cache.move_to_end(ruta)
        return v


def _activar(p, ruta):
    """Deja el predictor principal listo para ruta. Llamar con _lock tomado."""
    if _est["ruta"] == ruta:
        return "actual"
    if ruta in _en_proceso:                      # se esta pre-codificando: esperar en vez de repetir
        with _pre_lock:
            pass
    v = _en_cache(ruta)
    if v is not None:
        p.features, p.dataset = v
        _est["ruta"] = ruta
        return "cache"
    if _de_disco(p, ruta):                               # P.3.4: precodificada por el worker
        _guardar(ruta, p.features, p.dataset)
        _est["ruta"] = ruta
        return "disco"
    if INTERACTIVO == "liviano":                         # P.3.5: sin encoder no se codifica en el hub
        return "sin_cache"
    p.set_image(ruta)
    _guardar(ruta, p.features, p.dataset)
    _est["ruta"] = ruta
    return "codificada"


# ----------------------------------------------------------------- pre-codificacion continua
def _siguientes(proyecto, tid):
    if time.time() - _lista["t"] > 60 or _lista["proyecto"] != proyecto:
        r = requests.get(f"{cola.LS_URL}/api/projects/{proyecto}/export", headers=cola.HEADERS, timeout=120,
                         params={"exportType": "JSON", "download_all_tasks": "true"})
        r.raise_for_status()
        _lista.update(t=time.time(), proyecto=proyecto, tareas=sorted(r.json(), key=lambda t: t["id"]))
    pend = [t for t in _lista["tareas"] if not t.get("annotations") and t["id"] != tid]
    con = [t for t in pend if t.get("predictions")]          # revision por muestra: primero lo pre-etiquetado
    sin = [t for t in pend if not t.get("predictions")]
    circ = lambda xs: [t for t in xs if t["id"] > tid] + [t for t in xs if t["id"] < tid]
    return (circ(con) + circ(sin))[:PREVIAS]


def _apuntar(proyecto, tid, perfil):
    """Indica en que tarea va el usuario y despierta al hilo de pre-codificacion."""
    try:
        proyecto = int(str(proyecto).split(".")[0]) if proyecto is not None else None
    except ValueError:
        proyecto = None
    if proyecto is None:
        return
    _obj.update(proyecto=proyecto, tid=tid, perfil=perfil)
    if _est["hilo_pre"] is None or not _est["hilo_pre"].is_alive():
        _est["hilo_pre"] = threading.Thread(target=_bucle_pre, daemon=True, name="sam3-pre")
        _est["hilo_pre"].start()
    _ev.set()


def _puede_precodificar():
    """L.10: con trabajo semantico en cola la precodificacion cede la CPU (en 2 nucleos competir lo hace 2-4x mas lento)."""
    return (INTERACTIVO == "completo" and _est["pred"] is not None and not _est["calentando"]
            and not cola.ocupada())                      # P.3.5: el liviano no codifica (la cache viene del worker)


def _bucle_pre():
    while True:
        _ev.wait()
        _ev.clear()
        try:
            while _puede_precodificar():
                proyecto, tid, perfil = _obj["proyecto"], _obj["tid"], _obj["perfil"]
                falta = None
                for t in _siguientes(proyecto, tid):
                    ruta = cola.get_local_path(t["data"][perfil["campo_imagen"]], task_id=t["id"])
                    if ruta != _est["ruta"] and _en_cache(ruta) is None and not _hay_en_disco(ruta):
                        falta = (t["id"], ruta)
                        break
                if falta is None:
                    break                                    # las PREVIAS siguientes ya estan listas
                with _pre_lock:
                    _en_proceso.add(falta[1])
                    try:
                        t0 = time.time()
                        p2 = _pre_predictor()
                        p2.set_image(falta[1])
                        _guardar(falta[1], p2.features, p2.dataset)
                        log.info("pre-codificada tarea %s en %.0fs | en cache %d", falta[0], time.time() - t0,
                                 len(_cache))
                    finally:
                        _en_proceso.discard(falta[1])
        except Exception:
            log.exception("pre-codificacion fallo")


# ----------------------------------------------------------------- eleccion de mascara
def _seleccion(result):
    """Ultimo punto positivo = la pieza; negativos posteriores la recortan."""
    pts = [r for r in result or [] if r.get("type") == "keypointlabels"]
    pos = [i for i, r in enumerate(pts) if r.get("is_positive", True)]
    if not pos:
        return []
    i = pos[-1]
    return [pts[i]] + [r for r in pts[i + 1:] if not r.get("is_positive", True)]


def _modo_clic(label_config, from_name, clase):
    try:
        raiz = ET.fromstring(label_config or "")
    except ET.ParseError:
        return ""
    for ctrl in raiz.iter():
        if ctrl.get("name") == from_name:
            for lab in ctrl.iter("Label"):
                if lab.get("value") == clase:
                    return (lab.get("clic") or "").strip().lower()
    return ""


def _rango_area(perfil, clase):
    ps = [p for p in perfil["prompts"] if clase in p["clases"]]
    if not ps:
        return 0.0, 1.0
    return min(p["area_min"] for p in ps), max(p["area_max"] for p in ps)


def _elegir(areas, confs, modo, amin, amax):
    mejor = max(confs)
    piso = 0.0 if modo == "chico" else PISO_REL * mejor   # chico: lo pequeno puede venir con conf muy baja
    cands = [i for i in range(len(areas)) if confs[i] >= piso and amin <= areas[i] <= amax]
    if not cands:
        cands = [int(np.argmax(confs))]
    if modo == "grande":
        return max(cands, key=lambda i: areas[i])
    if modo == "chico":
        return min(cands, key=lambda i: areas[i])
    return max(cands, key=lambda i: confs[i])


def responder(task, context, perfil, version, label_config="", proyecto=None):
    if _est["pred"] is None or _est["calentando"]:          # no colgar a Label Studio durante la carga
        precalentar(perfil["imgsz"], perfil, proyecto)
        log.info("tarea %s | clic ignorado: modelo cargando, reintenta en un momento", task["id"])
        return []
    sel = _seleccion(context.get("result"))
    if not sel:
        return []
    v = sel[0]["value"]
    clase = (v.get("keypointlabels") or v.get("labels") or [None])[0]
    w0, h0 = sel[0]["original_width"], sel[0]["original_height"]
    puntos = [[r["value"]["x"] / 100 * w0, r["value"]["y"] / 100 * h0] for r in sel]
    etiquetas = [1] + [0] * (len(sel) - 1)
    ruta = cola.get_local_path(task["data"][perfil["campo_imagen"]], task_id=task["id"])
    t0 = time.time()
    with _lock:
        p = _predictor(perfil["imgsz"])
        origen = _activar(p, ruta)
        _origen[origen] = _origen.get(origen, 0) + 1
        if origen == "sin_cache":
            _disco["ultimo_motivo"] = SIN_CACHE.format(p=proyecto if proyecto is not None else task.get("project"))
            log.warning("tarea %s | %s", task["id"], _disco["ultimo_motivo"])
            return []
        t1 = time.time()
        p.args.conf = 0.0                                  # devolver siempre las 3 alternativas
        r = p(points=[puntos], labels=[etiquetas], multimask_output=True)   # anidado = un solo objeto
    _apuntar(proyecto if proyecto is not None else task.get("project"), task["id"], perfil)
    r = r[0] if isinstance(r, list) else r
    if r.masks is None or len(r.masks) == 0:
        log.info("tarea %s | clic sin mascara", task["id"])
        return []
    h, w = r.orig_shape
    masks = r.masks.data.cpu().numpy() > 0.5
    confs = r.boxes.conf.tolist() if r.boxes is not None else [1.0] * len(masks)
    areas = [float(m.mean()) for m in masks]
    modo = _modo_clic(label_config, perfil["from_name"], clase)
    k = _elegir(areas, confs, modo, MIN_PIX / masks[0].size, _rango_area(perfil, clase)[1])
    m = masks[k]
    if m.shape != (h, w):
        m = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
    poly = pipeline.poligono(m, perfil["simplificar"])
    if not poly:
        return []
    region = pipeline.a_ls({"clases": [clase], "conf": float(confs[k]), "poligono": poly}, perfil, w, h)
    log.info("tarea %s | clic %s modo=%s | imagen %s %.1fs | conf %s area%% %s -> #%d | total %.1fs",
             task["id"], clase, modo or "conf", origen, t1 - t0, [round(c, 2) for c in confs],
             [round(a * 100, 2) for a in areas], k, time.time() - t0)
    return [{"result": [region], "score": float(confs[k]), "model_version": version}]


