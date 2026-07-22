@echo off
cd /d "%~dp0"
echo Starting build...
venv\Scripts\python.exe build_exe.py
pause