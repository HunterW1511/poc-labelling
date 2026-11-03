"""L.2 / D.2 / D.6: exporta un lote para procesar en Colab (GPU), sin tunel.
Uso (en el contenedor): python /app/exportar_lote.py <proyecto> [--limite N] [--tareas ids] [--todas]
       [--muestra N [--semilla S] [--minimo M] [--prioridad archivo.json]] [--modo auto|sam3|hijo] [--reporte]
--modo auto: modelo hijo si el proyecto tiene uno activo en el registro; si no, SAM 3 semantico.
Genera /app/lotes/lote_p<id>_<version>_<fecha>.zip con manifiesto.json, fotos/, codigo/ y (hijo) modelo/."""
import argparse, datetime, json, zipfile
from collections import Counter
from pathlib import Path

import requests

import config
from cola import HEADERS, LS_URL, _ya_tiene, get_local_path
from config import LOTES
from muestra import carpeta_de, muestra_estratificada
from perfil import leer_perfil, limites_por_clase
from version import version_hijo, version_modelo
from worker import encabezado

APP = Path(__file__).resolve().parent
CODIGO = ["reglas.py", "pipeline.py", "hijo.py", "lote.py", "worker.py"]
MODELOS = Path(getattr(config, "MODELOS", Path(config.DATOS) / "modelos"))


def leer_prioridad(ruta):
    """Lista de ids, o reporte de diagnostico.py ({"anomalias": {tipo: [ids]}}) -> union de ids."""
    d = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if isinstance(d, dict):
        d = [i for v in (d.get("anomalias") or {}).values() for i in v]
    return {int(i) for i in d}


def hijo_activo(proyecto):
    """-> (nombre, ruta_pt, imgsz) del modelo activo del registro, o None."""
    f = MODELOS / f"p{proyecto}" / "registro.json"
    if not f.exists():
        return None
    reg = json.loads(f.read_text(encoding="utf-8"))
    act = reg.get("activo")
    if not act:
        return None
    m = next(m for m in reg["modelos"] if m["nombre"] == act)
    pt = MODELOS / m["ruta_pt"]
    if not pt.exists():
        raise SystemExit(f"El modelo activo {act} no tiene su .pt en {pt}")
    return act, pt, (m.get("resumen") or {}).get("imgsz") or 960


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proyecto", type=int)
    ap.add_argument("--limite", type=int, default=0, help="maximo de tareas (0 = sin limite)")
    ap.add_argument("--tareas", default="", help="ids separados por coma (solo esas tareas)")
    ap.add_argument("--todas", action="store_true", help="incluir tareas que ya tienen esta version")
    ap.add_argument("--muestra", type=int, default=0, help="muestra estratificada de N tareas sin anotar")
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--minimo", type=int, default=1, help="minimo por carpeta en la muestra")
    ap.add_argument("--prioridad", default="", help="json con ids (o reporte de diagnostico.py)")
    ap.add_argument("--modo", choices=["auto", "sam3", "hijo"], default="auto")
    ap.add_argument("--hijo-conf", type=float, default=0.25, help="confianza minima del modelo hijo")
    ap.add_argument("--reporte", action="store_true", help="no crear el zip; solo listar")
    a = ap.parse_args()

    r = requests.get(f"{LS_URL}/api/projects/{a.proyecto}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    cfg = r.json()["label_config"]
    perfil = leer_perfil(cfg)
    campo = perfil["campo_imagen"]

    hijo = hijo_activo(a.proyecto) if a.modo in ("auto", "hijo") else None
    if a.modo == "hijo" and not hijo:
        raise SystemExit(f"--modo hijo pero el proyecto {a.proyecto} no tiene modelo activo (xd.py modelos)")
    modo = "hijo" if hijo else "sam3"
    ver = version_hijo(perfil, hijo[0]) if hijo else version_modelo(perfil)
    print(f"Modo {modo}" + (f" | modelo {hijo[0]} (imgsz {hijo[2]}, conf {a.hijo_conf})" if hijo else "") +
          f" | version {ver}")

    r = requests.get(f"{LS_URL}/api/projects/{a.proyecto}/export", headers=HEADERS, timeout=600,
                     params={"exportType": "JSON", "download_all_tasks": "true"})
    r.raise_for_status()
    tareas = r.json()
    if not a.todas:
        tareas = [t for t in tareas if not _ya_tiene(t["id"], ver)]  # el export trae ids, no dicts
    if a.tareas:
        ids = {int(x) for x in a.tareas.split(",") if x.strip()}
        tareas = [t for t in tareas if t["id"] in ids]
    if a.muestra:
        n_anot = sum(1 for t in tareas if t.get("annotations"))
        tareas = [t for t in tareas if not t.get("annotations")]
        prio = leer_prioridad(a.prioridad) if a.prioridad else set()
        disp = Counter(carpeta_de(t["data"].get(campo)) for t in tareas)
        elegidos = set(muestra_estratificada(tareas, a.muestra, campo, a.semilla, a.minimo, prio))
        tareas = [t for t in tareas if t["id"] in elegidos]
        eleg = Counter(carpeta_de(t["data"].get(campo)) for t in tareas)
        epri = Counter(carpeta_de(t["data"].get(campo)) for t in tareas if t["id"] in prio)
        print(f"Muestra {len(tareas)}/{a.muestra} | semilla {a.semilla} | excluidas por anotadas {n_anot} | "
              f"prioridad {len(prio)} ids")
        print(f"{'carpeta':<16}{'disponibles':>12}{'elegidas':>10}{'prioridad':>11}")
        for c in sorted(disp):
            print(f"{c:<16}{disp[c]:>12}{eleg[c]:>10}{epri[c]:>11}")
    if a.limite:
        tareas = tareas[:a.limite]
    if not tareas:
        raise SystemExit(f"No hay tareas pendientes para {ver} en el proyecto {a.proyecto}")
    if a.reporte:
        print(f"REPORTE {len(tareas)} tareas | version {ver} | ids {','.join(str(t['id']) for t in tareas)}")
        return

    out = LOTES
    out.mkdir(exist_ok=True)
    zp = out / f"lote_p{a.proyecto}_{ver}_{datetime.datetime.now():%Y%m%d-%H%M}.zip"
    man = []
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for i, t in enumerate(tareas, 1):
            ruta = get_local_path(t["data"][campo], task_id=t["id"])
            nombre = f"fotos/{t['id']}_{Path(ruta).name}"
            z.write(ruta, nombre)
            man.append({"id": t["id"], "foto": nombre})
            print(f"  [{i}/{len(tareas)}] tarea {t['id']}")
        for c in CODIGO:
            z.write(APP / c, f"codigo/{c}")
        meta = {"proyecto": a.proyecto, "version": ver, "modo": modo, "perfil": perfil, "label_config": cfg,
                "creado": datetime.datetime.now().isoformat(timespec="seconds"), "tareas": man}
        if hijo:
            z.write(hijo[1], "modelo/best.pt")
            meta["hijo"] = {"nombre": hijo[0], "archivo": "modelo/best.pt", "conf": a.hijo_conf, "imgsz": hijo[2]}
            meta["limites"] = limites_por_clase(cfg)
        z.writestr("manifiesto.json", json.dumps(meta, ensure_ascii=True, indent=1))
        z.writestr("trabajo.json", json.dumps(encabezado("preetiquetado", zp.stem, proyecto=a.proyecto,
                                                         creado=meta["creado"]), ensure_ascii=True, indent=1))
    print(f"OK {len(man)} tareas | modo {modo} | version {ver} | {zp.stat().st_size / 1e6:.1f} MB -> {zp}")


if __name__ == "__main__":
    main()
