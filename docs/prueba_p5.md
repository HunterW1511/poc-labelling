# Prueba real de superposicion y encadenamiento (P.4.R3 / P.5.R3)

05/11/2026. Hub = laptop i7-7600U (Windows 10, CPU); worker = Kaggle (kernel privado `xd-worker`, 2 x T4).
Proyecto de prueba 14 con **100 imagenes sinteticas** de 1280x720 (plumas y desarmadores dibujados; solo sirven para
medir tiempos). Reemplaza el guion sin resultados que escribio Kiro.

## Flujo probado

```
python xd.py preetiquetar 14 --muestra 100 --trozo 16 --aplicar   # lote y precodificacion alineados: 16 + 84
python xd.py daemon --aplicar --intervalo 1                          # en la consola de la persona
  ciclo: worker --estado -> worker --traer -> lote-importar -> cache-importar -> worker --enviar
```

## Trozo 1 (16 fotos): primera tarea revisable

| Hora | Paso | Duracion |
| --- | --- | --- |
| 16:03:58 | T0: `preetiquetar --aplicar` | |
| 16:04:52 | Exporta los 2 lotes y las 2 precodificaciones **completos** (100 fotos) | 54 s |
| 16:05:55 | Arranca el daemon (a mano) | ~1 min |
| 16:06:24 | Subida del envio del trozo 1 (21 s) + dataset listo (3 s) | 29 s |
| 16:06:27 - 16:08:36 | Kernel v7 (sin cola de GPU): sha256 de `sam3.pt` 33 s, pip 11 s, pre-etiquetado 16 fotos en 2 GPU 50 s (carga SAM 3 33 s), precodificacion 16 en 2 GPU 23 s | 130 s |
| 16:08:36 - 16:10:27 | Kaggle cierra el kernel + el daemon lo detecta (sondeo cada minuto) | 1 min 51 s |
| 16:10:49 | Traer + importar 16 predicciones y 16 caches | 22 s |
| **16:10:49** | **Trozo 1 revisable** | **6 min 51 s desde T0** |
| 16:12:05 | Primer clic (tarea 1397): imagen de disco 0.3 s pero **7.5 s total**; segundo clic **0.9 s** | |

**Meta (< 5 min) no cumplida.** Optimizaciones medibles en P.4.R4: exportar solo el trozo 1 antes de enviar (~45 s),
encadenar el primer envio (~1 min humano), sondeo de 20 s mientras corre un envio (~1 min), no recalcular el sha256 de
3.45 GB en cada envio (~30 s), y calentar el clic al cargar el modelo (primer clic 7.5 s).

## Trozo 2 (84 fotos) y lote completo

- Kernel v8 lanzado por el daemon a las 16:11:26 (en cuanto termino el v7): 16:11:29 - 16:14:42 (**195 s**: sha 25 s;
  pre-etiquetado 84 en 2 GPU 85 s; precodificacion 84 en 2 GPU 56 s).
- Mientras corria se revisaba el trozo 1 (superposicion real).
- El primer daemon se detuvo antes de traerlo; un segundo daemon lo trajo e importo a las 18:36. Con el daemon
  encendido, el lote completo habria quedado revisable hacia las **16:16-16:17 (~12-13 min desde T0)**.
- Resultado: 100 predicciones en Label Studio, 100 caches en `motor/cache_sam3/`, los 4 trabajos `importado`.

## Segunda medida, con P.4.R4 (06/11/2026)

Mismo hub y worker (kernels v11 y v12). Proyecto de prueba recreado (16, slug `prueba-p4`) con las mismas 100 fotos y
sin predicciones. **Ojo:** la cache de SAM 3 de esas fotos ya estaba en `motor/cache_sam3/` (de la prueba anterior),
asi que no hubo precodificacion; el kernel solo pre-etiqueto. Falta repetirla con la cache apartada.

```
python xd.py preetiquetar 16 --muestra 100 --trozo 16 --enviar --aplicar   # T0; el trozo 1 sale solo
python xd.py daemon --aplicar --intervalo 1                                 # arrancado ~20 s despues
```

| Hora | Paso | R3 | R4 |
| --- | --- | --- | --- |
| 10:39:26 | T0 | | |
| 10:39:40 | Exporta solo el trozo 1 (16 fotos) | 54 s (las 100) | 14 s (con la muestra) |
| 10:40:08 | Trozo 1 en Kaggle (subida 13 s + dataset 4 s; sha de `sam3.pt` ya no se recalcula) | 2 min 58 s desde T0 | **42 s** desde T0 |
| 10:40:08 - 10:43:55 | Kernel v11: pip 11 s; 16 fotos en 2 GPU 187 s (**carga de SAM 3 172 s**, luego ~1 s por foto) | 130 s | 3 min 47 s |
| 10:43:55 | El daemon ve `complete` (sondeo ~25 s) | 1 min 51 s | < 30 s |
| 10:44:10 | Traer + importar 16 predicciones | 22 s | 15 s |
| **10:44:10** | **Trozo 1 revisable** | **6 min 51 s** | **4 min 44 s** |
| 10:44:56 | Trozo 2 en Kaggle (lo lanza el daemon en el mismo ciclo) | | |
| 10:44:56 - 10:52:10 | Kernel v12: 84 fotos en 2 GPU 382 s (**carga de SAM 3 328 s**, luego ~1.1 s por foto) | 195 s | 7 min 14 s |
| **10:52:47** | **Lote completo importado** | ~12-13 min (estimado) | **13 min 21 s** (medido) |

**Meta (< 5 min) cumplida para el trozo 1, sin precodificacion.** El primer clic con el calentamiento de R4 no se midio.

**Hallazgo: sin el sha, la carga de SAM 3 en Kaggle se hizo mucho mas lenta** (172 s y 328 s contra 33 s en R3). El
sha256 leia los 3.45 GB de `sam3.pt` en orden y los dejaba en la cache de paginas; sin el, los 2 procesos (uno por GPU)
leen en frio y a la vez desde `/kaggle/input`. Arreglo **P.4.R5**: `lanzador.precalentar` lee `sam3.pt` entera y en orden
en un hilo mientras corre el pip, y `ejecutar` la espera antes de cargar SAM 3. Si la carga vuelve a ~30 s, el trozo 1
quedaria en ~2.5-3 min y el lote completo en ~6-7 min. Ademas, el intervalo del daemon cuenta ahora desde el inicio del
ciclo (cada ciclo tarda 5-7 s con Kaggle; antes el "sondeo de 20 s" era de ~25-27 s).

## Tercera medida, con P.4.R5 y la cache apartada (06/11/2026)

Proyecto 17 (recreado), mismas 100 fotos, **sin cache en el hub** (`motor/cache_sam3` apartada en
`datos/cache_sam3_apartada`): el kernel pre-etiqueta **y** precodifica, como con fotos nuevas. Kernels v13 y v14.

| Hora | Paso | R4 (v11/v12, sin precodificar) | R5 (v13/v14, con precodificacion) |
| --- | --- | --- | --- |
| 11:09:22 | T0 (`preetiquetar 17 --muestra 100 --trozo 16 --enviar --aplicar`) | | |
| 11:10:06 | Muestra + exporta lote y precodificacion del trozo 1 | 14 s | 44 s (precodificacion 22 s) |
| 11:10:54 | Trozo 1 en Kaggle (subida 26 s + dataset 8 s) | 42 s desde T0 | 1 min 31 s desde T0 |
| 11:10:53 - 11:12:50 | Kernel v13: `sam3.pt` en memoria en 11 s (a la par del pip, sin espera); **carga de SAM 3 30.6 s**; pre-etiquetado 16 en 2 GPU 45 s; precodificacion 16 en 2 GPU 23 s; total 91 s | 207 s | 91 s |
| 11:12:50 | El daemon ve `complete` (ciclos cada ~20 s) | < 30 s | < 25 s |
| 11:12:50 - 11:13:39 | **Traer la salida: 69 MB de cache** | 15 s (sin cache) | **49 s** |
| **11:13:46** | **Trozo 1 revisable (16 predicciones + 16 caches)** | **4 min 44 s** | **4 min 24 s** |
| 11:14:28 | Trozo 2 en Kaggle (subida 31 s) | | |
| 11:14:27 - 11:17:21 | Kernel v14: `sam3.pt` 15 s; carga SAM 3 31.6 s; pre-etiquetado 84 en 2 GPU 81 s; precodificacion 84 en 2 GPU 46 s; total 153 s | 382 s | 153 s |
| 11:17:23 - 11:22:14 | **Traer la salida: 364 MB de cache (84 x 4.3 MB, ~1.25 MB/s)** | | **4 min 51 s** |
| 11:22:14 - 11:23:08 | Importar 84 predicciones (una peticion por tarea) | | 54 s |
| **11:23:09** | **Lote completo importado** | **13 min 21 s** | **13 min 47 s** |

**Meta (< 5 min) cumplida para el trozo 1 en el caso real** (con precodificacion). P.4.R5 funciono: la carga de SAM 3
volvio a ~31 s y los kernels bajaron a menos de la mitad. **Nuevo cuello de botella: bajar la cache de Kaggle**
(~4.3 MB por foto): en el trozo 2 tardo mas que el kernel. Sin esa bajada, el lote completo habria quedado hacia los
~8 min. El primer clic con el calentamiento de R4 sigue sin medirse.

### Primer clic (06/11/2026, proyecto 17)

Con el modelo cargado, el primer clic de la sesion tardo **0.2 s** (cache de disco que trajo el worker; R3: 7.5 s): el
calentamiento de R4 funciona. En esta prueba la carga tardo 108 s porque el checkpoint ligero
(`motor/cache_sam3/sam3_interactivo_<sha>.pt`) se aparto junto con la cache: **al apartar la cache, dejar ese archivo**.
Con el checkpoint ligero, SAM 3 queda listo en 3 s (+0.4 s de calentamiento). Arreglado tambien `xd.py precalentar`
(y `reiniciar-motor --precalentar`): desde L.10 mandaba un `/predict` vacio que ya no carga nada; ahora manda
`params: {"precalentar": true}` (test `motor/test_precalentar.py`).

## Cuarta medida, con P.4.R6 (06/11/2026): predicciones primero, cache despues

Proyecto 18 (recreado, slug `prueba-p4`), 99 fotos (Fondo 29 + Mesa 70; trozos 16 + 83), **sin cache en el hub**
(apartada en `datos/cache_sam3_apartada_r6`, con el checkpoint ligero en su sitio). Kernels v15 y v16.
**Ojo:** el daemon no corrio entre 12:35 y 13:04 (se cerro tras el arranque), asi que el tiempo desde T0 no sirve;
se mide desde que cada kernel termina. **La red estaba mucho mas lenta que en la tercera medida** (subida del trozo 2:
243 s contra 31 s; bajada 0.61 MB/s contra ~1.25-1.4 MB/s).

| Paso (trozo 2) | R5 (tercera medida) | R6 (esta) |
| --- | --- | --- |
| Kernel (83-84 fotos, 2 GPU) | 153 s | 155 s |
| Daemon ve `complete` -> predicciones traidas (fase pred, sin `.pt`) | 4 min 51 s (con la cache) | **44 s** |
| Importar las predicciones | 54 s (una peticion por tarea) | **19 s** (en bloque; 82 subidas, 1 omitida que ya existia) |
| **Kernel terminado -> predicciones del trozo 2 en Label Studio** | **~5 min 46 s** | **1 min 4 s** |
| Bajar la cache (fase cache) | (incluida arriba) | 360 MB en 586 s (0.61 MB/s) |
| Kernel terminado -> cache del trozo 2 en el hub | ~5 min 46 s | 10 min 38 s (red lenta) |

Trozo 1: la cache (16 fotos, 69 MB) bajo en 115 s (0.60 MB/s) **despues** de enviar el trozo 2, que ya no la espera.

**Lectura:** con la red de la tercera medida, las predicciones de todo el lote quedarian en Label Studio hacia los
**~8.5 min desde T0** (antes 13 min 47 s), y la cache del trozo 2 ~5 min despues (~13 min), mientras se revisa el
trozo 1 (16 fotos en ~5 min = < 19 s por foto). La meta de "lote completo con cache < 8 min" sigue sin cumplirse: el
cuello es la bajada de la cache (misma tasa con 16 y con 83 archivos). Sin medir: que ve quien revisa una tarea sin
cache (el motor liviano devuelve `sin_cache`), y si bajar en paralelo (4 `kernels output` con patrones por clave)
sube la tasa.
