# PoC-Labelling

Pre-etiquetado general y multiproyecto para vision artificial, sin licencias SaaS: del audio (o texto) que describe
un caso hasta un modelo "hijo" (YOLO) validado en vivo. Corre en una laptop sin GPU mas GPU gratuita en Colab.
Cada paso es un comando de `xd.py`; la UI (`ui.py`) solo los muestra y los lanza.

Contexto completo, decisiones y ruta al piloto: [docs/contexto.md](docs/contexto.md).
Reglas para agentes (Claude Code, Kiro): [CLAUDE.md](CLAUDE.md).
Manual de uso paso a paso: [docs/manual.md](docs/manual.md).

## Arquitectura

| Pieza | Donde | Que hace |
| --- | --- | --- |
| Label Studio 1.23 + Postgres | Docker (`docker-compose.yml`), http://127.0.0.1:8080 | Proyectos, tareas y revision humana. `mis_imagenes/` montada en solo lectura |
| Motor (`motor/`) | Docker, puerto 9090 | Backend ML: clic interactivo de SAM 3 y cola semantica de respaldo. `GET /estado` dice que esta cargado y por que espera la cola |
| `xd.py`, `ui.py`, `tablero.py` | Host | CLI (fuente de verdad), UI en http://127.0.0.1:8090 y tablero de solo lectura |
| `capturar.py`, `ver_cajas.py` | Host | Webcam: captura de fotos y modelo en vivo (OpenVINO o PyTorch) |
| Cuadernos (`notebooks/`) | Colab T4 | Asistente (Whisper + qwen2.5:14b), pre-etiquetado de lotes (SAM 3) y entrenamiento (YOLO). Intercambio por Drive para escritorio |

Direccion del piloto (docs/contexto.md, fases P.x): el trabajo pesado se va a un worker en Kaggle; el hub queda con
Label Studio, la UI y el clic interactivo usando la cache de SAM 3 que precodifica el worker.

## Instalacion

1. Docker Desktop (WSL2), Python 3.12-3.14 y Google Drive para escritorio.
2. `copy .env.example .env` y llenar los `***` (ver los comentarios del archivo). Nunca subir `.env`.
3. Pesos de SAM 3 (`sam3.pt`, unos 3.3 GB): pedirlos al responsable; no van en Git. Copiarlos a la raiz y a
   `PoC-Labelling/` en Drive (los usa Colab).
4. `docker compose up -d` y `pip install -r requirements.txt`.
5. `python xd.py estado` (servicios UP) y `python xd.py test` (todo en verde).
6. `python xd.py cuadernos --llevar --aplicar` copia los cuadernos a `Colab Notebooks` en tu Drive.

## Flujo de un proyecto

| Paso | Comando | Donde corre |
| --- | --- | --- |
| 1. Caso -> spec | `asistente SLUG --audio X` / `--texto X`, luego `asistente-importar SLUG [--aplicar]`. Sin asistente: `spec-nueva SLUG --titulo T [--aplicar]`, editar y `validar SLUG` | Colab (cuaderno asistente) o a mano |
| 2. Crear proyecto | `crear-proyecto SLUG [--aplicar]` (se niega si la spec tiene errores) | Host + Label Studio |
| 3. Fotos | `plan SLUG`, `python capturar.py SLUG`, `sincronizar SLUG` | Host (webcam) |
| 4. Pre-etiquetado | `preetiquetar N --muestra 30 [--aplicar]`, cuaderno preetiquetado, `lote-importar --fijar-version` | Colab |
| 5. Revision | Label Studio + clic de SAM 3 | Motor (CPU) |
| 6. Modelo hijo | `dataset N --drive`, cuaderno entrenamiento (poner PROYECTO), `registrar N --run ultimo --activar` | Colab |
| 7. Mas tareas | `preetiquetar N --modo hijo` | Colab |
| 8. Validacion | `aceptacion N`, `modelos N` | Host y contenedor |
| 9. En vivo | `ver N [--backend auto|pt|openvino]` | Host |

Todo lo que escribe tiene modo reporte; `--aplicar` escribe. La UI exige el reporte OK antes de aplicar.
Referencia de la spec: `motor/plantillas/LEEME_spec.md`.

## Comandos utiles

- `python xd.py -h` lista todo; `python xd.py <comando> -h` detalla cada uno.
- `python xd.py test [--solo host|motor] [-k texto] [-v]`: los tests del host y del contenedor; rc 0 solo si todos pasan.
- `python xd.py cuadernos [--traer | --llevar] [--forzar] [--aplicar]`: el repo es la fuente de verdad de los cuadernos.
- `python xd.py reiniciar-motor [--precalentar --proyecto N]`, `python xd.py archivar ARCHIVO [--aplicar]`.
- `motor/corregir_pares.py` (manual, en el contenedor): corrige pares de clases confundidas; lo consume `exportar_yolo --correcciones`.
- `herramientas/`: `inventario.ps1` (que datos hay), `limpiar.ps1` (vaciar datos, con reporte; `-Aplicar` borra) y
  `rotar_token.ps1` (rota el token de Label Studio sin mostrarlo). Rutas pensadas para `C:\PoC-Labelling`.

## Privacidad

- Nunca a Git ni a chats: `.env`, fotos, audios, textos del asistente, lotes, datasets ni modelos (`.gitignore` los
  bloquea, incluidas imagenes, audio y CSV en cualquier carpeta).
- Fotos de personas solo con permiso y sin terceros al fondo. Al terminar una prueba: `herramientas/limpiar.ps1` y
  vaciar la papelera de Drive.

## Problemas conocidos

- En CPU, cargar SAM 3 tarda de 3 a 7 minutos y codificar una foto, unos 20 s. `GET /estado` muestra
  `semantico_esperando_carga`, `semantico_cargando` y `precodificacion_en_pausa`: una cola quieta no es un bloqueo.
- Los dos SAM 3 (semantico e interactivo) pueden convivir si alguien etiqueta durante un lote: unos 9 GB.
  Docker necesita 10 GB o mas (`.wslconfig`).
- `ver`: OpenVINO siempre con `intel:cpu` y exportacion rectangular (L.9). La GPU Intel HD 620 no sirve con
  OpenVINO 2026 (deja `kernel.errors.txt`, ignorado en Git).
- Tras cambiar codigo de `motor/`: `docker compose restart motor` (gunicorn carga el codigo al arrancar).
- Si la cola de verdad parece bloqueada (`/estado` sin espera ni carga y sin lineas nuevas en el log), vuelca las pilas
  de los hilos del motor con py-spy (se pierde al reconstruir la imagen; solo para diagnostico):
  `docker compose exec -T motor pip install -q py-spy==0.4.0`, luego
  `docker cp herramientas/volcar_motor.sh ls_motor:/tmp/volcar.sh` y `docker exec --privileged ls_motor sh /tmp/volcar.sh`.
  Busca los hilos `sam3`, `sam3-int` y `sam3-pre` y en que linea esperan.