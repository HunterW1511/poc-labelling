"""Borra un proyecto creado por crear_proyecto.py (usa su registro). Por defecto SOLO REPORTE.
Uso: python /app/borrar_proyecto.py <slug> [--aplicar]
Protecciones: requiere proyectos/<slug>/proyecto.json, el titulo debe coincidir, nunca toca 1 ni 2.
Las fotos no se tocan (mis_imagenes es de solo lectura para Label Studio)."""
import argparse, datetime, json

import requests

from config import APP, HEADERS, LS_URL

PROTEGIDOS = set()   # L.0 20/10/2026: sin protegidos (todos los proyectos son desechables)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    registro = APP / "proyectos" / a.slug / "proyecto.json"
    if not registro.exists():
        raise SystemExit(f"No existe {registro}: solo borro proyectos creados con crear_proyecto.py")
    reg = json.loads(registro.read_text(encoding="utf-8"))
    pid = int(reg["proyecto"])
    if pid in PROTEGIDOS:
        raise SystemExit(f"El proyecto {pid} esta protegido")
    r = requests.get(f"{LS_URL}/api/projects/{pid}", headers=HEADERS, timeout=30)
    if r.status_code == 404:
        print(f"El proyecto {pid} ya no existe en Label Studio")
    else:
        r.raise_for_status()
        t = r.json()
        if t.get("title") != reg["titulo"]:
            raise SystemExit(f"NO borro: el titulo en Label Studio es {t.get('title')!r}, el registro dice {reg['titulo']!r}")
        print(f"Proyecto {pid} {t['title']!r} | {t.get('task_number')} tareas | storages {[s['id'] for s in reg['storages']]}")
        if not a.aplicar:
            print("SOLO REPORTE: usa --aplicar para borrar")
            return
        d = requests.delete(f"{LS_URL}/api/projects/{pid}", headers=HEADERS, timeout=300)
        print("DELETE", pid, "->", d.status_code)
        d.raise_for_status()
    if not a.aplicar:
        return
    destino = registro.with_name(f"proyecto_borrado_{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    registro.rename(destino)
    print("registro ->", destino.name)


if __name__ == "__main__":
    main()
