"""P.3.4: el clic (interactivo._activar) usa la cache de disco antes de codificar. Sin SAM 3: predictor falso.
Uso (en el contenedor): python /app/test_cache_clic.py"""
import logging, tempfile
from pathlib import Path

import torch

import cache_sam3 as CS
import interactivo as I

SHA_M, VER, IMGSZ = "ab" * 32, "8.4.174", 644
logging.getLogger("motor.interactivo").setLevel(logging.ERROR)   # el aviso de la cache danada es esperado


class Pred:
    device = "cpu"
    codificadas = 0

    def setup_source(self, ruta):
        self.dataset, self._bb_feat_sizes = ["ds", ruta], [[16, 16], [8, 8], [4, 4]]

    def set_image(self, ruta):
        self.setup_source(ruta)
        self.features = {"image_embed": torch.zeros(1, 256, 4, 4),
                         "high_res_feats": [torch.zeros(1, 32, 16, 16), torch.zeros(1, 64, 8, 8)]}
        Pred.codificadas += 1


with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    viejo = (I.CACHE_SAM3, dict(I._disco), dict(I._est), I.INTERACTIVO)
    try:
        I.INTERACTIVO = "completo"                       # P.3.4: como antes, codifica lo que falta
        I.CACHE_SAM3 = t / "cache"
        I._disco.update(sha=SHA_M, version=VER, calculando=False, ultimo_motivo=None)
        I._est.update(imgsz=IMGSZ, ruta=None)
        I._cache.clear()
        con, sin, rota = t / "con.jpg", t / "sin.jpg", t / "rota.jpg"
        for f in (con, sin, rota):
            f.write_bytes(f.name.encode())
        for f in (con, rota):
            c = CS.clave(CS.sha256_archivo(f), IMGSZ, SHA_M, VER)
            feats = {"image_embed": torch.ones(1, 256, 4, 4),
                     "high_res_feats": [torch.ones(1, 32, 16, 16), torch.ones(1, 64, 8, 8)]}
            CS.guardar(CS.archivo(I.CACHE_SAM3, c), CS.empaquetar(feats, c, IMGSZ))
        CS.archivo(I.CACHE_SAM3, CS.clave(CS.sha256_archivo(rota), IMGSZ, SHA_M, VER)).write_bytes(b"danado")
        p = Pred()
        assert I._activar(p, str(con)) == "disco" and Pred.codificadas == 0, "con cache: no codifica"
        assert p.dataset == ["ds", str(con)] and p.features["image_embed"].dtype == torch.float32
        assert float(p.features["image_embed"].mean()) == 1.0, "usa las features de disco"
        assert I._activar(p, str(con)) == "actual"
        assert I._activar(p, str(sin)) == "codificada" and Pred.codificadas == 1, "sin cache: codifica como siempre"
        assert I._activar(p, str(con)) == "cache", "lo cargado de disco tambien queda en RAM"
        assert I._activar(p, str(rota)) == "codificada" and "no valida" in I._disco["ultimo_motivo"]
        assert I._hay_en_disco(str(con)) and not I._hay_en_disco(str(sin))
        I._disco["sha"] = None
        I._disco["calculando"] = True                    # sha aun calculandose: sin cache de disco, se codifica
        I._cache.clear()
        I._est["ruta"] = None
        assert I._activar(p, str(con)) == "codificada"
        # P.3.5 liviano: sin image encoder; la foto sin cache no se codifica en el hub y no hay precodificacion local
        I.INTERACTIVO = "liviano"
        I._disco["sha"], I._disco["calculando"] = SHA_M, False
        I._cache.clear()
        I._est["ruta"] = None
        n = Pred.codificadas
        assert I._activar(p, str(con)) == "disco"
        assert I._activar(p, str(sin)) == "sin_cache" and Pred.codificadas == n, "liviano: nunca codifica"
        I._est["pred"], I._est["calentando"] = object(), False
        assert not I._puede_precodificar(), "liviano: sin precodificacion local"
    finally:
        I.INTERACTIVO = viejo[3]
        I.CACHE_SAM3 = viejo[0]
        I._disco.clear()
        I._disco.update(viejo[1])
        I._est.clear()
        I._est.update(viejo[2])
        I._cache.clear()
class Calentable(Pred):                              # P.4.R4: _calentar hace una inferencia falsa y deja todo limpio
    args = type("A", (), {"conf": 0.5})()
    llamadas = []

    def __call__(self, **kw):
        Calentable.llamadas.append((kw, {k: tuple(v.shape) if hasattr(v, "shape") else [tuple(x.shape) for x in v]
                                         for k, v in self.features.items()}))
        return []


c = Calentable()
I._calentar(c, 644)
kw, formas = Calentable.llamadas[0]
assert kw["points"] == [[[322, 322]]] and formas["image_embed"] == (1, 256, 4, 4) and c.features is None
print("TEST CACHE_CLIC OK: RAM -> disco -> codificar; cache danada o sin sha -> codifica")
