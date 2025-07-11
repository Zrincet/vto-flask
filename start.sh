#!/bin/bash

# VTO设备管理系统启动脚本

echo "=========================================="
echo "     VTO设备管理系统启动脚本"
echo "=========================================="

# 检查Python版本
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到Python 3，请先安装Python 3.7或更高版本"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "检测到Python版本: $PYTHON_VERSION"

# 检查是否存在虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "检查并安装依赖包..."
pip install -r requirements.txt

# 启动应用
echo "启动VTO设备管理系统..."
echo "请在浏览器中访问: http://localhost:8998"
echo "默认账户: admin / 123456"
echo "按 Ctrl+C 停止服务"
echo "=========================================="

python app.py 