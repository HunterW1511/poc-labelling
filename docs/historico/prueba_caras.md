# Prueba de universalidad: caso caras (PoC-Labelling)

Oct 19, 2026 · @IoT Lab

## Instruccion inicial y proposito

El caso de caras (Cara, Ojos, Cejas, Labios, Dientes, Cabello, Oreja, Lentes) se usa como prueba de punta a punta porque es facil de ejecutar: basta una webcam y la propia cara. Ademas no se parece en nada a los casos con los que se construyo el sistema (charolas, ensamble, productos).

El proposito es validar que el sistema es universal SIN adaptarlo al caso. No se toca codigo para que las caras funcionen. Lo que falle se arregla de forma general, de modo que sirva para cualquier proyecto, o se documenta como limitacion.

Instruccion para el nuevo chat: "Actua como un Senior MLOps & Computer Vision Engineer. Ejecutamos la prueba de universalidad con el caso caras siguiendo este documento, paso a paso y con las reglas de interaccion del documento de contexto. No adaptes el sistema al caso: si algo falla, propon un arreglo general o documentalo como limitacion."

## Reglas de privacidad

Las fotos de caras son datos biometricos. Se aplican estas reglas sin excepcion:

- Solo caras propias o de personas que dieron permiso explicito, y nunca de menores.
- No se comparten fotos, audios, datasets, lotes, `_pred.json` ni capturas en ningun chat, repositorio ni documento. En el chat solo se pegan salidas de texto: conteos, tablas y errores.
- La carpeta Fondo es una escena sin personas. No se usan carteles, pantallas ni fotos con caras ajenas como negativos.
- Los lotes y datasets pasan por Drive y Colab de la cuenta del proyecto y no se publican.
- Al terminar: borrar el proyecto con `xd.py borrar-proyecto caras --aplicar`, las fotos de `mis_imagenes\caras` y los lotes, datasets y runs del proyecto en Drive. Lo que se conserva son las metricas en texto.
- Nada de esto entra en GitLab: `.gitignore` ya debe excluir imagenes, lotes, datasets y modelos.

## Lo que ya sabemos y aplica al caso

El unico riesgo de traslape previsto es la regla de duplicados. Lo demas del nucleo no deberia afectar a las partes de la cara.

- **Fragmentos.** La regla solo compara candidatos de las MISMAS clases. Ojos, Labios u Oreja dentro de Cara no se descartan como fragmentos de la cara.
- **`dentro_de` no hace falta.** Solo tiene efecto entre clases que comparten prompt (`spec.py` avisa si no lo comparten). En la referencia, cada clase tiene su propio prompt en ingles.
- **Duplicados (IoU > 0.6 entre clases distintas).** Es el unico riesgo.
  - El par mas expuesto es Dientes dentro de Labios con la boca abierta: si la caja de los dientes ocupa casi toda la de los labios, una de las dos se elimina.
  - El segundo es Cabello y Cara con cabello corto o recogido.
  - Ojos frente a Lentes deberia estar a salvo, porque un ojo ocupa poco de la caja de los lentes.
- **Prompts compartidos.** Si el asistente pone el mismo prompt a dos clases (por ejemplo "eye" para Ojos y Cejas), salen ambiguas y `a_ls` toma la primera, como paso con los ejes del ensamble. El hijo lo resuelve despues.
- **El area no separa clases parecidas.** Area\_min y area\_max son EXPERTO; no se ponen en esta prueba.
- **El KPI es el conteo exacto por imagen**, no el mAP. Las clases con `max_por_imagen` 2 (Ojos, Cejas, Oreja) son las mas propensas a contar mal, y en Perfil solo se ve una de cada par.
- **Limitacion conocida de qwen2.5:14b.** Junta piezas parecidas, traduce nombres a prompts y repite preguntas. Si junta Ojos con Cejas o Labios con Dientes se documenta, y se puede repetir con `--modelo`.
- **Laptop sin GPU.** Asistente, pre-etiquetado y entrenamiento van a Colab. SAM 3 interactivo en CPU tarda 80-240 s en cargar: `precalentar` antes de etiquetar con clic.
- **Lanzadoras de Colab.** Procesan TODO zip pendiente: archivar lo viejo antes de cada paso.
- **`imagenes.raiz`.** La referencia usa `mis_imagenes/caras`. Si el asistente pone `mis_imagenes` a secas, las carpetas Fondo de distintos proyectos caerian en la misma ruta: verificarlo en el paso 2.

## Ruta completa en 8 pasos

Todos los comandos se corren desde `C:\PoC-Labelling`, uno por uno, esperando el prompt. Los que escriben se corren primero sin `--aplicar`, para ver el reporte. `N` es el numero del proyecto que devuelve el paso 2.

### 1. Audio -> spec

Se graba el audio con el guion de temas, sin leer la spec. Se guarda como `pruebas\caras.m4a` y no se comparte.

```powershell
python xd.py asistente caras --audio pruebas\caras.m4a
```

En Colab, abrir `asistente.ipynb` y correr la celda 1 si la sesion es nueva, y luego la celda 2.

```powershell
python xd.py asistente-importar caras --comparar caras-ref
```

Si hay preguntas, contestarlas sin grabar otra vez. Despues se vuelve a correr la celda 2 de Colab y el `asistente-importar`.

```powershell
python xd.py asistente caras --continuar --respuestas "..."
```

```powershell
python xd.py asistente-importar caras --aplicar
```

### 2. Crear el proyecto

```powershell
python xd.py crear-proyecto caras
```

```powershell
python xd.py crear-proyecto caras --aplicar
```

```powershell
Get-Content motor\proyectos\caras\proyecto.json
```

El campo `proyecto` de ese archivo es `N`.

### 3. Captura

```powershell
python xd.py plan caras --total 120 --variaciones
```

```powershell
python capturar.py caras --total 120
```

```powershell
python xd.py sincronizar caras
```

```powershell
python xd.py plan caras --total 120
```

### 4. Pre-etiquetado SAM 3 de una muestra

Antes, archivar los `lote_*.zip` viejos de Drive.

```powershell
python xd.py preetiquetar N --muestra 30
```

```powershell
python xd.py preetiquetar N --muestra 30 --aplicar
```

En Colab, abrir el notebook de pre-etiquetado y correr las celdas 1 y 2.

```powershell
python xd.py lote-importar --fijar-version
```

### 5. Revision en Label Studio

```powershell
python xd.py precalentar --proyecto N
```

En `http://127.0.0.1:8080/projects/N/`, revisar las 30 tareas de la muestra: corregir, completar con clic y dar Submit.

### 6. Dataset, entrenamiento y registro del hijo

```powershell
python xd.py dataset N --drive
```

En el notebook de entrenamiento, celda 1: `DS` con el nombre del zip y `PROYECTO = N`. Luego correr las celdas 2 y 3.

```powershell
python xd.py registrar N --run ultimo --activar
```

```powershell
python xd.py registrar N --run ultimo --activar --aplicar
```

### 7. El hijo pre-etiqueta mas tareas

```powershell
python xd.py preetiquetar N --muestra 30 --modo hijo
```

```powershell
python xd.py preetiquetar N --muestra 30 --modo hijo --aplicar
```

Correr la celda 2 del notebook de pre-etiquetado.

```powershell
python xd.py lote-importar --fijar-version
```

Revisar y dar Submit en Label Studio a esas 30 tareas.

### 8. Validacion y prueba en vivo

Las dos versiones salen de la salida de `lote-importar` en los pasos 4 y 7.

```powershell
python xd.py aceptacion N --versiones VERSION_SAM3,VERSION_HIJO
```

```powershell
docker compose exec -T motor python /app/diagnostico.py N
```

```powershell
python xd.py modelos N
```

```powershell
python xd.py ver N
```

## Guion de temas para el audio

El audio se graba hablando con naturalidad, en 40 a 90 segundos, sin leer la spec ni usar palabras del sistema: clase, prompt, carpeta, mezcla, negativo, importancia o max\_por\_imagen. Asi la prueba mide si el asistente entiende a un usuario real. Los temas, en cualquier orden:

1. Que se quiere detectar en una foto de una persona: la cara y sus partes, dichas con palabras normales.
2. Cuantas veces aparece cada parte en una foto (dos ojos, una boca...) y que en algunas fotos solo se ve un lado.
3. Que es lo mas importante de detectar y que es secundario.
4. Que fotos se van a tomar: de frente, sonriendo con los dientes, de lado y con lentes puestos.
5. Que tambien habra fotos sin ninguna persona.
6. Que cosas se pueden confundir: los dientes con los labios, las cejas con los ojos, el cabello con el fondo.
7. Que solo habra una persona por foto y que son fotos de webcam.

No se menciona en voz alta: los prompts en ingles, los numeros de fotos por carpeta ni los nombres exactos de las carpetas. Que los proponga el asistente es parte de lo que se mide.

Si el asistente pregunta algo, se contesta con `--continuar --respuestas` con la misma regla: describir el caso, no dictar la spec.

## Spec de referencia caras-ref

La spec `caras-ref` da 0 errores y 0 avisos con el `spec.py` actual. Se uso un `perfil.py` simulado, que no influye porque la spec no lleva `ajustes`. Sirve SOLO para `--comparar caras-ref`: nunca se corre `crear-proyecto caras-ref`.

Sus decisiones son 8 clases con un prompt propio en ingles cada una, Cara con importancia alta y las demas en null, sin claves EXPERTO, y 4 carpetas mezcla de 6 clases mas Fondo. Con las 8 clases en cada mezcla, el plan daria 26 por carpeta pero 15 de fondo.

```powershell
New-Item -ItemType Directory -Force motor\proyectos\caras-ref
```

```powershell
@'
{
 "esquema": 1,
 "proyecto": {
  "titulo": "Partes de la cara",
  "slug": "caras-ref",
  "descripcion": "Detectar la cara y sus partes en fotos de personas que dieron permiso"
 },
 "tipo": "poligonos",
 "negativos": [],
 "clases": [
  {"nombre": "Cara", "prompts": ["face"], "descripcion": "Rostro completo", "max_por_imagen": 1, "importancia": "alta"},
  {"nombre": "Ojos", "prompts": ["eye"], "descripcion": "Cada ojo por separado", "max_por_imagen": 2, "importancia": null},
  {"nombre": "Cejas", "prompts": ["eyebrow"], "descripcion": "Cada ceja por separado", "max_por_imagen": 2, "importancia": null},
  {"nombre": "Labios", "prompts": ["lips"], "descripcion": "Labios, boca cerrada o abierta", "max_por_imagen": 1, "importancia": null},
  {"nombre": "Dientes", "prompts": ["teeth"], "descripcion": "Dientes visibles al sonreir", "max_por_imagen": 1, "importancia": null},
  {"nombre": "Cabello", "prompts": ["hair"], "descripcion": "Cabello de la cabeza", "max_por_imagen": 1, "importancia": null},
  {"nombre": "Oreja", "prompts": ["ear"], "descripcion": "Cada oreja por separado", "max_por_imagen": 2, "importancia": null},
  {"nombre": "Lentes", "prompts": ["glasses"], "descripcion": "Lentes o anteojos puestos", "max_por_imagen": 1, "importancia": null}
 ],
 "carpetas": [
  {"nombre": "Frontal", "tipo": "mezcla", "clases": ["Cara", "Ojos", "Cejas", "Labios", "Cabello", "Oreja"], "descripcion": "De frente, boca cerrada, sin lentes"},
  {"nombre": "Sonrisa", "tipo": "mezcla", "clases": ["Cara", "Ojos", "Cejas", "Labios", "Dientes", "Cabello"], "descripcion": "De frente sonriendo con dientes visibles"},
  {"nombre": "Perfil", "tipo": "mezcla", "clases": ["Cara", "Ojos", "Cejas", "Labios", "Cabello", "Oreja"], "descripcion": "De lado o tres cuartos, con oreja visible"},
  {"nombre": "Con_lentes", "tipo": "mezcla", "clases": ["Cara", "Ojos", "Cejas", "Labios", "Cabello", "Lentes"], "descripcion": "De frente con lentes puestos"},
  {"nombre": "Fondo", "tipo": "negativo", "clases": [], "descripcion": "Escena sin personas"}
 ],
 "imagenes": {"raiz": "mis_imagenes/caras"},
 "motor": {"url": "http://motor:9090", "interactivo": true}
}
'@ | Set-Content -Encoding ascii motor\proyectos\caras-ref\spec.json
```

Verificacion en tu entorno: debe dar 0 errores y 0 avisos.

```powershell
docker compose exec -T motor python /app/spec.py /app/proyectos/caras-ref/spec.json
```

```powershell
python xd.py plan caras-ref --total 120
```

| Carpeta | Tipo | Fotos con --total 120 | Sin --total |
| --- | --- | --- | --- |
| Frontal | mezcla | 26 | 110 |
| Sonrisa | mezcla | 26 | 110 |
| Perfil | mezcla | 26 | 110 |
| Con\_lentes | mezcla | 26 | 110 |
| Fondo | negativo | 14 | 60 |
| Total |  | 118 | 500 |

El total con `--total 120` da 118 por el redondeo de cada carpeta.

## Que observar en cada etapa

Cada paso se juzga con un dato concreto. Si algo falla, se anota si es un fallo general, para arreglarlo en el sistema, o una limitacion, para documentarla.

| Paso | Que observar | Senal de alerta |
| --- | --- | --- |
| 1. Audio -> spec | La transcripcion trae bien los nombres. `--comparar caras-ref` da los aciertos de clases, max, importancia y carpetas. Se revisan los supuestos y las preguntas. | El LLM junta Ojos con Cejas o Labios con Dientes, repite un prompt entre clases, traduce un nombre como prompt raro o inventa importancia o max. Confirmar que el reporte es del ultimo trabajo. |
| 2. Crear proyecto | Las carpetas quedan bajo una raiz propia del proyecto, 1 storage por carpeta y el ML conectado con version `sam3-...`. | `imagenes.raiz` = `mis_imagenes` a secas, lo que hace chocar Fondo con otros proyectos. Tambien un titulo duplicado. |
| 3. Captura | El plan por carpeta y las variaciones son razonables para caras. `faltan` llega a 0 tras sincronizar. | Variaciones de pieza que no aplican a caras, como "rotacion de la pieza". Se anota como texto general del plan, no se adapta. |
| 4. Pre-etiquetado SAM 3 | La muestra queda estratificada por carpeta. Se mide el tiempo por foto en T4 y cuantas clases aparecen por foto. | Dientes o Labios que desaparecen en Sonrisa, Cabello o Cara que se pierden: es la regla de duplicados (IoU > 0.6). Tambien Ojos con mas de 2 instancias. |
| 5. Revision | Cuanto hay que corregir por clase y si el clic (SAM 3 interactivo) sirve para las partes chicas. | Clases que hay que dibujar casi siempre a mano. |
| 6. Hijo | En `metricas.json`: conteo exacto por imagen y MAE por clase. | Conteo muy bajo con solo 30 tareas revisadas: es esperable y se anota el numero, no se pule. |
| 7. Hijo pre-etiqueta | Elige el modo hijo solo porque hay modelo activo. Se mide el tiempo por foto frente a SAM 3. | El hijo hereda los huecos de SAM 3 (Dientes) o confunde Ojos y Cejas. |
| 8. Validacion | Aceptacion del hijo frente a sam3 (en ensamble fue 95% frente a 24%), diagnostico por clase y `ver` en vivo. | Conteo inestable en vivo con Ojos, Cejas y Oreja al girar la cara. |

Resultado esperado de la prueba: una tabla de aciertos de `--comparar`, las tasas de aceptacion, el KPI de conteo por clase y una lista de fallos clasificados como generales o como limitaciones.

## Archivos a adjuntar en el nuevo chat

Se suben las versiones ACTUALES desde `C:\PoC-Labelling`. Lo demas se pide con Get-Content cuando haga falta.

| Archivo | Por que |
| --- | --- |
| Contexto PoC-Labelling: retomar tras la etapa C | Contexto completo del sistema y reglas de interaccion |
| Este documento | Caso, ruta, guion, referencia y que observar |
| `xd.py` | CLI con todos los comandos de la ruta |
| `motor/plan.py` | Plan de captura del paso 3 |
| `motor/spec.py` | Validacion de la spec del asistente y de `caras-ref` |

Bajo demanda: `motor/proyectos/caras-ref/spec.json`, `capturar.py`, `motor/asistente.py`, `motor/comparar.py`, `motor/registro.py` y `motor/reglas.py`, este ultimo si la regla de duplicados borra partes.

No se comparten: `.env`, fotos, audios, lotes, `_pred.json`, datasets ni modelos.
