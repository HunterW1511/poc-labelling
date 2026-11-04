# Manual de uso de PoC-Labelling

Guia paso a paso para el equipo. Que es el sistema y como instalarlo: README.md.
Cada accion de la UI es un comando de `xd.py` (se indica entre parentesis); lo que escribe primero muestra un reporte
y solo escribe cuando lo confirmas.

## 1. Arrancar cada dia

1. Abre Docker Desktop y espera a que diga "running".
2. En PowerShell, dentro de `C:\PoC-Labelling`:
   - `docker compose up -d`
   - `python xd.py estado`: Label Studio y Motor deben decir UP.
   - `python ui.py` y abre http://127.0.0.1:8090 (deja esa consola abierta).
3. Label Studio esta en http://127.0.0.1:8080.

La primera vez que se usa SAM 3 tras arrancar, el motor tarda de 3 a 7 minutos en cargarlo (CPU). Es normal.

### Donde corre lo pesado (el "worker")
Lo dice `TRANSPORTE` en tu `.env` (instalacion en README.md):
- **Kaggle** (`TRANSPORTE=kaggle`, recomendado): en la UI, tarjeta **Pasos externos**, pulsa **Enviar a Kaggle**
  (revisa el reporte y confirma). Cuando quieras, **Traer de Kaggle**: si aun no termina te lo dice; si termino,
  confirma y el resultado queda listo para importar. No hace falta abrir Kaggle. Un envio tipico tarda de 2 a 7 min.
- **Colab** (`TRANSPORTE=drive`, respaldo): abre `worker.ipynb` en Colab (entorno **T4 GPU**), corre la celda 1
  (una vez por sesion) y la celda 2; despues pulsa **Reconciliar** en Pasos externos.

En los pasos de abajo, "el worker" es cualquiera de los dos.

## 2. Un proyecto de principio a fin

### 2.1 Describir el caso (spec)

Opcion A, con el asistente (voz o texto):
1. En la tarjeta **Asistente** escribe un slug (minusculas, digitos, `_` o `-`), graba la descripcion del caso
   (que objetos, cuantos caben por foto, que carpetas de fotos vas a tomar) y pulsa **Enviar trabajo**.
2. Pasalo por el worker (arriba: Kaggle o Colab).
3. En la UI pulsa **Ver ultimo resultado**. Si hay preguntas, respondelas y envia de nuevo (continuar).
4. **Revisar y aplicar spec** (`asistente-importar SLUG --aplicar`).

Opcion B, sin asistente:
1. En **Asistente** escribe el slug y pulsa **Usar plantilla (sin asistente)** (`spec-nueva SLUG --titulo T --aplicar`).
2. Edita `motor/proyectos/SLUG/spec.json` (referencia: `motor/plantillas/LEEME_spec.md`) y quita todas las marcas `CAMBIAR:`.
3. **Validar spec** (`validar SLUG`) hasta 0 errores. Con errores no se puede crear el proyecto.

### 2.2 Crear el proyecto
**Crear proyecto** (`crear-proyecto SLUG`): crea el proyecto en Label Studio y las carpetas en `mis_imagenes/SLUG/`.

### 2.3 Tomar las fotos
1. **Plan de captura** (`plan SLUG`): cuantas fotos por carpeta y que variar (posicion, rotacion, distancia, luz).
2. **Capturar fotos** (`python capturar.py SLUG [--carpeta NOMBRE] [--total N]`) con la webcam, o copia las fotos
   a las carpetas a mano. La ventana muestra la carpeta actual, cuantas llevas de la meta y que variar (cambia cada
   5 fotos). Empieza en la primera carpeta incompleta y, al cumplir la meta, sugiere la siguiente.
   Teclas: `espacio` guarda (la foto original, sin la barra), `n` / `p` carpeta siguiente / anterior,
   `g` cuadricula de tercios, `z` deshace la ultima, `q` sale. Al salir imprime el resumen por carpeta.
3. **Sincronizar fotos** (`sincronizar SLUG`): Label Studio crea una tarea por foto.

La carpeta de tipo negativo es fondo SIN objetos. Nunca personas al fondo de ninguna foto.

### 2.4 Pre-etiquetar una muestra
1. **Pre-etiquetar muestra** (`preetiquetar N --muestra 30`): deja un lote en Drive (`PoC-Labelling/lotes`).
2. Pasalo por el worker (Kaggle o Colab). **Pasos externos** en la UI muestra en que punto esta
   (con Colab, si dice "cambios sin guardar", pulsa **Reconciliar**).
3. **Importar predicciones** (`lote-importar --fijar-version`).

### 2.5 Revisar en Label Studio
Abre el proyecto, revisa cada tarea de la muestra y corrige. Para agregar un objeto: elige la etiqueta y haz clic
sobre el objeto (SAM 3 interactivo dibuja el poligono). El primer clic puede decir "modelo cargando": espera y
vuelve a hacer clic. El KPI es el conteo exacto por foto: que no falte ni sobre ningun objeto.

### 2.6 Entrenar el modelo hijo
1. **Exportar dataset** (`dataset N --drive`).
2. Pasalo por el worker (Kaggle o Colab): entrena el dataset mas reciente del proyecto (en Kaggle, con las dos T4).
   Los parametros (epocas, imgsz, modelo...) se eligen al exportar: `dataset N --drive --epochs 50`.
3. **Registrar modelo** (`registrar N --run ultimo --activar`).

### 2.7 Mas tareas con el hijo
**Pre-etiquetar muestra** en modo hijo (`preetiquetar N --modo hijo`) y repite 2.4 y 2.5: el hijo es mas rapido y
propone menos basura que SAM 3.

### 2.8 Validar
**Aceptacion** (`aceptacion N`) y **Modelos** (`modelos N`): que porcentaje se acepto sin cambios y que modelo es el activo.

### 2.9 Ver en vivo
**Ver en vivo** (`ver N`): abre la webcam con el modelo activo. Teclas: `+`/`-` confianza, `p` pausa, `s` guarda
una captura, `q` sale. `--backend pt` usa PyTorch en vez de OpenVINO.

## 3. Reglas que no se rompen
- Nunca subir ni compartir `.env`, fotos, audios, lotes, datasets ni modelos.
- Fotos de personas solo con permiso y sin terceros al fondo.
- Primero el reporte, luego confirmar. Nunca dos trabajos a la vez (la UI ya lo impide).
- Si editas un cuaderno en Colab: `python xd.py cuadernos --traer --aplicar` para llevarlo al repo.

## 4. Problemas frecuentes
| Sintoma | Causa probable | Que hacer |
| --- | --- | --- |
| El motor tarda minutos en responder | Esta cargando SAM 3 en CPU | `python xd.py estado`: si `calentando` o `semantico_cargando` estan en True, esperar |
| La cola no baja | Espera de carga, no bloqueo | Mira `semantico_esperando_carga` en `estado`; si todo esta en False y no hay log nuevo, ver README (py-spy) |
| "Crear proyecto" no aparece | La spec tiene errores o es `-ref` | **Validar spec** y corrige lo que diga |
| Colab: "Torch not compiled with CUDA" | El entorno no es GPU | Entorno de ejecucion -> Cambiar tipo -> T4 GPU y repetir celda 1 |
| Colab: "Connection refused" en el asistente | Ollama no esta corriendo | Repetir la celda 1 |
| Pasos externos no ve el resultado | Drive aun no sincroniza | Esperar un minuto y Actualizar |
| Pasos externos dice "cambios de estado sin guardar" | Colab dejo resultados que la cola aun no registra | **Reconciliar** (`trabajos --reconciliar`): revisa el reporte y confirma |
| Un trabajo aparece en Error | Fallo en Colab | Lee el error; **Reintentar** lo vuelve a enviar (`trabajos --reintentar ID`) o **Archivar** lo descarta |
| "Traer de Kaggle" dice que sigue en Kaggle | El kernel aun corre (o espera GPU) | Vuelve a pulsar en unos minutos; **Estado de Kaggle** dice queued/running/complete |
| Un envio a Kaggle volvio sin resultado para un trabajo | El worker fallo en ese trabajo (queda en Error con el motivo) | Lee el error en Pasos externos; **Reintentar** y **Enviar a Kaggle** de nuevo |
| `kaggle-pesos` o `worker` dicen "Sin credencial" | El token no esta en `~/.kaggle/access_token` | Guardalo con ese nombre exacto (sin `.txt`) |
| Quiero ver todos los trabajos | - | `python xd.py trabajos --todos` (la cola vive en `datos/trabajos.sqlite` y sobrevive a reinicios) |
| `git push` falla con GH007 | Tu Git usa el correo real | `git config --global user.email` con el correo noreply de GitHub |

## 5. Al terminar una prueba
`powershell -ExecutionPolicy Bypass -File herramientas\limpiar.ps1` (reporte) y luego con `-Aplicar`; despues vacia
la papelera de Drive. Borra el proyecto con **Borrar proyecto** (`borrar-proyecto SLUG --aplicar`).