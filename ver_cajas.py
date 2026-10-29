#!/usr/bin/env python3
"""D.8: prueba en vivo con webcam del modelo hijo registrado (corre en el host, no en Docker).
Uso: python ver_cajas.py <proyecto> [--modelo X] [--camara 0] [--conf 0.25] [--imgsz N]
Teclas: +/- confianza | p pausa | s guardar captura | q/ESC salir"""
import argparse, colorsys, hashlib, json, time
from collections import Counter
from pathlib import Path

import cv2

RAIZ = Path(__file__).resolve().parent
MODELOS = RAIZ / "motor" / "modelos"
TITULO = "ver_cajas (q salir)"


def modelo_registro(proyecto, nombre=""):
    f = MODELOS / f"p{proyecto}" / "registro.json"
    if not f.exists():
        raise SystemExit(f"No hay registro de modelos en {f} (usa: python xd.py registrar)")
    reg = json.loads(f.read_text(encoding="utf-8"))
    nombre = nombre or reg.get("activo")
    if not nombre:
        raise SystemExit("El proyecto no tiene modelo activo: usa --modelo X o  python xd.py modelos N --activar X --aplicar")
    m = next((m for m in reg["modelos"] if m["nombre"] == nombre), None)
    if m is None:
        raise SystemExit(f"No existe {nombre}; registrados: {[x['nombre'] for x in reg['modelos']]}")
    pt = MODELOS / m["ruta_pt"]
    if not pt.exists():
        raise SystemExit(f"Falta el archivo {pt}")
    return nombre, pt, m.get("resumen") or {}


def color(nombre):
    h = int(hashlib.md5(nombre.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.85, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)


def abrir(cam):
    for api in (cv2.CAP_DSHOW, cv2.CAP_ANY):
        c = cv2.VideoCapture(cam, api)
        if c.isOpened():
            return c
        c.release()
    raise SystemExit(f"No pude abrir la camara {cam}")


def dibujar(img, r, names, cabecera):
    cuenta = Counter()
    for (x1, y1, x2, y2), c, s in zip(r.boxes.xyxy.int().tolist(), r.boxes.cls.int().tolist(), r.boxes.conf.tolist()):
        n = names[c]
        cuenta[n] += 1
        col = color(n)
        cv2.rectangle(img, (x1, y1), (x2, y2), col, 2)
        cv2.putText(img, f"{n} {s:.2f}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    filas = [(cabecera, (255, 255, 255))]
    filas += [(f"{n:<14}{cuenta[n]:>3}", color(n) if cuenta[n] else (140, 140, 140)) for n in names.values()]
    filas.append((f"{'TOTAL':<14}{sum(cuenta.values()):>3}", (255, 255, 255)))
    alto, ancho = 20 * len(filas) + 8, max(260, 9 * len(cabecera))
    capa = img.copy()
    cv2.rectangle(capa, (0, 0), (ancho, alto), (0, 0, 0), -1)
    cv2.addWeighted(capa, 0.55, img, 0.45, 0, img)
    for i, (txt, col) in enumerate(filas):
        cv2.putText(img, txt, (8, 20 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
    return cuenta


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("proyecto", type=int)
    ap.add_argument("--modelo", default="", help="nombre en el registro (defecto: el activo)")
    ap.add_argument("--camara", type=int, default=0)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=0, help="defecto: el del entrenamiento (registro)")
    a = ap.parse_args()

    nombre, pt, res = modelo_registro(a.proyecto, a.modelo)
    imgsz = a.imgsz or res.get("imgsz") or 640
    print(f"Modelo {nombre} | {pt} | imgsz {imgsz} | conteo val {res.get('conteo_exactas')}/{res.get('conteo_imagenes')}")
    from ultralytics import YOLO                      # import lento: despues de validar
    model = YOLO(str(pt))
    names = model.names
    cap = abrir(a.camara)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    salida = RAIZ / "capturas"
    conf, fps, pausa, rehacer, frame, vis, cuenta = a.conf, 0.0, False, False, None, None, Counter()
    print("Teclas: +/- confianza | p pausa | s guardar | q/ESC salir")
    while True:
        if not pausa or rehacer or frame is None:
            if not pausa or frame is None:
                ok, frame = cap.read()
                if not ok:
                    print("La camara dejo de entregar imagenes")
                    break
            t0 = time.time()
            r = model.predict(frame, imgsz=imgsz, conf=conf, verbose=False)[0]
            dt = max(1e-3, time.time() - t0)
            fps = 1 / dt if not fps else 0.8 * fps + 0.2 / dt
            vis = frame.copy()
            cuenta = dibujar(vis, r, names, f"{nombre} | conf {conf:.2f} | {fps:.1f} fps" + (" | PAUSA" if pausa else ""))
            rehacer = False
        cv2.imshow(TITULO, vis)
        k = cv2.waitKey(1) & 0xFF
        if k in (ord("q"), 27) or cv2.getWindowProperty(TITULO, cv2.WND_PROP_VISIBLE) < 1:
            break
        if k in (ord("+"), ord("=")):
            conf, rehacer = min(0.95, round(conf + 0.05, 2)), True
        elif k in (ord("-"), ord("_")):
            conf, rehacer = max(0.05, round(conf - 0.05, 2)), True
        elif k == ord("p"):
            pausa, rehacer = not pausa, True
        elif k == ord("s"):
            salida.mkdir(exist_ok=True)
            base = salida / f"ver_{nombre}_{time.strftime('%Y%m%d_%H%M%S')}"
            cv2.imwrite(str(base) + ".jpg", vis)
            base.with_suffix(".json").write_text(json.dumps({"modelo": nombre, "conf": conf, "imgsz": imgsz,
                                                             "conteo": dict(cuenta)}, indent=1), encoding="utf-8")
            print(f"Guardado {base}.jpg  {dict(cuenta)}")
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
