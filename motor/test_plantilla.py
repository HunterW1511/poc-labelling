"""L.5: la plantilla es valida y xd._validar_spec suma las reglas del host. Uso: python motor/test_plantilla.py"""
import copy, json, sys
from pathlib import Path

M = Path(__file__).resolve().parent
sys.path[:0] = [str(M), str(M.parent)]
import spec   # noqa: E402
import xd     # noqa: E402

P = json.loads((M / "plantillas" / "spec_plantilla.json").read_text(encoding="utf-8"))
e, a = spec.validar(P)
assert not e, e
print("plantilla valida (spec.validar) OK:", len(a), "avisos")
e, _ = xd._validar_spec(copy.deepcopy(P), "plantilla")
assert len(e) == 1 and "CAMBIAR" in e[0], e
print("marcas CAMBIAR bloquean OK")
limpia = json.loads(json.dumps(P).replace("CAMBIAR: ", ""))
e, _ = xd._validar_spec(limpia, "plantilla")
assert not e, e
print("sin marcas: 0 errores OK")
e, _ = xd._validar_spec(copy.deepcopy(limpia), "otro")
assert any("proyecto.slug" in x for x in e), e
print("slug distinto de la carpeta OK")
s = copy.deepcopy(limpia)
s["imagenes"]["raiz"] = "otra/carpeta"
e, _ = xd._validar_spec(s, "plantilla")
assert any("mis_imagenes" in x for x in e), e
print("raiz fuera de mis_imagenes OK")
print("TEST PLANTILLA OK")
