# Reglas para agentes (Claude Code, Kiro y otros)

Lee primero: `README.md` (que es y como se usa), el contexto del piloto (vive fuera del repo; el usuario indica la ruta) y, para specs,
`motor/plantillas/LEEME_spec.md`. Usuario: IoT Lab (XalDigital). Idioma del codigo y la UI: espanol sin acentos (ASCII).

## Mapa del codigo
- `xd.py`: CLI, fuente de verdad de cada paso. `ui.py`: servidor (biblioteca estandar), lista blanca `ACCIONES`,
  un trabajo a la vez. `tablero.py`: SOLO lectura. `cuadernos.py`: limpieza y comparacion de cuadernos.
- `motor/` (contenedor, montado en /app): servicio (`_wsgi.py`, `model.py`, `cola.py`, `interactivo.py`, `config.py`),
  proyectos (`spec.py`, `generar.py`, `crear_proyecto.py`, `borrar_proyecto.py`, `sincronizar.py`, `plan.py`),
  datos (`muestra`, `diagnostico`, `correccion`, `registro`, `hijo`, `lote`, `exportar_*`, `importar_lote`,
  `aceptacion`), asistente (`esquema_llm`, `asistente`, `llm_ollama`, `trabajo`, `buzon`, `comparar`, `banco_asistente`).
- Modulos puros (sin red ni disco, corren en host y Colab): `spec`, `perfil`, `plan`, `esquema_llm`, `asistente`,
  `colores`, `comparar`, `banco_asistente`, `cuadernos`.
- `notebooks/`: cuadernos de Colab. `motor/fixtures/`: datos fijos de tests. `_archivo/`: codigo muerto (no versionado).

## Reglas de oro
1. **Nucleo intocable sin decidir la migracion:** `motor/reglas.py`, `motor/pipeline.py` y `leer_perfil`
   (en `perfil.py`) entran en el hash de version `sam3-<perfil>-<nucleo>`; cambiarlos deja huerfanas las predicciones.
2. **Nunca dos modelos pesados a la vez** en un mismo proceso o equipo (SAM 3 dos veces, Whisper + LLM): OOM.
3. **Todo lo que escribe tiene modo reporte;** `--aplicar` escribe. Nada destructivo sin reporte previo.
4. **General y multiproyecto:** nada fijo por caso en el codigo; lo especifico va en la spec del proyecto.
5. **Backend primero:** cada paso es un comando de `xd.py` probado por CLI; la UI no reimplementa logica.
6. **Privacidad:** nunca leer, copiar ni subir `.env`, fotos, audios, lotes, datasets ni modelos. Nunca imprimir tokens.
7. **El KPI es el conteo exacto por imagen,** no el mAP.

## Como trabajar
- Antes de cada commit: `python xd.py test` debe dar rc 0. Un test nuevo `motor/test_X.py` se agrega a
  `TESTS_HOST` o `TESTS_MOTOR` en `xd.py`; si no, `xd.py test` falla con rc 2 a proposito.
- Los tests no dependen de datos reales: usa `motor/fixtures/`.
- Cambios en `motor/`: `docker compose restart motor` antes de probar (gunicorn --preload).
- Configuracion: el motor solo lee el entorno en `config.py`; el host, en `xd.ENV` (.env). Variables nuevas van
  comentadas en `.env.example`.
- Versiones fijas e iguales en hub y Colab (`ultralytics==8.4.174`, timm, CLIP): `test_notebooks` lo verifica.
- Cuadernos: el repo es la fuente de verdad. Tras editar en Colab: `python xd.py cuadernos --traer --aplicar`.
  Nunca subir un cuaderno con salidas (`test_notebooks` lo bloquea).
- Verifica APIs y versiones leyendo el codigo real o un objeto real antes de asumir; pide el archivo antes de editarlo.
- Para el LLM del asistente prefiere arreglos deterministas en codigo a retocar el prompt (L.6: con 14B es fragil);
  mide con `python motor/banco_asistente.py` y el banco en Colab.
- Mide antes de optimizar (py-spy, `/estado`); en CPU de 2 nucleos el pre y postprocesado pesan tanto como el modelo.