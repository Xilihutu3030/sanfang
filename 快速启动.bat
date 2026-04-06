@echo off
chcp 65001 >nul
title 三防应急处置指挥决策辅助系统
echo ╔════════════════════════════════════════════════════════╗
echo ║     三防应急处置指挥决策辅助系统 v2.0               ║
echo ╚════════════════════════════════════════════════════════╝
echo.

echo [1/3] 检查Python环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo X 未检测到Python，请先安装Python 3.8+
    pause
    exit /b 1
)
echo OK Python环境正常

echo.
echo [2/3] 安装依赖包...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
if %errorlevel% neq 0 (
    echo ! 部分依赖安装失败，尝试继续运行
) else (
    echo OK 依赖安装完成
)

echo.
echo [3/3] 启动服务...
echo ════════════════════════════════════════════════════════
echo.
echo   系统启动后将自动打开浏览器
echo   如未自动打开，请手动访问: http://localhost:5000
echo.
echo   按 Ctrl+C 停止服务
echo ════════════════════════════════════════════════════════
echo.

:: 3秒后自动打开浏览器
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"

python app.py

pause >nul
