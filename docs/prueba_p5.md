# P.5.5: Prueba end-to-end del encadenamiento

Escrito: 05/11/2026  
Objetivo: verificar que el flujo completo funciona con mínima intervención manual (solo confirmaciones [S/n])

## Flujo esperado

```
Spec validada → auto-crear proyecto → capturar fotos → auto-sincronizar → 
exportar lote → enviar a Kaggle → daemon detecta terminado → auto-importa → 
tareas listas en Label Studio
```

## Preparación (una sola vez)

### 1. Daemon en segundo plano
Opción A (terminal separada, recomendado para la prueba):
```powershell
python xd.py daemon
# Dejar corriendo, Ctrl+C para detener al terminar
```

Opción B (background, para uso real):
```powershell
Start-Process python -ArgumentList "xd.py","daemon" -RedirectStandardOutput "datos\daemon.log" -RedirectStandardError "datos\daemon.log" -NoNewWindow
# Para detener: buscar el proceso y matarlo
```

### 2. Proyecto de prueba
- Nombre: `prueba-p5`
- 2 clases: `tornillo`, `tuerca`
- Plan: 6 fotos por clase = 12 fotos totales
- Método: spec manual (sin asistente)

## Pasos de la prueba (cronometrados)

**Tiempo estimado: ~15-20 min**

### Paso 1: Crear spec y proyecto (2 min)

```powershell
# Crear spec desde plantilla
python xd.py spec-nueva prueba-p5 --titulo "Prueba P.5 Encadenamiento" --aplicar

# Editar motor/proyectos/prueba-p5/spec.json:
# - En "clases": ["tornillo", "tuerca"]
# - Revisar "modo": "auto" (SAM 3)
# - Guardar

# Validar (debe salir rc=0)
python xd.py validar prueba-p5

# Crear proyecto en Label Studio
python xd.py crear-proyecto prueba-p5
```

**✓ Checkpoint 1:** Proyecto `prueba-p5` existe en http://127.0.0.1:8080

### Paso 2: Capturar fotos (3-5 min)

```powershell
python capturar.py prueba-p5 --total 12
# Capturar 6 tornillos (espacio para guardar, n/p para cambiar carpeta)
# Capturar 6 tuercas
# Al completar todas: "Sincronizar con Label Studio? [S/n]"
# Responder: S (Enter)
```

**✓ Checkpoint 2:** 12 tareas creadas en Label Studio sin anotaciones

### Paso 3: Exportar y enviar a Kaggle (1 min)

```powershell
# Exportar lote (12 fotos = 1 solo trozo, sin _t01/_t02)
python xd.py lote-exportar prueba-p5

# Enviar a Kaggle
python xd.py worker --enviar --aplicar
# Muestra: "envio_TIMESTAMP: subida X s | dataset listo tras Y s | kernel lanzado"
```

**✓ Checkpoint 3:**
- Archivo `lote_prueba-p5_*.zip` en `datos/kaggle/espejo/lotes/`
- Cola: `python xd.py trabajos --tipo preetiquetado` muestra estado `lanzado` o `corriendo`

### Paso 4: Daemon detecta y auto-importa (5-10 min)

**Sin hacer nada**, observar el log del daemon (terminal donde corre):
```
[TIMESTAMP] Ciclo N: consultando Kaggle...
  kernel: running
daemon: no hay trabajos listos pendientes de importar

[TIMESTAMP] Ciclo N+1: consultando Kaggle...
  kernel: complete
  envío envio_TIMESTAMP: lanzado -> terminado
daemon: 1 trabajo(s) listo(s) pendiente(s) de importar
  → importando predicciones ... (lote_prueba-p5_*.zip)...
```

**Monitoreo alternativo (otra terminal):**
```powershell
# Ver estado de la cola
python xd.py trabajos --tipo preetiquetado

# Ver log si daemon está en background
Get-Content datos\daemon.log -Wait -Tail 20
```

**✓ Checkpoint 4:**
- Envío en estado `terminado`
- Trabajo de preetiquetado en estado `importado`
- 12 tareas en Label Studio CON pre-anotaciones (máscaras de SAM 3)

### Paso 5: Verificación final (1 min)

```powershell
# Ver estado general
python xd.py estado

# Abrir Label Studio y revisar 2-3 tareas
# Deben tener máscaras pre-dibujadas (polígonos azules)
```

## Criterios de éxito

### ✅ Automatizaciones que deben funcionar SIN intervención:
1. **Sincronizar tras captura** (solo confirmar [S])
2. **Daemon detecta kernel terminado** (cada 5 min)
3. **Daemon auto-importa predicciones** (sin `lote-importar` manual)

### ✅ Pasos manuales esperados:
- Crear spec y proyecto
- Capturar fotos y confirmar sincronización
- Exportar y enviar a Kaggle

### ❌ Lo que NO debe requerir intervención:
- `worker --traer` manual
- `lote-importar` manual  
- Consultar Kaggle.com o abrir navegador

## Variantes opcionales

### Variante A: Con asistente (más completa, +10 min)
1. `python xd.py asistente prueba-p5 --texto "tornillos y tuercas, 6 fotos de cada uno"`
2. `python xd.py worker --enviar --aplicar`
3. Esperar daemon (trae resultado automáticamente)
4. `python xd.py asistente-importar prueba-p5 --aplicar` → confirmar [S] para crear proyecto (P.5.4)
5. Continuar desde captura...

### Variante B: Solo daemon (verificación mínima)
Si ya existe un envío `corriendo`:
```powershell
python xd.py daemon --solo-una-vez
# Verifica que detectó y procesó automáticamente
```

## Limpieza post-prueba

```powershell
# Detener daemon si está corriendo (Ctrl+C)

# Borrar proyecto de Label Studio
python xd.py borrar-proyecto prueba-p5

# Archivar trabajos de la cola
python xd.py archivar lote_prueba-p5_*.zip

# Borrar fotos (opcional)
Remove-Item -Recurse mis_imagenes\prueba-p5\

# Borrar spec (opcional)
Remove-Item -Recurse motor\proyectos\prueba-p5\
```

## Documentación de resultados

Al terminar, registrar en el contexto:
- ✓ Tiempo real de cada paso
- ✓ Logs relevantes del daemon
- ✓ Problemas encontrados (si los hay)
- ✓ Medida: "pasos encadenados sin intervención" (éxito/fallo)

## Notas

- El daemon consulta Kaggle cada 5 min: puede haber hasta 5 min de espera tras el kernel terminar
- Si el kernel falla, el daemon lo detecta y marca el envío como `fallido` (no importa)
- Los trozos (_t01, _t02) solo se generan con 16+ fotos; con 12 fotos va en un solo lote
- La prueba NO requiere cache previa: SAM 3 anotará sin precodificación (más lento, ~1.5-2s por foto)
