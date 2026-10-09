# Startet Quitly lokal unter Windows und öffnet die Webseite.
# Beim ersten Start: .env mit Zufallsschlüsseln, Eintrag für quitly.at in der hosts-Datei (Admin-Abfrage),
# Vertrauen in die lokale HTTPS-Zertifizierungsstelle (Windows fragt nach) und erster Benutzer.
$ErrorActionPreference = "Stop"
$Domain = if ($env:QUITLY_LOCAL_DOMAIN) { $env:QUITLY_LOCAL_DOMAIN } else { "quitly.at" }
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Say($msg) { Write-Host "`n> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "`nFEHLER: $msg" -ForegroundColor Red; Read-Host "Enter zum Schliessen"; exit 1 }

# 1. Docker vorhanden und gestartet?
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Start-Process "https://www.docker.com/products/docker-desktop/"
    Fail "Docker ist nicht installiert. Bitte Docker Desktop installieren und danach erneut starten."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Say "Docker Desktop wird gestartet ..."
    $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) { Start-Process $dd }
    for ($i = 0; $i -lt 90; $i++) { docker info *> $null; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 2 }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { Fail "Docker laeuft nicht. Bitte Docker Desktop oeffnen und erneut versuchen." }
}

# 2. Konfiguration mit kryptografisch zufaelligen Schluesseln
function RandomB64($n) { $b = New-Object byte[] $n; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b) }
function RandomHex($n) { $b = New-Object byte[] $n; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | ForEach-Object { $_.ToString("x2") }) -join "" }
if (-not (Test-Path ".env")) {
    Say "Erster Start: Konfiguration mit neuen Zufallsschluesseln wird erstellt ..."
    $text = [IO.File]::ReadAllText((Join-Path $Root ".env.example"))
    $text = $text -replace "(?m)^QUITLY_DOMAIN=.*$", "QUITLY_DOMAIN=$Domain"
    $text = $text -replace "(?m)^QUITLY_TLS=.*$", "QUITLY_TLS=internal"
    $text = $text -replace "(?m)^QUITLY_SECRET_KEY=.*$", ("QUITLY_SECRET_KEY=" + (RandomB64 32))
    $text = $text -replace "(?m)^QUITLY_ENCRYPTION_KEY=.*$", ("QUITLY_ENCRYPTION_KEY=" + (RandomB64 32))
    $text = $text -replace "(?m)^POSTGRES_PASSWORD=.*$", ("POSTGRES_PASSWORD=" + (RandomHex 24))
    $text = $text -replace "`r`n", "`n"
    [IO.File]::WriteAllText((Join-Path $Root ".env"), $text, (New-Object System.Text.UTF8Encoding $false))
    # Nur der aktuelle Benutzer darf die Datei lesen
    icacls ".env" /inheritance:r /grant:r "$($env:USERNAME):(R,W)" *> $null
}

# 3. quitly.at auf diesen Rechner zeigen lassen
$hosts = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
$escaped = [regex]::Escape($Domain)
if (-not (Select-String -Path $hosts -Pattern "^\s*[^#]\S*\s+$escaped(\s|$)" -Quiet)) {
    Say "Damit https://$Domain auf diesen Rechner zeigt, wird die hosts-Datei ergaenzt (Windows fragt nach Admin-Rechten)."
    $cmd = "Add-Content -Path '$hosts' -Value \"`r`n127.0.0.1 $Domain\""
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile", "-Command", $cmd
}

# 4. Starten
Say "Quitly wird gebaut und gestartet (beim ersten Mal einige Minuten) ..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "Start fehlgeschlagen. Details: docker compose logs" }

Say "Warte, bis Quitly bereit ist ..."
$ok = $false
for ($i = 0; $i -lt 90; $i++) {
    curl.exe -fsk --noproxy $Domain --resolve "${Domain}:443:127.0.0.1" "https://$Domain/api/health" *> $null
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Start-Sleep 2
}
if (-not $ok) { Fail "Quitly antwortet nicht. Details: docker compose logs" }

# 5. Lokale HTTPS-CA von Caddy vertrauen (Windows zeigt einen Sicherheitsdialog)
if (-not (Test-Path ".quitly-ca-trusted")) {
    Say "Einmalig: Zertifikat der lokalen Quitly-CA wird als vertrauenswuerdig eingetragen ..."
    docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt (Join-Path $Root ".quitly-root.crt") *> $null
    Import-Certificate -FilePath (Join-Path $Root ".quitly-root.crt") -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
    New-Item ".quitly-ca-trusted" -ItemType File | Out-Null
}

# 6. Erster Benutzer
$users = docker compose exec -T backend python -m app.cli list-users 2>$null
if (-not $users) {
    Say "Lege deinen Quitly-Benutzer an (Passwort mind. 4 Zeichen):"
    $name = Read-Host "Benutzername"
    docker compose exec backend python -m app.cli create-user $name
}

Say "Quitly laeuft: https://$Domain"
Start-Process "https://$Domain"
Write-Host "Beenden mit 'Quitly beenden.bat' oder: docker compose stop"
Start-Sleep 3
