@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 三防指挥系统

:: 检查是否已在运行
netstat -ano | findstr "0.0.0.0:5000" >nul 2>&1
if %errorlevel% equ 0 (
    echo 系统已在运行，正在打开浏览器...
    start http://localhost:5000
    timeout /t 2 >nul
    exit /b 0
)

echo.
echo   三防形势智能研判与指挥辅助系统 v2.0
echo   ──────────────────────────────────
echo   正在启动，请稍候...
echo.

:: 检查Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未安装Python，请先安装 Python 3.8+
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 静默安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple -q >nul 2>&1

:: 延迟打开浏览器
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:5000"

echo   服务启动中... 浏览器将自动打开
echo   访问地址: http://localhost:5000
echo.
echo   关闭此窗口即可停止系统
echo   ──────────────────────────────────
echo.

python app.py
