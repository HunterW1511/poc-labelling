"""L.7.4: notebooks/*.ipynb limpios y con las mismas versiones que el hub. Uso: python motor/test_notebooks.py"""
import json, re
from pathlib import Path

M = Path(__file__).resolve().parent
NB = M.parent / "notebooks"
ESPERADOS = {"worker.ipynb"}   # P.2.4: un solo cuaderno (lanza motor/worker.py de cada zip)
SOSPECHOSO = re.compile(r"hf_[A-Za-z0-9]{20,}|(?<![@\w])[0-9a-f]{40}\b|Token [A-Za-z0-9]|[\w.+-]+@[\w-]+\.[a-z]{2,}|"
                        r"G:\\\\|Mi unidad|/Users/|C:\\\\Users|executionInfo|provenance", re.I)
req = (M / "requirements.txt").read_text(encoding="utf-8")
PIN = {"ultralytics": re.search(r"^ultralytics==(\S+)", req, re.M).group(1),
       "timm": re.search(r"^timm==(\S+)", req, re.M).group(1),
       "clip": re.search(r"CLIP\.git@([0-9a-f]{40})", req).group(1)}

hay = {f.name for f in NB.glob("*.ipynb")}
assert hay == ESPERADOS, f"cuadernos en notebooks/: {sorted(hay)} (esperados {sorted(ESPERADOS)})"
for f in sorted(NB.glob("*.ipynb")):
    txt = f.read_text(encoding="utf-8")
    nb = json.loads(txt)
    assert nb.get("nbformat") == 4, f"{f.name}: nbformat {nb.get('nbformat')}"
    for i, c in enumerate(nb["cells"]):
        assert c.get("metadata") == {}, f"{f.name} celda {i}: metadata de Colab (puede traer tu usuario)"
        if c["cell_type"] == "code":
            assert c.get("outputs") == [] and c.get("execution_count") is None, f"{f.name} celda {i}: tiene salidas"
    m = SOSPECHOSO.search(txt)
    assert not m, f"{f.name}: posible dato personal o secreto: {m.group(0)!r}"
    src = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    for linea in (l for l in src.splitlines() if "pip" in l and "install" in l):
        if "ultralytics" in linea:
            assert f"ultralytics=={PIN['ultralytics']}" in linea, f"{f.name}: ultralytics no fijado en {PIN['ultralytics']}: {linea}"
        if "timm" in linea:
            assert f"timm=={PIN['timm']}" in linea, f"{f.name}: timm no fijado en {PIN['timm']}"
        if "CLIP" in linea:
            assert PIN["clip"] in linea, f"{f.name}: CLIP no fijado en el commit del hub"
        if "faster-whisper" in linea:
            assert "faster-whisper==" in linea, f"{f.name}: faster-whisper sin version fija"
    print(f"ok {f.name}: {len(nb['cells'])} celdas, limpio, versiones = hub")
print("TEST NOTEBOOKS OK")