"""L.4 / D.6: sube a Label Studio las predicciones generadas en Colab (modo sam3 o hijo).
Uso (en el contenedor): python /app/importar_lote.py <archivo_pred.json> [--sufijo colab] [--fijar-version]
--fijar-version: deja el model_version del proyecto en la version del lote (Label Studio muestra esas).
El archivo se busca tal cual o dentro de /app/lotes."""
import argparse, json
from pathlib import Path

import requests

from cola import HEADERS, LS_URL, _ya_tiene
from config import LOTES
from perfil import leer_perfil
from version import huella_perfil, version_modelo

PROTEGIDOS = {1, 2}


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
    subidas = omitidas = 0
    for p in lote["predicciones"]:
        ver = p["model_version"] + (f"-{a.sufijo}" if a.sufijo else "")
        if _ya_tiene(p["task"], ver):
            omitidas += 1
            print(f"  tarea {p['task']}: ya tiene {ver}, omito")
            continue
        requests.post(f"{LS_URL}/api/predictions", headers=HEADERS, timeout=60, json={
            "task": p["task"], "model_version": ver, "score": p["score"], "result": p["result"]}
        ).raise_for_status()
        subidas += 1
        print(f"  tarea {p['task']}: {len(p['result'])} regiones -> {ver}")
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
