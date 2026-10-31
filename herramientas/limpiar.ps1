param([switch]$Aplicar)
$R = 'C:\PoC-Labelling'
$E = @{}; Get-Content "$R\.env" | Where-Object { $_ -match '^[A-Za-z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; $E[$k] = $v.Trim().Trim('"').Trim("'") }
$lotes = $E['LOTES_DRIVE']
if (-not $lotes -or -not (Test-Path $lotes)) { 'LOTES_DRIVE vacio o inexistente: no hago nada'; exit 1 }
$base = Split-Path $lotes -Parent
function D($k, $sub) { if ($E[$k]) { $E[$k] } else { Join-Path $base $sub } }
$vaciar = @("$R\mis_imagenes", "$R\motor\proyectos", "$R\motor\modelos", "$R\motor\diagnosticos", "$R\motor\lotes",
            "$R\motor\datasets", "$R\ui\audios", "$R\ui\textos", $lotes, (D 'DATASETS_DRIVE' 'datasets'), (D 'RUNS_DRIVE' 'runs'), (D 'ASISTENTE_DRIVE' 'asistente'))
$borrar = @("$R\best.pt", 'C:\PoC-Respaldo\p2-ensamble')
$raices = @("$R\", "$base\", 'C:\PoC-Respaldo\p2-ensamble')
function Seguro($p) { ($raices | Where-Object { $p.StartsWith($_, 'OrdinalIgnoreCase') -or $p -eq $_ }) -and ($p -notmatch 'sam3\.pt$') }
function Tam($p) { $fs = @(Get-ChildItem $p -Recurse -File -Force -ErrorAction SilentlyContinue); if (-not (Test-Path $p -PathType Container)) { $fs = @(Get-Item $p) }; '{0,6} arch {1,8:N1} MB' -f $fs.Count, (($fs | Measure-Object Length -Sum).Sum / 1MB) }
$verbo = if ($Aplicar) { 'BORRANDO' } else { 'BORRARIA' }
foreach ($d in $vaciar) {
  if (-not (Test-Path $d)) { "--  $d  no existe"; continue }
  $hijos = @(Get-ChildItem $d -Force | Where-Object { $_.Name -ne '.gitkeep' })
  "$verbo contenido de $d  ($($hijos.Count) elementos, $(Tam $d))"
  if ($Aplicar) { foreach ($x in $hijos) { if (Seguro $x.FullName) { Remove-Item $x.FullName -Recurse -Force } else { "   NO toco $($x.FullName)" } } }
}
foreach ($b in $borrar) {
  if (-not (Test-Path $b)) { "--  $b  no existe"; continue }
  "$verbo $b  ($(Tam $b))"
  if ($Aplicar) { if (Seguro $b) { Remove-Item $b -Recurse -Force } else { "   NO toco $b" } }
}
if (-not $Aplicar) { 'SOLO REPORTE: usa -Aplicar para borrar' } else { 'OK limpieza aplicada' }
