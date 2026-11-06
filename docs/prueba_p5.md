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
