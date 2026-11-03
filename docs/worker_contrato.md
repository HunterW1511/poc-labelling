# Contrato del worker (P.2.2)

Un solo codigo (`motor/worker.py`, P.2.3) procesa los cuatro tipos de trabajo en Kaggle, en Colab (respaldo) o en
local. Este documento fija que entra, que sale y las reglas de ejecucion. Lo hace cumplir el codigo de P.2.3 con
sus tests; el hub no cambia de formato de resultados.

## 1. Estado de partida (antes de P.2)

Los tres cuadernos repiten el mismo bucle: buscar zips sin resultado, extraerlos, cargar el `codigo/` que trae el
zip, procesar, y escribir el resultado de forma atomica junto al zip. Lo que cambia por tipo:

| Tipo | Zip (lo arma el hub) | Trae `codigo/` | Entrada propia | Resultado de hoy | Error de hoy |
| --- | --- | --- | --- | --- | --- |
| asistente | `asist_<slug>_<fecha>.zip` | si (`buzon.MODULOS`) | `entrada.json` (+ `audio/`) | `<stem>_resultado.json` | `<stem>_error.txt` |
| preetiquetado | `lote_p<N>_<version>_<fecha>.zip` | si (`lote.py`, `pipeline.py`...) | `manifiesto.json`, `fotos/`, (`modelo/best.pt` en modo hijo) | `<stem>_pred.json` | ninguno (se pierde) |
| entrenamiento | `dataset_p<N>_..._<fecha>.zip` | **no**: la logica vive en el cuaderno | `resumen.json`, `det/` o `seg/` | `runs/<RUN>/weights/{best.pt, metricas.json}` (RUN = stem o stem_formato) | ninguno |
| precodificacion | (P.3) | - | - | - | - |

Los parametros del entrenamiento (`FORMATO`, `EPOCHS`, `IMGSZ`...) se editan hoy a mano en la celda 1.

## 2. Entrada: el trabajo

**Regla: todo zip trae su codigo** (`codigo/` con `worker.py` y lo que use su tipo). El lanzador (kernel de
Kaggle o cuaderno de Colab) es fijo y delgado: extrae, pone `codigo/` del zip en `sys.path`, importa `worker` y
llama `worker.procesar(...)`. Asi el codigo que corre es siempre el del hub que armo el trabajo, y un cambio en el
repo no obliga a tocar el lanzador.

Cada zip agrega un encabezado comun, `trabajo.json`, sin quitar sus archivos propios:

```json
{
  "esquema": 1,
  "tipo": "preetiquetado",          // asistente | preetiquetado | entrenamiento | precodificacion
  "trabajo": "lote_p3_sam3-xx_20261103-140000",   // = stem del zip
  "proyecto": 3,                    // null en asistente
  "slug": null,                     // asistente siempre
  "creado": "2026-11-03T14:00:00",
  "parametros": {}                  // propios del tipo (seccion 2.1)
}
```

### 2.1 Parametros por tipo
| Tipo | `parametros` | Notas |
| --- | --- | --- |
| asistente | `{}` | Todo sigue en `entrada.json` (modelo LLM, STT, idioma) |
| preetiquetado | `{}` | Todo sigue en `manifiesto.json` (modo, perfil, version, tareas) |
| entrenamiento | `formato` (det/seg), `modelo` (yolo11n...), `imgsz` 960, `epochs` 100, `patience` 30, `batch` 16, `conf_conteo` 0.25 | Los fija `xd.py dataset` (opciones con estos defectos); se acaba la edicion a mano del cuaderno |
| precodificacion | (P.3) | |

**Compatibilidad:** un zip sin `trabajo.json` (armado antes de P.2.3) se acepta; el tipo se deduce del nombre
(`asist_`, `lote_p`, `dataset_p`). Un `esquema` mayor que el del worker -> error claro, no un intento.

## 3. Salida: el resultado

`worker.procesar(d, salida, cache, entorno)` escribe en la carpeta `salida` que le da el lanzador:

| Archivo | Cuando | Contenido |
| --- | --- | --- |
| `<stem>.estado.json` | **siempre**, al final (bien o mal) | ver abajo; es la marca de "procesado" |
| `<stem>_resultado.json` | asistente OK | igual que hoy |
| `<stem>_pred.json` | preetiquetado OK | igual que hoy |
| `runs/<RUN>/...` | entrenamiento OK | igual que hoy: `weights/best.pt`, `weights/metricas.json`, graficas |
| `<stem>_error.txt` | cualquier fallo | traceback completo (hoy solo asistente) |

```json
{
  "esquema": 1, "trabajo": "<stem>", "tipo": "preetiquetado", "ok": true,
  "inicio": "...", "fin": "...", "seg": 123.4,
  "resultado": "<stem>_pred.json",            // o "runs/<RUN>" o null si fallo
  "error": null,                               // ultimas lineas del error si fallo
  "entorno": {"proveedor": "kaggle", "gpu": "Tesla T4", "python": "3.x", "torch": "x", "cuda": "x",
              "ultralytics": "8.4.174"}
}
```

Los nombres del resultado no cambian: `lote-importar`, `asistente-importar`, `registrar` y la reconciliacion de
P.1 siguen funcionando igual. Con Drive el lanzador usa como `salida` la misma carpeta del zip (como hoy); con
Kaggle, `/kaggle/working/` y el hub lo baja con el adaptador (P.2.5). `estado.json` es nuevo y la
reconciliacion lo usara para pasar a `error` tambien lotes y entrenamientos (hoy no se detecta).

## 4. Reglas de ejecucion

1. **Un modelo pesado a la vez.** El lanzador procesa los trabajos agrupados por modelo y libera memoria entre
   grupos (`cache.clear()`, `gc`, `torch.cuda.empty_cache()`, y `ollama stop` despues del asistente). Orden por
   envio: preetiquetado sam3 -> preetiquetado hijo -> precodificacion -> entrenamiento -> asistente (Whisper y
   luego LLM, como hoy en `trabajo.py`).
2. **Aislamiento de fallos.** Cada trabajo en su `try`: un fallo deja su `_error.txt` y `estado.json` con
   `ok: false` y el envio sigue con el siguiente.
3. **Escritura atomica.** Todo archivo de salida se escribe a `.tmp` y se renombra (nunca un resultado a medias).
4. **Idempotencia.** Si ya existe `<stem>.estado.json`, el trabajo se salta. Para reintentar, el hub archiva el
   estado viejo (como hoy `trabajos --reintentar` con el `_error.txt`).
5. **Codigo limpio por trabajo.** Antes de cada trabajo se quitan de `sys.modules` los modulos del `codigo/`
   anterior (como hoy los cuadernos).
6. **Entorno registrado.** Python, torch, CUDA, GPU y ultralytics van en cada `estado.json`; las versiones fijas
   (`ultralytics==8.4.174`, timm, CLIP, faster-whisper, ctranslate2) las instala el lanzador y `test_notebooks` las
   compara con el hub.
7. **Privacidad.** El envio lleva fotos: solo a datasets **privados**. Tras importar, el hub borra la version del
   envio en Kaggle (P.2.7). Nada se imprime del token ni de `.env`.
8. **Sin red hacia el hub.** El worker nunca abre conexiones al hub ni expone puertos (ni tuneles): solo lee su
   entrada y escribe su salida.

## 5. El envio (solo Kaggle, P.2.7)

Un envio agrupa los trabajos `enviado` de un operador en una version del dataset privado `xd-envios`:

```
envio.json      {"esquema": 1, "envio": "envio_<fecha>", "operador": "<usuario kaggle>",
                 "trabajos": [{"id": <id en la cola>, "tipo": "...", "archivo": "<zip>"}]}
<zips de los trabajos>
```

El kernel `xd-worker` (lanzador fijo) recorre `envio.json` en el orden de la regla 1. La cola pasa a
`en_proceso` cuando `kernels status` dice que corre, y cada trabajo a `listo` o `error` segun su `estado.json`.

## 6. Que cambia en el codigo (P.2.3 y P.2.4)
- `motor/worker.py` (nuevo): `procesar()`, despacho por tipo, `estado.json`, entorno, reglas 2 a 6.
- `motor/entrenar.py` (nuevo): la logica de las celdas 2 y 3 del cuaderno de entrenamiento (train, val y KPI de
  conteo, `metricas.json`), con `parametros` en lugar de variables de celda.
- `trabajo.py` y `lote.py` no cambian: `worker.py` los llama.
- Los zips: `buzon.armar`, `exportar_lote.py` y `exportar_yolo.py` agregan `trabajo.json` y `worker.py` (y el
  dataset agrega `codigo/` con `entrenar.py`). `exportar_*` corren en el contenedor: **no** son nucleo
  (`reglas.py`, `pipeline.py`, `leer_perfil` no se tocan; la huella de version no cambia).
- `notebooks/worker.ipynb` (P.2.4): un solo cuaderno de Colab que reemplaza a los tres.
