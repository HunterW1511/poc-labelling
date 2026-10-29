# PoC-Labelling: contexto unificado, limpieza y ruta al piloto

Oct 20, 2026 · @IoT Lab

## Cómo usar este documento

Este documento reemplaza al "Contexto PoC-Labelling: retomar tras la etapa C". Une lo hecho hasta la etapa E, la prueba de caras, las decisiones del piloto y un plan de limpieza alineado con ese piloto. La limpieza (sección 6) se hace todavía en formato chat, un paso a la vez. Al terminarla, este documento se reformula como contexto para Claude Code y Kiro (paso L.11).

Instrucción para el nuevo chat: "Actúa como un Senior MLOps & Computer Vision Engineer. Retomamos PoC-Labelling: las etapas 0 a E están completas y validadas con la prueba de caras. Sigue la limpieza (sección 6), paso a paso, con las reglas de la sección 4. Antes de empezar, confirma que entendiste el contexto y propón los sub-pasos de L.0 y L.1. Si necesitas ver un archivo, pídemelo antes de modificarlo."

| Adjuntar al inicio | Por qué |
| --- | --- |
| Este documento | Contexto completo y plan |
| `xd.py` | CLI: base de todo el flujo y de la limpieza |
| `ui.py`, `tablero.py`, `ui/index.html` | Interfaz de la etapa E, que la limpieza también toca |
| `motor/buzon.py` | Asistente y arreglo de la raíz por slug |
| `docker-compose.yml` y `env_ejemplo.txt` | Entorno, sin secretos |
| Listado de archivos (`Get-ChildItem` del inventario) | Para decidir qué es código muerto (L.3) |

Bajo demanda, según el paso: `motor/comparar.py`, `motor/spec.py`, `motor/esquema_llm.py`, `motor/asistente.py`, `motor/interactivo.py`, `motor/cola.py`, `motor/borrar_proyecto.py`, `ver_cajas.py` y los tres notebooks exportados como `.ipynb` (para L.7).

No compartir: `.env`, fotos, audios, lotes, datasets ni modelos.

## Estado actual del sistema

PoC-Labelling es un pre-etiquetado general y multiproyecto, sin licencias SaaS obligatorias. Va del audio de un caso a un modelo hijo validado en vivo. Todo corre en una laptop sin GPU y en Colab gratuito, y cada paso es un comando de `xd.py` que la UI de la etapa E solo muestra y lanza.

### Entorno

- **Host.** Windows con PowerShell, en `C:\PoC-Labelling`. Laptop i7-7600U con 2 núcleos, 17 GB y sin GPU. Python global 3.14.2 sin venv (cv2 5.0.0, ultralytics 8.4.174, torch cpu). `xd.py`, `ui.py`, `tablero.py`, `capturar.py`, `ver_cajas.py` y los módulos puros corren en el host. La webcam solo funciona en el host.
- **Docker Desktop (WSL2).**
  - `db`: postgres:16-alpine.
  - `label-studio`: 1.23.0, en `http://127.0.0.1:8080`, con `./mis_imagenes` montada en solo lectura.
  - `motor`: backend ML de SAM 3, puerto 9090, `./motor:/app`, `sam3.pt` en el volumen `motor_data`.
  - `docker-compose.gpu.yml`: sin probar.
- **Drive para escritorio**, en `G:\Mi unidad\PoC-Labelling\`:
  - `lotes`: incluye `_archivo`.
  - `datasets`.
  - `runs`.
  - `asistente`: buzón del asistente, con su propio `_archivo`.
- **Colab gratuito (T4)**, con tres notebooks: asistente, pre-etiquetado y entrenamiento.
- **`.env`**:
  - `POSTGRES_*`, `LS_ADMIN_*`, `LS_API_TOKEN` y `MOTOR_DEVICE`, `MOTOR_PREVIAS` (6) y `MOTOR_CACHE_MAX` (8).
  - `LOTES_DRIVE`, con los opcionales `DATASETS_DRIVE`, `RUNS_DRIVE` y `ASISTENTE_DRIVE`.
  - De la etapa E: `UI_PROTEGIDOS` (por defecto `1,2`) y `EJECUTOR` (por defecto `colab`).

### Flujo y quién lo hace

| Paso | Comando de `xd.py` | En la UI (`python ui.py`, `http://127.0.0.1:8090`) | Dónde corre |
| --- | --- | --- | --- |
| 1. Caso -> spec | `asistente SLUG --audio/--texto`, `asistente-importar SLUG [--aplicar]` | Tarjeta Asistente: grabar, enviar, respuestas, aplicar | Colab (Whisper + qwen2.5:14b) |
| 2. Crear proyecto | `crear-proyecto SLUG` | Crear proyecto | Host + Label Studio |
| 3. Captura | `plan SLUG`, `capturar.py SLUG`, `sincronizar SLUG` | Plan, Capturar fotos, Sincronizar | Host (webcam) |
| 4. Pre-etiquetado | `preetiquetar N --muestra K`, `lote-importar --fijar-version` | Pre-etiquetar muestra, Pasos externos | Colab (SAM 3 o hijo) |
| 5. Revisión | clic de SAM 3 interactivo | Precalentar SAM 3 y enlace a Label Studio | Motor en CPU |
| 6. Hijo | `dataset N --drive`, `registrar N --run ultimo --activar` | Exportar dataset, Registrar modelo | Colab (YOLO) |
| 7. Más tareas | `preetiquetar` en modo hijo | igual que el 4 | Colab |
| 8. Validación | `aceptacion N`, `diagnostico.py N` | Aceptación, Modelos | Host y contenedor |
| 9. En vivo | `ver N` | Ver en vivo | Host (CPU) |

Todo lo que escribe pasa por modo reporte y luego `--aplicar`, también desde la UI. El servidor de la UI rechaza un `--aplicar` sin reporte previo OK.

### Piezas principales

- **Motor (`motor/`).**
  - **Núcleo:** `reglas.py` y `pipeline.py`. Entran en el hash de versión `sam3-<perfil>-<núcleo>`; tocarlos deja huérfanas las predicciones.
  - **Servicio:** `cola.py`, `interactivo.py` (clic y precodificación), `_wsgi.py` (con `/estado`) y `model.py`.
  - **Proyectos:** `spec.py`, `generar.py`, `crear_proyecto.py`, `borrar_proyecto.py`, `sincronizar.py` y `plan.py`.
  - **Etapa D:** `muestra`, `diagnostico`, `correccion`, `registro`, `hijo`, `lote`, `exportar_*`, `importar_lote` y `aceptacion`.
  - **Etapa C:** `esquema_llm`, `asistente`, `llm_ollama`, `trabajo`, `buzon` y `comparar`.
- **UI de la etapa E, en la raíz.**
  - `ui.py`: servidor de la biblioteca estándar; lista blanca de acciones; un trabajo a la vez; cabecera `X-XD`; protegidos bloqueados en el servidor.
  - `tablero.py`: solo lectura; tarjetas por proyecto, siguiente paso, pasos externos y detalle del asistente.
  - `ui/index.html`.
- **Comandos añadidos en la etapa E:** `xd.py reiniciar-motor [--precalentar --proyecto N --forzar]` y `xd.py archivar ARCHIVO [--aplicar]`.
- **Tests:** en el host, `spec`, `plan`, `muestra`, `correccion`, `registro`, `aceptacion`, `esquema_llm`, `asistente`, `buzon` y `comparar`. En el contenedor, `generar` (hash bff21077), `spec`, `hijo` y `reglas`. La forma de correrlos no está unificada.

## Lo que se hizo

Las etapas 0 a E están completas. La prueba de caras (proyecto 10) recorrió los 9 pasos desde la UI sin código específico del caso.

| Etapa | Resultado |
| --- | --- |
| 0, A | Entorno Docker con Label Studio, Postgres y motor SAM 3; healthchecks; `config.py` como único lector del entorno |
| B | Spec JSON por proyecto -> XML, creador de proyectos, plan de captura, `capturar.py` |
| C | Asistente: audio o texto -> spec con faster-whisper y qwen2.5:14b en Colab, por buzón en Drive; `comparar` contra una referencia |
| D | Muestra estratificada, diagnóstico, correcciones, registro de modelos, modo hijo (YOLO + SAM 3 por caja), aceptación |
| E.1 | `ui.py` con trabajo único, salida en vivo y cancelación del árbol de procesos |
| E.2 | Tablero de solo lectura con siguiente paso, filtro de protegidos y borrados, y aviso de carpetas compartidas |
| E.3 | Acciones con reporte y confirmación, exigidas también en el servidor |
| E.4 | Asistente en el navegador: grabación `.webm`, resultado estructurado, `--continuar` |
| E.5 | Pasos externos: espera, listo y error de los trabajos de Colab; `xd.py archivar` |
| E.6 | Herramientas del host: Capturar fotos y Ver en vivo |
| E.7 | Prueba de punta a punta con caras |

### Arreglos generales que salieron de la etapa E

- `buzon.preparar_spec` fuerza `imagenes.raiz = mis_imagenes/<slug>`. Antes, las specs del asistente compartían `mis_imagenes/Fondo`.
- `interactivo._siguientes` precodifica primero las tareas con predicción y sin anotar. Antes elegía tareas que el revisor no iba a abrir.
- `xd.py reiniciar-motor`, con protección de cola y `--forzar` desde la UI.
- El tablero rotula el plan sin `--total` como "Plan completo" y normaliza el slug del asistente.

### Resultados de la prueba de caras

| Medida | SAM 3 | Hijo | Ensamble (referencia) |
| --- | --- | --- | --- |
| Aceptación sin cambios | 79% (40 tareas) | 98% (30 tareas) | 24% / 95% |
| Tiempo por foto en T4 | 1.4-6.5 s | 0.8 s | - |
| Candidatos crudos por foto | 12-79 | 2-14 | - |
| Clic en la laptop sin caché | 27-47 s por imagen | - | - |

El hijo se entrenó con 30 tareas revisadas. Dio mAP50 0.795 y conteo exacto de 0/7 en val; Ojo y Ceja fueron las clases débiles. Parte de los errores vino de seguir el guion a medias: había varias personas por foto, alguien al fondo de la escena de Fondo, y Fondo no se envió vacío. Los proyectos de prueba son desechables.

### Lecciones nuevas (no repetir)

- **El tiempo muerto domina el ciclo.** El cómputo en GPU es de segundos o pocos minutos. Lo que alarga el día son los arranques en frío, los traspasos manuales entre sesiones y el clic en CPU.
- **Fallos de qwen2.5:14b vistos en la prueba de caras:**
  - convierte "no se detectan" en un negativo (`lentes`), que suprimiría los ojos detrás de los lentes;
  - inventa adjetivos en los prompts ("curly hair");
  - no aplica una regla general ("los demás son individuales") y junta en una carpeta los grupos de fotos descritos.
- **`--continuar` corrige parcialmente.** Corrigió máximos, importancia y carpetas, pero conserva los prompts y negativos de la spec previa.
- **`comparar` tiene tres huecos:** no empareja sinónimos (Pelo/Cabello), exige el mismo conjunto de clases para emparejar carpetas y solo listó un sobrante.
- **El notebook de entrenamiento conserva el último `PROYECTO`.** Hay que eliminar la edición manual de la celda 1.
- **SAM 3 en conceptos conocidos rinde mucho más que en piezas industriales:** 79% de aceptación en caras frente a 24% en el ensamble.
- **Privacidad.** La regla incluye el fondo de la escena. Un negativo con una persona es un error de datos y un riesgo biométrico.

## Reglas de trabajo y seguridad

Estas reglas valen para la limpieza en formato chat. En L.11 se traducen a reglas para agentes (Claude Code y Kiro).

### Interacción

1. Se trabaja por etapas y sub-pasos: solo instrucciones y código de la etapa actual.
2. Respuestas cortas, un paso a la vez. Al final, preguntar si funcionó. No avanzar hasta que el usuario diga "Etapa completada" o pida ayuda con un error.
3. **Comandos de PowerShell exactos.**
   - **Archivos nuevos o reemplazos completos:** here-string `@' ... '@ | Set-Content -Encoding ascii ruta`, con `'@` pegado al margen y código ASCII sin acentos.
   - **Cambios pequeños:** `$c = Get-Content f -Raw; $c.Replace('viejo','nuevo') | Set-Content -Encoding ascii -NoNewline f`, y verificar con `Select-String`. Para un bloque largo: guardarlo antes en `$n = @' ... '@`.
   - **Pegarlos de uno en uno:** separar los comandos en bloques independientes y esperar el prompt entre uno y otro.
   - **Archivos con muchos cambios:** si un archivo cambia en muchos puntos, reemplazarlo completo.
   - **Scripts en el contenedor:** `docker compose exec -T motor python /app/script.py`.
4. Verificar APIs y versiones antes de asumir, leyendo un objeto real o el código. Pedir el archivo antes de modificarlo.
5. Antes de interpretar un reporte, confirmar que es del último trabajo.

### Diseño

- **Sistema general y multiproyecto.** Nada fijo por caso en el código: lo específico va en la spec del proyecto.
- **Backend primero.** Cada paso es un comando de `xd.py` probado por CLI. La UI no reimplementa lógica.
- **Operaciones destructivas.** Modo reporte por defecto y `--aplicar` para escribir.
- **Núcleo.** `reglas.py`, `pipeline.py` y `leer_perfil` cambian la versión `sam3-...`. No se tocan sin decidir antes la migración.
- **Nunca dos modelos pesados cargados a la vez:** SAM 3 dos veces, o Whisper junto con el LLM, provoca OOM.
- **El KPI es el conteo exacto por imagen**, no el mAP.

### Seguridad y privacidad

- **Proyectos 1 y 2.** Están protegidos en `borrar_proyecto.py` y en la UI (`UI_PROTEGIDOS`). Como todos los proyectos son desechables, L.0 decide si se quita esa protección. Si se quita, se hace como paso explícito y con reporte.
- **Fotos de caras.** Solo con permiso, sin terceros al fondo de la escena y sin compartir. Audios y textos del asistente (`ui/audios`, `ui/textos`) tampoco se comparten.
- **Token de Label Studio.** Se expuso en un chat anterior: hay que rotarlo (L.0).
- **Archivos que nunca se comparten ni se suben a Git:** `.env`, fotos, audios, lotes, datasets ni modelos.

## Decisiones de arquitectura para el piloto

El piloto es interno, para un equipo de 5 personas de la empresa, sin datos de clientes y con costo cero en la nube. La arquitectura aprobada es **Hub local -> Worker GPU en Kaggle (por API) -> respaldo en Colab (manual)**. El objetivo es eliminar los tiempos muertos: arranques en frío, traspasos manuales y el clic en CPU.

| # | Decisión | Motivo | Descartado |
| --- | --- | --- | --- |
| D1 | **Hub local**: Label Studio, Postgres, UI, cola de trabajos, hijo para `ver` | Datos y estado en un solo lugar; la webcam solo funciona en el host | - |
| D2 | **Worker GPU único en Kaggle**, lanzado por API; los pesos van como dataset de Kaggle; un solo código para asistente, pre-etiquetado, entrenamiento y precodificación | Kaggle permite lanzar en segundo plano sin navegador, con una cuota semanal más estable; quita los traspasos manuales | Tres notebooks en tres plataformas |
| D3 | **Colab como respaldo** con el mismo código del worker | Para cuando se agote la cuota de Kaggle | Colab como pieza fija |
| D4 | **HF ZeroGPU fuera** de la arquitectura base | Crear un Space ZeroGPU exige cuenta PRO; la cuota gratuita es de 3.5 min/día; riesgo de privacidad en una demo pública | Demo pública: solo con datos sintéticos y una community grant |
| D5 | **Almacenamiento detrás de un adaptador**: Drive, dataset de Kaggle y, en el futuro, un bucket privado (S3 o equivalente) | El salto comercial con datos sensibles no debe cambiar el flujo | Rutas fijas a Drive en el código |
| D6 | **Precodificación de SAM 3 en lote** en el worker, devolviendo la caché al hub (**prioridad alta**) | El clic pasaría de 27-47 s a unos 0.2 s, como con la imagen en caché | - |
| D7 | **Python como lenguaje.** Orden de optimización: medir con `py-spy`, optimizar el modelo, vectorizar con NumPy y luego Numba | La inferencia ya corre en C++/CUDA; los bloqueos son de diseño de la cola | Reescribir en Rust, C o C++ en el piloto |
| D8 | **Modelos por capacidad**, con interfaces estrictas: STT, extractor de spec, detector por texto, segmentador interactivo y detector entrenado. La elección se decide con nuestro banco de pruebas (`comparar`, `aceptacion`) | Agnosticismo útil sin una capa genérica | "Cualquier modelo"; LocateAnything-3B (licencia no comercial y optimizado para BF16 en Ampere; la T4 es Turing) |
| D9 | **Cola persistente en SQLite** en el hub, con una máquina de estados por trabajo y políticas por paso (automático o con confirmación) | Encadenar pasos sin intervención y sobrevivir reinicios | Kafka, RabbitMQ; Drive como cola implícita |
| D10 | **Superposición**: lotes en trozos con importación incremental, para revisar el primer trozo mientras el worker procesa el resto | La revisión humana y la GPU dejan de esperarse | Lotes monolíticos |
| D11 | **UI dual sobre la misma API**: modo guiado (asistente paso a paso) y modo profesional (la UI actual) | Ocultar la complejidad sin perder control | Dos backends |
| D12 | **Cuantización y LoRA**: al backlog como "Modo Flash" | Primero estabilidad del flujo actual | - |

Las cifras de las plataformas (cuotas de Kaggle y ZeroGPU, licencia de LocateAnything) son de la consulta del 20/10/2026 y cambian a menudo. Hay que verificarlas en la cuenta antes de construir cada pieza.

## Plan de limpieza (en formato chat)

La limpieza deja el repositorio limpio y, a la vez, prepara el piloto sin construirlo todavía. Hay que entender cada pieza antes de cederle control a un agente. Son 12 pasos (L.0 a L.11). Los que preparan el piloto se marcan en la tercera columna.

| Paso | Qué | Prepara para el piloto | Criterio de cierre |
| --- | --- | --- | --- |
| L.0 | **Decisiones previas:** quitar o no la protección de los proyectos 1 y 2; rotar el token de Label Studio | - | Decisión anotada; token nuevo en `.env` |
| L.1 | **Borrar los proyectos de prueba:** Label Studio, specs (`zz-*`, `ensamble-voz`, `productos-voz`, `caras`, `caras-ref`), `mis_imagenes`, Drive (lotes, datasets, runs, asistente), `motor/modelos`, diagnósticos, `ui/audios`, `ui/textos`. Siempre con reporte primero | Hub limpio para el equipo | El tablero y Pasos externos quedan vacíos |
| L.2 | **Git:** `.gitignore` (`.env`, `mis_imagenes`, `ui/audios`, `ui/textos`, `motor/lotes`, `motor/datasets`, `motor/modelos`, `motor/diagnosticos`, `*.bak`, `*.pt`, `__pycache__`); `env_ejemplo.txt` -> `.env.example` | Repositorio que se puede compartir con el equipo | `git status` sin datos ni secretos |
| L.3 | **Código muerto a `_archivo/`**, confirmado con búsqueda de imports: `exportar_dataset.py`, `preetiquetar.py` y `preetiquetar_sam3.py` en la raíz; `docker-compose.backup.yml` y `.roto.yml`; `motor/diag_multimask.py`, `diag_setimage.py` y `migrar_version.py`; `pruebas/`; zips `_viejo`. `pipeline.py` NO, porque es núcleo | - | Tests en verde y la ruta completa funciona |
| L.4 | **Tests unificados:** un solo comando que corra los del host y los del contenedor | Red de seguridad para cambios de agentes | `xd.py test` reporta todo en verde |
| L.5 | **Arreglos generales pequeños:** `comparar` (sinónimos, carpetas con distintas clases, sobrantes), aviso en `spec.py` cuando un negativo no está en inglés, test de la raíz en `test_buzon`, comentario en `esquema_llm.FIJO`, specs `-ref` sin siguiente paso en el tablero, alineación de las tablas del plan | - | Tests nuevos en verde |
| L.6 | **Asistente:** instrucciones contra adjetivos y contra negativos que se solapan con clases; aplicar reglas generales ("los demás"); un grupo de fotos descrito = una carpeta; `--continuar` que respete correcciones de prompts y negativos. Probar `--modelo qwen3:14b` con el mismo audio | Interfaz STT/LLM limpia (D8) | El audio de caras da una spec sin `lentes` ni adjetivos |
| L.7 | **Worker único:** unificar los tres notebooks de Colab en uno. Una celda de preparación y una lanzadora que procesa por tipo de trabajo (`asist_`, `lote_` y un pedido de entrenamiento escrito por `xd.py`), con un solo modelo pesado cargado a la vez. Se escribe para que el mismo código corra después en Kaggle. El entrenamiento ya no edita la celda 1. Un solo documento de notebook | D2, D3 y D5 | Asistente, pre-etiquetado y entrenamiento corren en una sola sesión sin editar celdas |
| L.8 | **Spike de la caché de SAM 3** (prioridad alta): medir el tamaño de `features` y `dataset` por imagen; serializar en Colab y cargar en el motor del hub; medir el clic con la caché importada. Solo medir, sin integrarlo | D6 | Cifra de MB por imagen y clic de menos de 1 s con caché importada, o un "no se puede" justificado |
| L.9 | **FPS de `ver`:** medir `--imgsz` 960, 640 y 480, y la exportación a OpenVINO | Mejora del uso en vivo | Tabla de FPS y precisión por opción |
| L.10 | **Concurrencia del motor:** explicar la cola atascada (`cola` 15 con `precodificando` 0) con `py-spy` y el log; corregir el diseño si es un bloqueo | D7 y D9 | La cola no crece sin trabajo real |
| L.11 | **Documentación para agentes:** README, `.env.example` comentado, reglas para Claude Code (`CLAUDE.md`) y para Kiro (steering), y reformular este documento | Ceder control a agentes con contexto | Un agente nuevo entiende el sistema solo con esos archivos |

Orden sugerido: L.0 -> L.1 -> L.2 -> L.3 -> L.4. Esos cinco dejan el terreno firme. Después, L.8 por su prioridad alta, y luego L.5, L.6, L.7, L.9, L.10 y L.11.

## Ruta de optimización hacia el piloto

Después de la limpieza, el piloto se construye en siete fases, ya con Claude Code o Kiro. Cada fase tiene una medida de antes y después. El objetivo es que el ciclo de audio a hijo validado deje de esperar a una persona entre pasos.

| Fase | Qué | Depende de | Medida |
| --- | --- | --- | --- |
| P.1 | **Cola persistente** en SQLite en el hub, con una máquina de estados por trabajo (pendiente, enviado, en proceso, listo, importado, error). Reemplaza la detección por archivos en Drive; Drive queda solo como transporte | L.7 | Trabajos que sobreviven a un reinicio del hub |
| P.2 | **Worker en Kaggle por API:** el código de L.7 con un adaptador de almacenamiento (dataset de Kaggle). Los pesos (sam3.pt, Whisper, qwen, YOLO base) van como dataset para no descargarlos en cada sesión. Colab queda como respaldo con el mismo código | P.1, L.7 | Tiempo desde "Enviar" hasta el resultado, sin abrir un navegador |
| P.3 | **Precodificación de SAM 3 en lote** en el worker, con la caché devuelta al hub e importada por el motor | L.8, P.2 | Clic de 27-47 s a menos de 1 s en las tareas de la muestra |
| P.4 | **Superposición:** lotes en trozos (por ejemplo, de 10) con importación incremental; la revisión empieza con el primero | P.1 | Minutos hasta poder revisar la primera tarea |
| P.5 | **Encadenamiento con políticas por paso:** automático o con confirmación, y confirmación anticipada antes de que termine el trabajo anterior | P.1 | Pasos encadenados sin intervención |
| P.6 | **Equipo de 5:** UI accesible en la red interna con autenticación (hoy solo escucha en 127.0.0.1 y no tiene usuarios); cuentas de Label Studio por persona; un hub fijo en lugar de la laptop | P.1 | 5 personas revisando a la vez sin bloquearse |
| P.7 | **UI dual:** modo guiado sobre la misma API (el "siguiente paso" del tablero convertido en asistente), y el modo profesional actual | P.1, P.5 | Un usuario nuevo completa un caso sin ver comandos |

P.6 es nueva respecto al debate. Un piloto para 5 personas cambia supuestos de la PoC: un solo trabajo a la vez, la UI solo en el host local y la laptop con 2 núcleos como hub. Conviene decidirla antes de P.1.

## Backlog y preguntas abiertas

### Backlog (después del piloto o cuando haga falta)

- **Modo Flash:** cuantización de los modelos (LLM, Whisper, hijo en int8 para `ver`) y LoRA. Va después de que el flujo esté estable.
- **Etapa F pendiente:** calibración del umbral de conteo por clase y puntuación de incertidumbre para priorizar la revisión. El registro del best.pt de charolas se revisa si el proyecto 1 se borra en L.0.
- **Nuevos modelos** por las interfaces de D8, cada uno evaluado con `comparar` y `aceptacion` antes de adoptarlo.
- **Bucket privado** (S3 o equivalente) detrás del adaptador de D5, para el salto comercial con datos sensibles.
- **Entorno:** probar `docker-compose.gpu.yml`, evaluar fp16 y dejar un solo OpenCV (headless).
- **Demo pública** opcional, solo con datos sintéticos y una community grant de Hugging Face.

### Preguntas abiertas

- [ ] L.0: ¿se borran también los proyectos 1 y 2? Hoy están protegidos en el código.
- [ ] P.6: ¿qué máquina hará de hub para el equipo de 5? La laptop actual tiene 2 núcleos y no tiene GPU.
- [ ] P.2: ¿una cuenta de Kaggle de equipo o una por persona? La cuota es por cuenta; revisar las condiciones de Kaggle antes de compartir una.
- [ ] L.8: si la caché de SAM 3 resulta demasiado grande para mover por Drive, la alternativa es precodificar solo la muestra que se va a revisar.

### Fuentes (consultadas el 20/10/2026)

- [Hugging Face: ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu). PRO para crear Spaces ZeroGPU; cuota diaria de 3.5 min para cuentas gratuitas.
- [GMI Cloud: GPU gratuitas 2026](https://www.gmicloud.ai/en/blog/best-free-gpu-cloud-options-for-ai-startups-and-researchers) y [gpuperhour.com](https://gpuperhour.com/blog/free-cloud-gpus-and-credits). Cuota de Kaggle de unas 30 h por semana, no documentada oficialmente y variable.
- [Thunder Compute](https://www.thundercompute.com/blog/google-colab-alternatives). Ejecución en segundo plano de Kaggle.
- [ComfyUI Wiki: LocateAnything-3B](https://comfyui-wiki.com/en/news/2026-06-29-nvidia-locateanything-3b-open-source-grounding-model). Licencia no comercial; optimizado para BF16 en Ampere o posterior.
