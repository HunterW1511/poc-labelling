# PoC-Labelling: contexto, estado y ruta al piloto

Actualizado: 31/10/2026 (fin de la limpieza L.0-L.11). Reemplaza al "contexto unificado" del 20/10/2026
(historico en `docs/historico/`). Uso basico en README.md; reglas para agentes en CLAUDE.md.

## Estado
- Hub en blanco: sin proyectos, fotos, lotes, datasets ni modelos. 17 tests en verde (`python xd.py test`).
- Repo en GitHub (privado). Token de Label Studio rotado; protecciones de los proyectos 1 y 2 quitadas
  (`UI_PROTEGIDOS=` vacio): todos los proyectos son desechables.
- Equipo: laptop i7-7600U (2 nucleos, 16 GB, sin GPU usable), Docker con 11 GB, Colab T4 gratuito.

## Lo que se hizo en la limpieza (tal como se hizo)
| Paso | Resultado |
| --- | --- |
| L.0 | Proteccion de 1 y 2 quitada; token legacy rotado (`herramientas/rotar_token.ps1`) |
| L.1 | Proyectos y datos de prueba borrados (Label Studio, mis_imagenes, Drive, motor/*, ui/audios, ui/textos) |
| L.2 | Git nuevo, `.gitignore` estricto (datos, modelos, imagenes, audio, CSV), `.env.example`, `.gitattributes` LF |
| L.3 | Codigo muerto a `_archivo/` (no versionado) tras buscar referencias; pesos de prueba borrados |
| L.4 | `xd.py test`: host + contenedor; falla (rc 2) si hay un test sin clasificar |
| L.5 | Camino sin asistente: `motor/plantillas/` (spec + LEEME), `xd.py spec-nueva` y `validar`; spec invalida bloqueada en CLI, UI y servidor |
| L.6 | Banco del asistente (`motor/banco_asistente.py`, 3 trampas): qwen2.5:14b se queda (qwen3:14b ~6x mas lento y fallo el escalado). Arreglos deterministas: preguntas ya respondidas fuera, mezcla de una clase -> pieza, escalado por relacion explicito |
| L.7 | Cuadernos en `notebooks/` sin salidas, con versiones fijas = hub (`test_notebooks`), sincronizados con `xd.py cuadernos` |
| L.8 | Spike cache SAM 3: 8.3 MB/imagen (f32) o 4.1 MB (f16); la de Colab sirve en el hub (IoU >= 0.9995); clic ~0.1 s con cache. Viable |
| L.9 | `ver --backend auto|pt|openvino`: OpenVINO intel:cpu con exportacion rectangular; en la laptop de -8% a +40% (inestable), paridad exacta |
| L.10 | Cola atascada explicada: un lote despertaba al interactivo, que tomaba el candado de carga (7.5 min de espera) y luego competian dos SAM 3 por 2 nucleos. Arreglado; `/estado` explica la espera |
| L.11 | README, CLAUDE.md, steering de Kiro, este documento, `requirements.txt` del host, `herramientas/` |

## Decisiones de arquitectura del piloto (vigentes)
Piloto interno para 5 personas, sin datos de clientes y con costo cero en la nube:
**hub local -> worker GPU en Kaggle (por API) -> respaldo en Colab**.
- D1 Hub local: Label Studio, Postgres, UI, cola, hijo para `ver` (la webcam solo funciona en el host).
- D2 Worker unico en Kaggle con los pesos como dataset; D3 Colab como respaldo con el mismo codigo.
- D4 HF ZeroGPU fuera. D5 Almacenamiento detras de un adaptador (Drive hoy; bucket privado en el futuro).
- D6 Precodificacion de SAM 3 en el worker, cache devuelta al hub (validada en L.8).
- D7 Python; medir con py-spy antes de optimizar. D8 Modelos por capacidad, elegidos con el banco (`comparar`, `aceptacion`, `banco_asistente`).
- D9 Cola persistente en SQLite. D10 Lotes en trozos con importacion incremental. D11 UI dual. D12 Modo Flash al backlog.

## Ruta al piloto
| Fase | Que | Medida |
| --- | --- | --- |
| P.1 | Cola persistente SQLite con maquina de estados por trabajo | Trabajos que sobreviven a un reinicio |
| P.2 | Worker en Kaggle por API. Incluye unificar los tres cuadernos en un worker unico con lanzador por tipo de trabajo (pendiente de L.7) | De "Enviar" al resultado sin navegador |
| P.3 | Precodificacion en el worker + cache en el hub. Clave: hash de foto, imgsz, hash de sam3.pt y version de ultralytics; cargar con `weights_only=True` y validar formas; no transportar el `dataset`. Explorar el interactivo sin backbone (`build_interactive_sam3(with_backbone=False)`) para un hub liviano | Clic < 1 s en la muestra |
| P.4 | Superposicion: lotes en trozos | Minutos hasta revisar la primera tarea |
| P.5 | Encadenamiento con politicas por paso | Pasos sin intervencion |
| P.6 | Equipo de 5: UI en red interna con autenticacion, cuentas de Label Studio por persona (pasar a Personal Access Tokens), hub fijo | 5 personas a la vez |
| P.7 | UI dual (modo guiado) | Un usuario nuevo completa un caso sin comandos |
Con el worker, la cola semantica local (`cola.py`) queda solo como respaldo.

## Backlog
- Asistente v2: negativos que se solapan con clases, reglas generales ("los demas"), un grupo de fotos = una carpeta,
  `--continuar` que respete correcciones, relaciones implicitas ("su cuchara") como datos, la confusion entre el color
  de la interfaz y el del objeto en las preguntas, qwen3 con `think: false`.
- Arreglos chicos pendientes del plan original: `comparar` (sinonimos, carpetas con distintas clases, sobrantes),
  aviso en `spec.py` si un negativo no esta en ingles, test de la raiz en `test_buzon`, comentario en
  `esquema_llm.FIJO`, specs `-ref` sin siguiente paso en el tablero, alineacion de las tablas del plan, textos
  "1 errores" en la UI.
- L.9 pendiente: FPS a imgsz 480 y precision por imgsz, con el primer modelo real del piloto.
- Etapa F: umbral de conteo por clase e incertidumbre para priorizar la revision. Modo Flash (int8, LoRA).
  Probar `docker-compose.gpu.yml`; un solo OpenCV (headless); torch del host igual al del motor.

## Lecciones (no repetir)
- El tiempo muerto domina: arranques en frio, traspasos manuales y el clic en CPU.
- SAM 3 rinde mucho mas en conceptos conocidos (caras 79%) que en piezas industriales (24%).
- Privacidad: incluye el fondo de la escena; nunca personas en fotos de prueba de objetos.
- OpenVINO: nunca `AUTO` (usar `intel:cpu`); exportar con la forma de la camara.
- No retocar el prompt del LLM 14B a ciegas: medir con el banco; preferir arreglos deterministas.

## Preguntas abiertas
- [ ] P.6: que maquina hace de hub para el equipo de 5.
- [ ] P.2: cuenta de Kaggle de equipo o por persona (revisar condiciones).
Las cifras de plataformas (cuotas de Kaggle, ZeroGPU) son del 20/10/2026: verificarlas antes de construir.