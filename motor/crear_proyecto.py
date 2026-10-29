"""Crea un proyecto de Label Studio desde una especificacion (B.4). Por defecto SOLO REPORTE; --aplicar escribe.
Uso: python /app/crear_proyecto.py <spec.json> [--aplicar]
Pasos: validar + generar XML -> proyecto con ajustes -> un storage localfiles por carpeta -> sync
       -> conexion al motor -> proyectos/<slug>/proyecto.json (registro)."""
import argparse, datetime, json, time

import requests

from config import APP, HEADERS, LS_URL
from generar import verificar
from spec import cargar, validar

RAIZ_LS = "/label-studio/files"                 # LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT
REGEX_IMG = r"(?i).*\.(jpg|jpeg|png|bmp|webp)$"


def api(m, ruta, **kw):
    r = requests.request(m, f"{LS_URL}{ruta}", headers=HEADERS, timeout=120, **kw)
    if not r.ok:
        raise SystemExit(f"{m} {ruta} -> {r.status_code}: {r.text[:400]}")
    return r.json() if r.content else None


def proyectos():
    d = api("GET", "/api/projects", params={"page_size": 1000})
    return d.get("results", []) if isinstance(d, dict) else d


def guardar(ruta, reg):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(reg, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")


def sync(sid, limite=300):
    api("POST", f"/api/storages/localfiles/{sid}/sync")
    t0 = time.time()
    while time.time() - t0 < limite:
        s = api("GET", f"/api/storages/localfiles/{sid}")
        if s.get("status") in ("completed", "failed"):
            return s
        time.sleep(2)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()

    spec = cargar(a.spec)
    for x in validar(spec)[1]:
        print("AVISO:", x)
    xml, perfil, ver = verificar(spec)                 # falla si la spec o el perfil no cuadran
    pr, slug = spec["proyecto"], spec["proyecto"]["slug"]
    raiz = ((spec.get("imagenes") or {}).get("raiz") or f"mis_imagenes/{slug}").strip("/")
    carpetas = [(k["nombre"], k["tipo"], f"{RAIZ_LS}/{raiz}/{k['nombre']}") for k in spec["carpetas"]]
    motor = spec.get("motor") or {}
    registro = APP / "proyectos" / slug / "proyecto.json"

    print(f"Proyecto  : {pr['titulo']!r} (slug {slug}) | version {ver}")
    print(f"Clases    : {perfil['clases']}")
    for n, t, r in carpetas:
        print(f"Storage   : {n:<14} {t:<9} {r}")
    print(f"Motor     : {motor.get('url', 'http://motor:9090')} (interactivo={motor.get('interactivo', True)})")
    print(f"Registro  : {registro}")

    dup = [p["id"] for p in proyectos() if p.get("title") == pr["titulo"]]
    if dup:
        raise SystemExit(f"Ya existe un proyecto con ese titulo (id {dup}): no creo duplicados")
    if registro.exists():
        raise SystemExit(f"Ya existe {registro}; si el proyecto se borro, elimina ese archivo primero")
    if not a.aplicar:
        print("SOLO REPORTE: usa --aplicar para crear")
        return

    p = api("POST", "/api/projects", json={
        "title": pr["titulo"], "description": pr.get("descripcion", ""), "label_config": xml,
        "sampling": "Sequential sampling", "show_collab_predictions": True, "maximum_annotations": 1,
        "model_version": ver})
    reg = {"proyecto": p["id"], "titulo": pr["titulo"], "slug": slug, "version": ver,
           "creado": datetime.datetime.now().isoformat(timespec="seconds"), "storages": [], "ml": None,
           "completo": False}
    guardar(registro, reg)                             # se guarda en cada paso: si algo falla, sabes que limpiar
    print(f"proyecto {p['id']} creado")
    for n, t, ruta in carpetas:
        s = api("POST", "/api/storages/localfiles", json={
            "project": p["id"], "title": n, "path": ruta, "regex_filter": REGEX_IMG,
            "use_blob_urls": True, "recursive_scan": False})
        s = sync(s["id"])
        reg["storages"].append({"id": s["id"], "carpeta": n, "tipo": t, "ruta": ruta,
                                "tareas": s.get("last_sync_count"), "estado": s.get("status")})
        guardar(registro, reg)
        print(f"storage {s['id']} {n:<14} sync {s.get('status')} | {s.get('last_sync_count')} tareas")
    if motor.get("url", "http://motor:9090"):
        m = api("POST", "/api/ml", json={"project": p["id"], "url": motor.get("url", "http://motor:9090"),
                                         "title": "motor", "is_interactive": bool(motor.get("interactivo", True))})
        reg["ml"] = {"id": m["id"], "estado": m.get("readable_state"), "version": m.get("model_version")}
        print(f"ml {m['id']} {m.get('readable_state')} | version {m.get('model_version')}")
    reg["completo"] = True
    guardar(registro, reg)
    t = api("GET", f"/api/projects/{p['id']}")
    print(f"OK proyecto {p['id']} | {t.get('task_number')} tareas | {t.get('sampling')} -> {registro}")


if __name__ == "__main__":
    main()
