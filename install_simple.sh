#!/bin/sh

# VTO设备管理系统 - 简化版安装脚本
# 适用于Padavan MIPS架构，减少命令检测严格性

# 配置变量
PACKAGE_URL="https://oss-hk.hozoy.cn/vto-flask/vto-mips-package.zip"
INSTALL_DIR="/opt/vto"
TMP_DIR="/opt/tmp"
MIN_SPACE_MB=200
PACKAGE_FILE="vto-mips-package.zip"

# 日志函数
log_info() {
    echo "[INFO] $1"
}

log_success() {
    echo "[SUCCESS] $1"
}

log_warning() {
    echo "[WARNING] $1"
}

log_error() {
    echo "[ERROR] $1"
}

error_exit() {
    log_error "$1"
    exit 1
}

# 简化的命令检查
check_command_simple() {
    local cmd="$1"
    local cmd_name="$2"
    
    # 尝试多种方式
    if command -v "$cmd" >/dev/null 2>&1; then
        log_info "$cmd_name 已找到"
        return 0
    fi
    
    # 检查常见路径
    for path in /bin /sbin /usr/bin /usr/sbin /opt/bin /opt/sbin; do
        if [ -x "$path/$cmd" ]; then
            log_info "$cmd_name 在 $path/$cmd 中找到"
            export PATH="$path:$PATH"
            return 0
        fi
    done
    
    # 尝试直接执行
    if "$cmd" --version >/dev/null 2>&1 || "$cmd" -V >/dev/null 2>&1; then
        log_info "$cmd_name 可直接执行"
        return 0
    fi
    
    log_warning "$cmd_name 未找到，但继续尝试..."
    return 1
}

# 检查并安装opkg
check_and_install_opkg() {
    log_info "检查opkg包管理器..."
    
    if command -v opkg >/dev/null 2>&1; then
        log_success "opkg已安装"
        return 0
    fi
    
    log_warning "opkg未安装，开始自动安装Entware..."
    
    # 检查/opt目录
    if [ ! -d "/opt" ]; then
        error_exit "/opt目录不存在，请先挂载存储设备到/opt目录"
    fi
    
    if ! touch "/opt/.test_write" 2>/dev/null; then
        error_exit "/opt目录无写入权限，请检查挂载状态"
    fi
    rm -f "/opt/.test_write"
    
    # 安装Entware
    log_info "下载并安装Entware..."
    
    install_success=false
    
    # 尝试不同的Entware安装脚本
    for url in \
        "http://bin.entware.net/mipselsf-k3.4/installer/generic.sh" \
        "http://bin.entware.net/mipssf-k3.4/installer/generic.sh" \
        "http://bin.entware.net/mipsel-k3.4/installer/generic.sh" \
        "http://bin.entware.net/mips-k3.4/installer/generic.sh" \
        "http://bin.entware.net/mipsel-k3.2/installer/generic.sh" \
        "http://bin.entware.net/mips-k3.2/installer/generic.sh"
    do
        log_info "尝试从 $url 安装..."
        if curl -s "$url" 2>/dev/null | /bin/sh; then
            log_success "Entware安装成功"
            install_success=true
            break
        else
            log_warning "安装失败，尝试下一个源..."
        fi
    done
    
    if [ "$install_success" = false ]; then
        error_exit "所有Entware安装源都失败，请手动安装"
    fi
    
    # 更新PATH
    export PATH="/opt/bin:/opt/sbin:$PATH"
    
    # 验证opkg
    if command -v opkg >/dev/null 2>&1; then
        log_success "opkg安装验证成功"
        
        # 更新包列表
        if opkg update >/dev/null 2>&1; then
            log_success "opkg包列表更新成功"
        else
            log_warning "opkg包列表更新失败，但继续安装过程"
        fi
        
        # 创建环境配置
        cat > /opt/etc/profile.d/entware.sh << 'EOF'
#!/bin/sh
export PATH="/opt/bin:/opt/sbin:$PATH"
export LD_LIBRARY_PATH="/opt/lib:$LD_LIBRARY_PATH"
EOF
        chmod +x /opt/etc/profile.d/entware.sh
        
    else
        error_exit "opkg安装后仍不可用，请检查安装"
    fi
}

# 检查磁盘空间
check_disk_space() {
    log_info "检查磁盘剩余空间..."
    
    AVAILABLE_KB=$(df /opt | tail -1 | cut -d' ' -f4)
    AVAILABLE_MB=$((AVAILABLE_KB / 1024))
    
    log_info "可用空间: $AVAILABLE_MB MB"
    
    if [ "$AVAILABLE_MB" -lt "$MIN_SPACE_MB" ]; then
        error_exit "磁盘空间不足，需要至少 $MIN_SPACE_MB MB，当前可用 $AVAILABLE_MB MB"
    fi
    
    log_success "磁盘空间检查通过"
}

# 下载安装包
download_package() {
    log_info "下载VTO安装包..."
    log_info "下载地址: $PACKAGE_URL"
    
    cd "$TMP_DIR" || error_exit "无法进入临时目录"
    
    rm -f "$PACKAGE_FILE"
    
    # 尝试下载
    if curl -L -o "$PACKAGE_FILE" "$PACKAGE_URL" --insecure; then
        log_success "安装包下载完成"
    else
        error_exit "安装包下载失败"
    fi
    
    if [ ! -f "$PACKAGE_FILE" ] || [ ! -s "$PACKAGE_FILE" ]; then
        error_exit "下载的安装包文件损坏或为空"
    fi
    
    log_info "安装包大小: $(ls -lh "$PACKAGE_FILE" | cut -d' ' -f5)"
}

# 解压安装包
extract_package() {
    log_info "解压安装包..."
    
    cd "$TMP_DIR" || error_exit "无法进入临时目录"
    
    rm -rf "vto-package"
    mkdir -p "vto-package"
    
    if unzip -q "$PACKAGE_FILE" -d "vto-package"; then
        log_success "安装包解压完成"
    else
        error_exit "安装包解压失败"
    fi
}

# 部署应用程序
deploy_application() {
    log_info "部署VTO应用程序..."
    
    if [ ! -d "$INSTALL_DIR" ]; then
        mkdir -p "$INSTALL_DIR" || error_exit "无法创建安装目录 $INSTALL_DIR"
    fi
    
    # 备份现有安装
    if [ -d "$INSTALL_DIR" ] && [ "$(ls -A $INSTALL_DIR)" ]; then
        BACKUP_DIR="$INSTALL_DIR"_backup_$(date +%Y%m%d_%H%M%S)
        log_info "备份现有安装到: $BACKUP_DIR"
        mv "$INSTALL_DIR" "$BACKUP_DIR"
        mkdir -p "$INSTALL_DIR"
    fi
    
    cd "$TMP_DIR/vto-package" || error_exit "无法进入解压目录"
    
    cp -r * "$INSTALL_DIR/" || error_exit "程序文件复制失败"
    
    chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true
    
    log_success "应用程序部署完成"
}

# 安装系统包
install_system_packages() {
    log_info "安装系统依赖包..."
    
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

# 从网络安装包
install_packages_from_network() {
    log_info "从网络安装系统依赖包..."
    
    if ! command -v opkg >/dev/null 2>&1; then
        log_error "opkg不可用，无法安装网络包"
        return 1
    fi
    
    if opkg update >/dev/null 2>&1; then
        log_success "opkg包列表更新成功"
    else
        log_warning "opkg包列表更新失败"
    fi
    
    PACKAGES="python3 python3-pip python3-dev sqlite3-cli unzip curl"
    
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

# 创建系统服务
create_service() {
    log_info "创建系统服务..."
    
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
    
    if [ ! -f "server.sh" ]; then
        error_exit "启动脚本不存在"
    fi
    
    if ./server.sh start; then
        log_success "VTO应用程序启动成功"
        log_info "应用访问地址: http://$(hostname -i):8998"
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

# 显示完成信息
show_completion_info() {
    echo
    log_success "=========================================="
    log_success "VTO设备管理系统安装完成！"
    log_success "=========================================="
    echo
    log_info "安装目录: $INSTALL_DIR"
    log_info "应用访问地址: http://$(hostname -i):8998"
    log_info "默认账户: admin / 123456"
    echo
    log_info "服务管理命令:"
    log_info "  启动服务: $INSTALL_DIR/server.sh start"
    log_info "  停止服务: $INSTALL_DIR/server.sh stop"
    log_info "  重启服务: $INSTALL_DIR/server.sh restart"
    log_info "  查看状态: $INSTALL_DIR/server.sh status"
    echo
    log_warning "请修改默认密码以确保安全！"
    echo
}

# 主安装流程
main() {
    echo
    log_info "=========================================="
    log_info "VTO设备管理系统自动安装程序（简化版）"
    log_info "适用于Padavan MIPS架构"
    log_info "=========================================="
    echo
    
    # 显示环境信息
    log_info "当前环境信息:"
    log_info "  系统架构: $(uname -m)"
    log_info "  系统版本: $(uname -r)"
    log_info "  当前用户: $(whoami)"
    log_info "  当前目录: $(pwd)"
    echo
    
    # 简化命令检查
    log_info "检查基本命令..."
    check_command_simple "curl" "curl命令"
    check_command_simple "unzip" "unzip命令"
    
    # 执行安装步骤
    check_and_install_opkg
    
    # 创建临时目录
    if [ ! -d "$TMP_DIR" ]; then
        mkdir -p "$TMP_DIR" || error_exit "无法创建临时目录 $TMP_DIR"
    fi
    
    check_disk_space
    download_package
    extract_package
    deploy_application
    install_system_packages
    create_service
    start_application
    cleanup_temp
    show_completion_info
    
    log_success "安装流程全部完成！"
}

# 脚本入口点
main "$@" 