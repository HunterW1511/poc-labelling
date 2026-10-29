"""Re-sincroniza los storages de un proyecto creado con crear_proyecto.py (fotos nuevas -> tareas).
Uso: python /app/sincronizar.py <slug>"""
import json, sys

from config import APP
from crear_proyecto import api, guardar, sync


def main():
    registro = APP / "proyectos" / sys.argv[1] / "proyecto.json"
    if not registro.exists():
        raise SystemExit(f"No existe {registro}")
    reg = json.loads(registro.read_text(encoding="utf-8"))
    for s in reg["storages"]:
        r = sync(s["id"])
        s["estado"] = r.get("status")
        print(f"storage {s['id']} {s['carpeta']:<14} {r.get('status')} | nuevas {r.get('last_sync_count')}")
    guardar(registro, reg)
    t = api("GET", f"/api/projects/{reg['proyecto']}")
    print(f"OK proyecto {reg['proyecto']} | total {t.get('task_number')} tareas")


if __name__ == "__main__":
    main()
