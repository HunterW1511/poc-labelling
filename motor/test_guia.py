"""P.7.1: guia.siguiente (puro) -> paso, quien, texto y accion de la lista blanca de ui.py. Sin red ni datos reales.
Uso: python test_guia.py"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import guia
import ui


def _t(**kw):
    """Tarjeta de un proyecto creado, con fotos y tareas al dia, sin anotar ni predecir."""
    t = {"slug": "s", "n": 7, "spec": True, "fotos": [{"tienes": 5}], "ls": {"task_number": 5},
         "lotes": {"en_colab": [], "sin_importar": []}, "modelos": {}}
    t.update(kw)
    return t


CASOS = [   # (tarjeta, paso, quien, accion, donde, cmd)
    (_t(protegido=True), None, "nada", None, "", ""),
    (_t(asistente={"ultimo": "pendiente"}), 1, "espera", None, "kaggle", ""),
    (_t(asistente={"ultimo": "error"}), 1, "ui", "asistente-importar", "cli", "python xd.py asistente-importar s"),
    (_t(asistente={"ultimo": "resultado"}), 1, "ui", "asistente-importar", "cli", "python xd.py asistente-importar s"),
    (_t(slug="caso-ref"), None, "nada", None, "", ""),
    (_t(spec_errores=["x"]), 1, "editar", "validar", "cli", "python xd.py validar s"),
    (_t(spec=False, n=None), 1, "ui", "spec-nueva", "cli", "python xd.py spec-nueva s"),
    (_t(n=None), 2, "ui", "crear-proyecto", "cli", "python xd.py crear-proyecto s"),
    (_t(lotes={"en_colab": ["lote_p7_x.zip"]}), 4, "espera", None, "kaggle", ""),
    (_t(lotes={"sin_importar": ["lote_p7_x_pred.json"]}), 4, "ui", "lote-importar", "cli",
     "python xd.py lote-importar --fijar-version"),
    (_t(fotos=[{"tienes": 0}, {"tienes": 3}]), 3, "host", "capturar", "host", "python capturar.py s"),
    (_t(fotos=[{"tienes": 9}]), 3, "ui", "sincronizar", "cli", "python xd.py sincronizar s"),
    (_t(runs_sin_registrar=["r1"]), 6, "ui", "registrar", "cli", "python xd.py registrar 7 --run ultimo --activar"),
    (_t(), 4, "ui", "preetiquetar", "cli", "python xd.py preetiquetar 7 --muestra 30"),
    (_t(ls={"task_number": 5, "total_predictions_number": 5}), 5, "label_studio", None, "label_studio", ""),
    (_t(ls={"task_number": 5, "num_tasks_with_annotations": 2}, datasets=["d.zip"]), 6, "ui", "dataset", "kaggle",
     "python xd.py dataset 7 --drive"),
    (_t(ls={"task_number": 5, "num_tasks_with_annotations": 2}), 6, "ui", "dataset", "cli", "python xd.py dataset 7 --drive"),
    (_t(ls={"task_number": 5, "num_tasks_with_annotations": 2}, modelos={"activo": "m"}), 7, "ui", "preetiquetar", "cli",
     "python xd.py preetiquetar 7 --muestra 30"),
    (_t(ls={"task_number": 5, "num_tasks_with_annotations": 5}, modelos={"activo": "m"}), 8, "ui", "aceptacion", "cli",
     "python xd.py aceptacion 7"),
]


def test_cada_rama():
    for t, paso, quien, acc, donde, cmd in CASOS:
        g = guia.siguiente(t, "kaggle")
        got = (g["paso"], g["quien"], (g["accion"] or {}).get("accion"), g["donde"], g["cmd"])
        assert got == (paso, quien, acc, donde, cmd), (t, got)
        assert g["fase"] == (guia.FASES[paso - 1] if paso else "") and g["texto"]


def test_acciones_en_la_lista_blanca():
    """Lo que el modo guiado propone, la UI lo puede correr: accion en ACCIONES, id correcto y opciones permitidas."""
    for t, *_ in CASOS:
        a = guia.siguiente(t, "kaggle")["accion"]
        if not a:
            continue
        defn = ui.ACCIONES.get(a["accion"])
        assert defn, a
        ident = defn["id"]
        assert (ident == "slug") == ("slug" in a) and (ident == "n") == ("n" in a), (a, ident)
        for k, v in a["opciones"].items():
            tipo = (defn.get("opciones") or {}).get(k)
            assert tipo is not None, (a, k)
            assert (v is True) == (tipo == "flag"), (a, k, tipo)


def test_espera_segun_ejecutor():
    t = _t(lotes={"en_colab": ["x"]})
    assert "Colab" in guia.siguiente(t, "colab")["texto"] and guia.siguiente(t, "colab")["donde"] == "colab"
    assert "Kaggle" in guia.siguiente(t, "kaggle")["texto"]


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print(f"ok {n}")
    print("TEST GUIA OK")
