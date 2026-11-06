"""L.4 / D.6: sube a Label Studio las predicciones generadas en Colab (modo sam3 o hijo).
Uso (en el contenedor): python /app/importar_lote.py <archivo_pred.json> [--sufijo colab] [--fijar-version]
--fijar-version: deja el model_version del proyecto en la version del lote (Label Studio muestra esas).
El archivo se busca tal cual o dentro de /app/lotes.
P.4.R6: un GET y un POST por lote (antes, dos peticiones por tarea)."""
import argparse, json
from pathlib import Path

import requests

from config import HEADERS, LOTES, LS_URL
from perfil import leer_perfil
from version import huella_perfil, version_modelo

PROTEGIDOS = {1, 2}


def existentes(pid):
    """P.4.R6: pares (tarea, model_version) que ya tiene el proyecto, en UNA peticion (antes: una por tarea)."""
    r = requests.get(f"{LS_URL}/api/predictions", params={"project": pid}, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return {(p.get("task"), p.get("model_version")) for p in r.json()}


def subir_en_bloque(pid, predicciones, sufijo=""):
    """P.4.R6: sube las predicciones que faltan en UNA peticion (/import/predictions no quita duplicados: por eso se
    filtran antes con existentes). -> (subidas, omitidas)"""
    ya = existentes(pid)
    nuevas, omitidas = [], 0
    for p in predicciones:
        ver = p["model_version"] + (f"-{sufijo}" if sufijo else "")
        if (p["task"], ver) in ya:
            omitidas += 1
            print(f"  tarea {p['task']}: ya tiene {ver}, omito")
            continue
        ya.add((p["task"], ver))                     # un lote con la misma tarea dos veces sube una sola
        nuevas.append({"task": p["task"], "model_version": ver, "score": p["score"], "result": p["result"]})
        print(f"  tarea {p['task']}: {len(p['result'])} regiones -> {ver}")
    if nuevas:
        requests.post(f"{LS_URL}/api/projects/{pid}/import/predictions", headers=HEADERS, timeout=300,
                      json=nuevas).raise_for_status()
    return len(nuevas), omitidas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--sufijo", default="", help="agrega -<sufijo> a model_version (para comparar)")
    ap.add_argument("--fijar-version", action="store_true", help="PATCH model_version del proyecto")
    a = ap.parse_args()
    ruta = Path(a.archivo)
    if not ruta.exists():
        ruta = LOTES / a.archivo
    lote = json.load(open(ruta, encoding="utf-8"))
    pid = lote["proyecto"]

    r = requests.get(f"{LS_URL}/api/projects/{pid}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    pj = r.json()
    perfil = leer_perfil(pj["label_config"])
    modo = lote.get("modo") or ("hijo" if lote["version"].startswith("hijo-") else "sam3")
    if modo == "sam3" and version_modelo(perfil) != lote["version"]:
        print(f"AVISO: el XML o el codigo cambio desde la exportacion (lote {lote['version']} vs actual "
              f"{version_modelo(perfil)}). Se sube con la version del lote; la cola local no la reconocera.")
    if modo == "hijo" and huella_perfil(perfil) != lote["version"].split("-")[-2]:
        print(f"AVISO: el XML cambio desde la exportacion (perfil {lote['version'].split('-')[-2]} vs actual "
              f"{huella_perfil(perfil)}).")

    ver_final = lote["version"] + (f"-{a.sufijo}" if a.sufijo else "")
    subidas, omitidas = subir_en_bloque(pid, lote["predicciones"], a.sufijo)
    print(f"OK {lote['lote']} (modo {modo}): {subidas} subidas, {omitidas} omitidas")

    actual = pj.get("model_version")
    if actual == ver_final:
        return
    if not a.fijar_version:
        print(f"Label Studio muestra las predicciones de model_version={actual!r}; para ver estas usa --fijar-version")
        return
    if pid in PROTEGIDOS:
        raise SystemExit(f"Proyecto {pid} protegido: no cambio su model_version")
    requests.patch(f"{LS_URL}/api/projects/{pid}", headers=HEADERS, timeout=30,
                   json={"model_version": ver_final}).raise_for_status()
    nuevo = requests.get(f"{LS_URL}/api/projects/{pid}", headers=HEADERS, timeout=30).json().get("model_version")
    print(f"model_version del proyecto {pid}: {actual!r} -> {nuevo!r}")


if __name__ == "__main__":
    main()
