# Spec de proyecto sin asistente (L.5)

Crear: `python xd.py spec-nueva <slug> --titulo "Mi proyecto"` (reporte) y luego con `--aplicar`.
Editar `motor/proyectos/<slug>/spec.json` y revisar con `python xd.py validar <slug>` hasta 0 errores.
Quitar todas las marcas `CAMBIAR:` antes de crear el proyecto.

## Raiz
| Clave | Obligatoria | Valor |
|---|---|---|
| esquema | si | 1 |
| proyecto | si | {titulo, slug, descripcion}; slug = nombre de la carpeta (minusculas, digitos, _ o -) |
| tipo | no | poligonos (defecto) o cajas |
| imgsz | no | entero 256-2048 (defecto 644). Cambiarlo invalida caches y modelos previos |
| negativos | no | lista de textos en ingles que NO son piezas (ej. shadow); sin @ ni ; |
| ajustes | no | globales de perfil.py salvo imgsz (validar lista las permitidas); numeros 0-2 |
| clases | si | lista, al menos una |
| carpetas | si | lista, al menos una; conviene una de tipo negativo |
| imagenes | no | {raiz}: dentro de mis_imagenes, sin '..' (defecto mis_imagenes/<slug>) |
| motor | no | {url: http://motor:9090, interactivo: true/false} |

## Clase
| Clave | Valor |
|---|---|
| nombre | letra inicial, luego letras, digitos o _ (sin espacios ni acentos) |
| prompts | lista en ingles: "texto" o "texto@0.20" (confianza propia). Sin prompts = solo manual |
| descripcion, color | texto libre (color: nombre o #RRGGBB) |
| max_por_imagen | entero >= 1 |
| area_min, area_max | fraccion de la imagen 0-1; area_min < area_max |
| conf | 0-1 |
| clic | grande, chico o vacio: que mascara elegir al hacer clic |
| importancia | alta, media o baja: pide mas fotos en el plan si es alta |
| dentro_de, contencion | para piezas que comparten prompt: una dentro de otra (contencion 0-2) |

Clases que comparten prompt: perfil.py fusiona sus limites y usa el mas permisivo (validar avisa).

## Carpeta
| Clave | Valor |
|---|---|
| nombre | letras, digitos, _ o -; es la subcarpeta dentro de imagenes.raiz |
| tipo | pieza (una clase sola), mezcla (varias juntas) o negativo (fondo sin piezas, sin clases) |
| clases | nombres de clases existentes |

Ejemplo real completo: motor/fixtures/spec_ensamble.json.
