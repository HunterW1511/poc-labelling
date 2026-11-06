"""P.2.3: entrenamiento YOLO + KPI de conteo (antes vivia en las celdas 2 y 3 del cuaderno de entrenamiento).
VIAJA en codigo/ del dataset_p<N>_*.zip; lo llama worker.py. Escribe runs/<RUN>/weights/{best.pt, metricas.json}
con el mismo formato de siempre (lo leen registrar, registro.py y la reconciliacion).
YOLO es inyectable para pruebas; ultralytics solo se importa al entrenar de verdad."""
import csv, datetime, json, re, sys
from collections import Counter
from pathlib import Path

DEFECTOS = {"formato": "det", "modelo": "", "imgsz": 960, "epochs": 100, "patience": 30, "batch": 16,
            "conf_conteo": 0.25, "device": ""}           # device "": auto (todas las GPU: Kaggle T4 x2 -> "0,1")
DEVICE = re.compile(r"^(cpu|\d+(,\d+)*)$")
MODELO_BASE = {"det": "yolo11n.pt", "seg": "yolo11n-seg.pt"}
ENTEROS = ("imgsz", "epochs", "patience", "batch")


def parametros(p=None):
    """Defectos + lo que trae trabajo.json, validado."""
    out = {**DEFECTOS, **{k: v for k, v in (p or {}).items() if v not in (None, "")}}
    desconocidos = sorted(set(out) - set(DEFECTOS))
    if desconocidos:
        raise ValueError(f"parametros desconocidos: {desconocidos}")
    if out["formato"] not in MODELO_BASE:
        raise ValueError(f"formato {out['formato']!r}: det o seg")
    for k in ENTEROS:
        out[k] = int(out[k])
        if out[k] < 1:
            raise ValueError(f"{k} debe ser >= 1")
    out["conf_conteo"] = float(out["conf_conteo"])
    if not 0 < out["conf_conteo"] < 1:
        raise ValueError("conf_conteo debe estar entre 0 y 1")
    out["modelo"] = out["modelo"] or MODELO_BASE[out["formato"]]
    out["device"] = str(out["device"]).replace(" ", "")
    if out["device"] and not DEVICE.match(out["device"]):
        raise ValueError(f"device {out['device']!r}: '' (auto), 'cpu', '0' o '0,1'")
    return out


# P.7 bloque 2.1: con pocas fotos, los defectos (batch 16, nbs 64 de ultralytics) dan muy pocos pasos del optimizador.
# Medido en la prueba P.7: 19 fotos -> 2 iteraciones por epoca, 1 paso cada 2 epocas, ~15 pasos en 31 epocas y nunca
# salio del warmup (>= 100 iteraciones): el hijo no detecto nada. Estas reglas solo tocan lo que la persona no fijo.
PEQUENO, DDP_MIN, MIN_PASOS, MAX_EPOCHS = 200, 100, 300, 300


def ajustar(p, n_train, explicitos=()):
    """Parametros segun el tamano del dataset. p: salida de parametros(); n_train: fotos de entrenamiento;
    explicitos: claves que fijo la persona (no se tocan). -> (p ajustado, {"nbs": N | None, "ajustes": [textos]})."""
    q, notas, nbs = dict(p), [], None
    if n_train < PEQUENO:
        if "batch" not in explicitos:
            b = max(2, min(q["batch"], n_train // 2))
            if b != q["batch"]:
                notas.append(f"batch {q['batch']} -> {b} ({n_train} fotos)")
                q["batch"] = b
        nbs = q["batch"]                                   # sin acumular gradientes: un paso por iteracion
        notas.append(f"nbs {nbs} (sin acumular)")
    pasos_ep = max(1, -(-max(1, n_train) // q["batch"]))
    if "epochs" not in explicitos:
        e = min(MAX_EPOCHS, max(q["epochs"], -(-MIN_PASOS // pasos_ep)))
        if e != q["epochs"]:
            notas.append(f"epochs {q['epochs']} -> {e} (>= {MIN_PASOS} pasos)")
            q["epochs"] = e
    if "patience" not in explicitos:
        pa = max(q["patience"], -(-q["epochs"] * 3 // 10))
        if pa != q["patience"]:
            notas.append(f"patience {q['patience']} -> {pa}")
            q["patience"] = pa
    return q, {"nbs": nbs, "ajustes": notas}


def dispositivo(device="", gpus=None):
    """'' -> todas las GPU (P.2.8: la cuota de Kaggle cuenta horas de sesion; T4 x2 entrena en DDP) o 'cpu'.
    -> (para entrenar, para validar y predecir: siempre una sola GPU)."""
    if device:
        return device, device.split(",")[0]
    if gpus is None:
        try:
            import torch
            gpus = torch.cuda.device_count()
        except Exception:
            gpus = 0
    if gpus <= 0:
        return "cpu", "cpu"
    return ",".join(str(i) for i in range(gpus)), "0"


def nombre_run(stem, formato):
    """El mismo nombre que usaba el cuaderno (lo espera la reconciliacion: stem o stem_formato)."""
    return stem if f"_{formato}_" in stem else f"{stem}_{formato}"


def preparar_yaml(d, formato):
    """data.yaml del zip con path absoluto a la carpeta extraida. -> ruta del yaml."""
    yml = Path(d) / formato / "data.yaml"
    if not yml.is_file():
        raise FileNotFoundError(f"el dataset no trae la carpeta {formato} (falta {formato}/data.yaml)")
    lineas = yml.read_text(encoding="utf-8").splitlines()
    ruta = json.dumps(str((Path(d) / formato).resolve()))       # comillas dobles: valido en YAML, tambien en Windows
    lineas = [f"path: {ruta}" if l.startswith("path:") else l for l in lineas]
    if not any(l.startswith("path:") for l in lineas):
        lineas.insert(0, f"path: {ruta}")
    yml.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return yml


def kpi_conteo(pares):
    """pares: [(Counter real por clase, Counter predicho)] -> (exactas, error_abs por clase, instancias reales).
    KPI del proyecto: una imagen es exacta si TODAS las clases coinciden en cantidad."""
    exactas, err, real_tot = 0, Counter(), Counter()
    for real, pred in pares:
        real_tot.update(real)
        dif = {c: pred[c] - real[c] for c in set(real) | set(pred)}
        exactas += all(v == 0 for v in dif.values())
        for c, v in dif.items():
            err[c] += abs(v)
    return exactas, err, real_tot


def _etiquetas(f):
    return Counter(int(l.split()[0]) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()) \
        if f.is_file() else Counter()


def entrenar(d, salida, params=None, proyecto=None, dataset="", YOLO=None, runs=None):
    """Entrena, valida y mide el conteo exacto en val. -> 'runs/<RUN>'.
    runs: carpeta de corridas (defecto salida/runs; en Drive, PoC-Labelling/runs como siempre)."""
    if YOLO is None:
        from ultralytics import YOLO
    d, salida = Path(d), Path(salida)
    runs = Path(runs) if runs else salida / "runs"
    p = parametros(params)
    fmt = p["formato"]
    yml = preparar_yaml(d, fmt)
    resumen = json.loads((d / "resumen.json").read_text(encoding="utf-8")) if (d / "resumen.json").is_file() else {}
    proyecto = proyecto if proyecto is not None else resumen.get("proyecto")
    stem = Path(dataset).stem if dataset else d.name
    run_n = nombre_run(stem, fmt)
    print(f"Dataset {dataset or stem} | run {run_n} | modelo {p['modelo']} | imagenes {resumen.get('imagenes')} | "
          f"correcciones {resumen.get('n_correcciones')}", flush=True)
    explicitos = {k for k, v in (params or {}).items() if v not in (None, "")}
    n_train = sum(1 for f in (d / fmt / "images" / "train").glob("*") if f.is_file())
    p, aj = ajustar(p, n_train, explicitos)
    dev, dev1 = dispositivo(p["device"])
    if "," in dev and n_train < DDP_MIN and "device" not in explicitos:
        aj["ajustes"].append(f"device {dev} -> {dev1} (pocas fotos: DDP no compensa)")
        dev = dev1
    print(f"device: entrenar {dev} | validar {dev1} | fotos de entrenamiento {n_train}", flush=True)
    for x in aj["ajustes"]:
        print(f"  ajuste: {x}", flush=True)
    extra = {"nbs": aj["nbs"]} if aj["nbs"] else {}
    YOLO(p["modelo"]).train(data=str(yml), epochs=p["epochs"], imgsz=p["imgsz"], batch=p["batch"],
                            patience=p["patience"], plots=True, project=str(runs), name=run_n,
                            exist_ok=True, device=dev, **extra)
    run = runs / run_n
    best = YOLO(str(run / "weights" / "best.pt"))
    names = best.names
    m = best.val(data=str(yml), imgsz=p["imgsz"], plots=False, device=dev1)
    por_clase = {names[i]: {} for i in names}
    for k, c in enumerate(m.box.ap_class_index):
        por_clase[names[int(c)]].update(ap50=round(float(m.box.ap50[k]), 4), ap50_95=round(float(m.box.ap[k]), 4))

    imgs = sorted((d / fmt / "images" / "val").glob("*"))
    pares = []
    for im in imgs:
        real = _etiquetas(d / fmt / "labels" / "val" / f"{im.stem}.txt")
        pred = Counter(best.predict(str(im), imgsz=p["imgsz"], conf=p["conf_conteo"], verbose=False, device=dev1)[0]
                       .boxes.cls.int().tolist())
        pares.append((real, pred))
    exactas, err, real_tot = kpi_conteo(pares)
    for i, nm in names.items():
        por_clase[nm].update(error_abs=err[i], mae=round(err[i] / max(1, len(imgs)), 3), instancias_val=real_tot[i])

    res_csv = run / "results.csv"
    epocas = sum(1 for _ in csv.DictReader(res_csv.open(encoding="utf-8"))) if res_csv.is_file() else None
    ul = getattr(sys.modules.get("ultralytics"), "__version__", None)
    met = {"esquema": 1, "creado": datetime.datetime.now().isoformat(timespec="seconds"),
           "proyecto": proyecto, "dataset": dataset or f"{stem}.zip", "resumen_dataset": resumen, "formato": fmt,
           "modelo_base": p["modelo"], "ultralytics": ul,
           "params": {"imgsz": p["imgsz"], "epochs": p["epochs"], "patience": p["patience"], "batch": p["batch"],
                      "conf_conteo": p["conf_conteo"], "device": dev, "nbs": aj["nbs"], "n_train": n_train,
                      "ajustes": aj["ajustes"]},
           "epocas_ejecutadas": epocas,
           "conteo": {"exactas": exactas, "imagenes": len(imgs), "tasa": round(exactas / max(1, len(imgs)), 3)},
           "map50": round(float(m.box.map50), 4), "map50_95": round(float(m.box.map), 4), "por_clase": por_clase}
    if fmt == "seg":
        met["seg"] = {"map50": round(float(m.seg.map50), 4), "map50_95": round(float(m.seg.map), 4)}
    destino = run / "weights" / "metricas.json"
    tmp = destino.with_name("metricas.json.tmp")
    tmp.write_text(json.dumps(met, ensure_ascii=True, indent=1), encoding="utf-8")
    tmp.replace(destino)

    print(f"CONTEO EXACTO {exactas}/{len(imgs)} ({met['conteo']['tasa']:.0%}) | mAP50 {met['map50']:.3f} | "
          f"mAP50-95 {met['map50_95']:.3f} | epocas {epocas}", flush=True)
    print(f"{'clase':<14}{'AP50':>7}{'err':>6}{'MAE':>7}{'inst':>6}")
    for nm, v in por_clase.items():
        print(f"{nm:<14}{v.get('ap50', 0):>7.3f}{v['error_abs']:>6}{v['mae']:>7.3f}{v['instancias_val']:>6}")
    return f"runs/{run_n}"
