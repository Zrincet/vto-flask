#!/bin/bash

# VTO设备管理系统 - MIPS架构离线打包脚本
# 在x86_64机器上运行，生成完全离线的Padavan MIPS架构部署包
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

# entware官方仓库
ENTWARE_REPO="http://bin.entware.net/mipselsf-k3.4"

# 预编译Python环境下载地址
VENV_URL="https://oss-hk.hozoy.cn/vto-flask/venv.zip"

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

# 显示帮助信息
show_help() {
    cat << EOF
VTO设备管理系统 - MIPS架构离线打包脚本

用法:
  ./build_package.sh [选项]

选项:
  -h, --help              显示此帮助信息
  --keep-workspace        保留工作目录（用于调试）

功能:
  ✓ 下载opkg核心文件
  ✓ 下载Python3和FFmpeg的ipk包
  ✓ 下载预编译的Python虚拟环境
  ✓ 打包VTO应用程序源码
  ✓ 生成完全离线的安装包

输出:
  生成的包文件: $OUTPUT_DIR/$PACKAGE_NAME

示例:
  # 普通打包
  ./build_package.sh

  # 保留工作目录用于调试
  ./build_package.sh --keep-workspace

EOF
}

# 创建工作目录
setup_workspace() {
    log_info "设置工作环境..."
    
    # 清理并创建工作目录
    rm -rf "$WORK_DIR"
    mkdir -p "$WORK_DIR"
    mkdir -p "$OUTPUT_DIR"
    
    # 创建包结构目录
    mkdir -p "$WORK_DIR/package"
    mkdir -p "$WORK_DIR/package/opkg-core"
    mkdir -p "$WORK_DIR/package/ipk-packages"
    mkdir -p "$WORK_DIR/package/install-scripts"
    
    log_success "工作环境创建完成: $WORK_DIR"
}

# 下载opkg核心文件
download_opkg_core() {
    log_info "下载opkg核心文件..."
    
    cd "$WORK_DIR/package/opkg-core"
    
    # 下载opkg二进制文件
    log_info "下载opkg二进制文件..."
    if wget --timeout=30 --tries=3 "$ENTWARE_REPO/installer/opkg" -O opkg 2>/dev/null; then
        chmod +x opkg
        log_success "✓ opkg二进制文件下载成功"
    else
        error_exit "opkg二进制文件下载失败"
    fi
    
    # 下载entware-opt包
    log_info "下载entware-opt包..."
    local ARCH="mipselsf-k3.4"
    local ENTWARE_OPT_URL="http://bin.entware.net/${ARCH}/entware-opt_227000-3_all.ipk"
    if wget --timeout=30 --tries=3 "$ENTWARE_OPT_URL" -O entware-opt.ipk 2>/dev/null; then
        log_success "✓ entware-opt包下载成功"
    else
        error_exit "entware-opt包下载失败"
    fi
    
    # 创建opkg配置文件
    cat > opkg.conf << 'EOF'
src/gz entware http://bin.entware.net/mipselsf-k3.4
dest root /opt
dest ram /tmp
lists_dir ext /opt/var/lib/opkg
option overlay_root /opt
arch all 100
arch mipselsf-k3.4 200
arch mipsel-3.4 300
EOF
    
    log_success "opkg核心文件准备完成"
}

# 下载所需的ipk包
download_ipk_packages() {
    log_info "下载MIPS架构的ipk包..."
    
    cd "$WORK_DIR/package/ipk-packages"
    
    # 定义需要下载的包列表
    local packages=(
        # Python3 环境及其依赖
        "python3_3.11.10-1_mipsel-3.4.ipk"
        "libpython3_3.11.10-1_mipsel-3.4.ipk"
        "python3-base_3.11.10-1_mipsel-3.4.ipk"
        "libbz2_1.0.8-1a_mipsel-3.4.ipk"
        "zlib_1.3.1-1_mipsel-3.4.ipk"
        "python3-light_3.11.10-1_mipsel-3.4.ipk"
        "python3-asyncio_3.11.10-1_mipsel-3.4.ipk"
        "python3-email_3.11.10-1_mipsel-3.4.ipk"
        "python3-cgi_3.11.10-1_mipsel-3.4.ipk"
        "python3-pydoc_3.11.10-1_mipsel-3.4.ipk"
        "python3-cgitb_3.11.10-1_mipsel-3.4.ipk"
        "python3-codecs_3.11.10-1_mipsel-3.4.ipk"
        "libffi_3.4.7-1_mipsel-3.4.ipk"
        "python3-ctypes_3.11.10-1_mipsel-3.4.ipk"
        "libgdbm_1.23-1_mipsel-3.4.ipk"
        "python3-dbm_3.11.10-1_mipsel-3.4.ipk"
        "python3-decimal_3.11.10-1_mipsel-3.4.ipk"
        "python3-distutils_3.11.10-1_mipsel-3.4.ipk"
        "python3-logging_3.11.10-1_mipsel-3.4.ipk"
        "liblzma_5.6.2-2_mipsel-3.4.ipk"
        "python3-lzma_3.11.10-1_mipsel-3.4.ipk"
        "python3-multiprocessing_3.11.10-1_mipsel-3.4.ipk"
        "libncursesw_6.4-3_mipsel-3.4.ipk"
        "python3-ncurses_3.11.10-1_mipsel-3.4.ipk"
        "libatomic_8.4.0-11_mipsel-3.4.ipk"
        "libopenssl_3.5.0-1_mipsel-3.4.ipk"
        "ca-certificates_20241223-1_all.ipk"
        "python3-openssl_3.11.10-1_mipsel-3.4.ipk"
        "libreadline_8.2-2_mipsel-3.4.ipk"
        "python3-readline_3.11.10-1_mipsel-3.4.ipk"
        "libsqlite3_3.49.1-2_mipsel-3.4.ipk"
        "python3-sqlite3_3.11.10-1_mipsel-3.4.ipk"
        "python3-unittest_3.11.10-1_mipsel-3.4.ipk"
        "python3-urllib_3.11.10-1_mipsel-3.4.ipk"
        "libuuid_2.41-1_mipsel-3.4.ipk"
        "python3-uuid_3.11.10-1_mipsel-3.4.ipk"
        "python3-xml_3.11.10-1_mipsel-3.4.ipk"
        # FFmpeg 及其依赖
        "ffmpeg_6.1.2-3_mipsel-3.4.ipk"
        "alsa-lib_1.2.11-1_mipsel-3.4.ipk"
        "libgmp_6.3.0-1_mipsel-3.4.ipk"
        "libnettle_3.10.1-1_mipsel-3.4.ipk"
        "libgnutls_3.8.9-1_mipsel-3.4.ipk"
        "libopus_1.5.2-1_mipsel-3.4.ipk"
        "libiconv-full_1.18-1_mipsel-3.4.ipk"
        "libv4l_1.28.0-1_mipsel-3.4.ipk"
        "shine_3.1.1-1_mipsel-3.4.ipk"
        "libx264_2024.05.13~4613ac3c-1_mipsel-3.4.ipk"
        "libffmpeg-full_6.1.2-3_mipsel-3.4.ipk"
    )
    
    local success_count=0
    local total_count=${#packages[@]}
    
    for package in "${packages[@]}"; do
        log_info "下载: $package"
        if wget --timeout=30 --tries=3 "$ENTWARE_REPO/$package" -O "$package" 2>/dev/null; then
            log_success "✓ $package 下载成功"
            success_count=$((success_count + 1))
        else
            log_warning "✗ $package 下载失败"
        fi
    done
    
    log_info "IPK包下载完成: $success_count/$total_count 成功"
    
    if [ $success_count -lt $((total_count * 80 / 100)) ]; then
        error_exit "关键包下载失败过多，请检查网络连接"
    fi
}

# 下载预编译的Python虚拟环境
download_python_venv() {
    log_info "下载预编译的Python虚拟环境..."
    
    cd "$WORK_DIR/package"
    
    if wget --timeout=60 --tries=3 "$VENV_URL" -O venv.zip 2>/dev/null; then
        log_success "✓ Python虚拟环境下载成功"
        
        # 解压验证
        if unzip -t venv.zip >/dev/null 2>&1; then
            log_success "✓ venv.zip 文件完整性验证通过"
        else
            error_exit "venv.zip 文件损坏"
        fi
    else
        log_warning "✗ Python虚拟环境下载失败，尝试使用curl..."
        if curl -L -o venv.zip "$VENV_URL" --connect-timeout 60 --max-time 300 --retry 3 --insecure; then
            log_success "✓ Python虚拟环境下载成功"
        else
            error_exit "Python虚拟环境下载失败"
        fi
    fi
}

# 创建安装脚本
create_install_scripts() {
    log_info "创建安装脚本..."
    
    cd "$WORK_DIR/package/install-scripts"
    
    # 创建opkg安装脚本
    cat > install_opkg.sh << 'EOF'
#!/bin/sh

# opkg离线安装脚本
log_info() {
    echo "[INFO] $1"
}

log_success() {
    echo "[SUCCESS] $1"
}

log_error() {
    echo "[ERROR] $1"
}

log_info "开始安装opkg包管理器..."

# 创建必要目录
mkdir -p /opt/bin /opt/etc /opt/lib/opkg /opt/var/lock /opt/var/lib/opkg

# 复制opkg二进制文件
if cp opkg /opt/bin/ && chmod +x /opt/bin/opkg; then
    log_success "opkg二进制文件安装完成"
else
    log_error "opkg二进制文件安装失败"
    exit 1
fi

# 复制配置文件
if cp opkg.conf /opt/etc/; then
    log_success "opkg配置文件安装完成"
else
    log_error "opkg配置文件安装失败"
    exit 1
fi

# 安装entware-opt包
if [ -f "entware-opt.ipk" ]; then
    log_info "安装entware-opt包..."
    if /opt/bin/opkg install entware-opt.ipk --force-depends --dest root; then
        log_success "entware-opt包安装成功"
    else
        log_info "entware-opt包安装失败，但继续进行"
    fi
fi

# 更新PATH环境变量
export PATH="/opt/bin:/opt/sbin:$PATH"

# 创建环境配置文件
mkdir -p /opt/etc/profile.d
cat > /opt/etc/profile.d/entware.sh << 'EOFENV'
#!/bin/sh
export PATH="/opt/bin:/opt/sbin:$PATH"
export LD_LIBRARY_PATH="/opt/lib:$LD_LIBRARY_PATH"
EOFENV
chmod +x /opt/etc/profile.d/entware.sh

log_success "opkg安装完成"
EOF

    # 创建IPK包安装脚本
    cat > install_ipk_packages.sh << 'EOF'
#!/bin/sh

# IPK包离线安装脚本
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
    local pkg_pattern="$1"
    local pkg_file=$(ls $pkg_pattern 2>/dev/null | head -1)
    
    if [ -f "$pkg_file" ]; then
        log_info "安装: $pkg_file"
        if /opt/bin/opkg install "$pkg_file" --force-depends --dest root 2>/dev/null; then
            log_success "✓ $pkg_file 安装成功"
        else
            log_warning "✗ $pkg_file 安装失败"
        fi
    else
        log_warning "✗ 包文件不存在: $pkg_pattern"
    fi
}

log_info "开始安装IPK依赖包..."

# 更新PATH环境变量
export PATH="/opt/bin:/opt/sbin:$PATH"

# 按依赖顺序安装包
install_package "zlib_*.ipk"
install_package "libbz2_*.ipk"
install_package "libffi_*.ipk"
install_package "libatomic_*.ipk"
install_package "liblzma_*.ipk"
install_package "libncursesw_*.ipk"
install_package "libreadline_*.ipk"
install_package "libgdbm_*.ipk"
install_package "libuuid_*.ipk"
install_package "libopenssl_*.ipk"
install_package "ca-certificates_*.ipk"
install_package "libsqlite3_*.ipk"
install_package "libpython3_*.ipk"
install_package "python3-base_*.ipk"
install_package "python3-light_*.ipk"
install_package "python3-codecs_*.ipk"
install_package "python3-email_*.ipk"
install_package "python3-urllib_*.ipk"
install_package "python3-xml_*.ipk"
install_package "python3-uuid_*.ipk"
install_package "python3-logging_*.ipk"
install_package "python3-decimal_*.ipk"
install_package "python3-distutils_*.ipk"
install_package "python3-multiprocessing_*.ipk"
install_package "python3-asyncio_*.ipk"
install_package "python3-cgi_*.ipk"
install_package "python3-cgitb_*.ipk"
install_package "python3-pydoc_*.ipk"
install_package "python3-ctypes_*.ipk"
install_package "python3-dbm_*.ipk"
install_package "python3-lzma_*.ipk"
install_package "python3-ncurses_*.ipk"
install_package "python3-openssl_*.ipk"
install_package "python3-readline_*.ipk"
install_package "python3-sqlite3_*.ipk"
install_package "python3-unittest_*.ipk"
install_package "python3_*.ipk"

# FFmpeg依赖
install_package "libgmp_*.ipk"
install_package "libnettle_*.ipk"
install_package "libgnutls_*.ipk"
install_package "libopus_*.ipk"
install_package "libiconv-full_*.ipk"
install_package "libv4l_*.ipk"
install_package "shine_*.ipk"
install_package "libx264_*.ipk"
install_package "alsa-lib_*.ipk"
install_package "libffmpeg-full_*.ipk"
install_package "ffmpeg_*.ipk"

log_success "IPK包安装完成"
EOF

    # 创建应用部署脚本
    cat > deploy_application.sh << 'EOF'
#!/bin/sh

# VTO应用部署脚本
log_info() {
    echo "[INFO] $1"
}

log_success() {
    echo "[SUCCESS] $1"
}

log_error() {
    echo "[ERROR] $1"
}

INSTALL_DIR="/opt/vto"

log_info "部署VTO应用程序..."

# 创建安装目录
mkdir -p "$INSTALL_DIR"

# 备份现有安装
if [ -d "$INSTALL_DIR" ] && [ "$(ls -A $INSTALL_DIR)" ]; then
    BACKUP_DIR="$INSTALL_DIR"_backup_$(date +%Y%m%d_%H%M%S)
    log_info "备份现有安装到: $BACKUP_DIR"
    mv "$INSTALL_DIR" "$BACKUP_DIR"
    mkdir -p "$INSTALL_DIR"
fi

# 复制应用文件
log_info "复制应用文件..."
cp -r *.py "$INSTALL_DIR/" 2>/dev/null || true
cp -r templates "$INSTALL_DIR/" 2>/dev/null || true
cp -r static "$INSTALL_DIR/" 2>/dev/null || true
cp -r models "$INSTALL_DIR/" 2>/dev/null || true
cp -r controllers "$INSTALL_DIR/" 2>/dev/null || true
cp -r routes "$INSTALL_DIR/" 2>/dev/null || true
cp -r services "$INSTALL_DIR/" 2>/dev/null || true
cp -r utils "$INSTALL_DIR/" 2>/dev/null || true
cp requirements.txt "$INSTALL_DIR/" 2>/dev/null || true
cp *.sh "$INSTALL_DIR/" 2>/dev/null || true

# 解压并复制Python虚拟环境
if [ -f "venv.zip" ]; then
    log_info "解压Python虚拟环境..."
    unzip -q venv.zip -d "$INSTALL_DIR/"
    log_success "Python虚拟环境部署完成"
fi

# 创建必要目录
mkdir -p "$INSTALL_DIR/logs"
mkdir -p "$INSTALL_DIR/db"
mkdir -p "$INSTALL_DIR/instance"

# 设置执行权限
chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true

log_success "应用程序部署完成"
EOF

    # 设置执行权限
    chmod +x *.sh
    
    log_success "安装脚本创建完成"
}

# 复制源代码
copy_source_code() {
    log_info "复制VTO源代码..."
    
    cd "$WORK_DIR/package"
    
    # 复制应用文件
    cp -r "$SOURCE_DIR"/*.py . 2>/dev/null || true
    cp -r "$SOURCE_DIR"/templates . 2>/dev/null || true
    cp -r "$SOURCE_DIR"/static . 2>/dev/null || true
    cp -r "$SOURCE_DIR"/models . 2>/dev/null || true
    cp -r "$SOURCE_DIR"/controllers . 2>/dev/null || true
    cp -r "$SOURCE_DIR"/routes . 2>/dev/null || true
    cp -r "$SOURCE_DIR"/services . 2>/dev/null || true
    cp -r "$SOURCE_DIR"/utils . 2>/dev/null || true
    cp "$SOURCE_DIR"/requirements.txt . 2>/dev/null || true
    cp "$SOURCE_DIR"/server.sh . 2>/dev/null || true
    cp "$SOURCE_DIR"/update_and_restart.sh . 2>/dev/null || true
    cp "$SOURCE_DIR"/README.md . 2>/dev/null || true
    
    # 检查关键文件
    if [ ! -f "app.py" ]; then
        error_exit "源代码中缺少 app.py 文件"
    fi
    
    if [ ! -f "requirements.txt" ]; then
        error_exit "源代码中缺少 requirements.txt 文件"
    fi
    
    log_success "源代码复制完成"
}

# 创建最终的zip包
create_package() {
    log_info "创建部署包..."
    
    cd "$WORK_DIR/package"
    
    # 直接压缩package目录下的内容，而不是package目录本身
    if zip -r "$OUTPUT_DIR/$PACKAGE_NAME" . >/dev/null 2>&1; then
        log_success "部署包创建成功: $OUTPUT_DIR/$PACKAGE_NAME"
        
        # 显示包大小
        PACKAGE_SIZE=$(ls -lh "$OUTPUT_DIR/$PACKAGE_NAME" | awk '{print $5}')
        log_info "包大小: $PACKAGE_SIZE"
        
        # 显示包内容概要
        log_info "包内容概要:"
        log_info "  ✓ opkg核心文件"
        log_info "  ✓ Python3和FFmpeg的IPK包"
        log_info "  ✓ 预编译Python虚拟环境"
        log_info "  ✓ VTO应用程序源码"
        log_info "  ✓ 离线安装脚本"
        
    else
        error_exit "部署包创建失败"
    fi
}

# 清理工作目录
cleanup_workspace() {
    if [ "$KEEP_WORKSPACE" != "true" ]; then
        log_info "清理工作目录..."
        rm -rf "$WORK_DIR"
        log_success "工作目录清理完成"
    else
        log_info "保留工作目录: $WORK_DIR"
    fi
}

# 主函数
main() {
    echo
    log_info "=========================================="
    log_info "VTO设备管理系统 - MIPS架构离线打包脚本"
    log_info "=========================================="
    echo
    
    # 处理命令行参数
    KEEP_WORKSPACE=false
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            --keep-workspace)
                KEEP_WORKSPACE=true
                shift
                ;;
            *)
                log_error "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # 检查必要工具
    if ! command -v wget >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
        error_exit "需要wget或curl命令来下载文件"
    fi
    
    if ! command -v zip >/dev/null 2>&1; then
        error_exit "需要zip命令来创建包文件"
    fi
    
    if ! command -v unzip >/dev/null 2>&1; then
        error_exit "需要unzip命令来验证zip文件"
    fi
    
    # 执行打包流程
    setup_workspace
    download_opkg_core
    download_ipk_packages
    download_python_venv
    create_install_scripts
    copy_source_code
    create_package
    cleanup_workspace
    
    echo
    log_success "=========================================="
    log_success "离线部署包创建完成！"
    log_success "=========================================="
    log_info "输出文件: $OUTPUT_DIR/$PACKAGE_NAME"
    log_info "使用方法: 将此文件上传到Padavan路由器，然后运行install_padavan.sh"
    echo
}

# 脚本入口点
main "$@"
