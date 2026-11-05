# Cache de SAM 3 para el clic del hub (P.3)

Objetivo de la fase: **clic en menos de 1 s y sin cargas de minutos en el hub** (laptop sin GPU). El worker (Kaggle,
GPU) codifica las fotos con el image encoder de SAM 3; el hub guarda esas codificaciones y el clic solo corre el
prompt encoder y el mask decoder (rapidos en CPU). Verificado el 03/11/2026 dentro del contenedor (ultralytics
8.4.174) y apoyado en el spike L.8 (`_archivo/L8_spike/`).

## 1. Como funciona hoy el clic

- `motor/interactivo.py`: un `SAM3Predictor` interactivo (`_predictor(imgsz)`) con SAM 3 **completo**: cargarlo en la
  laptop tarda 3-7 min; codificar una foto, 20-22 s (L.8).
- `_activar(p, ruta)`: si la foto esta en la cache en RAM (`_cache`, LRU de `CACHE_MAX` fotos, clave = ruta) pone
  `p.features, p.dataset`; si no, `p.set_image(ruta)` (codifica). Un hilo (`_bucle_pre`) precodifica por delante las
  siguientes tareas del proyecto con un segundo predictor que comparte el modelo.
- El clic: `p(points=[...], labels=[...], multimask_output=True)`.

## 2. Lo que dice la API (ultralytics 8.4.174, leido en el contenedor)

| Pieza | Comportamiento |
| --- | --- |
| `Predictor.set_image(img)` | `setup_model()` si hace falta, `setup_source(img)`, `preprocess` (letterbox a `imgsz`) y `self.features = get_im_features(im)` |
| `SAM2Predictor.get_im_features` (SAM 3 lo hereda) | `model.forward_image` + `_prepare_backbone_features` -> `{"image_embed": Tensor, "high_res_feats": [Tensor, Tensor]}`: **solo tensores** |
| `SAM2Predictor.setup_source` | ademas fija `_bb_feat_sizes` (las formas esperadas de cada tensor segun `imgsz`) |
| `Predictor.prompt_inference` | `features = get_im_features(im) if self.features is None else self.features`: **con features puestas no toca el encoder** |
| `src_shape` | sale de `self.batch` (la foto cargada): el hub siempre necesita la foto local (ya la tiene en `mis_imagenes`) |
| `build_interactive_sam3(ckpt, compile, with_backbone=True)` | existe `with_backbone=False` (sin el encoder de vision); `SAM3Predictor.get_model` no lo expone: hara falta una subclase (P.3.5) |

Conclusion: el clic con cache = `p.setup_source(foto_local)` + `p.features = cargadas` (tecnica de L.8, IoU >= 0.9995
en f16 frente al hub).

## 3. Diseno

### Clave
`<sha256 de la foto>_<imgsz>_<sha256 de sam3.pt, 12>_<ultralytics>` (nombre del archivo). Las features dependen de los
bytes de la foto, del `imgsz` (letterbox), de los pesos y del preprocesado de esa version de ultralytics. El sha de la
foto la identifica sin importar la ruta (hub, zip o Kaggle). El sha de `sam3.pt` lo da `pesos.json` en el worker; en el
hub se calcula una vez y se guarda junto a la cache (`modelo.json`: tamano, mtime, sha; se recalcula si cambian).

### Formato
`torch.save({"esquema": 1, "clave": ..., "imgsz": ..., "dtype": "float16", "features": {...}})`: tensores en **f16 y
en CPU** (4.1 MB por foto a imgsz 644; las formas crecen con `(imgsz/14)^2`: ~10 MB a 1008). Carga con
`torch.load(..., weights_only=True)` (solo tensores, numeros y textos: un archivo manipulado no ejecuta codigo), y antes
de usarla se valida: esquema, clave y **formas contra `_bb_feat_sizes`** de `setup_source`; se pasa a f32 en el hub.
Un archivo que no valida se ignora (y se codifica como hoy) con un aviso en el log.

### Donde vive
- Hub: `motor/cache_sam3/` (= `/app/cache_sam3` en el contenedor), ignorado en Git; presupuesto ~4 GB por 1000 fotos.
  Lo que no cabe se borra por antiguedad con un comando con reporte (no automatico).
- Transporte: la salida del worker trae `cache/<clave>.pt`; `worker --traer` la deja en el espejo (`cache/` se agrega a
  las carpetas de salida) y `xd.py cache-importar [--aplicar]` la mueve a `motor/cache_sam3/` (reporte: cuantas, MB,
  claves que no corresponden a fotos del hub).

### Cambios en el clic (`interactivo._activar`)
Orden: RAM (como hoy) -> **disco** (clave de la foto local; validar y cargar ~0.1-0.3 s) -> codificar (como hoy, solo
si no hay cache). Lo cargado de disco tambien entra a la cache en RAM. La precodificacion local (`_bucle_pre`) se salta
las fotos que ya estan en disco.

### Trabajo `precodificacion` (worker)
- `xd.py precodificar N [--todas] [--aplicar]`: zip con las fotos de las tareas del proyecto que aun no tienen cache
  (por sha), `trabajo.json` con `imgsz` del perfil, `worker.py` y el codigo. En Kaggle viaja como cualquier trabajo.
- `worker._precodificacion`: un `SAM3Predictor` (mismos overrides que el motor), `set_image` por foto, guarda las
  features en f16 en `salida/cache/`. Grupo de modelo propio (ya esta en `worker.ORDEN`).

### Hub liviano (P.3.5)
Si todas las fotos del proyecto tienen cache, el interactivo puede cargarse **sin backbone** (subclase de
`SAM3Predictor` cuyo `get_model` pasa `with_backbone=False`): menos RAM y carga mas rapida. Si una foto no tiene cache,
se cae al modelo completo como hoy. Se mide en la laptop (RAM, segundos de carga) antes de adoptarlo.

### Dos GPU en el worker (P.3.6; regla de oro 2 enmendada)
El lanzador parte los grupos SAM 3 (pre-etiquetado y precodificacion) en un subproceso por GPU
(`CUDA_VISIBLE_DEVICES`), cada uno con su SAM 3, y junta las salidas. Se mide con 1 y 2 GPU.

## 4. Riesgos y como se cubren
| Riesgo | Mitigacion |
| --- | --- |
| Otra version de ultralytics cambia `features` o el preprocesado | La version va en la clave y las formas se validan; `test_notebooks`/`test_lanzador` mantienen la misma version en hub y worker |
| f16 cambia la mascara | L.8: IoU >= 0.9995 y misma confianza; se vuelve a comprobar en P.3.7 con fotos reales |
| Disco del hub | Presupuesto y limpieza con reporte |
| Pickle malicioso | `weights_only=True` |
| El cliente cambia la foto | Otra foto = otro sha = otra clave (nunca se usa una cache equivocada) |

## 5. Medido en el spike de P.3.5 (05/11/2026, hub = laptop i7-7600U, CPU, imgsz 644, `motor/_p35/`, no versionado)

| | SAM 3 completo | Sin backbone (`with_backbone=False`) |
| --- | --- | --- |
| Carga | 345 s | **82 s** |
| RAM estable / pico al cargar | 2.7 GB / 5.5 GB | **0.8 GB** / 3.7 GB |
| Parametros | todo SAM 3 | 12 M (sin image encoder) |
| Clic desde la cache de disco | cargar 0.10 s + clic 0.11 s | cargar 0.42 s + clic 0.37 s; **siguientes 0.16 s** |
| Mascaras frente al completo con features en memoria | IoU 1.0 (f16) | **IoU 1.0, misma confianza** |

- Formas reales de las features a imgsz 644: `(1,256,46,46)`, `(1,32,184,184)`, `(1,64,92,92)`; archivo f16 4.3 MB.
- Codificar una foto en la laptop: 22.4 s (lo que la cache evita).
- El modelo sin backbone igual lee el `sam3.pt` completo (3.45 GB) para quedarse con 12 M de parametros: de ahi los
  82 s y el pico de 3.7 GB. Un checkpoint propio del interactivo (~50 MB, extraido una vez) deberia bajarlo a segundos.

## 6. Decision e implementacion (P.3.5, 05/11/2026)

**Opcion B: el hub usa siempre el interactivo liviano** (`MOTOR_INTERACTIVO=liviano`, defecto). Una foto sin cache
no se codifica en el hub: el clic no responde y el motor avisa "foto sin precodificar: `xd.py precodificar N` y
Enviar a Kaggle" (`/estado` -> `cache_disco.ultimo_motivo`, `clic_origen.sin_cache`). La precodificacion local queda
apagada. `MOTOR_INTERACTIVO=completo` vuelve al comportamiento anterior (carga de minutos, codifica en la CPU) para
cuando no haya worker.

**Checkpoint propio** (`motor/sam3_ligero.py`, `xd.py sam3-ligero [--aplicar]`): el `state_dict` del interactivo sin
image encoder, extraido una vez de `sam3.pt` y guardado como `motor/cache_sam3/sam3_interactivo_<sha12>.pt` con el sha de
`sam3.pt`; se carga con `strict=True` sobre la arquitectura construida sin leer `sam3.pt`. Si falta o no coincide con
los pesos actuales, se construye desde `sam3.pt` (82 s).

| Medido en la laptop | Completo | Sin backbone desde `sam3.pt` | **Checkpoint propio** |
| --- | --- | --- | --- |
| Extraer (una vez) | - | - | 58 s; 11.7 M parametros, 47 MB |
| Carga | 345 s | 82 s | **1 s** (0.7 s el `load_state_dict`) |
| RAM estable / pico | 2.7 / 5.5 GB | 0.8 / 3.7 GB | **0.4 / 0.46 GB** |
| Clic con cache | 0.11 s | 0.16 s | 0.31 s el primero, **0.16 s** despues |
| Mascaras | referencia | IoU 1.0 | **IoU 1.0, misma confianza** |
