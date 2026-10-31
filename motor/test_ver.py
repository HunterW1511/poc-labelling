"""L.9: forma rectangular de la exportacion OpenVINO de ver_cajas (sin camara ni modelo). Uso: python motor/test_ver.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ver_cajas import forma_rect   # noqa: E402

assert forma_rect(640, 720, 1280) == [384, 640], forma_rect(640, 720, 1280)
assert forma_rect(960, 720, 1280) == [544, 960], forma_rect(960, 720, 1280)
assert forma_rect(640, 480, 640) == [480, 640], forma_rect(640, 480, 640)
assert forma_rect(640, 1280, 720) == [640, 384], forma_rect(640, 1280, 720)
assert all(x % 32 == 0 for x in forma_rect(960, 1080, 1920))
print("TEST VER OK: forma rectangular multiplo de 32")