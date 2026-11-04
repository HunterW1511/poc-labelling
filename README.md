# PoC-Labelling

Pre-etiquetado general y multiproyecto para vision artificial, sin licencias SaaS: del audio (o texto) que describe
un caso hasta un modelo "hijo" (YOLO) validado en vivo. Corre en una laptop sin GPU (el hub) mas GPU gratuita en
Kaggle (worker por API) o, de respaldo, en Colab.
Cada paso es un comando de `xd.py`; la UI (`ui.py`) solo los muestra y los lanza.

Reglas para agentes (Claude Code, Kiro): [CLAUDE.md](CLAUDE.md).
Manual de uso paso a paso: [docs/manual.md](docs/manual.md).

## Arquitectura

| Pieza | Donde | Que hace |
| --- | --- | --- |
| Label Studio 1.23 + Postgres | Docker (`docker-compose.yml`), http://127.0.0.1:8080 | Proyectos, tareas y revision humana. `mis_imagenes/` montada en solo lectura |
| Motor (`motor/`) | Docker, puerto 9090 | Backend ML: clic interactivo de SAM 3 y cola semantica de respaldo. `GET /estado` dice que esta cargado y por que espera la cola |
| `xd.py`, `ui.py`, `tablero.py` | Host | CLI (fuente de verdad), UI en http://127.0.0.1:8090 y tablero de solo lectura |
| Cola de trabajos (`datos/trabajos.sqlite`) | Host (disco local, nunca en Drive) | Estado de cada trabajo externo (asistente, pre-etiquetado, entrenamiento): sobrevive a reinicios; Drive solo transporta. Diseno: [docs/cola_trabajos.md](docs/cola_trabajos.md) |
| `capturar.py`, `ver_cajas.py` | Host | Webcam: captura de fotos y modelo en vivo (OpenVINO o PyTorch) |
| Worker (`motor/worker.py`, viaja en cada zip) | **Kaggle** (kernel privado `xd-worker`, GPU T4 x2) o Colab T4 (`notebooks/worker.ipynb`) | Un solo codigo para asistente (Whisper + qwen2.5:14b), pre-etiquetado (SAM 3) y entrenamiento (YOLO). Contrato: [docs/worker_contrato.md](docs/worker_contrato.md); Kaggle: [docs/worker_kaggle.md](docs/worker_kaggle.md) |
| Transporte (`transporte.py`) | Host | `TRANSPORTE=kaggle` (espejo local `datos/kaggle/espejo`, envios por dataset privado) o `drive` (Drive para escritorio + Colab) |

Direccion del piloto: el hub queda con Label Studio, la UI y el clic interactivo; lo pesado va al worker. Siguiente:
la cache de SAM 3 precodificada en el worker para un clic rapido en el hub (P.3).

## Instalacion

1. Docker Desktop (WSL2), Python 3.12-3.14 y Google Drive para escritorio.
2. `copy .env.example .env` y llenar los `***` (ver los comentarios del archivo). Nunca subir `.env`.
3. Pesos de SAM 3 (`sam3.pt`, unos 3.45 GB): pedirlos al responsable; no van en Git. Copiarlos a la raiz (y a
   `PoC-Labelling/` en Drive si usaras Colab).
4. `docker compose up -d` y `pip install -r requirements.txt`.
5. `python xd.py estado` (servicios UP) y `python xd.py test` (todo en verde).
6. Worker en **Kaggle** (recomendado; una cuenta por persona, los terminos de Kaggle no permiten compartirla):
   - Cuenta con el telefono verificado; en Settings -> API crea un token y guardalo en `~/.kaggle/access_token`
     (sin extension `.txt`; nunca en el repo).
   - En `.env`: `TRANSPORTE=kaggle` y `KAGGLE_USUARIO=<tu usuario>` (el de la URL de tu perfil).
   - Una vez: `python xd.py kaggle-pesos` (reporte) y `python xd.py kaggle-pesos --aplicar` (sube `sam3.pt` como
     dataset privado `xd-pesos`; ~3 min). Lo corre la persona, no un agente.
7. Worker en **Colab** (respaldo): `TRANSPORTE=drive` y `python xd.py cuadernos --llevar --aplicar` (copia
   `worker.ipynb` a `Colab Notebooks` en tu Drive).

## Flujo de un proyecto

| Paso | Comando | Donde corre |
| --- | --- | --- |
| 1. Caso -> spec | `asistente SLUG --audio X` / `--texto X`, luego `asistente-importar SLUG [--aplicar]`. Sin asistente: `spec-nueva SLUG --titulo T [--aplicar]`, editar y `validar SLUG` | Worker o a mano |
| 2. Crear proyecto | `crear-proyecto SLUG [--aplicar]` (se niega si la spec tiene errores) | Host + Label Studio |
| 3. Fotos | `plan SLUG`, `python capturar.py SLUG`, `sincronizar SLUG` | Host (webcam) |
| 4. Pre-etiquetado | `preetiquetar N --muestra 30 [--aplicar]`, worker, `lote-importar --fijar-version` | Worker |
| 5. Revision | Label Studio + clic de SAM 3 | Motor (CPU) |
| 6. Modelo hijo | `dataset N --drive [--epochs E ...]`, worker, `registrar N --run ultimo --activar` | Worker (Kaggle: las 2 T4) |
| 7. Mas tareas | `preetiquetar N --modo hijo` | Worker |
| 8. Validacion | `aceptacion N`, `modelos N` | Host y contenedor |
| 9. En vivo | `ver N [--backend auto|pt|openvino]` | Host |

"Worker" = Kaggle: `worker --enviar --aplicar`, `worker --estado`, `worker --traer --aplicar` (en la UI: Enviar /
Estado / Traer de Kaggle); o Colab: `worker.ipynb` celdas 1 y 2 y luego Reconciliar.
Todo lo que escribe tiene modo reporte; `--aplicar` escribe. La UI exige el reporte OK antes de aplicar.
Referencia de la spec: `motor/plantillas/LEEME_spec.md`.

## Comandos utiles

- `python xd.py -h` lista todo; `python xd.py <comando> -h` detalla cada uno.
- `python xd.py test [--solo host|motor] [-k texto] [-v]`: los tests del host y del contenedor; rc 0 solo si todos pasan.
- `python xd.py cuadernos [--traer | --llevar] [--forzar] [--aplicar]`: el repo es la fuente de verdad de los cuadernos.
- `python xd.py trabajos [--todos] [--tipo T] [--estado E]`: la cola de trabajos. `--reconciliar [--aplicar]` la
  pone al dia con lo que hay en Drive; `--reintentar ID [--aplicar]` vuelve a enviar un trabajo en error.
- `python xd.py worker --enviar | --estado | --traer [--aplicar] [--limite MIN]`: envia a Kaggle los trabajos en espera
  (un envio = una version del dataset privado `xd-envios` + el kernel privado `xd-worker`), consulta el kernel y trae
  la salida al espejo local (reconcilia la cola; lo que no vuelve queda en error para Reintentar).
- `python xd.py kaggle-pesos [--pesos RUTA] [--aplicar]`: sube `sam3.pt` + SAM License como dataset **privado**
  `<KAGGLE_USUARIO>/xd-pesos` (una cuenta por persona; token en `~/.kaggle/access_token`). El `--aplicar` lo corre la persona.
- `python xd.py reiniciar-motor [--precalentar --proyecto N]`, `python xd.py archivar ARCHIVO [--aplicar]` (asist_*, lote_p* o dataset_p*).
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