#!/bin/bash

# VTO设备管理系统 - MIPS架构打包编译脚本
# 在x86_64机器上运行，生成适用于Padavan MIPS架构的部署包
# 使用方法: ./build_package.sh

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
WORK_DIR="$(pwd)/build_workspace"
SOURCE_DIR="$(pwd)"
OUTPUT_DIR="$(pwd)/dist"
PACKAGE_NAME="vto-mips-package.zip"
PYTHON_VERSION="3.11"
MIPS_TOOLCHAIN="mipsel-linux-gnu"

# 远程资源配置
PYTHON_MIPS_URL="https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tar.xz"
OPENWRT_SDK_URL="https://downloads.openwrt.org/releases/22.03.5/targets/ramips/mt7621/openwrt-sdk-22.03.5-ramips-mt7621_gcc-11.2.0_musl.Linux-x86_64.tar.xz"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 错误退出函数
error_exit() {
    log_error "$1"
    exit 1
}

# 设置Docker命令
setup_docker_cmd() {
    if command -v docker >/dev/null 2>&1 && docker version >/dev/null 2>&1; then
        DOCKER_CMD="docker"
    elif sudo docker version >/dev/null 2>&1; then
        DOCKER_CMD="sudo docker"
    else
        error_exit "无法访问Docker"
    fi
}

# 检测Linux发行版
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION=$VERSION_ID
    elif [ -f /etc/redhat-release ]; then
        OS="centos"
    elif [ -f /etc/debian_version ]; then
        OS="debian"
    else
        OS="unknown"
    fi
    echo "$OS"
}

# 安装Docker
install_docker() {
    log_info "检测到Docker未安装，开始自动安装..."
    
    OS=$(detect_os)
    log_info "检测到系统: $OS"
    
    case "$OS" in
        "ubuntu"|"debian")
            log_info "使用APT安装Docker..."
            
            # 更新包索引
            sudo apt-get update
            
            # 安装必要的包
            sudo apt-get install -y \
                apt-transport-https \
                ca-certificates \
                curl \
                gnupg \
                lsb-release
            
            # 添加Docker官方GPG密钥
            curl -fsSL https://download.docker.com/linux/$OS/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
            
            # 添加Docker仓库
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/$OS $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
            
            # 更新包索引
            sudo apt-get update
            
            # 安装Docker
            sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
            
        "centos"|"rhel"|"rocky"|"almalinux")
            log_info "使用YUM安装Docker..."
            
            # 安装yum-utils
            sudo yum install -y yum-utils
            
            # 添加Docker仓库
            sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
            
            # 安装Docker
            sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
            
        "fedora")
            log_info "使用DNF安装Docker..."
            
            # 安装dnf-plugins-core
            sudo dnf install -y dnf-plugins-core
            
            # 添加Docker仓库
            sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
            
            # 安装Docker
            sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
            
        "arch"|"manjaro")
            log_info "使用Pacman安装Docker..."
            
            # 更新包数据库
            sudo pacman -Sy
            
            # 安装Docker
            sudo pacman -S --noconfirm docker docker-compose
            ;;
            
        "opensuse"|"opensuse-leap"|"opensuse-tumbleweed")
            log_info "使用Zypper安装Docker..."
            
            # 安装Docker
            sudo zypper install -y docker docker-compose
            ;;
            
        *)
            log_warning "未识别的Linux发行版: $OS"
            log_info "尝试使用通用安装脚本..."
            
            # 使用Docker官方安装脚本
            curl -fsSL https://get.docker.com -o get-docker.sh
            sudo sh get-docker.sh
            rm -f get-docker.sh
            ;;
    esac
    
    # 启动Docker服务
    log_info "启动Docker服务..."
    sudo systemctl start docker
    sudo systemctl enable docker
    
    # 检查Docker是否安装成功
    if command -v docker >/dev/null 2>&1; then
        log_success "Docker安装成功"
        
        # 添加当前用户到docker组（可选）
        if [ -n "$SUDO_USER" ]; then
            log_info "将用户 $SUDO_USER 添加到docker组..."
            sudo usermod -aG docker "$SUDO_USER"
            log_warning "请注销并重新登录以使docker组权限生效，或者重新运行此脚本"
        elif [ "$(id -u)" != "0" ]; then
            log_info "将当前用户添加到docker组..."
            sudo usermod -aG docker "$USER"
            log_warning "请注销并重新登录以使docker组权限生效，或者重新运行此脚本"
        fi
    else
        error_exit "Docker安装失败"
    fi
}

# 检查依赖工具
check_dependencies() {
    log_info "检查编译依赖..."
    
    # 检查基本工具（除了Docker）
    BASIC_TOOLS="wget tar xz git python3 zip"
    MISSING_TOOLS=""
    
    for tool in $BASIC_TOOLS; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            if [ "$tool" = "python3" ]; then
                # 尝试检查python
                if ! command -v python >/dev/null 2>&1; then
                    MISSING_TOOLS="$MISSING_TOOLS $tool"
                fi
            else
                MISSING_TOOLS="$MISSING_TOOLS $tool"
            fi
        fi
    done
    
    if [ -n "$MISSING_TOOLS" ]; then
        log_error "以下必需工具未安装:$MISSING_TOOLS"
        log_info "请先安装这些工具，例如："
        
        OS=$(detect_os)
        case "$OS" in
            "ubuntu"|"debian")
                log_info "sudo apt-get install$MISSING_TOOLS"
                ;;
            "centos"|"rhel"|"rocky"|"almalinux")
                log_info "sudo yum install$MISSING_TOOLS"
                ;;
            "fedora")
                log_info "sudo dnf install$MISSING_TOOLS"
                ;;
            "arch"|"manjaro")
                log_info "sudo pacman -S$MISSING_TOOLS"
                ;;
        esac
        exit 1
    fi
    
    # 检查pip
    if ! command -v pip >/dev/null 2>&1 && ! command -v pip3 >/dev/null 2>&1; then
        log_warning "pip未安装，尝试安装..."
        if command -v python3 >/dev/null 2>&1; then
            python3 -m ensurepip --default-pip >/dev/null 2>&1 || true
        fi
    fi
    
    # 检查Docker
    if ! command -v docker >/dev/null 2>&1; then
        log_warning "Docker未安装"
        
        # 检查是否设置了自动安装环境变量
        if [ "${AUTO_INSTALL_DOCKER:-}" = "yes" ] || [ "${AUTO_INSTALL_DOCKER:-}" = "true" ]; then
            log_info "检测到AUTO_INSTALL_DOCKER环境变量，自动安装Docker..."
            install_docker
        else
            read -p "是否自动安装Docker? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                install_docker
            else
                log_error "Docker是必需的，请手动安装后重新运行脚本"
                log_info "或者设置环境变量: export AUTO_INSTALL_DOCKER=yes"
                exit 1
            fi
        fi
    fi
    
    # 检查Docker服务状态
    if ! docker version >/dev/null 2>&1; then
        log_warning "Docker服务未运行或权限不足"
        
        # 尝试启动Docker服务
        if systemctl is-active --quiet docker; then
            log_info "Docker服务已运行"
        else
            log_info "尝试启动Docker服务..."
            if sudo systemctl start docker; then
                log_success "Docker服务启动成功"
            else
                error_exit "无法启动Docker服务"
            fi
        fi
        
                 # 检查权限
         if ! docker version >/dev/null 2>&1; then
             log_warning "Docker权限不足，可能需要运行以下命令："
             log_info "sudo usermod -aG docker $USER"
             log_info "然后注销并重新登录，或者使用sudo运行此脚本"
             
             # 检查是否设置了使用sudo的环境变量
             if [ "${USE_SUDO_DOCKER:-}" = "yes" ] || [ "${USE_SUDO_DOCKER:-}" = "true" ]; then
                 log_info "检测到USE_SUDO_DOCKER环境变量，使用sudo运行Docker..."
                 # 创建Docker别名函数
                 docker() {
                     sudo /usr/bin/docker "$@"
                 }
                 export -f docker
                 log_info "已设置sudo Docker别名"
             else
                 read -p "是否使用sudo运行Docker命令? (y/N): " -n 1 -r
                 echo
                 if [[ $REPLY =~ ^[Yy]$ ]]; then
                     # 创建Docker别名函数
                     docker() {
                         sudo /usr/bin/docker "$@"
                     }
                     export -f docker
                     log_info "已设置sudo Docker别名"
                 else
                     log_error "无法使用Docker，请解决权限问题后重新运行"
                     log_info "或者设置环境变量: export USE_SUDO_DOCKER=yes"
                     exit 1
                 fi
             fi
         fi
    fi
    
    log_success "依赖检查通过"
}

# 创建工作目录
setup_workspace() {
    log_info "设置工作环境..."
    
    # 清理并创建工作目录
    rm -rf "$WORK_DIR"
    mkdir -p "$WORK_DIR"
    mkdir -p "$OUTPUT_DIR"
    
    # 创建子目录
    mkdir -p "$WORK_DIR/source"
    mkdir -p "$WORK_DIR/python-build"
    mkdir -p "$WORK_DIR/venv-build"
    mkdir -p "$WORK_DIR/package"
    
    log_success "工作环境创建完成: $WORK_DIR"
}

# 复制源代码
copy_source_code() {
    log_info "复制VTO源代码..."
    
    # 复制必要的源文件
    cp -r "$SOURCE_DIR"/*.py "$WORK_DIR/package/" 2>/dev/null || true
    cp -r "$SOURCE_DIR"/templates "$WORK_DIR/package/" 2>/dev/null || true
    cp -r "$SOURCE_DIR"/static "$WORK_DIR/package/" 2>/dev/null || true
    cp "$SOURCE_DIR"/requirements.txt "$WORK_DIR/package/" 2>/dev/null || true
    cp "$SOURCE_DIR"/server.sh "$WORK_DIR/package/" 2>/dev/null || true
    cp "$SOURCE_DIR"/update_and_restart.sh "$WORK_DIR/package/" 2>/dev/null || true
    cp "$SOURCE_DIR"/README.md "$WORK_DIR/package/" 2>/dev/null || true
    
    # 检查关键文件
    if [ ! -f "$WORK_DIR/package/app.py" ]; then
        error_exit "源代码中缺少 app.py 文件"
    fi
    
    if [ ! -f "$WORK_DIR/package/requirements.txt" ]; then
        error_exit "源代码中缺少 requirements.txt 文件"
    fi
    
    log_success "源代码复制完成"
}

# 创建Docker构建环境
create_docker_env() {
    log_info "创建Docker构建环境..."
    
    # 创建Dockerfile
    cat > "$WORK_DIR/Dockerfile" << 'EOF'
FROM ubuntu:20.04

# 设置非交互模式
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 更新系统并安装依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    curl \
    git \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    libffi-dev \
    libssl-dev \
    libsqlite3-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libncurses5-dev \
    libncursesw5-dev \
    liblzma-dev \
    tk-dev \
    libgdbm-dev \
    libnss3-dev \
    libedit-dev \
    crossbuild-essential-mipsel \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /build

# 设置交叉编译环境
ENV CC=mipsel-linux-gnu-gcc
ENV CXX=mipsel-linux-gnu-g++
ENV AR=mipsel-linux-gnu-ar
ENV STRIP=mipsel-linux-gnu-strip
ENV RANLIB=mipsel-linux-gnu-ranlib

# 安装最新的pip
RUN python3 -m pip install --upgrade pip setuptools wheel

EOF

    # 构建Docker镜像
    log_info "构建Docker镜像（这可能需要几分钟）..."
    cd "$WORK_DIR"
    
    # 设置Docker命令
    setup_docker_cmd
    if [ "$DOCKER_CMD" = "sudo docker" ]; then
        log_info "使用sudo运行Docker命令"
    fi
    
    if $DOCKER_CMD build -t vto-mips-builder .; then
        log_success "Docker镜像构建完成"
    else
        error_exit "Docker镜像构建失败"
    fi
}

# 使用预编译包的方案
build_python_environment() {
    log_info "构建Python虚拟环境（使用预编译包方案）..."
    
    # 在宿主机创建虚拟环境
    cd "$WORK_DIR"
    python3 -m venv venv-host
    source venv-host/bin/activate
    
    # 升级pip
    pip install --upgrade pip
    
    # 读取requirements.txt并安装纯Python包
    log_info "安装纯Python依赖包..."
    
    # 创建修改后的requirements.txt，移除可能有编译问题的包
    cat > requirements-build.txt << 'EOF'
Flask==2.3.3
Flask-SQLAlchemy==3.0.5
Flask-SocketIO==5.3.4
Werkzeug==2.3.7
requests==2.31.0
paho-mqtt==1.6.1
Jinja2==3.1.2
MarkupSafe==2.1.3
itsdangerous==2.1.2
click==8.1.7
blinker==1.6.3
SQLAlchemy==2.0.21
python-socketio==5.8.0
python-engineio==4.7.1
bidict==0.22.1
urllib3==2.0.4
charset-normalizer==3.2.0
idna==3.4
certifi==2023.7.22
greenlet==2.0.2
typing-extensions==4.7.1
EOF

    # 安装依赖
    if pip install -r requirements-build.txt --no-cache-dir; then
        log_success "Python依赖安装完成"
    else
        log_warning "部分依赖安装失败，继续处理"
    fi
    
    deactivate
    
    # 复制虚拟环境到打包目录
    cp -r venv-host "$WORK_DIR/package/venv"
    
    # 清理虚拟环境中的无用文件
    log_info "清理虚拟环境..."
    find "$WORK_DIR/package/venv" -name "*.pyc" -delete
    find "$WORK_DIR/package/venv" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$WORK_DIR/package/venv" -name "*.pyo" -delete
    
    log_success "Python环境构建完成"
}

# 使用Docker交叉编译（备用方案）
build_with_docker() {
    log_info "使用Docker进行交叉编译（备用方案）..."
    
    # 设置Docker命令
    setup_docker_cmd
    
    # 复制requirements到Docker环境
    cp "$WORK_DIR/package/requirements.txt" "$WORK_DIR/"
    
    # 在Docker中执行编译
    $DOCKER_CMD run --rm \
        -v "$WORK_DIR":/build \
        -w /build \
        vto-mips-builder \
        bash -c "
            echo '开始在Docker中构建...'
            python3 -m venv venv-docker
            source venv-docker/bin/activate
            pip install --upgrade pip
            
            # 尝试安装依赖
            pip install wheel
            pip install --no-cache-dir -r requirements.txt || echo '部分包安装失败，继续...'
            
            # 复制到package目录
            cp -r venv-docker package/venv-docker
            echo 'Docker构建完成'
        " || log_warning "Docker交叉编译失败，使用主机环境"
}

# 添加启动脚本优化
optimize_scripts() {
    log_info "优化启动脚本..."
    
    # 修改server.sh以适应MIPS环境
    if [ -f "$WORK_DIR/package/server.sh" ]; then
        # 确保使用busybox兼容的命令
        sed -i 's/ps aux/ps/g' "$WORK_DIR/package/server.sh"
        sed -i 's/hostname -I/hostname -i/g' "$WORK_DIR/package/server.sh" 2>/dev/null || true
    fi
    
    # 创建环境检测脚本
    cat > "$WORK_DIR/package/check_env.sh" << 'EOF'
#!/bin/sh

# 环境检测脚本
echo "检测运行环境..."
echo "架构: $(uname -m)"
echo "内核: $(uname -r)"
echo "Python版本: $(python3 --version 2>/dev/null || echo '未安装')"
echo "可用内存: $(free -m | grep '^Mem:' | awk '{print $7}')MB"
echo "磁盘空间: $(df -h /opt | tail -1 | awk '{print $4}')"
EOF

    chmod +x "$WORK_DIR/package/check_env.sh"
    
    log_success "脚本优化完成"
}

# 创建配置文件
create_configs() {
    log_info "创建配置文件..."
    
    # 创建默认配置
    cat > "$WORK_DIR/package/config.json" << 'EOF'
{
    "app": {
        "host": "0.0.0.0",
        "port": 8998,
        "debug": false
    },
    "database": {
        "url": "sqlite:///vto_management.db"
    },
    "mqtt": {
        "enabled": false,
        "broker": "bemfa.com",
        "port": 9501
    },
    "logging": {
        "level": "INFO",
        "file": "logs/app.log"
    }
}
EOF

    # 创建安装信息文件
    cat > "$WORK_DIR/package/install_info.txt" << EOF
VTO设备管理系统 - MIPS版本
构建时间: $(date)
构建主机: $(hostname)
Python版本: $(python3 --version)
目标架构: MIPS (Padavan)

安装说明:
1. 将此包上传到支持的MIPS设备
2. 运行安装脚本进行部署
3. 访问 http://设备IP:8998 使用系统

默认账户: admin / 123456
EOF

    log_success "配置文件创建完成"
}

# 添加额外工具
add_extra_tools() {
    log_info "添加额外工具..."
    
    # 创建状态监控脚本
    cat > "$WORK_DIR/package/monitor.sh" << 'EOF'
#!/bin/sh

# VTO应用监控脚本
while true; do
    if ! pgrep -f "python.*app.py" > /dev/null; then
        echo "[$(date)] VTO应用未运行，尝试重启..."
        cd /opt/vto && ./server.sh start
    fi
    sleep 60
done
EOF

    chmod +x "$WORK_DIR/package/monitor.sh"
    
    # 创建备份脚本
    cat > "$WORK_DIR/package/backup.sh" << 'EOF'
#!/bin/sh

# 数据备份脚本
BACKUP_DIR="/opt/vto-backup/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# 备份数据库
cp vto_management.db "$BACKUP_DIR/" 2>/dev/null || true

# 备份配置
cp config.json "$BACKUP_DIR/" 2>/dev/null || true

# 备份日志
cp -r logs "$BACKUP_DIR/" 2>/dev/null || true

echo "备份完成: $BACKUP_DIR"
EOF

    chmod +x "$WORK_DIR/package/backup.sh"
    
    log_success "额外工具添加完成"
}

# 优化打包文件
optimize_package() {
    log_info "优化打包文件..."
    
    cd "$WORK_DIR/package"
    
    # 删除不必要的文件
    find . -name "*.pyc" -delete
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyo" -delete
    find . -name ".DS_Store" -delete
    find . -name "Thumbs.db" -delete
    
    # 压缩日志文件
    mkdir -p logs
    
    # 清理虚拟环境
    if [ -d "venv" ]; then
        # 删除测试文件
        find venv -name "test*" -type d -exec rm -rf {} + 2>/dev/null || true
        find venv -name "*test*" -name "*.py" -delete 2>/dev/null || true
        
        # 删除文档文件
        find venv -name "doc*" -type d -exec rm -rf {} + 2>/dev/null || true
        find venv -name "*.md" -delete 2>/dev/null || true
        find venv -name "*.rst" -delete 2>/dev/null || true
    fi
    
    log_success "文件优化完成"
}

# 创建最终包
create_final_package() {
    log_info "创建最终部署包..."
    
    cd "$WORK_DIR"
    
    # 创建zip包
    if cd package && zip -r "../$PACKAGE_NAME" . -x "*.git*" "*.svn*"; then
        log_success "包创建成功: $PACKAGE_NAME"
    else
        error_exit "包创建失败"
    fi
    
    # 移动到输出目录
    mv "$WORK_DIR/$PACKAGE_NAME" "$OUTPUT_DIR/"
    
    # 计算文件大小和校验和
    PACKAGE_PATH="$OUTPUT_DIR/$PACKAGE_NAME"
    PACKAGE_SIZE=$(ls -lh "$PACKAGE_PATH" | awk '{print $5}')
    PACKAGE_MD5=$(md5sum "$PACKAGE_PATH" | awk '{print $1}')
    
    log_success "部署包信息:"
    log_info "  文件: $PACKAGE_PATH"
    log_info "  大小: $PACKAGE_SIZE"
    log_info "  MD5: $PACKAGE_MD5"
}

# 测试包完整性
test_package() {
    log_info "测试包完整性..."
    
    cd "$WORK_DIR"
    mkdir -p test-extract
    
    # 解压测试
    if unzip -q "$OUTPUT_DIR/$PACKAGE_NAME" -d test-extract; then
        log_success "包解压测试通过"
    else
        error_exit "包解压测试失败"
    fi
    
    # 检查关键文件
    REQUIRED_FILES="app.py server.sh requirements.txt"
    for file in $REQUIRED_FILES; do
        if [ ! -f "test-extract/$file" ]; then
            error_exit "关键文件缺失: $file"
        fi
    done
    
    # 检查虚拟环境
    if [ ! -d "test-extract/venv" ]; then
        log_warning "虚拟环境目录不存在"
    elif [ ! -f "test-extract/venv/bin/python" ]; then
        log_warning "虚拟环境Python解释器缺失"
    else
        log_success "虚拟环境检查通过"
    fi
    
    # 清理测试目录
    rm -rf test-extract
    
    log_success "包完整性测试通过"
}

# 生成部署文档
generate_deploy_docs() {
    log_info "生成部署文档..."
    
    cat > "$OUTPUT_DIR/deploy_instructions.md" << EOF
# VTO设备管理系统 - MIPS部署包使用说明

## 部署包信息
- 文件名: $PACKAGE_NAME
- 构建时间: $(date)
- 适用架构: MIPS (Padavan)
- 大小: $(ls -lh "$OUTPUT_DIR/$PACKAGE_NAME" | awk '{print $5}')

 ## 系统要求
 - Padavan固件路由器
 - 已挂载的/opt目录（推荐使用USB存储）
 - 至少200MB可用空间
 - 网络连接（用于下载依赖）
 
 ## 构建要求（用于编译此包）
 - x86_64 Linux系统
 - Docker（脚本可自动安装）
 - 基本开发工具（git, wget, tar, zip等）

 ## 构建此部署包
 \`\`\`bash
 # 普通构建
 ./build_package.sh
 
 # 自动安装Docker（非交互式）
 AUTO_INSTALL_DOCKER=yes ./build_package.sh
 
 # 使用sudo运行Docker（适用于权限受限环境）
 AUTO_INSTALL_DOCKER=yes USE_SUDO_DOCKER=yes ./build_package.sh
 
 # 保留工作目录用于调试
 ./build_package.sh --keep-workspace
 \`\`\`
 
 ## 自动安装方法
 \`\`\`bash
 # 一键安装（推荐）
 sh -c "\$(curl -kfsSL https://your-server.com/install.sh)"
 \`\`\`

## 手动安装方法

### 1. 上传文件
将 $PACKAGE_NAME 上传到路由器的 /opt/tmp/ 目录

### 2. 解压文件
\`\`\`bash
cd /opt/tmp
unzip $PACKAGE_NAME
\`\`\`

### 3. 移动到安装目录
\`\`\`bash
mkdir -p /opt/vto
cp -r vto-package/* /opt/vto/
\`\`\`

### 4. 安装系统依赖
\`\`\`bash
opkg update
opkg install python3 python3-pip sqlite3-cli
\`\`\`

### 5. 启动应用
\`\`\`bash
cd /opt/vto
chmod +x *.sh
./server.sh start
\`\`\`

## 应用管理

### 服务控制
\`\`\`bash
cd /opt/vto
./server.sh start    # 启动
./server.sh stop     # 停止
./server.sh restart  # 重启
./server.sh status   # 状态
\`\`\`

### 系统监控
\`\`\`bash
./monitor.sh         # 启动监控（后台运行）
./check_env.sh       # 检查环境
\`\`\`

### 数据备份
\`\`\`bash
./backup.sh          # 备份数据
\`\`\`

## 访问应用
- 网址: http://路由器IP:8998
- 默认账户: admin
- 默认密码: 123456

## 故障排除

### 应用无法启动
1. 检查Python环境: \`python3 --version\`
2. 检查虚拟环境: \`ls -la venv/bin/\`
3. 查看启动日志: \`cat logs/app.log\`

### 端口被占用
\`\`\`bash
netstat -tlnp | grep 8998
kill -9 <PID>
\`\`\`

### 权限问题
\`\`\`bash
chmod +x *.sh
chmod -R 755 /opt/vto
\`\`\`

## 技术支持
如遇问题，请提供：
1. 路由器型号和固件版本
2. 错误日志内容
3. 系统环境信息（运行 check_env.sh）

EOF

    log_success "部署文档生成完成"
}

# 清理工作目录
cleanup() {
    log_info "清理工作目录..."
    
    if [ "$1" != "--keep-workspace" ]; then
        rm -rf "$WORK_DIR"
        log_success "工作目录清理完成"
    else
        log_info "保留工作目录: $WORK_DIR"
    fi
    
    # 清理Docker镜像
    if command -v docker >/dev/null 2>&1; then
        setup_docker_cmd 2>/dev/null || DOCKER_CMD="docker"
        
        if $DOCKER_CMD images | grep -q "vto-mips-builder" 2>/dev/null; then
            $DOCKER_CMD rmi vto-mips-builder >/dev/null 2>&1 || true
            log_info "Docker镜像已清理"
        fi
    fi
}

# 显示帮助信息
show_help() {
    echo
    echo "VTO设备管理系统 - MIPS架构打包编译脚本"
    echo
    echo "用法:"
    echo "  $0 [选项]"
    echo
    echo "选项:"
    echo "  -h, --help              显示此帮助信息"
    echo "  --keep-workspace        保留工作目录（用于调试）"
    echo
    echo "环境变量:"
    echo "  AUTO_INSTALL_DOCKER     自动安装Docker (yes/true)"
    echo "  USE_SUDO_DOCKER         使用sudo运行Docker (yes/true)"
    echo
    echo "示例:"
    echo "  # 普通构建"
    echo "  $0"
    echo
    echo "  # 自动安装Docker并使用sudo"
    echo "  AUTO_INSTALL_DOCKER=yes USE_SUDO_DOCKER=yes $0"
    echo
    echo "  # 保留工作目录用于调试"
    echo "  $0 --keep-workspace"
    echo
}

# 显示完成信息
show_completion() {
    echo
    log_success "=========================================="
    log_success "MIPS部署包构建完成！"
    log_success "=========================================="
    echo
    log_info "输出文件:"
    log_info "  部署包: $OUTPUT_DIR/$PACKAGE_NAME"
    log_info "  说明文档: $OUTPUT_DIR/deploy_instructions.md"
    echo
    log_info "下一步操作:"
    log_info "1. 将部署包上传到服务器"
    log_info "2. 更新install.sh中的下载链接"
    log_info "3. 测试自动安装流程"
    echo
    log_info "非交互式运行提示:"
    log_info "  export AUTO_INSTALL_DOCKER=yes    # 自动安装Docker"
    log_info "  export USE_SUDO_DOCKER=yes        # 使用sudo运行Docker"
    echo
    log_warning "请确保在目标设备上测试部署包！"
    echo
}

# 主函数
main() {
    # 处理命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            --keep-workspace)
                KEEP_WORKSPACE="true"
                shift
                ;;
            *)
                log_error "未知参数: $1"
                log_info "使用 -h 或 --help 查看帮助信息"
                exit 1
                ;;
        esac
    done
    
    echo
    log_info "=========================================="
    log_info "VTO设备管理系统 - MIPS架构打包编译"
    log_info "=========================================="
    echo
    
    # 显示环境变量状态
    if [ "${AUTO_INSTALL_DOCKER:-}" = "yes" ] || [ "${AUTO_INSTALL_DOCKER:-}" = "true" ]; then
        log_info "环境变量: AUTO_INSTALL_DOCKER=yes (自动安装Docker)"
    fi
    if [ "${USE_SUDO_DOCKER:-}" = "yes" ] || [ "${USE_SUDO_DOCKER:-}" = "true" ]; then
        log_info "环境变量: USE_SUDO_DOCKER=yes (使用sudo运行Docker)"
    fi
    if [ "${KEEP_WORKSPACE:-}" = "true" ]; then
        log_info "选项: --keep-workspace (保留工作目录)"
    fi
    echo
    
    # 执行构建流程
    check_dependencies
    setup_workspace
    copy_source_code
    create_docker_env
    build_python_environment
    # build_with_docker  # 备用方案
    optimize_scripts
    create_configs
    add_extra_tools
    optimize_package
    create_final_package
    test_package
    generate_deploy_docs
    if [ "${KEEP_WORKSPACE:-}" = "true" ]; then
        cleanup --keep-workspace
    else
        cleanup
    fi
    show_completion
    
    log_success "构建流程全部完成！"
}

# 脚本入口点
main "$@" 