@echo off
chcp 65001 >nul

echo ==========================================
echo      VTO设备管理系统启动脚本
echo ==========================================

REM 检查Python版本
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: 未找到Python，请先安装Python 3.7或更高版本
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo 检测到Python版本: %PYTHON_VERSION%

REM 检查是否存在虚拟环境
if not exist "venv" (
    echo 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
echo 激活虚拟环境...
call venv\Scripts\activate.bat

REM 安装依赖
echo 检查并安装依赖包...
pip install -r requirements.txt

REM 启动应用
echo 启动VTO设备管理系统...
echo 请在浏览器中访问: http://localhost:8998
echo 默认账户: admin / 123456
echo 按 Ctrl+C 停止服务
echo ==========================================

python app.py

pause 