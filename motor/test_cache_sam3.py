"""P.3.4: cache_sam3.py (clave, memo del sha, buscar) y xd.py cache-importar, sin SAM 3 ni red. Uso: python test_cache_sam3.py"""
import io, json, os, sys, tempfile
from contextlib import closing, redirect_stdout
from pathlib import Path
from types import SimpleNamespace as NS

import torch

M = Path(__file__).resolve().parent
sys.path.insert(0, str(M.parent))
import cache_sam3 as CS
import cola_trabajos as C
import xd

SHA_M, VER = "ab" * 32, "8.4.174"
ESP = [(4, 4), (16, 16), (8, 8)]                    # [image_embed, high_res 0, high_res 1] (alto, ancho)


def _feats():
    return {"image_embed": torch.randn(1, 256, 4, 4),
            "high_res_feats": [torch.randn(1, 32, 16, 16), torch.randn(1, 64, 8, 8)]}


def _falla(exc, f, *a, **kw):
    try:
        f(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"se esperaba {exc.__name__}")


def _cache_de(carpeta, foto, imgsz=644):
    c = CS.clave(CS.sha256_archivo(foto), imgsz, SHA_M, VER)
    CS.guardar(CS.archivo(carpeta, c), CS.empaquetar(_feats(), c, imgsz))
    return c


def test_clave_y_memo_del_sha():
    _falla(ValueError, CS.clave, "x", 644, SHA_M, VER)
    assert CS.espacial_de([[16, 16], [8, 8], [4, 4]]) == ESP
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        pt = t / "sam3.pt"
        pt.write_bytes(b"pesos")
        memo = t / "c" / "modelo.json"
        assert CS.sha_memorizado(pt, memo) is None                          # no calcula nada
        s = CS.sha_modelo(pt, memo)
        assert s == CS.sha256_archivo(pt) and CS.sha_memorizado(pt, memo) == s
        pt.write_bytes(b"otros pesos")                                     # cambian los pesos: el memo deja de valer
        os.utime(pt, (1, 1))
        assert CS.sha_memorizado(pt, memo) is None and CS.sha_modelo(pt, memo) == CS.sha256_archivo(pt)


def test_buscar():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        foto, otra = t / "a.jpg", t / "b.jpg"
        foto.write_bytes(b"foto a")
        otra.write_bytes(b"foto b")
        cache = t / "cache"
        assert CS.buscar(cache, foto, 644, SHA_M, VER) == (None, "sin cache")
        c = _cache_de(cache, foto)
        f, motivo = CS.buscar(cache, foto, 644, SHA_M, VER, espacial=ESP)
        assert motivo == "disco" and f["image_embed"].dtype == torch.float32 and CS.hay(cache, foto, 644, SHA_M, VER)
        assert CS.buscar(cache, foto, 1008, SHA_M, VER)[1] == "sin cache"            # otro imgsz, otra clave
        assert CS.buscar(cache, foto, 644, "cd" * 32, VER)[1] == "sin cache"         # otros pesos
        assert CS.buscar(cache, otra, 644, SHA_M, VER)[1] == "sin cache" and not CS.hay(cache, otra, 644, SHA_M, VER)
        assert "tamanos" in CS.buscar(cache, foto, 644, SHA_M, VER, espacial=[(5, 5), (16, 16), (8, 8)])[1]
        CS.archivo(cache, c).write_bytes(b"no es un torch.save")                    # archivo danado: nunca lanza
        f, motivo = CS.buscar(cache, foto, 644, SHA_M, VER)
        assert f is None and motivo.startswith("cache no valida")
        foto.write_bytes(b"foto a cambiada")                                         # otra foto = otra clave
        assert CS.buscar(cache, foto, 644, SHA_M, VER)[1] == "sin cache"
        assert CS.buscar(cache, t / "no_existe.jpg", 644, SHA_M, VER)[1].startswith("sin clave")


def test_cache_importar():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        viejo = (xd.RAIZ, xd.ENV, xd.TRABAJOS_DB)
        try:
            xd.RAIZ, xd.ENV, xd.TRABAJOS_DB = t, {"TRANSPORTE": "kaggle"}, t / "datos" / "trabajos.sqlite"
            lotes = t / "datos" / "kaggle" / "espejo" / "lotes"
            fotos = []
            for i in (1, 2):
                (t / f"{i}.jpg").write_bytes(f"foto {i}".encode())
                fotos.append({"tarea": i, "clave": _cache_de(lotes / "cache", t / f"{i}.jpg")})
            (lotes / "cache" / "basura.pt").write_bytes(b"x")
            (lotes / "pre_p3_x_cache.json").write_text(json.dumps({"fotos": fotos}))
            with closing(C.abrir(xd.TRABAJOS_DB)) as con:
                tr, _ = C.crear(con, "precodificacion", "pre_p3_x.zip", proyecto=3, estado="enviado")
                C.mover(con, tr["id"], "listo", resultado="pre_p3_x_cache.json")
            dest = t / "motor" / "cache_sam3"
            dest.mkdir(parents=True)
            CS.guardar(dest / f"{fotos[1]['clave']}.pt", CS.empaquetar(_feats(), fotos[1]["clave"], 644))   # ya estaba
            out = io.StringIO()
            with redirect_stdout(out):
                xd.cmd_cache_importar(NS(aplicar=False))
            assert "nuevos 1" in out.getvalue() and "ya en el hub 1" in out.getvalue() and "invalido 1" in out.getvalue()
            assert (lotes / "cache" / f"{fotos[0]['clave']}.pt").exists()                 # el reporte no mueve nada
            out = io.StringIO()
            with redirect_stdout(out):
                xd.cmd_cache_importar(NS(aplicar=True))
            assert all((dest / f"{f['clave']}.pt").is_file() for f in fotos), out.getvalue()
            assert sorted(p.name for p in (lotes / "cache").iterdir()) == ["basura.pt"]      # lo invalido se queda
            with closing(C.abrir(xd.TRABAJOS_DB)) as con:
                assert C.obtener(con, tr["id"])["estado"] == "importado"
            assert CS.buscar(dest, t / "1.jpg", 644, SHA_M, VER)[1] == "disco"
        finally:
            xd.RAIZ, xd.ENV, xd.TRABAJOS_DB = viejo


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("TEST CACHE_SAM3 OK")
