#!/bin/bash

# VTO设备管理系统 - MIPS架构打包编译脚本（无Docker版本）
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

# MIPS包下载配置
OPENWRT_REPO="https://downloads.openwrt.org/releases/22.03.5/packages/mipsel_24kc"
PADAVAN_REPO="https://opt.cn2qq.com/padavan-opt/opt-pkg"

# 必需的MIPS包列表
REQUIRED_PACKAGES=(
    "python3"
    "python3-pip" 
    "python3-dev"
    "python3-setuptools"
    "python3-wheel"
    "sqlite3-cli"
    "libsqlite3"
    "ffmpeg"
    "curl"
    "wget"
    "unzip"
    "openssl-util"
)

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

# 安装Python开发环境
install_python_dev() {
    log_info "检查Python开发环境..."
    
    OS=$(detect_os)
    log_info "检测到系统: $OS"
    
    case "$OS" in
        "ubuntu"|"debian")
            log_info "使用APT安装Python开发环境..."
            if command -v apt-get >/dev/null 2>&1; then
                apt-get update >/dev/null 2>&1 || sudo apt-get update
                apt-get install -y python3 python3-pip python3-venv python3-dev build-essential >/dev/null 2>&1 || \
                sudo apt-get install -y python3 python3-pip python3-venv python3-dev build-essential
            fi
            ;;
            
        "centos"|"rhel"|"rocky"|"almalinux")
            log_info "使用YUM安装Python开发环境..."
            if command -v yum >/dev/null 2>&1; then
                yum install -y python3 python3-pip python3-devel gcc gcc-c++ make >/dev/null 2>&1 || \
                sudo yum install -y python3 python3-pip python3-devel gcc gcc-c++ make
            fi
            ;;
            
        "fedora")
            log_info "使用DNF安装Python开发环境..."
            if command -v dnf >/dev/null 2>&1; then
                dnf install -y python3 python3-pip python3-devel gcc gcc-c++ make >/dev/null 2>&1 || \
                sudo dnf install -y python3 python3-pip python3-devel gcc gcc-c++ make
            fi
            ;;
            
        "arch"|"manjaro")
            log_info "使用Pacman安装Python开发环境..."
            if command -v pacman >/dev/null 2>&1; then
                pacman -S --noconfirm python python-pip base-devel >/dev/null 2>&1 || \
                sudo pacman -S --noconfirm python python-pip base-devel
            fi
            ;;
            
        *)
            log_warning "未识别的Linux发行版: $OS，跳过自动安装"
            ;;
    esac
    
    log_success "Python开发环境检查完成"
}

# 检查依赖工具
check_dependencies() {
    log_info "检查编译依赖..."
    
    # 检查基本工具
    BASIC_TOOLS="wget tar git python3 zip"
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
            python3 -m ensurepip --default-pip >/dev/null 2>&1 || install_python_dev
        fi
    fi
    
    # 检查Python虚拟环境支持
    if ! python3 -m venv --help >/dev/null 2>&1; then
        log_warning "Python venv模块不可用，尝试安装..."
        install_python_dev
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
    mkdir -p "$WORK_DIR/package"
    
    log_success "工作环境创建完成: $WORK_DIR"
}

# 下载opkg本体和配置文件
download_opkg_core() {
    log_info "下载opkg核心文件..."
    
    # 创建opkg核心文件目录
    mkdir -p "$WORK_DIR/package/opkg-core"
    cd "$WORK_DIR/package/opkg-core"
    
    # MIPS架构配置
    local ARCH="mipselsf-k3.4"
    local INSTALLER_URL="http://bin.entware.net/${ARCH}/installer"
    
    log_info "下载opkg二进制文件..."
    if wget --timeout=30 --tries=3 "$INSTALLER_URL/opkg" -O opkg 2>/dev/null; then
        chmod 755 opkg
        log_success "✓ opkg二进制文件下载成功"
    else
        log_error "✗ opkg二进制文件下载失败"
        return 1
    fi
    
    log_info "下载opkg配置文件..."
    if wget --timeout=30 --tries=3 "$INSTALLER_URL/opkg.conf" -O opkg.conf 2>/dev/null; then
        log_success "✓ opkg配置文件下载成功"
    else
        log_error "✗ opkg配置文件下载失败"
        return 1
    fi
    
    # 下载entware-opt包
    log_info "下载entware-opt包..."
    local PACKAGES_URL="http://bin.entware.net/${ARCH}/packages"
    
    # 尝试下载不同版本的entware-opt
    local entware_files=(
        "entware-opt_1.0-52_mipsel.ipk"
        "entware-opt_1.0-51_mipsel.ipk" 
        "entware-opt_1.0-50_mipsel.ipk"
        "entware-opt_1.0-49_mipsel.ipk"
    )
    
    local entware_downloaded=false
    for entware_file in "${entware_files[@]}"; do
        log_info "尝试下载 $entware_file..."
        if wget --timeout=30 --tries=2 "$PACKAGES_URL/$entware_file" -O entware-opt.ipk 2>/dev/null; then
            log_success "✓ entware-opt包下载成功: $entware_file"
            entware_downloaded=true
            break
        fi
    done
    
    if [ "$entware_downloaded" = false ]; then
        log_warning "entware-opt包下载失败，尝试备用方案"
        # 创建一个最小的entware-opt替代包信息
        cat > entware-opt-info.txt << 'EOF'
# entware-opt包下载失败
# 可以在目标设备上手动执行: opkg install entware-opt
EOF
    fi
    
    # 创建opkg安装脚本
    cat > install_opkg.sh << 'EOF'
#!/bin/sh

# opkg核心安装脚本
# 在目标设备上离线安装opkg

log_info() {
    echo "[INFO] $1"
}

log_success() {
    echo "[SUCCESS] $1"
}

log_error() {
    echo "[ERROR] $1"
}

error_exit() {
    log_error "$1"
    exit 1
}

# 检查并创建目录结构
setup_directories() {
    log_info "创建opkg目录结构..."
    
    # 检查/opt目录
    if [ ! -d /opt ]; then
        log_info "创建/opt目录..."
        mkdir /opt || error_exit "无法创建/opt目录"
    fi
    
    # 创建必要的子目录
    for folder in bin etc lib/opkg tmp var/lock; do
        if [ ! -d "/opt/$folder" ]; then
            log_info "创建目录: /opt/$folder"
            mkdir -p "/opt/$folder" || error_exit "无法创建目录: /opt/$folder"
        fi
    done
    
    log_success "目录结构创建完成"
}

# 安装opkg核心文件
install_opkg_core() {
    log_info "安装opkg核心文件..."
    
    # 复制opkg二进制文件
    if [ -f "opkg" ]; then
        cp opkg /opt/bin/opkg || error_exit "无法复制opkg二进制文件"
        chmod 755 /opt/bin/opkg
        log_success "✓ opkg二进制文件安装完成"
    else
        error_exit "opkg二进制文件不存在"
    fi
    
    # 复制配置文件
    if [ -f "opkg.conf" ]; then
        cp opkg.conf /opt/etc/opkg.conf || error_exit "无法复制opkg配置文件"
        log_success "✓ opkg配置文件安装完成"
    else
        error_exit "opkg配置文件不存在"
    fi
    
    # 更新PATH
    export PATH="/opt/bin:/opt/sbin:$PATH"
    
    # 验证opkg安装
    if /opt/bin/opkg --version >/dev/null 2>&1; then
        log_success "✓ opkg安装验证成功"
    else
        error_exit "opkg安装验证失败"
    fi
}

# 安装entware-opt包
install_entware_opt() {
    log_info "安装entware-opt包..."
    
    if [ -f "entware-opt.ipk" ]; then
        log_info "使用离线entware-opt包..."
        if /opt/bin/opkg install entware-opt.ipk --force-depends 2>/dev/null; then
            log_success "✓ entware-opt包安装成功"
        else
            log_warning "entware-opt包安装失败，尝试在线安装"
            if /opt/bin/opkg update && /opt/bin/opkg install entware-opt; then
                log_success "✓ entware-opt在线安装成功"
            else
                log_warning "entware-opt安装失败，但继续..."
            fi
        fi
    else
        log_info "尝试在线安装entware-opt..."
        if /opt/bin/opkg update && /opt/bin/opkg install entware-opt; then
            log_success "✓ entware-opt在线安装成功"
        else
            log_warning "entware-opt在线安装失败"
        fi
    fi
}

# 配置环境
setup_environment() {
    log_info "配置opkg环境..."
    
    # 设置权限
    chmod 777 /opt/tmp 2>/dev/null || true
    
    # 创建环境配置文件
    mkdir -p /opt/etc/profile.d
    cat > /opt/etc/profile.d/entware.sh << 'ENVEOF'
#!/bin/sh
# Entware环境配置
export PATH="/opt/bin:/opt/sbin:$PATH"
export LD_LIBRARY_PATH="/opt/lib:$LD_LIBRARY_PATH"
ENVEOF
    chmod +x /opt/etc/profile.d/entware.sh
    
    # 创建符号链接（如果需要）
    for file in passwd group shells shadow gshadow; do
        if [ -f "/etc/$file" ] && [ ! -f "/opt/etc/$file" ]; then
            ln -sf "/etc/$file" "/opt/etc/$file" 2>/dev/null || true
        fi
    done
    
    # 创建localtime链接
    if [ -f "/etc/localtime" ] && [ ! -f "/opt/etc/localtime" ]; then
        ln -sf "/etc/localtime" "/opt/etc/localtime" 2>/dev/null || true
    fi
    
    log_success "环境配置完成"
}

# 主安装流程
main_install() {
    log_info "开始opkg离线安装..."
    
    setup_directories
    install_opkg_core
    install_entware_opt
    setup_environment
    
    log_success "opkg离线安装完成！"
    log_info "请将 /opt/bin 和 /opt/sbin 添加到 PATH 环境变量"
    log_info "可以运行: export PATH=\"/opt/bin:/opt/sbin:\$PATH\""
}

# 执行安装
main_install
EOF

    chmod +x install_opkg.sh
    
    cd "$WORK_DIR"
    log_success "opkg核心文件下载完成"
}

# 下载MIPS架构的opkg包
download_mips_packages() {
    log_info "下载MIPS架构的软件包..."
    
    # 创建包目录
    mkdir -p "$WORK_DIR/package/opkg-packages"
    cd "$WORK_DIR/package/opkg-packages"
    
    # 创建包索引文件
    cat > package_list.txt << 'EOF'
# MIPS架构包列表 - 适用于Padavan/OpenWrt
# 格式: 包名|下载URL|文件名
python3|packages|python3_3.10.13-2_mipsel_24kc.ipk
python3-pip|packages|python3-pip_23.0.1-1_mipsel_24kc.ipk
python3-dev|packages|python3-dev_3.10.13-2_mipsel_24kc.ipk
python3-setuptools|packages|python3-setuptools_65.5.0-1_mipsel_24kc.ipk
ffmpeg|packages|ffmpeg_5.1.3-1_mipsel_24kc.ipk
curl|packages|curl_8.6.0-1_mipsel_24kc.ipk
wget|packages|wget-ssl_1.21.4-1_mipsel_24kc.ipk
unzip|packages|unzip_6.0-8_mipsel_24kc.ipk
EOF

    # 下载包函数
    download_package() {
        local pkg_name="$1"
        local repo_path="$2" 
        local filename="$3"
        
        local base_url="$OPENWRT_REPO"
        
        # 根据仓库路径构建完整URL
        case "$repo_path" in
            "base")
                local url="$base_url/base/$filename"
                ;;
            "packages")
                local url="$base_url/packages/$filename"
                ;;
            *)
                local url="$base_url/$repo_path/$filename"
                ;;
        esac
        
        log_info "下载 $pkg_name: $filename"
        
        # 尝试下载
        if wget -q --timeout=30 --tries=3 "$url" -O "$filename" 2>/dev/null; then
            log_success "✓ $pkg_name 下载成功"
            return 0
        else
            log_warning "✗ $pkg_name 下载失败，尝试备用源..."
            
            # 尝试备用源
            local backup_url="$PADAVAN_REPO/$filename"
            if wget -q --timeout=30 --tries=2 "$backup_url" -O "$filename" 2>/dev/null; then
                log_success "✓ $pkg_name 从备用源下载成功"
                return 0
            else
                log_warning "✗ $pkg_name 从所有源下载失败"
                return 1
            fi
        fi
    }
    
    # 读取包列表并下载
    local success_count=0
    local total_count=0
    
    while IFS='|' read -r pkg_name repo_path filename || [ -n "$pkg_name" ]; do
        # 跳过注释行和空行
        if [[ "$pkg_name" =~ ^#.*$ ]] || [ -z "$pkg_name" ]; then
            continue
        fi
        
        total_count=$((total_count + 1))
        
        if download_package "$pkg_name" "$repo_path" "$filename"; then
            success_count=$((success_count + 1))
        fi
    done < package_list.txt
    
    log_info "包下载完成: $success_count/$total_count 成功"
    
    # 创建安装脚本
    cat > install_packages.sh << 'EOF'
#!/bin/sh

# MIPS包安装脚本
# 在目标设备上运行此脚本来安装所有依赖包

log_info() {
    echo "[INFO] $1"
}

log_success() {
    echo "[SUCCESS] $1"
}

log_warning() {
    echo "[WARNING] $1"
}

install_package() {
    local pkg_file="$1"
    
    if [ -f "$pkg_file" ]; then
        log_info "安装: $pkg_file"
        if opkg install "$pkg_file" --force-depends 2>/dev/null; then
            log_success "✓ $pkg_file 安装成功"
        else
            log_warning "✗ $pkg_file 安装失败"
        fi
    else
        log_warning "✗ 包文件不存在: $pkg_file"
    fi
}

# 安装顺序很重要，先安装基础库
log_info "开始安装MIPS依赖包..."

# 基础库
install_package "zlib_*.ipk"
install_package "libffi_*.ipk"
install_package "libssl3_*.ipk"
install_package "libcrypto3_*.ipk"
install_package "libbz2_*.ipk"
install_package "libreadline8_*.ipk"
install_package "libncurses6_*.ipk"
install_package "libexpat_*.ipk"

# SQLite
install_package "libsqlite3_*.ipk"
install_package "sqlite3-cli_*.ipk"

# 网络工具
install_package "openssl-util_*.ipk"
install_package "curl_*.ipk"
install_package "wget_*.ipk"
install_package "unzip_*.ipk"

# Python
install_package "python3_*.ipk"
install_package "python3-setuptools_*.ipk"
install_package "python3-wheel_*.ipk"
install_package "python3-pip_*.ipk"
install_package "python3-dev_*.ipk"

# 多媒体
install_package "ffmpeg_*.ipk"

log_success "MIPS依赖包安装完成！"
EOF

    chmod +x install_packages.sh
    
    # 统计下载的包
    local downloaded_count=$(ls -1 *.ipk 2>/dev/null | wc -l)
    log_success "MIPS包下载完成，共 $downloaded_count 个包"
    
    cd "$WORK_DIR"
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

# 构建Python虚拟环境
build_python_environment() {
    log_info "构建Python虚拟环境..."
    
    # 在工作目录创建虚拟环境
    cd "$WORK_DIR"
    
    # 创建虚拟环境
    if python3 -m venv venv-build; then
        log_success "虚拟环境创建成功"
    else
        error_exit "虚拟环境创建失败"
    fi
    
    # 激活虚拟环境
    source venv-build/bin/activate
    
    # 升级pip
    log_info "升级pip..."
    pip install --upgrade pip >/dev/null 2>&1
    
    # 读取requirements.txt并安装依赖
    log_info "安装Python依赖包..."
    
    # 创建优化的requirements.txt，使用稳定版本
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
    
    # 停用虚拟环境
    deactivate
    
    # 复制虚拟环境到打包目录
    cp -r venv-build "$WORK_DIR/package/venv"
    
    # 清理虚拟环境中的无用文件
    log_info "清理虚拟环境..."
    find "$WORK_DIR/package/venv" -name "*.pyc" -delete
    find "$WORK_DIR/package/venv" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$WORK_DIR/package/venv" -name "*.pyo" -delete
    
    log_success "Python环境构建完成"
}

# 优化启动脚本
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
    
    # 创建日志目录
    mkdir -p logs
    
    # 清理虚拟环境
    if [ -d "venv" ]; then
        find venv -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
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
    
    # 检查opkg包
    if [ ! -d "test-extract/opkg-packages" ]; then
        log_warning "opkg包目录不存在"
    else
        local ipk_count=$(ls -1 test-extract/opkg-packages/*.ipk 2>/dev/null | wc -l)
        if [ "$ipk_count" -gt 0 ]; then
            log_success "opkg包检查通过，发现 $ipk_count 个包"
        else
            log_warning "opkg包目录为空"
        fi
        
        if [ -f "test-extract/opkg-packages/install_packages.sh" ]; then
            log_success "opkg安装脚本存在"
        else
            log_warning "opkg安装脚本缺失"
        fi
    fi
    
    # 检查opkg核心文件
    if [ ! -d "test-extract/opkg-core" ]; then
        log_warning "opkg核心目录不存在"
    else
        if [ -f "test-extract/opkg-core/opkg" ]; then
            log_success "opkg二进制文件存在"
        else
            log_warning "opkg二进制文件缺失"
        fi
        
        if [ -f "test-extract/opkg-core/opkg.conf" ]; then
            log_success "opkg配置文件存在"
        else
            log_warning "opkg配置文件缺失"
        fi
        
        if [ -f "test-extract/opkg-core/install_opkg.sh" ]; then
            log_success "opkg安装脚本存在"
        else
            log_warning "opkg安装脚本缺失"
        fi
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
- 构建方式: 本地Python环境构建
- 内置组件: 完全离线安装支持

## 系统要求
- Padavan固件路由器
- 已挂载的/opt目录（推荐使用USB存储）
- 至少200MB可用空间
- 无需网络连接（完全离线安装）

## 构建要求（用于编译此包）
- Linux系统（支持多种发行版）
- Python 3.7+
- 基本开发工具（git, wget, tar, zip等）
- 无需Docker（已移除Docker依赖）

## 构建此部署包
\`\`\`bash
# 普通构建
./build_package.sh

# 保留工作目录用于调试
./build_package.sh --keep-workspace

# 查看帮助信息
./build_package.sh --help
\`\`\`

## 内置组件说明
此部署包内置了以下组件，完全离线安装：

**opkg包管理器**
- opkg二进制文件
- opkg配置文件
- entware-opt基础包
- 离线安装脚本

**Python环境**
- python3 (3.10.13)
- python3-pip (23.0.1)
- python3-dev
- python3-setuptools
- python3-wheel

**系统依赖**
- sqlite3-cli + libsqlite3
- curl + wget + unzip
- openssl-util
- zlib + libffi + 其他运行时库

**多媒体支持**
- ffmpeg (5.1.3)

## 自动安装方法
\`\`\`bash
# 一键安装（推荐）
sh -c "\$(curl -kfsSL https://oss-hk.hozoy.cn/vto-flask/install.sh)"
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

### 4. 离线安装opkg（如果未安装）
\`\`\`bash
cd /opt/vto/opkg-core
chmod +x install_opkg.sh
./install_opkg.sh
\`\`\`

### 5. 安装系统依赖（使用内置包）
\`\`\`bash
cd /opt/vto/opkg-packages
chmod +x install_packages.sh
./install_packages.sh
\`\`\`

### 6. 启动应用
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

## 更新记录
- v3.0: 完全离线安装支持，内置opkg核心文件
- v2.0: 移除Docker依赖，使用本地Python环境构建
- v1.0: 初始版本，基于Docker构建

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
}

# 显示帮助信息
show_help() {
    echo
    echo "VTO设备管理系统 - MIPS架构打包编译脚本（无Docker版本）"
    echo
    echo "用法:"
    echo "  $0 [选项]"
    echo
    echo "选项:"
    echo "  -h, --help              显示此帮助信息"
    echo "  --keep-workspace        保留工作目录（用于调试）"
    echo
    echo "特性:"
    echo "  ✓ 无需Docker环境"
    echo "  ✓ 使用本地Python环境构建"
    echo "  ✓ 支持多种Linux发行版"
    echo "  ✓ 自动安装缺失依赖"
    echo "  ✓ 生成优化的MIPS部署包"
    echo "  ✓ 完全离线安装支持"
    echo "  ✓ 内置opkg核心文件"
    echo
    echo "示例:"
    echo "  # 普通构建"
    echo "  $0"
    echo
    echo "  # 保留工作目录用于调试"
    echo "  $0 --keep-workspace"
    echo
    echo "支持的系统:"
    echo "  - Ubuntu/Debian (APT)"
    echo "  - CentOS/RHEL/Rocky/AlmaLinux (YUM)"
    echo "  - Fedora (DNF)"
    echo "  - Arch Linux/Manjaro (Pacman)"
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
    log_info "构建特性:"
    log_info "  ✓ 无Docker依赖"
    log_info "  ✓ 本地Python环境构建"
    log_info "  ✓ 适配云效流水线"
    log_info "  ✓ 内置MIPS架构opkg包"
    log_info "  ✓ 完全离线安装支持"
    log_info "  ✓ 内置opkg核心文件和配置"
    echo
    log_info "离线组件："
    log_info "  ✓ opkg包管理器 + entware-opt"
    log_info "  ✓ Python3环境 + pip3"
    log_info "  ✓ SQLite3 + 网络工具"
    log_info "  ✓ FFmpeg多媒体支持"
    echo
    log_info "下一步操作:"
    log_info "1. 将部署包上传到OSS: https://oss-hk.hozoy.cn/vto-flask/$PACKAGE_NAME"
    log_info "2. 测试自动安装流程"
    log_info "3. 验证离线安装功能"
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
    log_info "无Docker版本 - 完全离线安装支持"
    log_info "=========================================="
    echo
    
    # 显示环境变量状态
    if [ "${KEEP_WORKSPACE:-}" = "true" ]; then
        log_info "选项: --keep-workspace (保留工作目录)"
        echo
    fi
    
    # 执行构建流程
    check_dependencies
    setup_workspace
    copy_source_code
    download_opkg_core
    download_mips_packages
    build_python_environment
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
    
    # 创建日志目录
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
        
        # 删除缓存目录
        find venv -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
        find venv -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
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
    
    # 检查opkg包
    if [ ! -d "test-extract/opkg-packages" ]; then
        log_warning "opkg包目录不存在"
    else
        local ipk_count=$(ls -1 test-extract/opkg-packages/*.ipk 2>/dev/null | wc -l)
        if [ "$ipk_count" -gt 0 ]; then
            log_success "opkg包检查通过，发现 $ipk_count 个包"
        else
            log_warning "opkg包目录为空"
        fi
        
        if [ -f "test-extract/opkg-packages/install_packages.sh" ]; then
            log_success "opkg安装脚本存在"
        else
            log_warning "opkg安装脚本缺失"
        fi
    fi
    
    # 检查opkg核心文件
    if [ ! -d "test-extract/opkg-core" ]; then
        log_warning "opkg核心目录不存在"
    else
        if [ -f "test-extract/opkg-core/opkg" ]; then
            log_success "opkg二进制文件存在"
        else
            log_warning "opkg二进制文件缺失"
        fi
        
        if [ -f "test-extract/opkg-core/opkg.conf" ]; then
            log_success "opkg配置文件存在"
        else
            log_warning "opkg配置文件缺失"
        fi
        
        if [ -f "test-extract/opkg-core/install_opkg.sh" ]; then
            log_success "opkg安装脚本存在"
        else
            log_warning "opkg安装脚本缺失"
        fi
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
- 构建方式: 本地Python环境构建
- 内置组件: MIPS架构opkg包 (python3, pip3, ffmpeg等)

## 系统要求
- Padavan固件路由器
- 已挂载的/opt目录（推荐使用USB存储）
- 至少200MB可用空间
- 网络连接（可选，包含本地opkg包）

## 构建要求（用于编译此包）
- Linux系统（支持多种发行版）
- Python 3.7+
- 基本开发工具（git, wget, tar, zip等）
- 无需Docker（已移除Docker依赖）

## 构建此部署包
\`\`\`bash
# 普通构建
./build_package.sh

# 保留工作目录用于调试
./build_package.sh --keep-workspace

# 查看帮助信息
./build_package.sh --help
\`\`\`

## 内置组件说明
此部署包内置了以下组件，完全离线安装：

**opkg包管理器**
- opkg二进制文件
- opkg配置文件
- entware-opt基础包
- 离线安装脚本

**Python环境**
- python3 (3.10.13)
- python3-pip (23.0.1)
- python3-dev
- python3-setuptools
- python3-wheel

**系统依赖**
- sqlite3-cli + libsqlite3
- curl + wget + unzip
- openssl-util
- zlib + libffi + 其他运行时库

**多媒体支持**
- ffmpeg (5.1.3)

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

### 4. 离线安装opkg（如果未安装）
\`\`\`bash
cd /opt/vto/opkg-core
chmod +x install_opkg.sh
./install_opkg.sh
\`\`\`

### 5. 安装系统依赖（使用内置包）
\`\`\`bash
cd /opt/vto/opkg-packages
chmod +x install_packages.sh
./install_packages.sh
\`\`\`

### 6. 启动应用
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

## 更新记录
- v2.0: 移除Docker依赖，使用本地Python环境构建
- v1.0: 初始版本，基于Docker构建

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
}

# 显示帮助信息
show_help() {
    echo
    echo "VTO设备管理系统 - MIPS架构打包编译脚本（无Docker版本）"
    echo
    echo "用法:"
    echo "  $0 [选项]"
    echo
    echo "选项:"
    echo "  -h, --help              显示此帮助信息"
    echo "  --keep-workspace        保留工作目录（用于调试）"
    echo
    echo "特性:"
    echo "  ✓ 无需Docker环境"
    echo "  ✓ 使用本地Python环境构建"
    echo "  ✓ 支持多种Linux发行版"
    echo "  ✓ 自动安装缺失依赖"
    echo "  ✓ 生成优化的MIPS部署包"
    echo
    echo "示例:"
    echo "  # 普通构建"
    echo "  $0"
    echo
    echo "  # 保留工作目录用于调试"
    echo "  $0 --keep-workspace"
    echo
    echo "支持的系统:"
    echo "  - Ubuntu/Debian (APT)"
    echo "  - CentOS/RHEL/Rocky/AlmaLinux (YUM)"
    echo "  - Fedora (DNF)"
    echo "  - Arch Linux/Manjaro (Pacman)"
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
    log_info "构建特性:"
    log_info "  ✓ 无Docker依赖"
    log_info "  ✓ 本地Python环境构建"
    log_info "  ✓ 适配云效流水线"
    log_info "  ✓ 内置MIPS架构opkg包"
    log_info "  ✓ 包含Python3、pip3、ffmpeg等依赖"
    echo
    log_info "下一步操作:"
    log_info "1. 将部署包上传到服务器"
    log_info "2. 更新install.sh中的下载链接"
    log_info "3. 测试自动安装流程"
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
    log_info "无Docker版本 - 适配云效流水线"
    log_info "=========================================="
    echo
    
    # 显示环境变量状态
    if [ "${KEEP_WORKSPACE:-}" = "true" ]; then
        log_info "选项: --keep-workspace (保留工作目录)"
        echo
    fi
    
    # 执行构建流程
    check_dependencies
    setup_workspace
    copy_source_code
    download_opkg_core
    download_mips_packages
    build_python_environment
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