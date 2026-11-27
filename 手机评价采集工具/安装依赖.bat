@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   手机评价采集器 - 安装依赖
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 创建虚拟环境...
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 (
        echo 创建失败：请先安装 Python 3.10-3.13，并勾选 Add Python to PATH。
        pause
        exit /b 1
    )
) else (
    echo [1/3] 虚拟环境已存在，跳过创建。
)

echo [2/3] 安装依赖...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo 安装失败：检查网络，或换用国内镜像后重试。
    pause
    exit /b 1
)

echo [3/3] 自检...
".venv\Scripts\python.exe" -c "import tkinter, rapidocr_onnxruntime; print('依赖自检通过')"
if errorlevel 1 (
    echo 自检失败。
    pause
    exit /b 1
)

echo.
echo 安装完成。双击“启动界面.bat”开始使用。
pause
