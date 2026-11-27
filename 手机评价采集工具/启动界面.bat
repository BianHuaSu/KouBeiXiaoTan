@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo 还没有安装依赖，请先双击“安装依赖.bat”。
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" gui.py
