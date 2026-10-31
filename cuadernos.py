"""L.7: cuadernos de Colab. El repo (notebooks/) es la fuente de verdad; en Drive viven las copias que se abren
en Colab. PURO, biblioteca estandar. limpiar(nb) quita salidas y metadatos personales; diferencias() compara codigo."""
import copy, json

NOMBRES = ("asistente.ipynb", "preetiquetado.ipynb", "entrenamiento.ipynb")


def limpiar(nb):
    nb = copy.deepcopy(nb)
    for c in nb.get("cells", []):
        c["metadata"] = {}
        if c.get("cell_type") == "code":
            c["outputs"], c["execution_count"] = [], None
        c.pop("attachments", None)
    md = nb.get("metadata", {})
    nb["metadata"] = {k: md[k] for k in ("kernelspec", "language_info", "accelerator") if k in md}
    if isinstance(md.get("colab"), dict) and md["colab"].get("gpuType"):
        nb["metadata"]["colab"] = {"gpuType": md["colab"]["gpuType"]}
    return nb


def texto(nb):
    return json.dumps(limpiar(nb), ensure_ascii=True, indent=1) + "\n"


def fuente(nb):
    return [(c.get("cell_type"), "".join(c.get("source") or [])) for c in nb.get("cells", [])]


def diferencias(a, b):
    """'' si el codigo es igual; si no, un resumen corto."""
    fa, fb = fuente(a), fuente(b)
    if fa == fb:
        return ""
    n = sum(1 for x, y in zip(fa, fb) if x != y) + abs(len(fa) - len(fb))
    return f"{n} celda(s) distinta(s) ({len(fa)} en repo, {len(fb)} en Drive)"