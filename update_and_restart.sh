#!/bin/bash

# 更新并重启VTO Web应用脚本
# 功能：从远程服务器下载最新代码，解压，杀死旧进程，重新启动应用

# 设置变量
DOWNLOAD_URL="https://oss-hk.hozoy.cn/vto-flask/release.zip"
BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
CURRENT_DIR=$(pwd)
VENV_PATH="$CURRENT_DIR/venv"
APP_FILE="app.py"
LOG_FILE="logs/update_restart.log"
PID_FILE="app.pid"

# 创建日志目录
mkdir -p logs

# 日志记录函数
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 错误处理函数
error_exit() {
    log_message "错误: $1"
    exit 1
}

# 检查依赖
check_dependencies() {
    log_message "检查依赖..."
    
    # 检查wget
    # if ! command -v wget >/dev/null 2>&1; then
    #     error_exit "wget 未安装，请先安装 wget"
    # fi
    
    # # 检查unzip
    # if ! command -v unzip >/dev/null 2>&1; then
    #     error_exit "unzip 未安装，请先安装 unzip"
    # fi
    
    # # 检查虚拟环境目录
    # if [ ! -d "$VENV_PATH" ]; then
    #     error_exit "虚拟环境目录 $VENV_PATH 不存在"
    # fi
    
    log_message "依赖检查通过"
}

# 备份当前版本
backup_current_version() {
    log_message "创建备份..."
    
    # 创建备份目录
    mkdir -p "$BACKUP_DIR"
    
    # 备份重要文件和目录
    cp -r templates "$BACKUP_DIR/" 2>/dev/null || true
    cp -r static "$BACKUP_DIR/" 2>/dev/null || true
    cp -r instance "$BACKUP_DIR/" 2>/dev/null || true
    cp app.py "$BACKUP_DIR/" 2>/dev/null || true
    cp requirements.txt "$BACKUP_DIR/" 2>/dev/null || true
    cp *.py "$BACKUP_DIR/" 2>/dev/null || true
    
    log_message "备份完成，备份目录: $BACKUP_DIR"
}

# 下载最新版本
download_latest_version() {
    log_message "开始下载最新版本..."

    # 删除旧的下载文件
    rm -f release.zip

    # 下载最新版本（不要用 tee 分流，可能导致文件写入失败）
    if wget "$DOWNLOAD_URL" -O release.zip; then
        log_message "下载完成"
    else
        error_exit "下载失败，请检查网络连接或URL是否正确"
    fi

    # 验证下载的文件
    if [ ! -f "release.zip" ] || [ ! -s "release.zip" ]; then
        error_exit "下载的文件不存在或为空"
    fi

    log_message "下载验证通过"
}

# 解压新版本
extract_new_version() {
    log_message "解压新版本..."
    
    # 解压到临时目录
    rm -rf temp_extract
    mkdir -p temp_extract
    
    if unzip -q release.zip -d temp_extract; then
        log_message "解压完成"
    else
        error_exit "解压失败，文件可能损坏"
    fi
    
    # 复制解压后的文件（第一层直接是源代码文件）
    cp -r temp_extract/* . 2>/dev/null || true
    
    # 清理临时文件
    rm -rf temp_extract release.zip
    
    log_message "文件更新完成"
}

# 查找并杀死旧进程
kill_old_process() {
    log_message "查找并杀死旧进程..."
    
    # 查找Python进程运行app.py（兼容BusyBox）
    PIDS=$(ps | grep "python" | grep "app.py" | grep -v grep | awk '{print $1}')
    
    if [ -z "$PIDS" ]; then
        log_message "未找到运行中的应用进程"
        return 0
    fi
    
    # 逐个杀死进程
    for PID in $PIDS; do
        log_message "发现进程 PID: $PID"
        if kill -TERM "$PID" 2>/dev/null; then
            log_message "向进程 $PID 发送 TERM 信号"
            
            # 等待进程结束
            count=0
            while kill -0 "$PID" 2>/dev/null && [ $count -lt 10 ]; do
                sleep 1
                count=$((count + 1))
            done
            
            # 如果进程仍在运行，强制杀死
            if kill -0 "$PID" 2>/dev/null; then
                log_message "进程 $PID 未响应 TERM 信号，使用 KILL 信号强制终止"
                kill -KILL "$PID" 2>/dev/null
            fi
            
            log_message "进程 $PID 已终止"
        else
            log_message "无法终止进程 $PID"
        fi
    done
    
    # 额外检查端口占用（兼容BusyBox）
    if command -v lsof >/dev/null 2>&1; then
        PORT_PID=$(lsof -ti:8998 2>/dev/null || true)
        if [ -n "$PORT_PID" ]; then
            log_message "端口 8998 仍被进程 $PORT_PID 占用，强制终止"
            kill -KILL "$PORT_PID" 2>/dev/null || true
        fi
    else
        # 使用netstat作为替代方案
        if command -v netstat >/dev/null 2>&1; then
            PORT_PID=$(netstat -tlnp 2>/dev/null | grep ":8998 " | awk '{print $7}' | cut -d'/' -f1 | head -1)
            if [ -n "$PORT_PID" ] && [ "$PORT_PID" != "-" ]; then
                log_message "端口 8998 仍被进程 $PORT_PID 占用，强制终止"
                kill -KILL "$PORT_PID" 2>/dev/null || true
            fi
        else
            log_message "无法检查端口占用（lsof和netstat都不可用）"
        fi
    fi
    
    log_message "进程清理完成"
}

# 安装/更新依赖
install_dependencies() {
    log_message "检查并安装依赖..."
    
    # 激活虚拟环境
    source "$VENV_PATH/bin/activate"
    
    # 检查requirements.txt是否存在
    if [ -f "requirements.txt" ]; then
        log_message "更新Python依赖..."
        pip install -r requirements.txt 2>&1 | tee -a "$LOG_FILE"
        log_message "依赖更新完成"
    else
        log_message "未找到requirements.txt，跳过依赖更新"
    fi
}

# 启动新应用
start_new_application() {
    log_message "启动新应用..."
    
    # 激活虚拟环境
    source "$VENV_PATH/bin/activate"
    
    # 检查应用文件是否存在
    if [ ! -f "$APP_FILE" ]; then
        error_exit "应用文件 $APP_FILE 不存在"
    fi
    
    # 使用nohup启动应用
    nohup python "$APP_FILE" > logs/app.log 2>&1 &
    
    # 获取新进程PID
    NEW_PID=$!
    echo $NEW_PID > "$PID_FILE"
    
    log_message "应用已启动，PID: $NEW_PID"
    
    # 等待应用启动
    log_message "等待应用启动..."
    sleep 5
    
    # 检查应用是否正常启动
    if kill -0 $NEW_PID 2>/dev/null; then
        log_message "应用启动成功"
        log_message "应用访问地址: http://localhost:8998"
    else
        error_exit "应用启动失败，请检查日志文件 logs/app.log"
    fi
}

# 清理旧备份
cleanup_old_backups() {
    log_message "清理旧备份..."
    
    # 保留最近5个备份
    BACKUP_COUNT=$(ls -1d backup_* 2>/dev/null | wc -l)
    if [ $BACKUP_COUNT -gt 5 ]; then
        ls -1td backup_* 2>/dev/null | tail -n +6 | xargs rm -rf
        log_message "已清理旧备份，保留最近5个备份"
    fi
}

# 主函数
main() {
    log_message "开始执行更新重启脚本..."
    log_message "工作目录: $CURRENT_DIR"
    
    # 检查依赖
    check_dependencies
    
    # 备份当前版本
    backup_current_version
    
    # 下载最新版本
    download_latest_version
    
    # 解压新版本
    extract_new_version
    
    # 杀死旧进程
    kill_old_process
    
    # 安装/更新依赖
    install_dependencies
    
    # 启动新应用
    start_new_application
    
    # 清理旧备份
    cleanup_old_backups
    
    log_message "更新重启完成！"
    log_message "备份目录: $BACKUP_DIR"
    log_message "应用访问地址: http://localhost:8998"
    log_message "日志文件: logs/app.log"
    log_message "如果应用有问题，可以使用备份目录恢复"
}

# 脚本入口
main "$@" 