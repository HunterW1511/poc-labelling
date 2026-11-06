# P.4 Superposicion: lotes en trozos con envios escalonados

Escrito al abrir P.4 (05/11/2026). Objetivo: primera tarea revisable con clic funcionando en
menos de 5 min, incluso con lotes de cientos de fotos.

## 1. Flujo actual (punto de partida)

### Pre-etiquetado
```
xd.py preetiquetar N            (en el contenedor)
  -> exportar_lote.py N
       Lee Label Studio: tareas sin version actual
       Descarga fotos con get_local_path()
       Empaca: fotos/ + codigo/ (reglas, pipeline, hijo, lote, worker) + manifiesto.json + trabajo.json
       -> lotes/lote_p<N>_<ver>_<fecha>.zip   (un solo zip)
  -> registra en cola_trabajos (estado "pendiente")
  -> xd.py worker --enviar
       Sube el zip a xd-envios (Kaggle dataset, .zip.xd)
       Lanza kernel xd-worker
       Estado cola -> "enviado"
  [Kaggle corre: lanzador.py -> worker.py -> lote.py -> _pred.json]
  [Kaggle termina: salida disponible como un bloque]
  -> xd.py worker --traer
       Descarga la salida del kernel terminado
       Copia _pred.json a lotes/
       Estado cola -> "listo"
  -> xd.py lote-importar lote_p<N>_*_pred.json
       importar_lote.py: sube predicciones a Label Studio por tarea
       Estado cola -> "importado"
```

### Precodificacion (cache de SAM 3 para el clic)
```
xd.py precodificar N            (en el contenedor)
  -> exportar_pre.py N
       Lee tareas del proyecto, filtra las que ya tienen cache
       Empaca: fotos/ + fotos.json (tarea, foto, sha256) + trabajo.json + codigo/
       -> lotes/pre_p<N>_<fecha>.zip   (un solo zip)
  -> registra en cola_trabajos como tipo "precodificacion"
  -> xd.py worker --enviar / --traer
  [Worker produce: cache/<clave>.pt + <stem>_cache.json]
  -> xd.py cache-importar
       Copia los .pt al motor, motor carga en RAM
```

### Restriccion clave de Kaggle
La salida de un kernel solo esta disponible cuando **todo el kernel termina**. No hay resultados
parciales entre trozos dentro del mismo envio. La superposicion solo existe **entre envios**:
un envio que termina mientras el siguiente corre.

Con Colab/Drive el cuaderno escribe cada resultado en Drive al terminar; la importacion
incremental es casi gratuita. Queda como nota para una mejora futura; P.4 se centra en Kaggle.

---

## 2. Costo fijo por envio

Medido en P.2.8 y P.3.7 (Kaggle T4 x2):

| Etapa            | Tiempo medido |
|------------------|---------------|
| Pesos sam3.pt    | 22-26 s       |
| Instalacion pip  | 11-20 s       |
| Carga de SAM 3   | 15-33 s       |
| **Total arranque** | **~1-3 min** |

Cada envio adicional paga este costo. Con fotos de 0.7-1.1 s/foto (P.3.7, P.2.8), un primer
trozo de 16 fotos termina en ~3-4 min de kernel (arranque + proceso), lo que cabe en el
objetivo de < 5 min de punta a punta.

---

## 3. Decisiones de diseno

### D-P4.1 Politica de trozos: "primero chico, resto junto"
Un lote se parte en exactamente **dos envios**:
- **Trozo 1** (N fotos configurables, defecto 16): viaja solo en su propio envio. Llega rapido.
- **Trozo 2..M** (el resto): se agrupan en un segundo envio que se lanza en paralelo o
  inmediatamente despues del primero.

No se generan mas de dos envios por lote para no multiplicar el costo de arranque.

### D-P4.2 Tamano del primer trozo (defecto: 16)
El lanzador parte trabajos SAM 3 de >=16 fotos entre las dos T4 (MIN_PARTIR=16 en lanzador.py).
Con 16 fotos el primer trozo usa las dos GPU; con menos, una sola. Se usa 16 como defecto y se
deja configurable con `--trozo K` en los comandos.

### D-P4.3 Cada trozo lleva su pred y su cache en el mismo envio
Con el hub liviano (D19) una foto sin cache no responde al clic. Por eso cada trozo debe incluir
tanto el pre-etiquetado (exportar_lote) como la precodificacion (exportar_pre) de las mismas
fotos, y viajar en el mismo envio. El worker procesa ambos trabajos antes de terminar.

### D-P4.4 Campo "grupo" en la cola de trabajos
Hoy cada zip es un trabajo independiente. Con trozos, varios trabajos pertenecen al mismo lote
original. Se agrega el campo `grupo` (texto, nullable) a la tabla `trabajos` con una migracion
de esquema (ESQUEMA -> 3). El grupo identifica el lote de origen, por ejemplo
`"lote_p13_sam3-abc-def"`. No hace falta un estado nuevo: cada trozo avanza por los estados
existentes de forma independiente.

### D-P4.5 Importar lo que haya llegado (sin automatismo en P.4)
El paso "Traer e importar" se hace a mano o con un boton en la UI: `worker --traer`, luego
`lote-importar` y `cache-importar` de los archivos que llegaron. El tablero muestra el `grupo`
para que el operador sepa "trozo 1 de 2 listo". La automatizacion (traer e importar solo cuando
llega un envio) queda para P.5 (encadenamiento).

---

## 4. Que cambia por sub-paso

### P.4.2 Trozos al exportar
- `motor/exportar_lote.py`: nuevo argumento `--trozo K`; si K>0 y hay mas de K tareas,
  genera dos zips: `lote_p<N>_<ver>_<fecha>_t01.zip` y `lote_p<N>_<ver>_<fecha>_t02.zip`.
  El `manifiesto.json` de cada zip incluye `{"trozo": 1, "trozos": 2, "grupo": "<stem_base>"}`.
- `motor/exportar_pre.py`: mismo argumento `--trozo K`; genera `pre_p<N>_<fecha>_t01.zip`
  y `pre_p<N>_<fecha>_t02.zip`. El `trabajo.json` incluye el mismo campo `grupo`.
- `xd.py preetiquetar` / `precodificar`: pasan `--trozo` al contenedor (defecto 16).

### P.4.3 Envios escalonados
- `motor/cola_trabajos.py`: migracion ESQUEMA 3, agrega columna `grupo` a `trabajos`.
- `xd.py worker --enviar`: detecta trabajos con el mismo `grupo`, los agrupa en un envio.
  Los del trozo 1 (pred + cache) van en el primer envio; los del trozo 2 en el segundo.
  Lanza el primer envio, espera que Kaggle lo acepte, lanza el segundo.

### P.4.4 Importar lo que haya llegado
- `xd.py worker --traer`: ya importa todo lo disponible; solo necesita mostrar el `grupo`
  en el resumen ("trozo 1 de 2").
- `tablero.py`: columna o indicador de `grupo` en la vista de trabajos listos.
- `ui.py`: el boton "Traer" muestra el grupo en el resultado.

### P.4.5 Prueba real
- Lote de ~100 fotos (proyecto de prueba), trozo 1 = 16 fotos.
- Medida: desde `xd.py preetiquetar` hasta tarea visible en Label Studio con clic funcionando,
  < 5 min.
- Limpieza del proyecto de prueba, actualizacion de README/manual, push.

---

## 5. Lo que NO cambia
- `worker.py`, `lanzador.py` y `lote.py` en el motor: ya procesan un zip por trabajo.
  Un trozo es simplemente otro trabajo; no hay logica nueva en el worker.
- `importar_lote.py`: ya importa un `_pred.json` a la vez; se llama una vez por trozo.
- `cache_sam3.py` y `cache-importar`: igual, uno por trozo.
- Estados de la cola: sin cambios. El campo `grupo` es solo informativo.

## Revision P.4.R1 (Claude Code, 05/11/2026): lo que hace el codigo

La version de P.4.3 lanzaba los envios t01 y t02 seguidos sobre el **mismo kernel** y el **mismo dataset** (`-d`
borraba la version que leia el primero) y `--traer` solo bajaba la ultima version del kernel: el trozo 1 nunca llegaba
antes. Ademas el trozo 1 del lote y el de la precodificacion eran fotos distintas. Corregido:

- **Un envio por llamada** (`xd.py worker --enviar`): toma el **trozo mas bajo pendiente** de todos los grupos (los
  trabajos sin trozo cuentan como trozo 1). Los trozos posteriores esperan; mientras un envio corre no sale otro
  (el kernel es uno solo).
- **Cada envio guarda su version del kernel** (cola esquema 4, `envios.version`, leida de "Kernel version N
  successfully pushed"). `--estado` y `--traer` recorren los envios pendientes y consultan/bajan **su** version
  (`<usuario>/xd-worker/<N>`): el trozo 1 se trae aunque el trozo 2 ya corra.
- **Trozos alineados**: `preetiquetar --aplicar` precodifica las **mismas tareas, en el mismo orden y con el mismo
  `--trozo`** (`exportar_pre.py --tareas`); el trozo 1 viaja con su pre-etiquetado y su cache en el mismo envio.
  `--sin-precodificar` lo desactiva.
- Flujo: `preetiquetar N --muestra 100 --aplicar` -> `worker --enviar --aplicar` (trozo 1) -> `worker --traer
  --aplicar` + `lote-importar` + `cache-importar` (revisar) -> `worker --enviar --aplicar` (trozo 2) -> ...
  P.5.R1 (daemon) encadena estos pasos.
- Tests: `test_kaggle.test_envios_escalonados_por_trozo` y `test_xd_trabajos.test_preetiquetar_precodifica_las_mismas_tareas`.

## Prueba real (P.4.R3, 05/11/2026): ver docs/prueba_p5.md

100 fotos en trozos de 16 + 84: el trozo 1 quedo revisable (predicciones + cache) a los **6 min 51 s** de T0, mientras el
trozo 2 corria en Kaggle; el lote completo ~12-13 min. Superposicion real, pero **la meta (< 5 min) no se cumplio**:
P.4 sigue abierta con P.4.R4 (exportar el trozo 1 primero, encadenar el primer envio, sondeo rapido, sha de los pesos
sin recalcular, calentar el clic) y una nueva medida.
