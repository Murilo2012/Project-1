@echo off
REM Sobe o APEX. Se o ambiente virtual nao existir, roda a instalacao antes.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado. Rodando a instalacao...
    powershell -ExecutionPolicy Bypass -File "scripts\instalar.ps1"
    if errorlevel 1 exit /b 1
)

REM UTF-8 no console, senao acento vira lixo no HUD.
chcp 65001 >nul

".venv\Scripts\python.exe" -m apex %*
