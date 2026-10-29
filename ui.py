"""Etapa E: interfaz web delgada sobre xd.py (solo biblioteca estandar).
E.1 trabajo unico + salida en vivo; E.2 tablero (tablero.py); E.3 acciones con reporte y confirmacion;
E.4 asistente (audio del navegador); E.5 pasos externos; E.6 herramientas del host (capturar, ver).
Uso: python ui.py  ->  http://127.0.0.1:8090"""
import codecs, json, os, re, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import tablero

RAIZ = Path(__file__).resolve().parent
HTML = RAIZ / "ui" / "index.html"
AUDIOS, TEXTOS = RAIZ / "ui" / "audios", RAIZ / "ui" / "textos"   # datos personales: no compartir ni subir a git
HOST, PUERTO = "127.0.0.1", 8090
MAX_AUDIO = 60 * 1024 * 1024
PERMITIDOS = {"estado", "precalentar", "reiniciar-motor"}      # servicios (E.1)
SCRIPTS = {"xd.py", "capturar.py"}
ARG = re.compile(r"^[A-Za-z0-9_.,:@=/\\ -]{0,200}$")
VALOR = re.compile(r"^[A-Za-z0-9_.,:@=/-]{1,200}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
VOCAB = re.compile(r"^[^\x00-\x1f\"]{1,300}$")
MODELO = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")
TEXTO = re.compile(r"^[^\x00-\x1f\"]{1,120}$")               # titulos: admite espacios (sin shell: lista de args)
# id = "slug" | "n" | "archivo" | None; aplicar = tiene modo reporte (se confirma con --aplicar);
# script = otro programa del host (por defecto xd.py); ventana = abre una ventana de OpenCV en el escritorio
ACCIONES = {
    "spec-nueva": {"id": "slug", "aplicar": True, "titulo": "Spec desde plantilla", "opciones": {"--titulo": "texto"}},
    "validar": {"id": "slug", "titulo": "Validar spec"},
    "crear-proyecto": {"id": "slug", "aplicar": True, "titulo": "Crear proyecto"},
    "capturar": {"id": "slug", "script": "capturar.py", "ventana": True, "titulo": "Capturar fotos",
                 "opciones": {"--total": "int", "--carpeta": "str", "--camara": "int"}},
    "sincronizar": {"id": "slug", "titulo": "Sincronizar fotos"},
    "plan": {"id": "slug", "titulo": "Plan de captura", "opciones": {"--total": "int", "--variaciones": "flag"}},
    "asistente-importar": {"id": "slug", "aplicar": True, "titulo": "Resultado del asistente",
                           "opciones": {"--forzar": "flag", "--comparar": "str"}},
    "preetiquetar": {"id": "n", "aplicar": True, "titulo": "Pre-etiquetar muestra",
                     "opciones": {"--muestra": "int", "--modo": ["auto", "sam3", "hijo"]}},
    "lote-importar": {"id": None, "titulo": "Importar predicciones", "opciones": {"--fijar-version": "flag"}},
    "dataset": {"id": "n", "titulo": "Exportar dataset", "opciones": {"--formato": ["det", "seg", "ambos"], "--drive": "flag"}},
    "registrar": {"id": "n", "aplicar": True, "titulo": "Registrar modelo", "opciones": {"--run": "str", "--activar": "flag"}},
    "modelos": {"id": "n", "titulo": "Modelos"},
    "aceptacion": {"id": "n", "titulo": "Aceptacion", "opciones": {"--versiones": "str"}},
    "ver": {"id": "n", "ventana": True, "titulo": "Ver en vivo",
            "opciones": {"--modelo": "str", "--camara": "int", "--conf": "str", "--imgsz": "int"}},
    "borrar-proyecto": {"id": "slug", "aplicar": True, "titulo": "Borrar proyecto"},
    "archivar": {"id": "archivo", "aplicar": True, "titulo": "Archivar"},
}
ESCRIBEN_SIN_APLICAR = {"sincronizar", "lote-importar"}        # escriben en Label Studio sin modo reporte


class Trabajo:
    """Un solo trabajo a la vez (nunca dos modelos pesados ni dos ventanas de camara juntos)."""
    def __init__(self):
        self.lock = threading.Lock()
        self.p, self.id, self.cmd, self.salida = None, 0, [], []
        self.rc, self.t0, self.fin = None, 0.0, None

    def corriendo(self):
        return self.p is not None and self.rc is None

    def fue_ok(self, cmd, args):
        """El ultimo trabajo fue exactamente este comando de xd.py (sin --aplicar) y termino OK."""
        return (not self.corriendo() and self.rc == 0 and len(self.cmd) > 2
                and Path(self.cmd[2]).name == "xd.py" and self.cmd[3:] == [cmd, *args])

    def lanzar(self, cmd, args, script="xd.py"):
        if script not in SCRIPTS:
            raise ValueError(f"script no permitido: {script}")
        with self.lock:
            if self.corriendo():
                raise RuntimeError("ya hay un trabajo corriendo")
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            self.cmd = [sys.executable, "-u", str(RAIZ / script), *([cmd] if script == "xd.py" else []), *args]
            self.id += 1
            self.salida, self.rc, self.t0, self.fin = [], None, time.time(), None
            self.p = subprocess.Popen(self.cmd, cwd=RAIZ, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, env=env)
            threading.Thread(target=self._leer, args=(self.p,), daemon=True).start()
            return self.id

    def _leer(self, p):
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            b = p.stdout.read1(4096)
            if not b:
                break
            self.salida.append(dec.decode(b))
        self.salida.append(dec.decode(b"", final=True))
        rc = p.wait()
        self.fin = time.time()
        self.rc = rc

    def cancelar(self):
        """Cierra el proceso y sus hijos (p. ej. la ventana de ver_cajas.py que abre xd.py ver)."""
        if not self.corriendo():
            return
        if os.name == "nt":
            subprocess.call(["taskkill", "/T", "/F", "/PID", str(self.p.pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.p.terminate()

    def estado(self):
        return {"id": self.id, "cmd": " ".join([Path(self.cmd[2]).name, *self.cmd[3:]]) if self.cmd else "",
                "salida": "".join(self.salida), "rc": self.rc, "corriendo": self.corriendo(),
                "seg": round((self.fin or time.time()) - self.t0) if self.id else 0}


T = Trabajo()


def armar(d):
    """Valida una accion -> (comando, args, script). ValueError o PermissionError si no procede."""
    nombre = d.get("accion")
    a = ACCIONES.get(nombre)
    if not a:
        raise ValueError(f"accion no permitida: {nombre}")
    args, n = [], None
    if a["id"] == "slug":
        slug = str(d.get("slug") or "")
        if not SLUG.match(slug):
            raise ValueError(f"slug invalido: {slug!r}")
        args.append(slug)
        n = tablero.proyecto_de(slug)
    elif a["id"] == "n":
        n = d.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError(f"proyecto invalido: {n!r}")
        args.append(str(n))
    elif a["id"] == "archivo":
        nom = str(d.get("archivo") or "")
        if Path(nom).name != nom or not re.fullmatch(r"(asist_.+|lote_p\d+_.+)\.zip", nom):
            raise ValueError(f"archivo no archivable: {nom!r}")
        args.append(nom)
    defs = a.get("opciones") or {}
    for k, v in (d.get("opciones") or {}).items():
        tipo = defs.get(k)
        if tipo is None:
            raise ValueError(f"{nombre}: opcion no permitida {k}")
        if tipo == "flag":
            if v is True:
                args.append(k)
            elif v not in (False, None):
                raise ValueError(f"{k}: true o false")
            continue
        v = "" if v is None else str(v).strip()
        if not v:
            continue
        if tipo == "int" and not re.fullmatch(r"\d{1,6}", v):
            raise ValueError(f"{k}={v!r}: debe ser un entero")
        if isinstance(tipo, list) and v not in tipo:
            raise ValueError(f"{k}={v!r}: debe ser {tipo}")
        if tipo == "str" and not VALOR.match(v):
            raise ValueError(f"{k}={v!r}: caracteres no permitidos")
        if tipo == "texto" and not TEXTO.match(v):
            raise ValueError(f"{k}: texto de una linea, sin comillas, hasta 120 caracteres")
        args += [k, v]
    aplicar = bool(d.get("aplicar"))
    if aplicar and not a.get("aplicar"):
        raise ValueError(f"{nombre} no tiene modo --aplicar")
    if (aplicar or nombre in ESCRIBEN_SIN_APLICAR) and n in tablero.PROTEGIDOS:
        raise PermissionError(f"proyecto {n} protegido: {nombre} no se ejecuta desde la UI")
    if nombre == "lote-importar":
        prot = sorted(p for p, l in tablero._lotes(tablero._drive()).items()
                      if l["sin_importar"] and p in tablero.PROTEGIDOS)
        if prot:
            raise PermissionError(f"hay predicciones sin importar de proyectos protegidos {prot}: archivalas en Drive")
    if nombre == "crear-proyecto":                     # defensa en el servidor: nunca crear con spec invalida
        e, _ = tablero.xd._validar_spec(tablero._json(tablero.PROYECTOS / args[0] / "spec.json"), args[0])
        if e:
            raise ValueError(f"la spec de {args[0]} tiene {len(e)} errores; corrigela antes de crear: {e[0]}")
    if aplicar:
        if not T.fue_ok(nombre, args):
            raise PermissionError("primero corre el reporte con las mismas opciones y que termine OK")
        args.append("--aplicar")
    return nombre, args, a.get("script", "xd.py")


def guardar_audio(h, rfile):
    """Cuerpo crudo del POST -> ui/audios/<slug>_<fecha><ext>."""
    slug, ext = h.get("X-Slug") or "", (h.get("X-Ext") or "").lower()
    if not SLUG.match(slug):
        raise ValueError("slug invalido: solo minusculas, digitos, _ o -")
    if ext not in tablero.buzon.AUDIO_EXT:
        raise ValueError(f"formato {ext!r} no soportado: {sorted(tablero.buzon.AUDIO_EXT)}")
    n = int(h.get("Content-Length") or 0)
    if not 0 < n <= MAX_AUDIO:
        raise ValueError("audio vacio o de mas de 60 MB")
    AUDIOS.mkdir(parents=True, exist_ok=True)
    f = AUDIOS / f"{slug}_{time.strftime('%Y%m%d-%H%M%S')}{ext}"
    f.write_bytes(rfile.read(n))
    return {"audio": f.name, "kb": round(n / 1024)}


def _txt(slug, tipo, texto):
    TEXTOS.mkdir(parents=True, exist_ok=True)
    f = TEXTOS / f"{slug}_{time.strftime('%Y%m%d-%H%M%S')}_{tipo}.txt"
    f.write_text(texto, encoding="utf-8")
    return str(f)


def armar_asistente(d):
    """Formulario del asistente -> args de xd.py asistente. Texto y respuestas viajan en .txt."""
    slug = str(d.get("slug") or "")
    if not SLUG.match(slug):
        raise ValueError("slug invalido: solo minusculas, digitos, _ o -")
    args = [slug]
    audio = str(d.get("audio") or "")
    if audio:
        if Path(audio).name != audio or not (AUDIOS / audio).is_file():
            raise ValueError("audio no encontrado en ui/audios")
        args += ["--audio", str(AUDIOS / audio)]
    texto, resp = str(d.get("texto") or "").strip(), str(d.get("respuestas") or "").strip()
    continuar = d.get("continuar") is True
    if not (audio or texto or continuar):
        raise ValueError("graba o sube un audio, o escribe el texto del caso")
    if continuar and not (resp or audio or texto):
        raise ValueError("escribe las respuestas a las preguntas")
    if texto:
        args += ["--texto", _txt(slug, "texto", texto)]
    if resp:
        args += ["--respuestas", _txt(slug, "respuestas", resp)]
    voc = str(d.get("vocabulario") or "").strip()
    if voc:
        if not VOCAB.match(voc):
            raise ValueError("vocabulario: texto de una linea, sin comillas")
        args += ["--vocabulario", voc]
    mod = str(d.get("modelo") or "").strip()
    if mod:
        if not MODELO.match(mod):
            raise ValueError("modelo invalido (ej. qwen2.5:14b)")
        args += ["--modelo", mod]
    if continuar:
        args.append("--continuar")
    if d.get("nuevo") is True:
        args.append("--nuevo")
    return args


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _enviar(self, codigo, cuerpo, tipo):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, codigo, datos):
        self._enviar(codigo, json.dumps(datos).encode("utf-8"), "application/json")

    def _api_ok(self):
        if self.headers.get("X-XD") != "1":            # otra pagina del navegador no puede mandarla
            self._json(403, {"error": "falta la cabecera X-XD"})
            return False
        return True

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._enviar(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if not self.path.startswith("/api/"):
            return self._json(404, {"error": "no existe"})
        if not self._api_ok():
            return
        try:
            if self.path == "/api/trabajo":
                return self._json(200, T.estado())
            if self.path == "/api/proyectos":
                return self._json(200, tablero.proyectos())
            if self.path == "/api/servicios":
                return self._json(200, tablero.servicios())
            if self.path == "/api/externos":
                return self._json(200, tablero.externos())
            if self.path == "/api/acciones":
                return self._json(200, {"acciones": ACCIONES, "protegidos": sorted(tablero.PROTEGIDOS)})
            if self.path.startswith("/api/asistente?"):
                slug = (parse_qs(urlparse(self.path).query).get("slug") or [""])[0]
                if not SLUG.match(slug):
                    return self._json(400, {"error": "slug invalido"})
                return self._json(200, tablero.asistente_detalle(slug))
        except Exception as e:                         # solo lectura: el error se muestra en la UI
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        self._json(404, {"error": "no existe"})

    def do_POST(self):
        if not self._api_ok():
            return
        if self.path == "/api/audio":                  # cuerpo crudo, no JSON
            try:
                return self._json(200, guardar_audio(self.headers, self.rfile))
            except ValueError as e:
                return self._json(400, {"error": str(e)})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"error": "JSON invalido"})
        try:
            if self.path == "/api/ejecutar":
                cmd, args = d.get("cmd"), d.get("args") or []
                if cmd not in PERMITIDOS:
                    return self._json(400, {"error": f"comando no permitido: {cmd}"})
                if not isinstance(args, list) or not all(isinstance(x, str) and ARG.match(x) for x in args):
                    return self._json(400, {"error": "argumentos invalidos"})
                return self._json(200, {"id": T.lanzar(cmd, args)})
            if self.path == "/api/accion":
                cmd, args, script = armar(d)
                return self._json(200, {"id": T.lanzar(cmd, args, script)})
            if self.path == "/api/asistente":
                return self._json(200, {"id": T.lanzar("asistente", armar_asistente(d))})
            if self.path == "/api/cancelar":
                T.cancelar()
                return self._json(200, T.estado())
        except PermissionError as e:
            return self._json(403, {"error": str(e)})
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except RuntimeError as e:
            return self._json(409, {"error": str(e)})
        self._json(404, {"error": "no existe"})


def main():
    srv = ThreadingHTTPServer((HOST, PUERTO), Manejador)
    print(f"UI en http://{HOST}:{PUERTO}  (Ctrl+C para salir)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nUI detenida")


if __name__ == "__main__":
    main()
