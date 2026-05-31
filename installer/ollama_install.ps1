# Installazione di Ollama: rileva, scarica e installa in modalita' silent.
# Importato da bootstrap.ps1 (dot-sourcing).

function Test-OllamaInstalled {
    if (Get-Command ollama -ErrorAction SilentlyContinue) { return $true }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $true }
    }
    return $false
}

function Get-OllamaExePath {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe"
    )
    foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
    return $null
}

function Install-Ollama {
    param([Parameter(Mandatory)][string]$RuntimeDir)
    $downloadsDir = Join-Path $RuntimeDir 'downloads'
    if (-not (Test-Path $downloadsDir)) {
        New-Item -ItemType Directory -Path $downloadsDir -Force | Out-Null
    }
    $setupPath = Join-Path $downloadsDir 'OllamaSetup.exe'

    Invoke-DownloadWithProgress `
        -Url 'https://ollama.com/download/OllamaSetup.exe' `
        -Destination $setupPath `
        -Description 'Ollama installer (~600 MB)'

    Write-Log 'Eseguo installer Ollama in modalita silent (/SILENT)' 'INFO' Yellow
    # L'installer Ollama (NSIS-based, ma con bundle Inno per versioni recenti)
    # supporta /SILENT. Usiamo /SILENT che funziona con entrambi.
    $proc = Start-Process -FilePath $setupPath -ArgumentList '/SILENT' -PassThru -Wait
    if ($proc.ExitCode -ne 0) {
        Write-Log "Installer Ollama exit code $($proc.ExitCode); tentativo /S come fallback" 'WARN' Yellow
        $proc = Start-Process -FilePath $setupPath -ArgumentList '/S' -PassThru -Wait
        if ($proc.ExitCode -ne 0) {
            throw "Installazione Ollama fallita (exit $($proc.ExitCode)). Prova a lanciare manualmente: $setupPath"
        }
    }
    Write-Log 'Ollama installato.' 'OK' Green
}

function Start-OllamaIfNeeded {
    if (Test-OllamaApiAlive) {
        Write-Log 'Servizio Ollama gia attivo.' 'OK' Green
        return
    }
    $exe = Get-OllamaExePath
    if (-not $exe) {
        throw 'ollama.exe non trovato dopo installazione.'
    }
    Write-Log 'Avvio ollama serve in background...' 'INFO' Yellow
    Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    # Attendi fino a ~30s che l'API risponda.
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-OllamaApiAlive) {
            Write-Log "Servizio Ollama avviato (dopo $i s)." 'OK' Green
            return
        }
    }
    throw 'Timeout: Ollama non risponde su http://localhost:11434 dopo 30s.'
}

function Ensure-OllamaModel {
    param(
        [Parameter(Mandatory)][string]$ModelTag,
        [string]$OllamaExe
    )
    if (-not $OllamaExe) { $OllamaExe = Get-OllamaExePath }
    $list = & $OllamaExe list 2>$null
    $shortName = $ModelTag.Split(':')[0]
    if ($list -match $shortName) {
        Write-Log "Modello '$ModelTag' gia presente." 'OK' Green
        return
    }
    Write-Log "Scarico modello '$ModelTag' (puo richiedere vari minuti)..." 'INFO' Yellow
    & $OllamaExe pull $ModelTag
    if ($LASTEXITCODE -ne 0) {
        throw "ollama pull $ModelTag fallito (exit $LASTEXITCODE)."
    }
    Write-Log "Modello '$ModelTag' scaricato." 'OK' Green
}
