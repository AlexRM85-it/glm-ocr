@echo off
REM Entry point per l'utente. Chiama il bootstrap PowerShell, poi se tutto OK
REM lancia l'app Streamlit. Doppio click oppure dal terminale.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\installer\bootstrap.ps1"
if errorlevel 1 (
    echo.
    echo [GLM-OCR] Bootstrap fallito. Vedi messaggi sopra o logs\bootstrap.log
    echo.
    pause
)
