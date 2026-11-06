"""P.7: guia.siguiente (puro) -> paso del flujo de 10, quien, texto y accion de la lista blanca de ui.py.
Sin red ni datos reales. Uso: python test_guia.py"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import guia
import ui


def _t(**kw):
    """Tarjeta de un proyecto creado, con fotos y tareas al dia, sin anotar ni predecir."""
    t = {"slug": "s", "n": 7, "spec": True, "fotos": [{"tienes": 5}], "ls": {"task_number": 5},
         "lotes": {"en_colab": [], "sin_importar": []}, "modelos": {}, "en_espera": {}}
    t.update(kw)
    return t


def _ls(anot=0, pred=0, ver="sam3-x"):
    return {"task_number": 5, "num_tasks_with_annotations": anot, "total_predictions_number": pred, "model_version": ver}


HIJO = {"activo": "hijo-1", "n": 1}
CASOS = [   # (tarjeta, paso, quien, accion, cmd)
    (_t(protegido=True), None, "nada", None, ""),
    # 2. Describir el caso
    (_t(asistente={"ultimo": "pendiente"}), 2, "espera", None, ""),
    (_t(asistente={"ultimo": "error"}), 2, "ui", "asistente-importar", "python xd.py asistente-importar s"),
    (_t(asistente={"ultimo": "resultado"}), 2, "ui", "asistente-importar", "python xd.py asistente-importar s"),
    (_t(slug="caso-ref"), None, "nada", None, ""),
    (_t(spec_errores=["x"]), 2, "editar", "validar", "python xd.py validar s"),
    (_t(spec=False, n=None), 2, "ui", "spec-nueva", "python xd.py spec-nueva s"),
    (_t(n=None), 2, "ui", "crear-proyecto", "python xd.py crear-proyecto s"),
    # 3. Fotos
    (_t(fotos=[{"tienes": 0}, {"tienes": 3}]), 3, "host", "capturar", "python capturar.py s"),
    (_t(fotos=[{"tienes": 9}]), 3, "ui", "sincronizar", "python xd.py sincronizar s"),
    # 4-6. Pre-etiquetar, verificar y modelo hijo
    (_t(), 4, "ui", "preetiquetar", "python xd.py preetiquetar 7 --muestra 50"),
    (_t(lotes={"en_colab": ["lote_p7_x.zip"]}), 4, "espera", None, ""),
    (_t(en_espera={"preetiquetado": 1}), 4, "espera", None, ""),
    (_t(lotes={"sin_importar": ["lote_p7_x_pred.json"]}), 4, "ui", "lote-importar", "python xd.py lote-importar --fijar-version"),
    (_t(ls=_ls(pred=5)), 5, "label_studio", None, ""),
    (_t(ls=_ls(anot=2, pred=5)), 5, "label_studio", None, ""),                 # 2.2: faltan para el minimo
    (_t(ls=_ls(anot=5, pred=5)), 5, "label_studio", "dataset", "python xd.py dataset 7 --drive"),
    (_t(ls=_ls(anot=2, pred=5), en_espera={"entrenamiento": 1}), 6, "espera", None, ""),
    (_t(ls=_ls(anot=2, pred=5), runs_sin_registrar=["r1"]), 6, "ui", "registrar",
     "python xd.py registrar 7 --run ultimo --activar"),
    # 7-10. Con el hijo activo
    (_t(ls=_ls(anot=2, pred=5), modelos=HIJO), 7, "ui", "preetiquetar", "python xd.py preetiquetar 7 --muestra 3 --modo hijo"),
    (_t(ls=_ls(anot=2, pred=5), modelos=HIJO, en_espera={"preetiquetado": 1}), 7, "espera", None, ""),
    (_t(ls=_ls(anot=2, pred=8, ver="hijo-1-abc"), modelos=HIJO), 8, "label_studio", None, ""),
    (_t(ls=_ls(anot=5, pred=8, ver="hijo-1-abc"), modelos=HIJO), 8, "label_studio", "dataset", "python xd.py dataset 7 --drive"),
    (_t(ls=_ls(anot=5, pred=8), modelos=HIJO), 9, "ui", "dataset", "python xd.py dataset 7 --drive"),
    (_t(ls=_ls(anot=5, pred=8, ver="hijo-1-abc"), modelos=HIJO, en_espera={"entrenamiento": 1}), 9, "espera", None, ""),
    (_t(ls=_ls(anot=5, pred=8, ver="hijo-1-abc"), modelos=HIJO, runs_sin_registrar=["r2"]), 9, "ui", "registrar",
     "python xd.py registrar 7 --run ultimo --activar"),
    (_t(ls=_ls(anot=5, pred=8, ver="hijo-2-abc"), modelos={"activo": "hijo-2", "n": 2}), 10, "host", "ver", "python xd.py ver 7"),
]


def test_cada_rama():
    for t, paso, quien, acc, cmd in CASOS:
        g = guia.siguiente(t, "kaggle")
        got = (g["paso"], g["quien"], (g["accion"] or {}).get("accion"), g["cmd"])
        assert got == (paso, quien, acc, cmd), (t, got)
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
            if isinstance(tipo, list):
                assert v in tipo, (a, k, v)


def test_minimo_para_entrenar():
    """2.2: 50 revisadas (o todas si el proyecto tiene menos); el texto dice cuantas faltan."""
    assert guia.faltan_para_entrenar(49, 150) == 1 and guia.faltan_para_entrenar(50, 150) == 0
    assert guia.faltan_para_entrenar(3, 5) == 2 and guia.faltan_para_entrenar(5, 5) == 0
    assert guia.faltan_para_entrenar(0, 0) == 1                       # sin tareas no se entrena
    t = _t(ls={"task_number": 150, "num_tasks_with_annotations": 26, "total_predictions_number": 30})
    g = guia.siguiente(t, "kaggle")                                   # el caso de la prueba P.7
    assert g["paso"] == 5 and g["accion"] is None and "faltan 24" in g["texto"], g


def test_flujo_de_diez_pasos():
    assert len(guia.FASES) == 10 and guia.FASES[0] == "Crear proyecto" and guia.FASES[-1] == "Probar en vivo"
    assert "caso-nuevo" in ui.ACCIONES and ui.ACCIONES["caso-nuevo"]["aplicar"]


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print(f"ok {n}")
    print("TEST GUIA OK")
