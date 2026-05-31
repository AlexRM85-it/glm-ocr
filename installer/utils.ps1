# Utility condivise per i vari step del bootstrap.

$Script:LogFile = $null

function Initialize-Log {
    param([Parameter(Mandatory)][string]$InstallDir)
    $logsDir = Join-Path $InstallDir 'logs'
    if (-not (Test-Path $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
    }
    $Script:LogFile = Join-Path $logsDir 'bootstrap.log'
    "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - Bootstrap start =====" |
        Out-File -FilePath $Script:LogFile -Append -Encoding utf8
}

function Write-Log {
    param(
        [Parameter(Mandatory)][string]$Message,
        [string]$Level = 'INFO',
        [System.ConsoleColor]$Color = 'Gray'
    )
    $stamp = Get-Date -Format 'HH:mm:ss'
    $line  = "[$stamp][$Level] $Message"
    Write-Host $line -ForegroundColor $Color
    if ($Script:LogFile) {
        $line | Out-File -FilePath $Script:LogFile -Append -Encoding utf8
    }
}

function Write-Step {
    param([int]$Index, [int]$Total, [string]$Message)
    Write-Host ""
    Write-Host "[$Index/$Total] $Message" -ForegroundColor Cyan
    if ($Script:LogFile) {
        "[$Index/$Total] $Message" | Out-File -FilePath $Script:LogFile -Append -Encoding utf8
    }
}

function Invoke-DownloadWithProgress {
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Destination,
        [string]$Description = 'download'
    )
    Write-Log "Scarico $Description da $Url"
    $tmp = "$Destination.partial"
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.UserAgent = 'GLM-OCR-Bootstrap/1.0'
        $resp = $req.GetResponse()
        $totalBytes = $resp.ContentLength
        $stream = $resp.GetResponseStream()
        $fs = [System.IO.File]::Create($tmp)
        $buffer = New-Object byte[] 65536
        $read = 0; $totalRead = 0
        $lastPct = -1
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $fs.Write($buffer, 0, $read)
            $totalRead += $read
            if ($totalBytes -gt 0) {
                $pct = [int](($totalRead / $totalBytes) * 100)
                if ($pct -ne $lastPct -and $pct % 5 -eq 0) {
                    Write-Progress -Activity $Description -Status "$pct% ($totalRead / $totalBytes byte)" -PercentComplete $pct
                    $lastPct = $pct
                }
            }
        }
        $fs.Close(); $stream.Close(); $resp.Close()
        Write-Progress -Activity $Description -Completed
        Move-Item -Path $tmp -Destination $Destination -Force
        Write-Log "$Description completato ($totalRead byte)" 'OK' Green
    }
    catch {
        if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
        throw "Download fallito: $($_.Exception.Message)"
    }
}

function Test-OllamaApiAlive {
    try {
        $r = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Get-FileHashSafe {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash
}
