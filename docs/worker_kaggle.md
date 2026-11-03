# Worker GPU en Kaggle (P.2.1: investigacion y decision)

Investigado el 03/11/2026. Kaggle cambia cuotas y API sin aviso: lo marcado **[medir]** se confirma con la cuenta
real en P.2.6 a P.2.8, y lo marcado **[decidir]** necesita el OK del responsable antes de construir.
Las paginas de Kaggle (`kaggle.com/docs`, `kaggle.com/terms`) se cargan con JavaScript y no se pudieron leer
directamente; donde no hubo fuente oficial se dice.

## 1. Lo verificado

### Cuota y sesiones
| Dato | Valor | Fuente / confianza |
| --- | --- | --- |
| Cuota GPU | ~30 h por semana, se reinicia semanal; "a veces mas" segun demanda | Varias fuentes de 2026 que citan la doc de Kaggle. **[medir]** en la cuenta (Settings muestra la cuota) |
| Sesion maxima GPU | 12 h en fuentes recientes; 9 h en guias viejas | No confirmado en la doc oficial. Nuestros trabajos duran minutos: no es limitante |
| GPU | T4 x2 (`NvidiaTeslaT4`) o P100 de 16 GB; la CLI tambien lista `NvidiaL4` y otras restringidas | CLI oficial (`--accelerator`, `machine_shape`) |
| Disco de salida | `/kaggle/working` ~20 GB | No oficial. Alcanza para la cache de P.3 (4.1 MB por foto en f16: ~4800 fotos por envio) |
| Datasets privados | 100-200 GB en total segun la edicion de la fuente; se cuenta sin comprimir; maximo ~50 archivos en la raiz | Libros de Kaggle; **[medir]** |
| Ejecucion en segundo plano | Un `kernels push` corre en los servidores de Kaggle sin navegador | CLI oficial |

### API (CLI oficial `kaggle` 2.2.5, 22/10/2026, Python >= 3.11: sirve en el hub con 3.14)
- **Kernels:** `kaggle kernels push -p CARPETA [--accelerator NvidiaTeslaT4] [-t SEGUNDOS]` sube y ejecuta;
  `kaggle kernels status USUARIO/SLUG` (corriendo, completo o fallido; valores exactos **[medir]**);
  `kaggle kernels output USUARIO/SLUG -p DESTINO [--file-pattern REGEX] [-o]` descarga la salida.
- **`kernel-metadata.json`:** `id`, `title`, `code_file`, `language: python`, `kernel_type: script|notebook`,
  `is_private` (por defecto `true`), `enable_gpu` (por defecto `false`), `enable_internet` (por defecto `false`),
  `machine_shape`, `dataset_sources: ["usuario/slug"]`, `model_sources`, `kernel_sources`. Un issue reporta que
  el servidor espera `dataset_data_sources`: **[medir]** con el primer push.
- **Datasets:** `kaggle datasets create -p CARPETA` (privado por defecto; `-u` lo haria publico: **nunca**),
  `kaggle datasets version -p CARPETA -m "mensaje" [-d]` (`-d` borra versiones viejas), `kaggle datasets status`.
  Cuanto tarda una version nueva en estar disponible para un kernel: **[medir]**.
- **Autenticacion:** la CLI nueva usa un **API token** (`~/.kaggle/access_token` o `KAGGLE_API_TOKEN`); el
  `kaggle.json` es el metodo "legacy". Preferimos el token, guardado solo en el hub, nunca en el repo ni impreso.

### Modelos que viajan
- **SAM 3 (`sam3.pt`, 3.3 GB):** la SAM License (19/11/2025) permite usar, copiar y reproducir; las condiciones de
  redistribucion (incluir copia del acuerdo) aplican al ponerlo "a disposicion de un tercero". Un dataset
  **privado** para uso propio no parece distribucion, pero el texto no define "distribuir". Decision: dataset
  privado con el `LICENSE` de SAM dentro; nunca publico. Va a la lista legal junto con AGPL (contexto, sec. 9).
- **qwen2.5:14b (Ollama):** corre en T4 (Ollama usa CUDA; no TPU). Dos caminos: `ollama pull` con internet en cada
  sesion (~9 GB) o un GGUF en dataset privado + `Modelfile` + `ollama create` (sin internet). Empezar con `pull` y
  medir; si el arranque pasa de ~3 min, mover a dataset. Qwen2.5 es Apache-2.0.
- **Whisper (`large-v3-turbo`, faster-whisper):** igual que el LLM; nunca a la vez que el LLM (regla de oro 2).

### Imagen de Kaggle
No se encontraron las versiones 2026 de Python y torch de la imagen. El worker instala las versiones fijas
(`ultralytics==8.4.174`, timm, CLIP) igual que los cuadernos de Colab e **imprime** Python, torch, CUDA y
ultralytics al arrancar: el primer push las deja registradas **[medir]**.

## 2. Hallazgo critico: terminos de uso y cuenta compartida (afecta a D2)

Los Terms of Use de Kaggle prohiben que **varias personas operen bajo un mismo User ID, aunque sea una
organizacion**, y que una persona opere mas de una cuenta; la sancion puede ser perder la cuenta (texto citado
por las busquedas; la pagina no se pudo abrir directamente).

D2 decia: "cuenta personal, una sola cuota semanal para los 5". Si los 5 lanzan trabajos de Kaggle con la cuenta
de una persona a traves del hub, es al menos una zona gris y arriesga la cuenta.

**Propuesta [decidir]: una cuenta de Kaggle por persona.**
- Cada persona crea su cuenta y su API token. El hub guarda los tokens fuera del repo (un archivo por persona,
  como hoy `~/.kaggle/`), y cada envio usa el token de **quien lo lanza**.
- Durante P.2 solo hay un operador (el responsable): cumple los terminos desde el primer dia. El selector de
  persona llega con la autenticacion de P.6.
- Efecto colateral bueno: 5 cuotas (~150 h por semana) en lugar de una.
- La cola guarda un campo `operador` por trabajo (migracion de esquema 1 -> 2 en P.2.7).

## 3. Decisiones de arquitectura (propuestas)

1. **Un kernel por envio, no por trabajo.** El arranque en frio (instalar paquetes, cargar modelos) domina el
   costo y la cuota cuenta el tiempo de sesion. Un "envio" agrupa los trabajos pendientes, los procesa ordenados
   por modelo (todo lo de SAM 3, luego YOLO, luego Whisper y despues el LLM), liberando memoria entre grupos (un
   solo modelo pesado a la vez). Un trabajo que falla no tumba a los demas: deja su `error.txt`.
2. **Entradas por datasets privados:**
   - `xd-pesos`: `sam3.pt` + `LICENSE` de SAM (+ GGUF y Whisper si el arranque lo pide). Se sube una vez (P.2.6).
   - `xd-envios`: una version por envio con los zips de los trabajos y un `envio.json` (ids de la cola).
   - El codigo viaja dentro de cada zip, como hoy: el kernel es un lanzador fijo y delgado.
3. **Salidas:** `/kaggle/working/<trabajo>/resultado.json | error.txt + artefactos`; el hub las baja con
   `kernels output` y las mete a la cola (enviado -> en_proceso -> listo | error). El transporte Kaggle implementa
   la misma interfaz que Drive (P.2.5).
4. **Internet encendido al principio** (instalar versiones fijas y Ollama). Pasar a ruedas en un dataset solo si
   el arranque es lento o Kaggle lo pide. Puede requerir verificar el telefono de la cuenta **[medir]**.
5. **CLI `kaggle` por subprocess**, como `docker compose`: interfaz estable y documentada; `pip install kaggle` en
   el hub (`requirements.txt`). Sin llamadas REST a mano.
6. **Colab sigue de respaldo** con el mismo `worker.py`; el transporte Drive no se toca.

## 3b. Decisiones tomadas (03/11/2026)
- **D2: una cuenta de Kaggle por persona**; cada envio usa el token de quien lo lanza.
- **Proveedor del piloto: Kaggle.** Se evaluo Alibaba Cloud PAI-DSW (free trial): ~250 horas-computo al mes
  (A10: ~36 h al mes), cobro automatico por uso al terminar el trial, verificacion real-name, y DSW es un IDE (los
  trabajos irian por PAI-DLC y un endpoint por PAI-EAS, de pago). Queda para el **escalado** como otra
  implementacion del adaptador de transporte (D5). Kaggle no permite tuneles ni URLs de entrada, pero el diseno no
  los necesita: el hub empuja trabajos y trae resultados; el clic interactivo se resuelve en P.3 con cache.

## 4. Lo que se mide en P.2.6-P.2.8 (anotar maquina y fecha)
- Cuota real en la cuenta y la que consume cada envio.
- Tiempo desde `datasets version` hasta que el kernel lo ve; desde `kernels push` hasta `running` (cola de GPU).
- Arranque en frio: instalacion, carga de SAM 3, `ollama pull` frente a GGUF en dataset.
- Tiempo por foto (SAM 3 y modo hijo) y por entrenamiento corto en T4 frente a Colab.
- Valores reales de `kernels status` y la clave correcta de datasets en el metadata.

## 5. Fuentes (consultadas el 03/11/2026)
- CLI oficial, kernels: https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md
- CLI oficial, metadata de kernels: https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md
- CLI oficial, datasets: https://github.com/Kaggle/kaggle-cli/blob/main/docs/datasets.md
- CLI oficial, autenticacion e instalacion: https://github.com/Kaggle/kaggle-cli/blob/main/docs/README.md
- Paquete `kaggle` 2.2.5: https://pypi.org/project/kaggle/
- Issue `dataset_sources` frente a `dataset_data_sources`: https://github.com/Kaggle/kaggle-cli/issues/633
- Terminos de uso de Kaggle: https://kaggle.com/terms
- Cuota (no oficial): https://aifree.dev/offer/kaggle-free-gpu-tpu , https://agentdeals.dev/vendor/kaggle ,
  https://www.clusy.io/compare/colab-vs-kaggle
- Limites de datasets (libros de Kaggle): https://subscription.packtpub.com/book/data/9781801817479/3/ch03lvl1sec07/setting-up-a-dataset
- SAM License: https://huggingface.co/facebook/sam3/blob/main/LICENSE
- Ollama en Kaggle: https://dev.to/ifeanyi_idiaye_3f6d81ed8a/run-deepseek-r-1-thinking-model-in-kaggle-notebook-using-ollama-5195 ;
  Ollama con GGUF propio: https://qwen.readthedocs.io/en/latest/run_locally/ollama.html
- Imagen de Kaggle: https://www.github.com/Kaggle/docker-python/releases/latest
- PAI-DSW (free quota, horas-computo por tipo de instancia): https://help.aliyun.com/en/pai/faq-about-dsw ;
  free trials de Alibaba Cloud: https://help.aliyun.com/en/user-center/product-overview/learn-about-free-trials ;
  API de DSW: https://www.alibabacloud.com/help/en/pai/developer-reference/api-pai-dsw-2022-01-01-overview
- Kaggle bloquea SSH por ngrok (reportes de usuarios): https://github.com/abhishekkrthakur/colabcode/issues/73
