# Cola de trabajos del hub (P.1)

Diseno de la cola persistente en SQLite que reemplaza la deteccion de estados por archivos en Drive.
Drive (y despues Kaggle, D5) queda solo como transporte: lleva zips y resultados, pero el estado vive en el hub.

## 1. Como se detecta hoy (antes de P.1)

| Tipo | Se crea con | Archivo enviado | "Listo" cuando | "Importado" cuando | Error |
| --- | --- | --- | --- | --- | --- |
| asistente | `asistente SLUG` | `asist_<slug>_<fecha>.zip` (se arma directo en el buzon de Drive) | existe `<trabajo>_resultado.json` | `asistente-importar --aplicar`; hoy se deduce porque `spec.json` es mas nueva que el resultado | existe `<trabajo>_error.txt` |
| preetiquetado | `preetiquetar N --aplicar` (`lote-exportar`) | `lote_p<N>_*.zip` (en `motor/lotes/`, copiado a `LOTES_DRIVE`) | existe `<lote>_pred.json` | `lote-importar`: hay copia en `motor/lotes/` | no se detecta |
| entrenamiento | `dataset N --drive` | `dataset_p<N>_*.zip` (en `motor/datasets/`, copiado a `DATASETS_DRIVE`) | existe `runs/<stem>*/weights/metricas.json` | `registrar N --run R --aplicar`: el origen `runs/<R>` esta en el registro | no se detecta |
| precodificacion | (P.3) | - | - | - | - |

Problemas: el estado se recalcula en cada lectura y depende de nombres, fechas en el nombre y mtimes; un fallo en
Colab de preetiquetado o entrenamiento deja el trabajo "en espera" para siempre; no hay historial ni intentos.

## 2. Donde vive

- Archivo `datos/trabajos.sqlite` en el disco local del hub, ignorado en Git. **Nunca en Drive**: un SQLite
  sincronizado por Drive se corrompe.
- Solo lo usa el host (`xd.py`, `tablero.py`, `ui.py`); el contenedor del motor no lo monta.
- Modulo `motor/cola_trabajos.py` (solo biblioteca estandar: `sqlite3`, sin red); no es puro porque escribe la base.
- Conexion con `journal_mode=WAL` y `busy_timeout` (la UI lee mientras un comando de `xd.py` escribe; P.6 suma
  usuarios). Transacciones cortas.
- Version del esquema en `PRAGMA user_version`; una migracion por version, nunca a mano.

## 3. Esquema

```sql
CREATE TABLE trabajos (
  id          INTEGER PRIMARY KEY,
  tipo        TEXT NOT NULL,     -- asistente | preetiquetado | entrenamiento | precodificacion
  proyecto    INTEGER,           -- N de Label Studio (null en asistente)
  slug        TEXT,              -- slug del proyecto (asistente siempre; los demas si se conoce)
  estado      TEXT NOT NULL,     -- ver seccion 4
  archivo     TEXT NOT NULL,     -- nombre del zip enviado, sin carpeta (la carpeta la decide el tipo y el adaptador)
  resultado   TEXT,              -- nombre del resultado (_resultado.json, _pred.json, carpeta del run)
  creado      TEXT NOT NULL,     -- ISO local, como el resto del repo (%Y-%m-%dT%H:%M:%S)
  actualizado TEXT NOT NULL,
  intentos    INTEGER NOT NULL DEFAULT 0,
  error       TEXT,              -- ultimo error (recortado), null si no hay
  UNIQUE (tipo, archivo)         -- registrar dos veces el mismo zip no duplica (idempotente)
);
CREATE TABLE eventos (           -- historial: una fila por transicion o intento fallido
  id INTEGER PRIMARY KEY, trabajo INTEGER NOT NULL REFERENCES trabajos(id),
  de TEXT, a TEXT NOT NULL, fecha TEXT NOT NULL, detalle TEXT
);
```

Solo nombres de archivo, nunca rutas absolutas: la ruta de Drive cambia por maquina y por adaptador (D5).

## 4. Estados y transiciones

| Estado | Significado |
| --- | --- |
| `pendiente` | Registrado en el hub; el zip existe localmente pero aun no esta en el transporte |
| `enviado` | El zip esta en Drive (o, desde P.2, entregado al worker) |
| `en_proceso` | El worker lo tomo. **Solo alcanzable desde P.2**: Colab hoy no avisa |
| `listo` | El resultado esta en el transporte, falta llevarlo al hub o a Label Studio |
| `importado` | Resultado aplicado (spec escrita, predicciones subidas, modelo registrado). Final |
| `error` | Fallo el paso remoto (por ejemplo `_error.txt`) |
| `archivado` | Descartado a mano (`archivar`) o reemplazado. Final |

Transiciones validas (cualquier otra -> `ValueError`):

```
pendiente  -> enviado | error | archivado
enviado    -> en_proceso | listo | error | archivado
en_proceso -> listo | error
listo      -> importado | archivado
error      -> pendiente (reintento, intentos + 1) | archivado
```

Reglas:
- Cada transicion se hace con `UPDATE ... WHERE id = ? AND estado = ?` (el estado esperado): si otro proceso ya lo
  movio, no se pisa y se informa.
- Un fallo **del lado del hub** (por ejemplo, `importar_lote.py` falla) no cambia el estado: el trabajo sigue en
  `listo`, se guarda `error` y sube `intentos`, y se puede reintentar. Solo un fallo **remoto** pasa a `error`.
- `asistente` se arma directo en Drive: se registra y pasa a `enviado` en el mismo comando.
- `asistente --continuar` crea un trabajo nuevo; el anterior en `listo` del mismo slug pasa a `archivado`
  (reemplazado), para que el tablero no ofrezca aplicar un resultado viejo.
- `importado` se marca sobre el trabajo concreto que se aplico (hoy `asistente-importar` toma el ultimo resultado
  del slug; debe anotar cual).

## 5. Quien escribe cada transicion

| Transicion | asistente | preetiquetado | entrenamiento |
| --- | --- | --- | --- |
| -> `pendiente` / `enviado` | `asistente` | `lote-exportar` (pendiente al crear el zip, enviado al copiarlo) | `dataset --drive` (igual) |
| `enviado` -> `listo` / `error` | reconciliacion: `_resultado.json` / `_error.txt` | reconciliacion: `_pred.json` | reconciliacion: `metricas.json` del run |
| `listo` -> `importado` | `asistente-importar --aplicar` | `lote-importar` | `registrar --aplicar` |
| -> `archivado` | `archivar`, `asistente --continuar` | `archivar` | `archivar` (acepta `dataset_p*` desde P.1.4) |
| `error` -> `pendiente` | `trabajos --reintentar ID` (mueve el `_error.txt` a `_archivo/`; vuelve a `enviado` si el zip sigue en Drive) | igual | igual |

La **reconciliacion** (`xd.py trabajos --reconciliar`, P.1.3) es el unico lugar que mira archivos en Drive: avanza
`enviado -> listo/error`, reporta huerfanos (archivos sin fila, por ejemplo de antes de P.1) y trabajos que llevan
mucho en `enviado`. Con reporte primero; `--aplicar` escribe. Desde P.2 el worker de Kaggle informa directamente y la
reconciliacion queda como respaldo para Colab.

## 6. Lo que no cambia

- `tablero.externos()` conserva su salida (`tipo`, `archivo`, `estado` en `en_espera | listo | error`, `accion`); desde
  P.1.5 lee `tablero.vista()`: la cola mas la reconciliacion aplicada EN MEMORIA (`cola_trabajos.proyectar`), sin
  escribir ni crear la base. `pendiente`, `enviado` y `en_proceso` se muestran como `en_espera`. Si hay cambios sin
  guardar, la UI ofrece **Reconciliar** (`trabajos --reconciliar`, con reporte). Unica diferencia visible: un trabajo
  en `error` se muestra por su zip (no por el `_error.txt`) y ofrece Reintentar y Archivar.
- El candado de `ui.py` (`/api/trabajo`, un comando a la vez) es otra cosa y se queda igual.
- Nucleo (`reglas.py`, `pipeline.py`, `leer_perfil`) y cuadernos: sin cambios en P.1.

## 7. Criterio de cierre de P.1

Un trabajo `enviado` sobrevive a reiniciar `ui.py` y `docker compose restart`, el tablero lo muestra igual y la
reconciliacion lo lleva a `listo` cuando aparece el resultado.

**Cumplido el 03/11/2026 en el hub (laptop i7-7600U):** un trabajo `asistente` real en Drive siguio en `enviado` tras
`docker compose restart motor` y reiniciar `ui.py` (CLI y `/api/externos` con su id, reconciliacion sin
diferencias); luego `archivar --aplicar` lo dejo en `archivado` y la UI dejo de mostrarlo. Datos de prueba borrados.

## 8. Esquema 2: envios (P.2.7b)

Migracion automatica 1 -> 2 al abrir la base (conserva todos los trabajos; `PRAGMA user_version = 2`).

- `trabajos` gana `operador` (usuario de Kaggle que lo envio; una cuenta por persona, D2) y `envio` (nombre del
  envio en el que viaja).
- Tabla nueva `envios (nombre, proveedor, operador, estado, creado, actualizado, detalle)`; estados:
  `lanzado -> corriendo -> terminado | fallido -> traido`.
- Con `TRANSPORTE=kaggle`, `enviado` significa "el zip esta en el espejo local"; `xd.py worker --enviar` toma los
  `enviado` sin envio (`por_enviar`), los sube juntos y solo si el push del kernel salio bien los asigna al envio
  (`crear_envio`). Un fallo antes de eso no cambia la cola.
- `worker --estado --aplicar`: `corriendo` pasa los trabajos del envio a `en_proceso`.
- `worker --traer --aplicar`: baja la salida al espejo, reconcilia (`listo` o `error` por trabajo) y lo que no
  volvio pasa a `error` (`sin_salida`), para poder Reintentar. Un reintento (`error -> pendiente`) saca al trabajo
  de su envio y el siguiente `--enviar` lo vuelve a tomar.
- P.4.R6: `--traer` va en dos fases. `--fase pred` baja todo menos los `.pt` (KB) y deja el envio en `parcial` si
  llevaba precodificacion (si no, `traido`); `--fase cache` baja solo los `.pt` de los envios en `parcial` y los pasa
  a `traido` (si la bajada falla, siguen en `parcial`). `--fase todo` (defecto, boton de la UI) hace las dos.
- UI (Pasos externos, solo con Kaggle): **Enviar a Kaggle**, **Estado de Kaggle**, **Traer de Kaggle**, cada uno con
  reporte y confirmacion; el texto de cada trabajo dice en que punto esta su envio.
