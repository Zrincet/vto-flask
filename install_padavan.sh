#!/bin/sh

# VTO设备管理系统 - Padavan MIPS架构安装脚本
# 适用于Padavan固件的路由器 (MIPS架构)
# 使用方法: sh install_padavan.sh

# BusyBox兼容脚本 - 使用简单的日志输出

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

# 检查/opt目录挂载状态和剩余空间
check_opt_space() {
    log_info "检查/opt目录挂载状态和剩余空间..."
    
    # 检查/opt目录是否存在
    if [ ! -d "/opt" ]; then
        error_exit "/opt目录不存在，请确保已正确挂载存储设备到/opt目录"
    fi
    
    # 检查/opt目录权限
    if ! touch "/opt/.test_write" 2>/dev/null; then
        error_exit "/opt目录无写入权限，请检查挂载状态或权限设置"
    fi
    rm -f "/opt/.test_write"
    
    # 获取/opt分区的可用空间（KB）
    # 使用df命令，BusyBox版本兼容
    AVAILABLE_KB=$(df /opt | tail -1 | awk '{print $4}')
    
    # 检查是否获取到有效数值
    if [ -z "$AVAILABLE_KB" ] || [ "$AVAILABLE_KB" -eq 0 ] 2>/dev/null; then
        log_warning "无法获取准确的磁盘空间信息，尝试继续安装"
        AVAILABLE_MB=0
    else
        AVAILABLE_MB=$((AVAILABLE_KB / 1024))
    fi
    
    log_info "可用空间: $AVAILABLE_MB MB"
    
    if [ "$AVAILABLE_MB" -gt 0 ] && [ "$AVAILABLE_MB" -lt "$MIN_SPACE_MB" ]; then
        error_exit "磁盘空间不足，需要至少 $MIN_SPACE_MB MB，当前可用 $AVAILABLE_MB MB"
    fi
    
    log_success "/opt目录检查通过"
}

# 创建临时目录
create_temp_dir() {
    log_info "创建临时目录..."
    
    # 创建临时目录
    if [ ! -d "$TMP_DIR" ]; then
        if mkdir -p "$TMP_DIR"; then
            log_success "临时目录创建完成: $TMP_DIR"
        else
            error_exit "无法创建临时目录 $TMP_DIR"
        fi
    else
        log_info "临时目录已存在: $TMP_DIR"
    fi
    
    # 清理旧的安装包
    if [ -f "$TMP_DIR/$PACKAGE_FILE" ]; then
        log_info "清理旧的安装包..."
        rm -f "$TMP_DIR/$PACKAGE_FILE"
    fi
}

# 下载安装包
download_package() {
    log_info "下载VTO安装包..."
    log_info "下载地址: $PACKAGE_URL"
    
    cd "$TMP_DIR" || error_exit "无法进入临时目录"
    
    # 检查curl命令是否可用（BusyBox兼容检测）
    if ! curl --help >/dev/null 2>&1; then
        # 尝试使用wget作为备选
        if wget --help >/dev/null 2>&1; then
            log_info "curl不可用，使用wget下载..."
            USE_WGET=true
        else
            error_exit "curl和wget都不可用，请确保至少安装其中一个"
        fi
    else
        log_info "使用curl下载..."
        USE_WGET=false
    fi
    
    # 下载安装包，添加超时和重试机制
    log_info "开始下载，请耐心等待..."
    if [ "$USE_WGET" = true ]; then
        # 使用wget下载
        if wget -O "$PACKAGE_FILE" "$PACKAGE_URL" --timeout=30 --tries=3 --no-check-certificate; then
            log_success "安装包下载完成"
        else
            error_exit "安装包下载失败，请检查网络连接"
        fi
    else
        # 使用curl下载
        if curl -L -o "$PACKAGE_FILE" "$PACKAGE_URL" --connect-timeout 30 --max-time 300 --retry 3 --insecure; then
            log_success "安装包下载完成"
        else
            error_exit "安装包下载失败，请检查网络连接"
        fi
    fi
    
    # 检查文件完整性
    if [ ! -f "$PACKAGE_FILE" ] || [ ! -s "$PACKAGE_FILE" ]; then
        error_exit "下载的安装包文件损坏或为空"
    fi
    
    # 显示下载文件信息
    PACKAGE_SIZE=$(ls -lh "$PACKAGE_FILE" | awk '{print $5}')
    log_info "安装包大小: $PACKAGE_SIZE"
}

# 解压安装包
extract_package() {
    log_info "解压安装包..."
    
    cd "$TMP_DIR" || error_exit "无法进入临时目录"
    
    # 检查unzip命令是否可用（BusyBox兼容检测）
    if ! unzip 2>&1 | grep -q "Usage:"; then
        error_exit "unzip命令不可用，请确保已安装unzip"
    fi
    
    # 创建解压目录
    rm -rf "vto-package"
    mkdir -p "vto-package"
    
    # 解压文件
    if unzip -q "$PACKAGE_FILE" -d "vto-package"; then
        log_success "安装包解压完成"
    else
        error_exit "安装包解压失败，请检查文件完整性"
    fi
    
    # 检查解压后的目录结构
    if [ ! -d "vto-package" ]; then
        error_exit "解压后目录结构异常"
    fi
    
    # 检查关键文件是否存在（支持两种目录结构）
    if [ -d "vto-package/opkg-core" ]; then
        log_info "发现opkg-core目录，可以进行离线安装"
    elif [ -d "vto-package/package/opkg-core" ]; then
        log_info "发现opkg-core目录（在package子目录中），可以进行离线安装"
        # 调整路径，将package子目录的内容移到上一级
        cd vto-package
        if [ -d "package" ]; then
            mv package/* . 2>/dev/null || true
            rmdir package 2>/dev/null || true
        fi
        cd ..
    else
        log_warning "未找到opkg-core目录，可能需要在线安装opkg"
    fi
}

# 安装opkg包管理器
install_opkg() {
    log_info "开始安装opkg包管理器..."
    
    # 检查opkg是否已经安装
    if opkg --version >/dev/null 2>&1; then
        log_success "opkg已经安装，版本: $(opkg --version 2>/dev/null | head -1 || echo '未知')"
        return 0
    fi
    
    log_info "opkg未安装，开始离线安装..."
    
    # 检查离线opkg文件是否存在
    if [ ! -d "$TMP_DIR/vto-package/opkg-core" ]; then
        error_exit "未找到离线opkg安装文件，请检查安装包内容"
    fi
    
    cd "$TMP_DIR/vto-package/opkg-core" || error_exit "无法进入opkg-core目录"
    
    # 检查安装脚本
    if [ -f "install_opkg.sh" ]; then
        log_info "执行opkg离线安装脚本..."
        chmod +x install_opkg.sh
        
        if ./install_opkg.sh; then
            log_success "opkg离线安装成功"
        else
            error_exit "opkg离线安装失败"
        fi
    else
        error_exit "未找到opkg安装脚本"
    fi
    
    # 更新PATH环境变量
    export PATH="/opt/bin:/opt/sbin:$PATH"
    
    # 验证opkg安装
    if opkg --version >/dev/null 2>&1; then
        OPKG_VERSION=$(opkg --version 2>/dev/null | head -1 || echo "未知版本")
        log_success "opkg安装验证成功，版本: $OPKG_VERSION"
    else
        error_exit "opkg安装后验证失败"
    fi
}

# 安装系统依赖包
install_system_packages() {
    log_info "开始安装系统依赖包..."
    
    # 确保opkg可用
    if ! opkg --version >/dev/null 2>&1; then
        error_exit "opkg不可用，请先安装opkg包管理器"
    fi
    
    # 更新PATH环境变量
    export PATH="/opt/bin:/opt/sbin:$PATH"
    
    # 检查是否存在IPK包安装脚本
    if [ -d "$TMP_DIR/vto-package/ipk-packages" ] && [ -f "$TMP_DIR/vto-package/install-scripts/install_ipk_packages.sh" ]; then
        log_info "发现离线IPK包，使用离线安装..."
        
        cd "$TMP_DIR/vto-package/ipk-packages"
        
        # 复制安装脚本到当前目录
        cp "$TMP_DIR/vto-package/install-scripts/install_ipk_packages.sh" .
        chmod +x install_ipk_packages.sh
        
        if ./install_ipk_packages.sh; then
            log_success "离线IPK包安装完成"
            
            # 验证关键包安装
            verify_package_installation
            return 0
        else
            log_warning "离线IPK包安装失败"
            error_exit "系统依赖包安装失败"
        fi
    else
        error_exit "未找到离线IPK包，无法进行完全离线安装"
    fi
}

# 删除手动安装关键包函数 - 不再需要
# install_packages_manually() 已移除
# install_single_package() 已移除

# 验证包安装
verify_package_installation() {
    log_info "验证关键包安装状态..."
    
    # 检查Python环境
    if python3 --version >/dev/null 2>&1; then
        PYTHON_VERSION=$(python3 --version 2>&1)
        log_success "Python3 安装成功: $PYTHON_VERSION"
    else
        log_error "Python3 安装失败"
    fi
    
    # 检查pip3
    if pip3 --version >/dev/null 2>&1; then
        PIP_VERSION=$(pip3 --version 2>&1 | head -1)
        log_success "pip3 安装成功: $PIP_VERSION"
    else
        log_warning "pip3 不可用，可能影响Python包管理"
    fi
    
    # 检查SQLite
    if sqlite3 -version >/dev/null 2>&1; then
        SQLITE_VERSION=$(sqlite3 -version 2>&1)
        log_success "SQLite3 安装成功: $SQLITE_VERSION"
    else
        log_warning "SQLite3 不可用，可能影响数据库功能"
    fi
    
    # 检查FFmpeg
    if ffmpeg -version >/dev/null 2>&1; then
        FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -1)
        log_success "FFmpeg 安装成功: $FFMPEG_VERSION"
    else
        log_warning "FFmpeg 不可用，可能影响视频功能"
    fi
    
    # 检查基础工具
    for tool in curl wget unzip; do
        if $tool --version >/dev/null 2>&1 || $tool -V >/dev/null 2>&1; then
            log_success "$tool 可用"
        else
            log_warning "$tool 不可用"
        fi
    done
}

# 安装Python虚拟环境和依赖
install_python_environment() {
    log_info "设置Python虚拟环境..."
    
    cd "$TMP_DIR/vto-package" || error_exit "无法进入解压目录"
    
    # 检查Python3是否可用
    if ! python3 --version >/dev/null 2>&1; then
        error_exit "Python3 不可用，请确保已正确安装Python3"
    fi
    
    # 按依赖顺序安装virtualenv工具及其依赖
    log_info "安装virtualenv工具及其依赖..."
    
    # 创建pip缓存目录
    mkdir -p /opt/tmp/pip
    
    # 安装distlib（基础依赖）
    if [ -f "distlib-0.4.0-py2.py3-none-any.whl" ]; then
        log_info "安装distlib依赖..."
        if pip3 install distlib-0.4.0-py2.py3-none-any.whl --no-deps --cache-dir /opt/tmp/pip 2>/dev/null; then
            log_success "distlib安装成功"
        else
            log_warning "distlib安装失败"
        fi
    else
        log_warning "未找到distlib包"
    fi
    
    # 安装platformdirs
    if [ -f "platformdirs-4.3.8-py3-none-any.whl" ]; then
        log_info "安装platformdirs依赖..."
        if pip3 install platformdirs-4.3.8-py3-none-any.whl --no-deps --cache-dir /opt/tmp/pip 2>/dev/null; then
            log_success "platformdirs安装成功"
        else
            log_warning "platformdirs安装失败"
        fi
    else
        log_warning "未找到platformdirs包"
    fi
    
    # 安装filelock
    if [ -f "filelock-3.18.0-py3-none-any.whl" ]; then
        log_info "安装filelock依赖..."
        if pip3 install filelock-3.18.0-py3-none-any.whl --no-deps --cache-dir /opt/tmp/pip 2>/dev/null; then
            log_success "filelock安装成功"
        else
            log_warning "filelock安装失败"
        fi
    else
        log_warning "未找到filelock包"
    fi
    
    # 最后安装virtualenv工具
    if [ -f "virtualenv-20.32.0-py3-none-any.whl" ]; then
        log_info "安装virtualenv工具..."
        if pip3 install virtualenv-20.32.0-py3-none-any.whl --no-deps --cache-dir /opt/tmp/pip 2>/dev/null; then
            log_success "virtualenv工具安装成功"
            
            # 验证virtualenv安装
            if virtualenv --version >/dev/null 2>&1; then
                VIRTUALENV_VERSION=$(virtualenv --version 2>&1)
                log_success "virtualenv验证成功: $VIRTUALENV_VERSION"
            else
                log_warning "virtualenv安装后验证失败"
            fi
        else
            log_warning "virtualenv工具安装失败，尝试系统自带venv模块"
        fi
    else
        log_warning "未找到virtualenv工具，使用系统自带venv模块"
    fi
}

# 部署VTO应用
deploy_vto_application() {
    log_info "部署VTO应用程序..."
    
    # 检查部署脚本是否存在
    if [ -f "$TMP_DIR/vto-package/install-scripts/deploy_application.sh" ]; then
        log_info "使用部署脚本进行应用部署..."
        
        cd "$TMP_DIR/vto-package"
        
        # 复制部署脚本到当前目录
        cp install-scripts/deploy_application.sh .
        chmod +x deploy_application.sh
        
        if ./deploy_application.sh; then
            log_success "VTO应用部署成功"
        else
            error_exit "VTO应用部署失败"
        fi
    else
        # 手动部署（备用方案）
        log_info "使用手动方式部署应用..."
        
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
        
        # 复制应用文件到安装目录
        log_info "复制应用文件..."
        
        # 复制Python源码
        cp -r *.py "$INSTALL_DIR/" 2>/dev/null || true
        cp -r templates "$INSTALL_DIR/" 2>/dev/null || true
        cp -r static "$INSTALL_DIR/" 2>/dev/null || true
        cp -r models "$INSTALL_DIR/" 2>/dev/null || true
        cp -r controllers "$INSTALL_DIR/" 2>/dev/null || true
        cp -r routes "$INSTALL_DIR/" 2>/dev/null || true
        cp -r services "$INSTALL_DIR/" 2>/dev/null || true
        cp -r utils "$INSTALL_DIR/" 2>/dev/null || true
        
        # 复制配置和脚本文件
        cp requirements.txt "$INSTALL_DIR/" 2>/dev/null || true
        cp *.sh "$INSTALL_DIR/" 2>/dev/null || true
        
        # 解压并复制虚拟环境
        if [ -f "venv.zip" ]; then
            log_info "解压Python虚拟环境到安装目录..."
            unzip -q venv.zip -d "$INSTALL_DIR/"
            log_success "虚拟环境部署完成"
        elif [ -d "venv" ]; then
            log_info "复制Python虚拟环境..."
            cp -r venv "$INSTALL_DIR/"
            log_success "虚拟环境复制完成"
        fi
        
        # 创建必要的目录
        mkdir -p "$INSTALL_DIR/logs"
        mkdir -p "$INSTALL_DIR/db"
        mkdir -p "$INSTALL_DIR/instance"
        
        # 设置执行权限
        chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true
        
        log_success "应用程序部署完成"
    fi
}

# 创建系统服务
create_system_service() {
    log_info "创建系统服务..."
    
    # 确保init.d目录存在
    mkdir -p /opt/etc/init.d
    
    # 创建VTO启动脚本
    cat > /opt/etc/init.d/S99vto << 'EOF'
#!/bin/sh

DAEMON="VTO Flask App"
PIDFILE="/var/run/vto.pid"
VTO_DIR="/opt/vto"

start() {
    echo -n "Starting $DAEMON: "
    cd "$VTO_DIR"
    if [ -f "$VTO_DIR/server.sh" ]; then
        ./server.sh start >/dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo "OK"
        else
            echo "FAIL"
        fi
    else
        echo "FAIL (script not found)"
    fi
}

stop() {
    echo -n "Stopping $DAEMON: "
    cd "$VTO_DIR"
    if [ -f "$VTO_DIR/server.sh" ]; then
        ./server.sh stop >/dev/null 2>&1
        echo "OK"
    else
        echo "FAIL (script not found)"
    fi
}

restart() {
    stop
    sleep 1
    start
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    *)
        echo "Usage: $0 {start|stop|restart}"
        exit 1
        ;;
esac

exit 0
EOF

    chmod +x /opt/etc/init.d/S99vto 2>/dev/null || true
    log_success "系统服务创建完成"
}

# 启动VTO应用
start_vto_application() {
    log_info "启动VTO应用程序..."
    
    cd "$INSTALL_DIR" || error_exit "无法进入安装目录"
    
    # 检查启动脚本
    if [ ! -f "server.sh" ]; then
        error_exit "启动脚本不存在"
    fi
    
    # 设置执行权限
    chmod +x server.sh
    
    # 检查虚拟环境
    if [ ! -d "venv" ] || [ ! -f "venv/bin/python" ]; then
        log_warning "虚拟环境不存在或损坏"
    fi
    
    # 启动应用
    log_info "正在启动VTO应用，请稍候..."
    if ./server.sh start; then
        log_success "VTO应用程序启动成功"
        
        # 获取IP地址
        LOCAL_IP=$(hostname -i 2>/dev/null || ip route get 1 | awk '{print $NF;exit}' 2>/dev/null || echo "localhost")
        
        log_info "应用访问地址: http://$LOCAL_IP:8998"
        log_info "默认账户: admin"
        log_info "默认密码: 123456"
    else
        log_error "VTO应用程序启动失败"
        log_info "请检查日志文件: $INSTALL_DIR/logs/app.log"
    fi
}

# 清理临时文件
cleanup_temp_files() {
    log_info "清理临时文件..."
    
    if [ -d "$TMP_DIR" ]; then
        # 保留重要文件，清理下载的安装包
        rm -f "$TMP_DIR/$PACKAGE_FILE"
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
    
    # 获取IP地址
    LOCAL_IP=$(hostname -i 2>/dev/null || ip route get 1 | awk '{print $NF;exit}' 2>/dev/null || echo "localhost")
    log_info "应用访问地址: http://$LOCAL_IP:8998"
    log_info "默认账户: admin / 123456"
    echo
    log_info "服务管理命令:"
    log_info "  启动服务: $INSTALL_DIR/server.sh start"
    log_info "  停止服务: $INSTALL_DIR/server.sh stop"
    log_info "  重启服务: $INSTALL_DIR/server.sh restart"
    log_info "  查看状态: $INSTALL_DIR/server.sh status"
    echo
    log_info "系统服务:"
    log_info "  启动: /opt/etc/init.d/S99vto start"
    log_info "  停止: /opt/etc/init.d/S99vto stop"
    log_info "  重启: /opt/etc/init.d/S99vto restart"
    echo
    log_info "日志文件: $INSTALL_DIR/logs/"
    log_info "配置文件: $INSTALL_DIR/config.json"
    echo
    log_info "已安装的组件:"
    log_info "  ✓ opkg包管理器（离线安装）"
    log_info "  ✓ Python3 3.11.10（完整环境）"
    log_info "  ✓ SQLite3数据库支持"
    log_info "  ✓ FFmpeg 6.1.2多媒体支持"
    log_info "  ✓ virtualenv虚拟环境工具"
    log_info "  ✓ pycryptodome MIPS版本"
    log_info "  ✓ 预编译Python虚拟环境"
    log_info "  ✓ VTO Flask应用程序"
    echo
    log_warning "请修改默认密码以确保安全！"
    log_info "访问系统后，进入用户管理页面修改admin密码"
    echo
}

# 显示系统环境信息
show_environment_info() {
    echo
    log_info "=========================================="
    log_info "系统环境信息"
    log_info "=========================================="
    log_info "系统架构: $(uname -m)"
    log_info "系统版本: $(uname -r)"
    log_info "BusyBox版本: $(/bin/busybox --help 2>/dev/null | head -1 || echo '未知')"
    log_info "当前用户: $(whoami)"
    log_info "当前目录: $(pwd)"
    
    # 检查关键命令
    log_info "检查关键命令:"
    
    # 检查curl
    if curl --help >/dev/null 2>&1; then
        log_info "  curl: 可用"
    else
        log_warning "  curl: 未找到"
    fi
    
    # 检查wget
    if wget --help >/dev/null 2>&1; then
        log_info "  wget: 可用"
    else
        log_warning "  wget: 未找到"
    fi
    
    # 检查unzip
    if unzip 2>&1 | grep -q "Usage:"; then
        log_info "  unzip: 可用"
    else
        log_warning "  unzip: 未找到"
    fi
    
    # 检查tar
    if tar --help >/dev/null 2>&1; then
        log_info "  tar: 可用"
    else
        log_warning "  tar: 未找到"
    fi
    echo
}

# 主安装流程
main() {
    echo
    log_info "=========================================="
    log_info "VTO设备管理系统 - Padavan安装程序"
    log_info "适用于MIPS架构的Padavan固件"
    log_info "=========================================="
    echo
    
    # 显示环境信息
    show_environment_info
    
    # 执行安装步骤
    log_info "开始执行安装步骤..."
    echo
    
    # 步骤1: 检查/opt空间
    check_opt_space
    echo
    
    # 步骤2: 创建临时目录
    create_temp_dir
    echo
    
    # 步骤3: 下载安装包
    download_package
    echo
    
    # 步骤4: 解压安装包
    extract_package
    echo
    
    # 步骤5: 安装opkg
    install_opkg
    echo
    
    # 步骤6: 安装系统依赖包
    install_system_packages
    echo
    
    # 步骤7: 设置Python环境
    install_python_environment
    echo
    
    # 步骤8: 部署VTO应用
    deploy_vto_application
    echo
    
    # 步骤9: 创建系统服务
    create_system_service
    echo
    
    # 步骤10: 启动应用
    start_vto_application
    echo
    
    # 步骤11: 清理临时文件
    cleanup_temp_files
    echo
    
    # 显示完成信息
    show_completion_info
    
    log_success "VTO设备管理系统安装流程全部完成！"
}

# 脚本入口点
main "$@"
