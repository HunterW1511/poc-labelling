Set-Location C:\PoC-Labelling
$f = 'C:\PoC-Labelling\.env'
$old = (Get-Content $f | Where-Object { $_ -match '^LS_API_TOKEN=' }) -replace '^LS_API_TOKEN=',''
$s = Read-Host 'Pega el token nuevo (no se ve)' -AsSecureString
$b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
$new = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b).Trim()
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b)
"largo: $($new.Length)"
if ($new -notmatch '^[A-Za-z0-9._-]{20,}$') { $r = ($new.ToCharArray() | Where-Object { "$_" -notmatch '[A-Za-z0-9._-]' } | ForEach-Object { [int]$_ } | Sort-Object -Unique) -join ','; "formato invalido: no escribo | codigos_raros: $r | hex40: $($new -match '[0-9a-f]{40}') | segmentos: $(($new -split '\.').Count)"; exit 1 }
if ($new -eq $old) { 'igual al de .env: no escribo'; exit 1 }
try { $u = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/current-user/whoami' -Headers @{ Authorization = "Token $new" } }
catch { "Label Studio rechaza el token: $($_.Exception.Response.StatusCode.value__)"; exit 1 }
$c = Get-Content $f -Raw
($c -replace '(?m)^LS_API_TOKEN=.*$', "LS_API_TOKEN=$new") | Set-Content -Encoding ascii -NoNewline $f
"OK .env actualizado para $($u.email)"
docker compose up -d motor
docker compose exec -T -w /app motor python -c "import requests; from config import HEADERS, LS_URL; print('motor ->', requests.get(LS_URL + '/api/current-user/whoami', headers=HEADERS, timeout=30).status_code)"
