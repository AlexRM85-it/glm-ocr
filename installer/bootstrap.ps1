# Bootstrap idempotente per GLM-OCR.
# - Scarica Python embedded se manca
# - Installa pip + dipendenze
# - Installa Ollama silent se manca
# - Scarica modello glm-ocr se manca
# - Applica eventuale update in staging
# - Lancia l'app Streamlit

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# ----- Percorsi base ----------------------------------------------------------
$InstallDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$AppDir     = Join-Path $InstallDir 'app'
$RuntimeDir = Join-Path $InstallDir 'runtime'
$DataDir    = Join-Path $InstallDir 'data'
$PyDir      = Join-Path $RuntimeDir 'python'
$PyExe      = Join-Path $PyDir 'python.exe'

# Versioni / URL (aggiornabili)
$PythonVersion = '3.12.7'
$PythonEmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = 'https://bootstrap.pypa.io/get-pip.py'
$DefaultModelTag = 'glm-ocr:latest'

# ----- Inizializzazione -------------------------------------------------------
. (Join-Path $PSScriptRoot 'utils.ps1')
. (Join-Path $PSScriptRoot 'ollama_install.ps1')

foreach ($d in @($RuntimeDir, $DataDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}
Initialize-Log -InstallDir $InstallDir

Write-Host ""
Write-Host "=== GLM-OCR Bootstrap ===" -ForegroundColor Magenta
Write-Host "Install dir: $InstallDir" -ForegroundColor DarkGray

$TotalSteps = 6
$Step = 0

# ----- [1] Python embedded ----------------------------------------------------
$Step++
Write-Step $Step $TotalSteps 'Runtime Python'
if (Test-Path $PyExe) {
    Write-Log "Python embedded gia presente: $PyExe" 'OK' Green
} else {
    $downloadsDir = Join-Path $RuntimeDir 'downloads'
    if (-not (Test-Path $downloadsDir)) { New-Item -ItemType Directory -Path $downloadsDir -Force | Out-Null }
    $zipPath = Join-Path $downloadsDir "python-$PythonVersion-embed-amd64.zip"

    Invoke-DownloadWithProgress -Url $PythonEmbedUrl -Destination $zipPath -Description "Python $PythonVersion embedded (~25 MB)"

    Write-Log "Estraggo Python in $PyDir" 'INFO' Yellow
    if (Test-Path $PyDir) { Remove-Item $PyDir -Recurse -Force }
    Expand-Archive -Path $zipPath -DestinationPath $PyDir -Force

    # Abilita 'import site' nel ._pth per permettere pip di funzionare.
    $pthFile = Get-ChildItem $PyDir -Filter 'python*._pth' | Select-Object -First 1
    if ($pthFile) {
        $content = Get-Content $pthFile.FullName -Raw
        if ($content -notmatch '(?m)^\s*import\s+site') {
            $content = $content -replace '(?m)^\s*#\s*import\s+site', 'import site'
            if ($content -notmatch '(?m)^\s*import\s+site') {
                # Se la riga non c'e' proprio, la aggiungo in fondo.
                $content += "`r`nimport site`r`n"
            }
            Set-Content -Path $pthFile.FullName -Value $content -Encoding ASCII
            Write-Log "Patch ._pth: import site abilitato." 'OK' Green
        }
    }
    Write-Log 'Python embedded installato.' 'OK' Green
}

# ----- [2] pip + dipendenze ---------------------------------------------------
$Step++
Write-Step $Step $TotalSteps 'pip + dipendenze Python'

# Installazione pip (idempotente: se gia presente, get-pip aggiorna senza danni).
$hasPip = $false
try {
    & $PyExe -m pip --version > $null 2>&1
    if ($LASTEXITCODE -eq 0) { $hasPip = $true }
} catch {}

if (-not $hasPip) {
    $getPipPath = Join-Path (Join-Path $RuntimeDir 'downloads') 'get-pip.py'
    Invoke-DownloadWithProgress -Url $GetPipUrl -Destination $getPipPath -Description 'get-pip.py'
    Write-Log 'Installo pip...' 'INFO' Yellow
    & $PyExe $getPipPath --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw "Installazione pip fallita (exit $LASTEXITCODE)" }
}

# Installazione/aggiornamento dipendenze: idempotente via hash di requirements.
$reqFile = Join-Path $AppDir 'requirements.txt'
$hashFile = Join-Path $RuntimeDir '.requirements_hash'
$forceFlag = Join-Path $RuntimeDir '.force_pip_install'
$curHash = Get-FileHashSafe -Path $reqFile
$prevHash = if (Test-Path $hashFile) { Get-Content $hashFile -Raw } else { '' }
$needsInstall = (Test-Path $forceFlag) -or ($curHash -ne $prevHash)

if ($needsInstall) {
    Write-Log 'Installo dipendenze Python (pip install -r requirements.txt)...' 'INFO' Yellow
    & $PyExe -m pip install --no-warn-script-location -r $reqFile
    if ($LASTEXITCODE -ne 0) { throw "pip install fallito (exit $LASTEXITCODE)" }
    Set-Content -Path $hashFile -Value $curHash -Encoding ASCII -NoNewline
    if (Test-Path $forceFlag) { Remove-Item $forceFlag -Force }
    Write-Log 'Dipendenze installate.' 'OK' Green
} else {
    Write-Log 'Dipendenze Python gia aggiornate.' 'OK' Green
}

# ----- [3] Ollama -------------------------------------------------------------
$Step++
Write-Step $Step $TotalSteps 'Ollama'
if (Test-OllamaInstalled) {
    Write-Log 'Ollama gia installato.' 'OK' Green
} else {
    Install-Ollama -RuntimeDir $RuntimeDir
}

# ----- [4] Avvio servizio Ollama ----------------------------------------------
$Step++
Write-Step $Step $TotalSteps 'Servizio Ollama'
Start-OllamaIfNeeded

# ----- [5] Modello glm-ocr ----------------------------------------------------
$Step++
Write-Step $Step $TotalSteps "Modello $DefaultModelTag"
$modelTag = $DefaultModelTag
$forcePullFlag = Join-Path $DataDir '.force_model_pull'
if (Test-Path $forcePullFlag) {
    $newTag = (Get-Content $forcePullFlag -Raw).Trim()
    if ($newTag) { $modelTag = $newTag }
    Remove-Item $forcePullFlag -Force
    Write-Log "Force-pull richiesto per: $modelTag" 'INFO' Yellow
}
Ensure-OllamaModel -ModelTag $modelTag

# ----- [6] Apply eventuale update + launch app --------------------------------
$Step++
Write-Step $Step $TotalSteps 'Update + avvio app'

# Applica eventuale update gia scaricato.
& $PyExe -c "import sys; sys.path.insert(0, r'$AppDir'); import updater; print('applied' if updater.apply_pending_update() else 'no update')" 2>&1 | ForEach-Object { Write-Log $_ 'INFO' DarkCyan }

# L'apply estrae il nuovo app/ (incluso requirements.txt) DOPO lo step [2] pip e lo
# step [5] modello: se l'update ha cambiato dipendenze o modello, i flag sono stati
# scritti ora -> ricontrolliamo qui per non rimandare al riavvio successivo.
$curHash2 = Get-FileHashSafe -Path $reqFile
$prevHash2 = if (Test-Path $hashFile) { Get-Content $hashFile -Raw } else { '' }
if ((Test-Path $forceFlag) -or ($curHash2 -ne $prevHash2)) {
    Write-Log 'Update ha cambiato le dipendenze: reinstallo prima dell avvio...' 'INFO' Yellow
    & $PyExe -m pip install --no-warn-script-location -r $reqFile
    if ($LASTEXITCODE -ne 0) { throw "pip install (post-update) fallito (exit $LASTEXITCODE)" }
    Set-Content -Path $hashFile -Value $curHash2 -Encoding ASCII -NoNewline
    if (Test-Path $forceFlag) { Remove-Item $forceFlag -Force }
    Write-Log 'Dipendenze aggiornate dopo update.' 'OK' Green
}

# Stesso discorso per il pull del modello (flag scritto dall'apply dopo lo step [5]).
$forcePullFlagPost = Join-Path $DataDir '.force_model_pull'
if (Test-Path $forcePullFlagPost) {
    $newTagPost = (Get-Content $forcePullFlagPost -Raw).Trim()
    Remove-Item $forcePullFlagPost -Force
    if ($newTagPost) {
        Write-Log "Update richiede il pull del modello: $newTagPost" 'INFO' Yellow
        Ensure-OllamaModel -ModelTag $newTagPost
    }
}

Write-Log 'Avvio Streamlit...' 'INFO' Green
Write-Host ""
Write-Host "Browser: http://localhost:8501" -ForegroundColor Magenta
Write-Host "Premi Ctrl+C in questa finestra per chiudere l'app." -ForegroundColor DarkGray
Write-Host ""

& $PyExe -m streamlit run (Join-Path $AppDir 'app.py')
exit $LASTEXITCODE
