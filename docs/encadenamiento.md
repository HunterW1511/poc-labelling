# P.5 Encadenamiento: pasos automaticos sin intervencion

Escrito al abrir P.5 (05/11/2026). Objetivo: que los pasos se encadenen solos, reduciendo los clicks y
la espera del operador.

## 1. Encadenamientos identificados

Del flujo actual (seccion 2 del README), los cuellos de botella manuales son:

| Paso manual | Siguiente paso | Riesgo | Automatizable |
|---|---|---|---|
| Worker termina en Kaggle | `worker --traer`, `lote-importar`, `cache-importar` | Bajo | **Si**, polling |
| Todas las fotos capturadas | `sincronizar` | Bajo | Si, al salir de `capturar.py` |
| Spec validada sin errores | `crear-proyecto` | Alto (irreversible) | No, requiere confirmacion |
| Dataset exportado | Entrenar en el worker | Medio | Si con confirmacion |
| Modelo registrado | `preetiquetar --modo hijo` | Medio | Si con confirmacion |
| Todas las tareas anotadas | `dataset --drive` | Bajo | Si, pero es raro (el flujo es iterativo) |

**Decision:** empezamos por el mas claro y seguro: traer e importar cuando el envio termina (P.5.2).

## 2. Politicas de encadenamiento

| Politica | Cuando aplica | Usuario hace |
|---|---|---|
| **Automatico** | Paso de bajo riesgo, reversible, sin ambiguedad | Nada (sucede en segundo plano) |
| **Sugerido** | Paso logico siguiente pero que el usuario puede no querer | Ve un aviso/boton, decide si procede |
| **Manual** | Paso irreversible, con parametros, o que requiere juicio | Lo lanza cuando quiera |

## 3. Mecanismos tecnicos

### Opcion A: Daemon/servicio en segundo plano (elegida para P.5.2)
Un proceso Python separado (`python xd.py daemon` o similar) que:
- Corre en el host, se arranca al inicio
- Polling cada N minutos (configurable, defecto 5 min)
- Lee la cola, detecta envios en `lanzado`/`corriendo`, consulta Kaggle
- Si cambio a `terminado`/`fallido`: `worker --traer --aplicar`
- Si llegan resultados (`listo`): `lote-importar` y `cache-importar`
- Log en `datos/daemon.log`

Ventajas: simple, no requiere cambios en Kaggle ni Label Studio.  
Desventajas: consume recursos todo el tiempo (minimos: solo polling).

### Opcion B: Hooks de la cola
Usar el sistema de hooks existente (`.kiro/hooks/`) con trigger `PostToolUse` o `PostTaskExec`.
No aplica bien aqui: los hooks son sincronos y dentro del contexto de Kiro, no un servicio persistente.

### Opcion C: Webhooks de Kaggle/Label Studio
Kaggle no tiene webhooks. Label Studio si, pero para eventos de anotacion, no para trabajos externos.
Descartado por ahora.

**Decision:** Opcion A (daemon) para P.5.2.

## 4. Diseno de P.5.2: daemon de encadenamiento

### Comando
```
python xd.py daemon [--intervalo 5] [--solo-una-vez]
```

- `--intervalo N`: minutos entre chequeos (defecto 5)
- `--solo-una-vez`: chequea una vez y sale (para testing)

### Logica del ciclo

1. Lee la cola con `_cola(crear=False)`
2. Filtra envios en estado `lanzado` o `corriendo` con proveedor `kaggle`
3. Para cada envio:
   - `worker --estado` (sin `--aplicar`, solo lectura)
   - Si el kernel cambio a `complete` o `error`:
     - `worker --traer --aplicar` (baja la salida, reconcilia la cola)
4. Filtra trabajos en estado `listo` (tipo `preetiquetado` o `precodificacion`)
5. Para trabajos de preetiquetado `listo`:
   - `lote-importar --fijar-version --aplicar`
6. Para trabajos de precodificacion `listo`:
   - `cache-importar --aplicar`
7. Log de cada accion con timestamp en `datos/daemon.log`
8. Espera `intervalo` minutos, repite

### Estados de transicion automatica

| Estado inicial | Condicion | Accion | Estado final |
|---|---|---|---|
| Envio `lanzado` | Kernel en Kaggle = `running` | Actualizar cola | Envio `corriendo` |
| Envio `corriendo` | Kernel = `complete` o `error` | `worker --traer --aplicar` | Envio `terminado`/`fallido`, trabajos -> `listo`/`error` |
| Trabajo `listo` (preetiquetado) | Existe `_pred.json` | `lote-importar` | Trabajo `importado` |
| Trabajo `listo` (precodificacion) | Existe cache | `cache-importar` | Trabajo `importado` |

### Logs
`datos/daemon.log` (rotacion manual por ahora):
```
2026-11-05 14:23:10 [INFO] Daemon iniciado (intervalo 5 min)
2026-11-05 14:23:11 [INFO] Envio envio_20261105-142000: corriendo
2026-11-05 14:28:12 [INFO] Envio envio_20261105-142000: terminado, trayendo...
2026-11-05 14:29:45 [INFO] Traido: 2 archivos, 2 trabajos -> listo
2026-11-05 14:29:46 [INFO] Importando lote_p13_..._t01_pred.json
2026-11-05 14:30:01 [INFO] Importado: 16 tareas
2026-11-05 14:30:02 [INFO] Importando cache: 16 archivos
2026-11-05 14:30:15 [INFO] Cache importada
```

### Arranque y parada
- Arranque manual: `python xd.py daemon` (corre en primer plano con Ctrl+C para parar)
- Arranque en background: `python xd.py daemon > datos/daemon.log 2>&1 &` (Linux/Mac) o con `start /b` (Windows)
- Parada: Ctrl+C o matar el proceso

Para el piloto (5 personas), arranque manual es suficiente. Un servicio systemd/Windows Service queda para
el escalado.

## 5. Otros encadenamientos (P.5.3-5.4, priorizados despues de P.5.2)

### P.5.3 Sincronizar tras captura completa
Al salir de `capturar.py`, si todas las carpetas cumplen su meta:
```
Todas las carpetas completas (120/120 fotos). Sincronizar con Label Studio? [S/n]
```
Si `S` o Enter: `python xd.py sincronizar SLUG`.

### P.5.4 Crear proyecto tras spec validada
`asistente-importar` al terminar sin errores:
```
Spec importada sin errores. Crear proyecto en Label Studio? [S/n]
```
Si `S`: `python xd.py crear-proyecto SLUG --aplicar`.

## 6. Lo que NO se automatiza (requiere juicio humano)

- Decidir cuantas fotos capturar (el plan es una recomendacion)
- Decidir cuando exportar el dataset (depende de cuanto reviso)
- Decidir los parametros de entrenamiento (epochs, batch, etc.)
- Decidir cuando activar un modelo hijo (depende de la aceptacion)
- Borrar proyectos o archivar trabajos

## 7. Impacto en la UI

La UI podria mostrar:
- Estado del daemon (corriendo / detenido)
- Ultimo chequeo (hace N minutos)
- Proxima accion automatica prevista

Esto queda para P.7 (UI dual). En P.5 el daemon es CLI puro.

## Revision P.5.R1 (Claude Code, 05/11/2026): lo que hace el codigo

El daemon de P.5.2 llamaba a `motor/importar_pred.py` (no existe), solo buscaba trabajos `listo` sin resultado (un
`listo` siempre lo tiene) y nunca descargaba la salida de Kaggle: no importaba nada. Reescrito:

```
python xd.py daemon [--intervalo 5] [--una-vez] [--aplicar]
```

- Cada ciclo hace, en orden y con los mismos comandos que a mano: `worker --estado` -> `worker --traer` ->
  `lote-importar --fijar-version` -> `cache-importar` -> `worker --enviar` (el siguiente trozo, solo si el kernel esta
  libre). Con Drive/Colab: `trabajos --reconciliar` en lugar de estado/traer, y sin enviar.
- **Sin `--aplicar` solo reporta** (regla de oro 3): no trae, no importa, no envia. Con `--aplicar` es el modo
  "automatico" del diseno.
- Un paso que falla imprime el motivo y el ciclo sigue; el daemon no se cae. Ctrl+C lo detiene.
- No escribe `datos/daemon.log`: la salida va a la consola (para guardarla:
  `python xd.py daemon --aplicar *> datos\daemon.log` en PowerShell).
- Test: `test_kaggle.test_daemon_ciclo_completo` (reporte sin escribir; trozo 1 -> traer e importar lotes y cache ->
  trozo 2 -> traer e importar; todo `importado`).
