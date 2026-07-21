@echo off
title Programming Toolbox

cd /d "%~dp0"

echo ========================================
echo   Programming Toolbox - 编程工具箱
echo ========================================
echo.
echo Stopping old instances...

powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -like '*ProgrammingToolbox*main.py*' -or $_.CommandLine -like '*辅助工具箱*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" 2>nul

echo Clearing cache...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" 2>nul

echo Starting...

if not exist "venv\Scripts\python.exe" (
    echo.
    echo [ERROR] venv not found. Run the following commands first:
    echo   python -m venv venv
    echo   venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"venv\Scripts\python.exe" "main.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start.
    pause
    exit /b 1
)