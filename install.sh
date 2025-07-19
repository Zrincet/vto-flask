#!/bin/sh

# VTO设备管理系统 - Padavan MIPS架构自动安装脚本
# 适用于Padavan固件的路由器
# 功能：自动安装Entware、opkg包管理器，并部署VTO应用
# 使用方法: sh -c "$(curl -kfsSL https://your-server.com/install.sh)"

# BusyBox兼容脚本 - 移除颜色输出

# 配置变量
PACKAGE_URL="https://oss-hk.hozoy.cn/vto-flask/vto-mips-package.zip"
INSTALL_DIR="/opt/vto"
TMP_DIR="/opt/tmp"
MIN_SPACE_MB=200
PACKAGE_FILE="vto-mips-package.zip"

# 日志函数（BusyBox兼容）
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

# 错误退出函数
error_exit() {
    log_error "$1"
    exit 1
}

# 检查命令是否存在
check_command() {
    # 尝试多种方式查找命令
    if command -v "$1" >/dev/null 2>&1; then
        log_info "命令 '$1' 已找到: $(command -v "$1")"
        return 0
    fi
    
    # 尝试在常见路径中查找
    for path in /bin /sbin /usr/bin /usr/sbin /opt/bin /opt/sbin; do
        if [ -x "$path/$1" ]; then
            log_info "命令 '$1' 在 $path/$1 中找到"
            export PATH="$path:$PATH"
            return 0
        fi
    done
    
    # 如果还是找不到，尝试直接执行看是否可用
    if "$1" --version >/dev/null 2>&1 || "$1" -V >/dev/null 2>&1; then
        log_info "命令 '$1' 可直接执行"
        return 0
    fi
    
    error_exit "命令 '$1' 未找到，请确保已安装"
}

# 检查并安装opkg
check_and_install_opkg() {
    log_info "检查opkg包管理器..."
    
    if command -v opkg >/dev/null 2>&1; then
        log_success "opkg已安装"
        return 0
    fi
    
    log_warning "opkg未安装，开始离线安装opkg..."
    
    # 检查/opt目录是否已挂载
    if [ ! -d "/opt" ]; then
        error_exit "/opt目录不存在，请先挂载存储设备到/opt目录"
    fi
    
    # 检查/opt目录权限
    if ! touch "/opt/.test_write" 2>/dev/null; then
        error_exit "/opt目录无写入权限，请检查挂载状态"
    fi
    rm -f "/opt/.test_write"
    
    # 检测MIPS架构
    ARCH=$(uname -m)
    case "$ARCH" in
        "mips"|"mipsel"|"mips64"|"mips64el")
            log_info "检测到MIPS架构: $ARCH"
            ;;
        *)
            log_warning "未知架构: $ARCH，尝试继续安装"
            ;;
    esac
    
    # 检查是否有离线opkg文件
    if [ -d "$TMP_DIR/vto-package/opkg-core" ]; then
        log_info "发现离线opkg文件，开始离线安装..."
        
        cd "$TMP_DIR/vto-package/opkg-core"
        
        if [ -f "install_opkg.sh" ]; then
            log_info "执行离线opkg安装脚本..."
            chmod +x install_opkg.sh
            if ./install_opkg.sh; then
                log_success "离线opkg安装成功"
                
                # 更新PATH环境变量
                export PATH="/opt/bin:/opt/sbin:$PATH"
                
                # 验证opkg是否可用
                if command -v opkg >/dev/null 2>&1; then
                    log_success "opkg安装验证成功"
                    return 0
                else
                    log_warning "opkg安装后验证失败，尝试在线安装"
                fi
            else
                log_warning "离线opkg安装失败，尝试在线安装"
            fi
        else
            log_warning "离线opkg安装脚本不存在，尝试在线安装"
        fi
    else
        log_warning "未发现离线opkg文件，尝试在线安装"
    fi
    
    # 如果离线安装失败，尝试在线安装Entware
    log_info "尝试在线安装Entware..."
    
    # 尝试不同的Entware安装脚本（BusyBox兼容）
    install_success=false
    
    # 尝试第一个源
    log_info "尝试从 http://bin.entware.net/mipselsf-k3.4/installer/generic.sh 安装..."
    if curl -s "http://bin.entware.net/mipselsf-k3.4/installer/generic.sh" 2>/dev/null | /bin/sh; then
        log_success "Entware安装成功"
        install_success=true
    else
        log_warning "第一个源安装失败，尝试备用源..."
        
        # 尝试第二个源
        log_info "尝试从 http://bin.entware.net/mipssf-k3.4/installer/generic.sh 安装..."
        if curl -s "http://bin.entware.net/mipssf-k3.4/installer/generic.sh" 2>/dev/null | /bin/sh; then
            log_success "Entware安装成功"
            install_success=true
        else
            log_warning "第二个源安装失败，尝试备用源..."
            
            # 尝试第三个源
            log_info "尝试从 http://bin.entware.net/mipsel-k3.4/installer/generic.sh 安装..."
            if curl -s "http://bin.entware.net/mipsel-k3.4/installer/generic.sh" 2>/dev/null | /bin/sh; then
                log_success "Entware安装成功"
                install_success=true
            else
                error_exit "所有Entware安装源都失败，请检查网络连接或手动安装"
            fi
        fi
    fi
    
    if [ "$install_success" = false ]; then
        error_exit "所有Entware安装源都失败，请手动安装"
    fi
    
    # 更新PATH环境变量
    export PATH="/opt/bin:/opt/sbin:$PATH"
    
    # 验证opkg是否可用
    if command -v opkg >/dev/null 2>&1; then
        log_success "opkg安装验证成功"
        
        # 更新opkg包列表
        log_info "更新opkg包列表..."
        if opkg update >/dev/null 2>&1; then
            log_success "opkg包列表更新成功"
        else
            log_warning "opkg包列表更新失败，但继续安装过程"
        fi
        
        # 创建环境配置脚本
        mkdir -p /opt/etc/profile.d
        cat > /opt/etc/profile.d/entware.sh << 'EOF'
#!/bin/sh
# Entware环境配置
export PATH="/opt/bin:/opt/sbin:$PATH"
export LD_LIBRARY_PATH="/opt/lib:$LD_LIBRARY_PATH"
EOF
        chmod +x /opt/etc/profile.d/entware.sh
        
        log_info "Entware环境配置已保存"
        
    else
        error_exit "opkg安装后仍不可用，请检查安装"
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
    AVAILABLE_KB=$(df /opt | tail -1 | cut -d' ' -f4)
    AVAILABLE_MB=$((AVAILABLE_KB / 1024))
    
    log_info "可用空间: $AVAILABLE_MB MB"
    
    if [ "$AVAILABLE_MB" -lt "$MIN_SPACE_MB" ]; then
        error_exit "磁盘空间不足，需要至少 $MIN_SPACE_MB MB，当前可用 $AVAILABLE_MB MB"
    fi
    
    log_success "磁盘空间检查通过"
}



# 安装必要的系统包
install_system_packages() {
    log_info "安装系统依赖包..."
    
    # 检查是否存在本地opkg包（在解压后的目录中）
    if [ -d "$TMP_DIR/vto-package/opkg-packages" ] && [ -f "$TMP_DIR/vto-package/opkg-packages/install_packages.sh" ]; then
        log_info "发现离线opkg包，使用离线安装..."
        
        cd "$TMP_DIR/vto-package/opkg-packages"
        chmod +x install_packages.sh
        
        if ./install_packages.sh; then
            log_success "离线依赖包安装完成"
            return 0
        else
            log_warning "离线包安装失败，尝试网络安装..."
        fi
    elif [ -d "$INSTALL_DIR/opkg-packages" ] && [ -f "$INSTALL_DIR/opkg-packages/install_packages.sh" ]; then
        log_info "发现本地opkg包，使用本地安装..."
        
        cd "$INSTALL_DIR/opkg-packages"
        chmod +x install_packages.sh
        
        if ./install_packages.sh; then
            log_success "本地依赖包安装完成"
            return 0
        else
            log_warning "本地包安装失败，尝试网络安装..."
        fi
    else
        log_info "未发现离线包，尝试网络安装..."
    fi
    
    # 备用方案：从网络安装
    install_packages_from_network
}

# 从网络安装包（备用方案）
install_packages_from_network() {
    log_info "从网络安装系统依赖包..."
    
    # 确保opkg可用
    if ! command -v opkg >/dev/null 2>&1; then
        log_error "opkg不可用，无法安装网络包"
        return 1
    fi
    
    # 更新包列表
    if opkg update >/dev/null 2>&1; then
        log_success "opkg包列表更新成功"
    else
        log_warning "opkg包列表更新失败"
    fi
    
    # 检查并安装必要包
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
    if curl -L -o "$PACKAGE_FILE" "$PACKAGE_URL" --insecure; then
        log_success "安装包下载完成"
    else
        error_exit "安装包下载失败"
    fi
    
    # 检查文件完整性
    if [ ! -f "$PACKAGE_FILE" ] || [ ! -s "$PACKAGE_FILE" ]; then
        error_exit "下载的安装包文件损坏或为空"
    fi
    
    log_info "安装包大小: $(ls -lh "$PACKAGE_FILE" | cut -d' ' -f5)"
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
        BACKUP_DIR="$INSTALL_DIR"_backup_$(date +%Y%m%d_%H%M%S)
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

# 显示安装完成信息
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
    log_info "日志文件: $INSTALL_DIR/logs/"
    echo
    log_info "Entware环境:"
    log_info "  opkg路径: /opt/bin/opkg"
    log_info "  包目录: /opt/var/opkg-lists/"
    log_info "  安装目录: /opt/"
    echo
    log_warning "请修改默认密码以确保安全！"
    echo
}

# 显示环境信息
show_environment_info() {
    log_info "当前环境信息:"
    log_info "  系统架构: $(uname -m)"
    log_info "  系统版本: $(uname -r)"
    log_info "  当前用户: $(whoami)"
    log_info "  当前目录: $(pwd)"
    log_info "  PATH环境: $PATH"
    echo
    
    # 检查关键命令
    log_info "检查关键命令:"
    for cmd in curl unzip opkg; do
        if command -v "$cmd" >/dev/null 2>&1; then
            log_info "  $cmd: $(command -v "$cmd")"
        else
            log_warning "  $cmd: 未找到"
        fi
    done
    echo
}

# 主安装流程
main() {
    echo
    log_info "=========================================="
    log_info "VTO设备管理系统自动安装程序"
    log_info "适用于Padavan MIPS架构"
    log_info "功能：自动安装Entware + opkg + VTO应用"
    log_info "=========================================="
    echo
    
    # 显示环境信息
    show_environment_info
    
    # 检查基本环境（除了opkg）
    log_info "检查基本命令..."
    
    # 检查curl（如果检测失败，尝试直接使用）
    if ! check_command "curl" 2>/dev/null; then
        log_warning "curl命令检测失败，尝试直接使用..."
        # 尝试直接执行curl
        if curl --version >/dev/null 2>&1 || curl -V >/dev/null 2>&1; then
            log_success "curl命令可直接使用"
        else
            error_exit "curl命令不可用，请确保已安装"
        fi
    fi
    
    check_command "unzip"
    
    # 检查并安装opkg
    check_and_install_opkg
    
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