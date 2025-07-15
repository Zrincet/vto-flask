#!/bin/bash

# VTO Web应用重启脚本
# 功能：杀死旧进程并重新启动应用

# 设置变量
CURRENT_DIR=$(pwd)
VENV_PATH="$CURRENT_DIR/venv"
APP_FILE="app.py"
LOG_FILE="logs/restart.log"
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

    # 检查应用文件是否存在
    if [ ! -f "$APP_FILE" ]; then
        error_exit "应用文件 $APP_FILE 不存在"
    fi

    # 检查虚拟环境目录
    if [ ! -d "$VENV_PATH" ]; then
        log_message "警告: 虚拟环境目录 $VENV_PATH 不存在，将使用系统Python"
    fi

    log_message "依赖检查完成"
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

# 启动应用
start_application() {
    log_message "启动应用..."

    # 如果虚拟环境存在，则激活它
    if [ -d "$VENV_PATH" ]; then
        log_message "激活虚拟环境: $VENV_PATH"
        source "$VENV_PATH/bin/activate"
    else
        log_message "使用系统Python环境"
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
        log_message "应用日志: logs/app.log"
    else
        error_exit "应用启动失败，请检查日志文件 logs/app.log"
    fi
}

# 显示应用状态
show_status() {
    log_message "检查应用状态..."

    # 检查PID文件
    if [ -f "$PID_FILE" ]; then
        SAVED_PID=$(cat "$PID_FILE")
        if kill -0 "$SAVED_PID" 2>/dev/null; then
            log_message "应用正在运行，PID: $SAVED_PID"
        else
            log_message "PID文件存在但进程未运行，PID: $SAVED_PID"
        fi
    else
        log_message "PID文件不存在"
    fi

    # 检查端口占用
    if command -v lsof >/dev/null 2>&1; then
        PORT_STATUS=$(lsof -ti:8998 2>/dev/null || echo "未占用")
        log_message "端口8998状态: $PORT_STATUS"
    fi

    # 检查进程
    RUNNING_PIDS=$(ps | grep "python" | grep "app.py" | grep -v grep | awk '{print $1}' || echo "")
    if [ -n "$RUNNING_PIDS" ]; then
        log_message "发现运行中的应用进程: $RUNNING_PIDS"
    else
        log_message "未发现运行中的应用进程"
    fi
}

# 主函数
main() {
    case "$1" in
        status)
            log_message "检查应用状态..."
            show_status
            ;;
        stop)
            log_message "停止应用..."
            kill_old_process
            log_message "应用已停止"
            ;;
        start)
            log_message "启动应用..."
            check_dependencies
            start_application
            log_message "应用启动完成"
            ;;
        restart|"")
            log_message "重启应用..."
            log_message "工作目录: $CURRENT_DIR"
            check_dependencies
            kill_old_process
            start_application
            log_message "应用重启完成"
            ;;
        *)
            echo "用法: $0 {start|stop|restart|status}"
            echo "  start   - 启动应用"
            echo "  stop    - 停止应用"
            echo "  restart - 重启应用（默认）"
            echo "  status  - 检查应用状态"
            exit 1
            ;;
    esac
}

# 脚本入口
main "$@"
