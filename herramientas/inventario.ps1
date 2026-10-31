Set-Location C:\PoC-Labelling
$E = @{}; Get-Content .env | Where-Object { $_ -match '^[A-Za-z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; $E[$k] = $v.Trim().Trim('"').Trim("'") }
$lotes = $E['LOTES_DRIVE']; $base = Split-Path $lotes -Parent
function D($k, $sub) { if ($E[$k]) { $E[$k] } else { Join-Path $base $sub } }
$raices = [ordered]@{
  'mis_imagenes' = 'C:\PoC-Labelling\mis_imagenes'; 'proyectos' = 'C:\PoC-Labelling\motor\proyectos'
  'modelos' = 'C:\PoC-Labelling\motor\modelos'; 'diagnosticos' = 'C:\PoC-Labelling\motor\diagnosticos'
  'lotes_local' = 'C:\PoC-Labelling\motor\lotes'; 'datasets_loc' = 'C:\PoC-Labelling\motor\datasets'
  'ui_audios' = 'C:\PoC-Labelling\ui\audios'; 'ui_textos' = 'C:\PoC-Labelling\ui\textos'
  'drv_lotes' = $lotes; 'drv_datasets' = (D 'DATASETS_DRIVE' 'datasets'); 'drv_runs' = (D 'RUNS_DRIVE' 'runs'); 'drv_asist' = (D 'ASISTENTE_DRIVE' 'asistente')
}
function Tam($p) { $fs = @(Get-ChildItem $p -Recurse -File -Force -ErrorAction SilentlyContinue); '{0,6} arch {1,9:N1} MB' -f $fs.Count, (($fs | Measure-Object Length -Sum).Sum / 1MB) }
foreach ($k in $raices.Keys) {
  $r = $raices[$k]
  if (-not (Test-Path $r)) { "== $k  $r  NO EXISTE"; continue }
  "== $k  $r  $(Tam $r)"
  $hijos = @(Get-ChildItem $r -Force | Sort-Object Name)
  $hijos | Select-Object -First 40 | ForEach-Object { if ($_.PSIsContainer) { '   [d] {0,-45} {1}' -f $_.Name, (Tam $_.FullName) } else { '   [a] {0,-45} {1,9:N1} KB' -f $_.Name, ($_.Length / 1KB) } }
  if ($hijos.Count -gt 40) { "   ... y $($hijos.Count - 40) mas" }
}
'== .pt fuera de los volumenes de Docker'
Get-ChildItem C:\PoC-Labelling, $base -Recurse -File -Filter *.pt -ErrorAction SilentlyContinue | ForEach-Object { '   {0,-90} {1,8:N1} MB' -f $_.FullName, ($_.Length / 1MB) }
