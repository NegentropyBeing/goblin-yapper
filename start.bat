@echo off
rem Inicia o Goblin Yapper a partir do codigo-fonte (Passo 5 do docs\TESTE.md).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente .venv nao encontrado. Siga o Passo 4 do docs\TESTE.md primeiro.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m goblin_yapper %*
if errorlevel 1 pause
