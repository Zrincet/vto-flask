#!/bin/sh

# VTO设备管理系统 - Padavan MIPS架构自动安装脚本
# 适用于Padavan固件的路由器
# 使用方法: sh -c "$(curl -kfsSL https://your-server.com/install.sh)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
PACKAGE_URL="https://oss-hk.hozoy.cn/vto-flask/vto-mips-package.zip"
INSTALL_DIR="/opt/vto"
TMP_DIR="/opt/tmp"
MIN_SPACE_MB=200
PACKAGE_FILE="vto-mips-package.zip"

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

# 检查命令是否存在
check_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        error_exit "命令 '$1' 未找到，请确保已安装"
    fi
}

# 检查/opt目录挂载状态
check_opt_mount() {
    log_info "检查/opt目录挂载状态..."
    
    if [ ! -d "/opt" ]; then
        error_exit "/opt目录不存在，请确保已正确挂载存储设备"
    fi
    
    # 检查/opt是否为挂载点
    if ! mount | grep -q "/opt"; then
        log_warning "/opt可能未正确挂载，请确保已挂载存储设备到/opt"
    fi
    
    # 测试写入权限
    if ! touch "/opt/.test_write" 2>/dev/null; then
        error_exit "/opt目录无写入权限"
    fi
    rm -f "/opt/.test_write"
    
    log_success "/opt目录检查通过"
}

# 检查磁盘空间
check_disk_space() {
    log_info "检查磁盘剩余空间..."
    
    # 获取/opt分区的可用空间（KB）
    AVAILABLE_KB=$(df /opt | tail -1 | awk '{print $4}')
    AVAILABLE_MB=$((AVAILABLE_KB / 1024))
    
    log_info "可用空间: ${AVAILABLE_MB}MB"
    
    if [ "$AVAILABLE_MB" -lt "$MIN_SPACE_MB" ]; then
        error_exit "磁盘空间不足，需要至少 ${MIN_SPACE_MB}MB，当前可用 ${AVAILABLE_MB}MB"
    fi
    
    log_success "磁盘空间检查通过"
}



# 安装必要的系统包
install_system_packages() {
    log_info "安装系统依赖包..."
    
    # 检查是否存在本地opkg包
    if [ -d "$INSTALL_DIR/opkg-packages" ] && [ -f "$INSTALL_DIR/opkg-packages/install_packages.sh" ]; then
        log_info "发现本地opkg包，使用本地安装..."
        
        cd "$INSTALL_DIR/opkg-packages"
        chmod +x install_packages.sh
        
        if ./install_packages.sh; then
            log_success "本地依赖包安装完成"
        else
            log_warning "本地包安装失败，尝试网络安装..."
            install_packages_from_network
        fi
    else
        log_info "未发现本地包，从网络安装..."
        install_packages_from_network
    fi
}

# 从网络安装包（备用方案）
install_packages_from_network() {
    log_info "从网络安装系统依赖包..."
    
    # 更新包列表
    if opkg update >/dev/null 2>&1; then
        log_success "opkg包列表更新成功"
    else
        log_warning "opkg包列表更新失败"
    fi
    
    # 检查并安装必要包
    PACKAGES="python3 python3-pip python3-dev sqlite3-cli unzip wget curl"
    
    for pkg in $PACKAGES; do
        if ! opkg list-installed | grep -q "^$pkg "; then
            log_info "安装 $pkg..."
            if opkg install "$pkg" >/dev/null 2>&1; then
                log_success "$pkg 安装成功"
            else
                log_warning "$pkg 安装失败，可能影响功能"
            fi
        else
            log_info "$pkg 已安装"
        fi
    done
}

# 创建临时目录
create_temp_dir() {
    log_info "创建临时目录..."
    
    if [ ! -d "$TMP_DIR" ]; then
        mkdir -p "$TMP_DIR" || error_exit "无法创建临时目录 $TMP_DIR"
    fi
    
    log_success "临时目录创建完成: $TMP_DIR"
}

# 下载安装包
download_package() {
    log_info "下载VTO安装包..."
    log_info "下载地址: $PACKAGE_URL"
    
    cd "$TMP_DIR" || error_exit "无法进入临时目录"
    
    # 删除旧的安装包
    rm -f "$PACKAGE_FILE"
    
    # 下载安装包
    if wget "$PACKAGE_URL" -O "$PACKAGE_FILE" --no-check-certificate; then
        log_success "安装包下载完成"
    else
        error_exit "安装包下载失败"
    fi
    
    # 检查文件完整性
    if [ ! -f "$PACKAGE_FILE" ] || [ ! -s "$PACKAGE_FILE" ]; then
        error_exit "下载的安装包文件损坏或为空"
    fi
    
    log_info "安装包大小: $(ls -lh "$PACKAGE_FILE" | awk '{print $5}')"
}

# 解压安装包
extract_package() {
    log_info "解压安装包..."
    
    cd "$TMP_DIR" || error_exit "无法进入临时目录"
    
    # 创建解压目录
    rm -rf "vto-package"
    mkdir -p "vto-package"
    
    # 解压文件
    if unzip -q "$PACKAGE_FILE" -d "vto-package"; then
        log_success "安装包解压完成"
    else
        error_exit "安装包解压失败"
    fi
    
    # 检查解压后的目录结构
    if [ ! -d "vto-package" ]; then
        error_exit "解压后目录结构异常"
    fi
}

# 安装Python虚拟环境和依赖
install_python_env() {
    log_info "设置Python虚拟环境..."
    
    cd "$TMP_DIR/vto-package" || error_exit "无法进入解压目录"
    
    # 检查是否有预编译的虚拟环境
    if [ -d "venv" ]; then
        log_info "发现预编译的Python虚拟环境"
    else
        log_info "创建新的Python虚拟环境..."
        if python3 -m venv venv; then
            log_success "虚拟环境创建成功"
        else
            error_exit "虚拟环境创建失败"
        fi
        
        # 激活虚拟环境并安装依赖
        if [ -f "requirements.txt" ]; then
            log_info "安装Python依赖..."
            . venv/bin/activate
            pip install --upgrade pip >/dev/null 2>&1
            if pip install -r requirements.txt; then
                log_success "Python依赖安装完成"
            else
                log_warning "部分Python依赖安装失败"
            fi
            deactivate
        fi
    fi
}

# 部署应用程序
deploy_application() {
    log_info "部署VTO应用程序..."
    
    # 创建安装目录
    if [ ! -d "$INSTALL_DIR" ]; then
        mkdir -p "$INSTALL_DIR" || error_exit "无法创建安装目录 $INSTALL_DIR"
    fi
    
    # 备份现有安装（如果存在）
    if [ -d "$INSTALL_DIR" ] && [ "$(ls -A $INSTALL_DIR)" ]; then
        BACKUP_DIR="${INSTALL_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
        log_info "备份现有安装到: $BACKUP_DIR"
        mv "$INSTALL_DIR" "$BACKUP_DIR"
        mkdir -p "$INSTALL_DIR"
    fi
    
    # 复制程序文件
    cd "$TMP_DIR/vto-package" || error_exit "无法进入解压目录"
    
    # 复制所有文件到安装目录
    cp -r * "$INSTALL_DIR/" || error_exit "程序文件复制失败"
    
    # 设置执行权限
    chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true
    
    log_success "应用程序部署完成"
}

# 检查并设置虚拟环境
setup_virtual_env() {
    log_info "检查Python虚拟环境..."
    
    cd "$INSTALL_DIR" || error_exit "无法进入安装目录"
    
    if [ ! -d "venv" ] || [ ! -f "venv/bin/python" ]; then
        log_info "虚拟环境不存在或损坏，从安装包复制..."
        
        if [ -d "$TMP_DIR/vto-package/venv" ]; then
            cp -r "$TMP_DIR/vto-package/venv" . || error_exit "虚拟环境复制失败"
            log_success "虚拟环境复制完成"
        else
            error_exit "安装包中未找到虚拟环境"
        fi
    else
        log_success "虚拟环境已存在"
    fi
    
    # 测试虚拟环境
    if . venv/bin/activate && python --version >/dev/null 2>&1; then
        log_success "虚拟环境测试通过"
        deactivate
    else
        error_exit "虚拟环境测试失败"
    fi
}

# 创建系统服务
create_service() {
    log_info "创建系统服务..."
    
    # 创建启动脚本
    cat > /opt/etc/init.d/S99vto << 'EOF'
#!/bin/sh

case "$1" in
    start)
        echo "Starting VTO service..."
        cd /opt/vto && ./server.sh start
        ;;
    stop)
        echo "Stopping VTO service..."
        cd /opt/vto && ./server.sh stop
        ;;
    restart)
        echo "Restarting VTO service..."
        cd /opt/vto && ./server.sh restart
        ;;
    *)
        echo "Usage: $0 {start|stop|restart}"
        exit 1
        ;;
esac
EOF

    chmod +x /opt/etc/init.d/S99vto 2>/dev/null || true
    log_success "系统服务创建完成"
}

# 启动应用程序
start_application() {
    log_info "启动VTO应用程序..."
    
    cd "$INSTALL_DIR" || error_exit "无法进入安装目录"
    
    # 检查启动脚本
    if [ ! -f "server.sh" ]; then
        error_exit "启动脚本不存在"
    fi
    
    # 启动应用
    if ./server.sh start; then
        log_success "VTO应用程序启动成功"
        log_info "应用访问地址: http://$(hostname -I | awk '{print $1}'):8998"
        log_info "默认账户: admin / 123456"
    else
        error_exit "VTO应用程序启动失败"
    fi
}

# 清理临时文件
cleanup_temp() {
    log_info "清理临时文件..."
    
    if [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
        log_success "临时文件清理完成"
    fi
}

# 显示安装完成信息
show_completion_info() {
    echo
    log_success "=========================================="
    log_success "VTO设备管理系统安装完成！"
    log_success "=========================================="
    echo
    log_info "安装目录: $INSTALL_DIR"
    log_info "应用访问地址: http://$(hostname -I | awk '{print $1}'):8998"
    log_info "默认账户: admin / 123456"
    echo
    log_info "服务管理命令:"
    log_info "  启动服务: $INSTALL_DIR/server.sh start"
    log_info "  停止服务: $INSTALL_DIR/server.sh stop"
    log_info "  重启服务: $INSTALL_DIR/server.sh restart"
    log_info "  查看状态: $INSTALL_DIR/server.sh status"
    echo
    log_info "日志文件: $INSTALL_DIR/logs/"
    echo
    log_warning "请修改默认密码以确保安全！"
    echo
}

# 主安装流程
main() {
    echo
    log_info "=========================================="
    log_info "VTO设备管理系统自动安装程序"
    log_info "适用于Padavan MIPS架构"
    log_info "=========================================="
    echo
    
    # 检查基本环境
    check_command "opkg"
    check_command "wget"
    check_command "unzip"
    
    # 执行安装步骤
    check_opt_mount
    check_disk_space
    create_temp_dir
    download_package
    extract_package
    install_python_env
    deploy_application
    setup_virtual_env
    install_system_packages
    create_service
    start_application
    cleanup_temp
    show_completion_info
    
    log_success "安装流程全部完成！"
}

# 脚本入口点
main "$@" 