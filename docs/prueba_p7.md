# Prueba real del modo guiado (P.7), de punta a punta

06/11/2026. Hub = laptop i7-7600U (Windows 10, CPU); worker = Kaggle (kernel privado `xd-worker`, 2 x T4).
Caso real: proyecto 19 `plumas-y-desarmadores` ("Plumas y Desarmadores"), 150 fotos tomadas con la camara del hub,
clases `Pluma` y `Desatornillador`, carpetas Pluma, Desatornillador, Mezcla y Fondo. Lo hizo la persona en el modo
guiado, con el Automatico (daemon) encendido; el agente vigilo la cola y midio.

## Tiempos por paso

| Paso | Que | Tiempo |
| --- | --- | --- |
| 2. Describir (asistente, audio) | Trabajo creado -> resultado en el hub | **6 min 51 s** |
| | arranque y subida ~1 min; `pip` 9 s; instalar Ollama 50 s; Whisper (bajar + transcribir 15 s) 23 s; bajar qwen2.5:14b (~9 GB) ~70 s; **LLM 145 s** (1886 tokens de entrada, 540 de salida); regreso ~45 s | |
| 4. Pre-etiquetar (SAM 3, muestra de 25 en trozos 16 + 9) | Lote creado 14:50:23 -> trozo 1 importado / con cache | 2 min 52 s / 4 min 44 s |
| | -> trozo 2 importado / con cache | 5 min 37 s / 6 min 2 s |
| 6. Modelo hijo (19 + 7 fotos, 31 epocas) | Envio -> resultado en el hub | ~2 min 42 s |
| 7. Pre-etiquetar con el hijo (124 fotos, 16 + 108) | Lote creado 15:16:58 -> trozo 1 / trozo 2 importados | 3 min 10 s / 6 min 29 s |
| Re-etiquetado con SAM 3 (123 fotos, 16 + 107, ya con cache) | Lote creado 15:32:44 -> trozo 1 / trozo 2 importados | 2 min 12 s / 5 min 15 s |
| 9. Modelo final (117 + 32 fotos, 100 epocas) | Envio 15:50:12 -> resultado en el hub 15:56:11 | **~6 min** |
| 10. Probar en vivo (`p19_det_20261106-2148`, yolo11n det, imgsz 960) | En el hub (CPU) | **~6 FPS** |

## Calidad

- **SAM 3** en las 149 fotos revisadas: **92% de aceptacion por region** (514 aceptadas, 6 con clase cambiada, 41
  borradas, 3 anadidas). Pluma 95%, Desatornillador 89%. Por carpeta: Mezcla 97%, Pluma 92%, Desatornillador 71%,
  Fondo 57% (marca regiones de mas que hay que borrar).
- **Hijo** (19 fotos de entrenamiento): conteo exacto 1/7, mAP50 0.20, precision 0.007; **0 detecciones** en las 124
  fotos que pre-etiqueto (`crudas 0` en todas, con conf 0.25).
- **Modelo final** (117 fotos): conteo exacto **21/32 (66%)**, mAP50 0.948.
- Ojo: la aceptacion de SAM 3 es por region y el conteo exacto del modelo es por foto (el KPI); no son la misma medida.

## Fallos encontrados (y arreglados)

| Fallo | Causa | Arreglo |
| --- | --- | --- |
| `registrar` no encontraba `best.pt` | P.4.R6: la fase pred excluia todos los `.pt`; el envio de entrenamiento no lleva precodificacion y se marcaba `traido` sin bajar los pesos | La cache se reconoce por su clave (`cache_sam3.CLAVE`), no por la extension (`b174a06`); los pesos se recuperaron de la salida del kernel v21 |
| Una linea larga en la consola deformaba la UI | La lista de ids de `preetiquetar` no tiene espacios; el `pre` no partia palabras y la columna del grid crecia con su contenido | `overflow-wrap:anywhere` y columnas `minmax(0,1fr)` (`426fc5c`) |
| Las fotos del paso 7 quedaron sin pre-etiquetar | El hijo, entrenado con 19 fotos, no detecta nada; el flujo lo activo y lo uso aunque era mucho peor que SAM 3 | `modelos N --desactivar` (`db4a17b`) y re-etiquetado con SAM 3. Pendiente: no activar un hijo peor que SAM 3 y minimo de fotos antes de entrenar |

## Lo que dejo la prueba para despues

Ver los pendientes ordenados en el contexto del piloto: asistente con la API de Claude (modo optimizado, D14),
calidad del hijo y cuando saltarlo, timers y avisos por trozo, portabilidad (cada quien su hub, Mac), entrenamiento,
en vivo (poligonos y cajas, mas FPS) y el diseno de la UI.
