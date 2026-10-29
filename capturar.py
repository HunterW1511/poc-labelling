"""Captura de fotos por carpeta segun el plan (B.6). OpenCV, independiente del motor; corre en el host.
Uso: python capturar.py SLUG [--camara 0] [--carpeta NOMBRE] [--total N] [--ancho 1280] [--alto 720]
Teclas: espacio guardar | n / p carpeta siguiente / anterior | g cuadricula | z deshacer | q salir"""
import argparse, sys, time

import cv2

import xd

sys.path.insert(0, str(xd.RAIZ / "motor"))
from plan import plan_captura  # noqa: E402

F = cv2.FONT_HERSHEY_SIMPLEX
CADA = 5                                # fotos por cada variacion sugerida
TITULO = "Captura (espacio guardar, n/p carpeta, g cuadricula, z deshacer, q salir)"


def abrir(camara, ancho, alto):
    cap = cv2.VideoCapture(camara, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(camara)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
    if not cap.isOpened():
        raise SystemExit(f"No pude abrir la camara {camara}")
    return cap


def nombre(carpeta):
    t = time.time()
    return f"{carpeta}_{time.strftime('%Y%m%d_%H%M%S', time.localtime(t))}_{int(t * 1000) % 1000:03d}.jpg"


def cuadricula(vis):
    h, w = vis.shape[:2]
    for k in (1, 2):
        cv2.line(vis, (w * k // 3, 0), (w * k // 3, h), (200, 200, 200), 1)
        cv2.line(vis, (0, h * k // 3), (w, h * k // 3), (200, 200, 200), 1)


def barra(vis, f, n, var, sig, aviso):
    w, h = vis.shape[1], vis.shape[0]
    cv2.rectangle(vis, (0, 0), (w, 66), (255, 255, 255), -1)
    listo = n >= f["fotos"]
    cv2.putText(vis, f"{f['carpeta']} [{f['tipo']}]  {n}/{f['fotos']}" + ("  META CUMPLIDA" if listo else ""),
                (8, 26), F, 0.7, (0, 140, 0) if listo else (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(vis, f"variar: {var}", (8, 54), F, 0.55, (90, 90, 90), 1, cv2.LINE_AA)
    if listo and sig:
        cv2.putText(vis, f"siguiente incompleta: {sig} (n)", (w - 380, 54), F, 0.5, (0, 120, 200), 1, cv2.LINE_AA)
    if aviso:
        cv2.putText(vis, aviso, (8, h - 12), F, 0.6, (0, 0, 255), 2, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--camara", type=int, default=0)
    ap.add_argument("--carpeta", default="", help="empezar en esta carpeta (si no, la primera incompleta)")
    ap.add_argument("--total", type=int, default=0, help="presupuesto total (escala el plan)")
    ap.add_argument("--ancho", type=int, default=1280)
    ap.add_argument("--alto", type=int, default=720)
    a = ap.parse_args()

    spec = xd._spec(a.slug)
    base = xd._raiz(spec, a.slug)
    filas = plan_captura(spec, a.total or None)
    cuentas = {f["carpeta"]: xd._contar(base / f["carpeta"]) for f in filas}
    if a.carpeta:
        i = next((k for k, f in enumerate(filas) if f["carpeta"] == a.carpeta), None)
        if i is None:
            raise SystemExit(f"La carpeta {a.carpeta!r} no esta en la spec: {[f['carpeta'] for f in filas]}")
    else:
        i = next((k for k, f in enumerate(filas) if cuentas[f["carpeta"]] < f["fotos"]), 0)

    cap = abrir(a.camara, a.ancho, a.alto)
    guardadas, rejilla, aviso, t_aviso = [], False, "", 0.0
    print(f"Captura {a.slug} en {base} | empieza en {filas[i]['carpeta']}")
    while True:
        ok, img = cap.read()
        if not ok:
            print("La camara dejo de entregar imagen")
            break
        f = filas[i]
        n = cuentas[f["carpeta"]]
        var = f["variaciones"][(n // CADA) % len(f["variaciones"])] if f["variaciones"] else ""
        sig = next((x["carpeta"] for x in filas[i + 1:] + filas[:i] if cuentas[x["carpeta"]] < x["fotos"]), "")
        if time.time() - t_aviso > 2:
            aviso = ""
        vis = img.copy()
        if rejilla:
            cuadricula(vis)
        barra(vis, f, n, var, sig, aviso)
        cv2.imshow(TITULO, vis)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q") or cv2.getWindowProperty(TITULO, cv2.WND_PROP_VISIBLE) < 1:
            break
        if k == ord(" "):
            d = base / f["carpeta"]
            d.mkdir(parents=True, exist_ok=True)
            ruta = d / nombre(f["carpeta"])
            cv2.imwrite(str(ruta), img)                     # la imagen original, sin barra ni cuadricula
            guardadas.append(ruta)
            cuentas[f["carpeta"]] += 1
            aviso, t_aviso = f"guardada {ruta.name}", time.time()
        elif k == ord("z") and guardadas:
            r = guardadas.pop()
            r.unlink(missing_ok=True)
            cuentas[r.parent.name] -= 1
            aviso, t_aviso = f"deshecha {r.name}", time.time()
        elif k == ord("n"):
            i = (i + 1) % len(filas)
        elif k == ord("p"):
            i = (i - 1) % len(filas)
        elif k == ord("g"):
            rejilla = not rejilla
    cap.release()
    cv2.destroyAllWindows()

    print(f"\nGuardadas en esta sesion: {len(guardadas)}")
    for f in filas:
        n = cuentas[f["carpeta"]]
        print(f"  {f['carpeta']:<14} {n:>4}/{f['fotos']:<4} {'OK' if n >= f['fotos'] else 'faltan ' + str(f['fotos'] - n)}")
    if guardadas:
        print(f"\nPara que entren a Label Studio:  python xd.py sincronizar {a.slug}")


if __name__ == "__main__":
    main()
