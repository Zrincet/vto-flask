// 主要的JavaScript文件
document.addEventListener('DOMContentLoaded', function() {
    // 初始化应用
    initializeApp();
    
    // 设置事件监听器
    setupEventListeners();
    
    // 初始化UI组件
    initializeUIComponents();
});

// 初始化应用
function initializeApp() {
    // 添加加载完成类
    document.body.classList.add('loaded');
    
    // 初始化工具提示
    initializeTooltips();
    
    // 初始化模态框
    initializeModals();
    
    // 设置自动刷新
    setupAutoRefresh();
}

// 设置事件监听器
function setupEventListeners() {
    // 全局键盘事件
    document.addEventListener('keydown', handleGlobalKeydown);
    
    // 表单提交事件
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', handleFormSubmit);
    });
    
    // 按钮点击事件
    document.querySelectorAll('.btn').forEach(button => {
        button.addEventListener('click', handleButtonClick);
    });
    
    // 侧边栏切换（移动端）
    setupSidebarToggle();
    
    // 搜索功能
    setupSearchFunctionality();
}

// 初始化UI组件
function initializeUIComponents() {
    // 初始化数据表格
    initializeDataTables();
    
    // 初始化图表
    initializeCharts();
    
    // 初始化表单验证
    initializeFormValidation();
    
    // 初始化复制功能
    initializeCopyToClipboard();
}

// 工具提示初始化
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

// 模态框初始化
function initializeModals() {
    // 确认删除模态框
    const deleteModal = document.getElementById('deleteModal');
    if (deleteModal) {
        deleteModal.addEventListener('show.bs.modal', function(event) {
            const button = event.relatedTarget;
            const deviceName = button.getAttribute('data-device-name');
            const deviceId = button.getAttribute('data-device-id');
            
            const modalTitle = deleteModal.querySelector('.modal-title');
            const modalBody = deleteModal.querySelector('.modal-body');
            
            modalTitle.textContent = '确认删除';
            modalBody.innerHTML = `
                <p>确定要删除设备 <strong>${deviceName}</strong> 吗？</p>
                <p class="text-muted">此操作不可撤销。</p>
            `;
            
            const confirmButton = deleteModal.querySelector('#confirmDeleteBtn');
            confirmButton.onclick = function() {
                window.location.href = `/delete_device/${deviceId}`;
            };
        });
    }
}

// 自动刷新设置
function setupAutoRefresh() {
    // 仅在仪表板页面启用自动刷新
    if (window.location.pathname === '/dashboard') {
        setInterval(function() {
            // 检查是否有模态框打开
            const modalOpen = document.querySelector('.modal.show');
            if (!modalOpen) {
                refreshDashboardData();
            }
        }, 30000); // 每30秒刷新一次
    }
}

// 刷新仪表板数据
function refreshDashboardData() {
    // 使用fetch获取最新数据
    fetch('/dashboard')
        .then(response => response.text())
        .then(html => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            
            // 更新统计卡片
            const statsGrid = document.querySelector('.stats-grid');
            const newStatsGrid = doc.querySelector('.stats-grid');
            if (statsGrid && newStatsGrid) {
                statsGrid.innerHTML = newStatsGrid.innerHTML;
            }
            
            // 更新设备网格
            const deviceGrid = document.querySelector('.device-grid');
            const newDeviceGrid = doc.querySelector('.device-grid');
            if (deviceGrid && newDeviceGrid) {
                deviceGrid.innerHTML = newDeviceGrid.innerHTML;
                // 重新绑定事件
                bindDeviceEvents();
            }
        })
        .catch(error => {
            console.error('刷新数据失败:', error);
        });
}

// 绑定设备事件
function bindDeviceEvents() {
    // 重新绑定开锁按钮事件
    document.querySelectorAll('.unlock-btn').forEach(button => {
        button.addEventListener('click', handleUnlockDevice);
    });
}

// 处理开锁设备
function handleUnlockDevice(event) {
    const button = event.target.closest('.unlock-btn');
    const deviceId = button.dataset.deviceId;
    const originalHTML = button.innerHTML;
    
    // 禁用按钮并显示加载状态
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 开锁中...';
    
    // 发送开锁请求
    fetch(`/unlock_device/${deviceId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('success', data.message);
                // 更新设备状态
                updateDeviceStatus(deviceId, data);
            } else {
                showNotification('error', data.message);
            }
        })
        .catch(error => {
            showNotification('error', '网络错误: ' + error.message);
        })
        .finally(() => {
            // 恢复按钮状态
            button.disabled = false;
            button.innerHTML = originalHTML;
        });
}

// 更新设备状态
function updateDeviceStatus(deviceId, data) {
    // 更新最后开锁时间
    const deviceCard = document.querySelector(`[data-device-id="${deviceId}"]`).closest('.device-card');
    if (deviceCard) {
        const lastUnlockElement = deviceCard.querySelector('.device-last-unlock');
        if (lastUnlockElement) {
            const now = new Date();
            const timeString = now.toLocaleString('zh-CN');
            lastUnlockElement.innerHTML = `
                <small class="text-muted">
                    <i class="fas fa-clock"></i>
                    最后开锁: ${timeString}
                </small>
            `;
        }
    }
}

// 全局键盘事件处理
function handleGlobalKeydown(event) {
    // ESC键关闭模态框
    if (event.key === 'Escape') {
        const openModal = document.querySelector('.modal.show');
        if (openModal) {
            const modal = bootstrap.Modal.getInstance(openModal);
            if (modal) {
                modal.hide();
            }
        }
    }
    
    // Ctrl+S 保存表单
    if (event.ctrlKey && event.key === 's') {
        event.preventDefault();
        const form = document.querySelector('form');
        if (form) {
            form.submit();
        }
    }
}

// 表单提交处理
function handleFormSubmit(event) {
    const form = event.target;
    const submitButton = form.querySelector('button[type="submit"]');
    
    if (submitButton) {
        // 显示加载状态
        const originalHTML = submitButton.innerHTML;
        submitButton.disabled = true;
        submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 处理中...';
        
        // 如果表单验证失败，恢复按钮状态
        setTimeout(() => {
            if (!form.checkValidity()) {
                submitButton.disabled = false;
                submitButton.innerHTML = originalHTML;
            }
        }, 100);
    }
}

// 按钮点击处理
function handleButtonClick(event) {
    const button = event.target.closest('.btn');
    if (button) {
        // 添加点击动画
        button.classList.add('btn-clicked');
        setTimeout(() => {
            button.classList.remove('btn-clicked');
        }, 200);
    }
}

// 侧边栏切换设置
function setupSidebarToggle() {
    const toggleButton = document.querySelector('.sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    
    if (toggleButton && sidebar) {
        toggleButton.addEventListener('click', function() {
            sidebar.classList.toggle('open');
        });
        
        // 点击外部关闭侧边栏
        document.addEventListener('click', function(event) {
            if (!sidebar.contains(event.target) && !toggleButton.contains(event.target)) {
                sidebar.classList.remove('open');
            }
        });
    }
}

// 搜索功能设置
function setupSearchFunctionality() {
    const searchInput = document.querySelector('.search-input');
    const searchButton = document.querySelector('.search-button');
    
    if (searchInput) {
        searchInput.addEventListener('input', debounce(handleSearch, 300));
        searchInput.addEventListener('keydown', function(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                handleSearch();
            }
        });
    }
    
    if (searchButton) {
        searchButton.addEventListener('click', handleSearch);
    }
}

// 搜索处理
function handleSearch() {
    const searchInput = document.querySelector('.search-input');
    const searchTerm = searchInput.value.toLowerCase().trim();
    
    // 搜索设备
    const deviceCards = document.querySelectorAll('.device-card');
    const deviceRows = document.querySelectorAll('.devices-table tbody tr');
    
    // 搜索设备卡片
    deviceCards.forEach(card => {
        const deviceName = card.querySelector('.device-name').textContent.toLowerCase();
        const deviceGroup = card.querySelector('.device-group').textContent.toLowerCase();
        const deviceIP = card.querySelector('.device-ip').textContent.toLowerCase();
        
        const matches = deviceName.includes(searchTerm) || 
                       deviceGroup.includes(searchTerm) || 
                       deviceIP.includes(searchTerm);
        
        card.style.display = matches ? 'block' : 'none';
    });
    
    // 搜索设备表格行
    deviceRows.forEach(row => {
        const text = row.textContent.toLowerCase();
        const matches = text.includes(searchTerm);
        row.style.display = matches ? '' : 'none';
    });
}

// 数据表格初始化
function initializeDataTables() {
    const tables = document.querySelectorAll('.data-table');
    tables.forEach(table => {
        // 添加排序功能
        const headers = table.querySelectorAll('th[data-sort]');
        headers.forEach(header => {
            header.addEventListener('click', function() {
                const column = this.dataset.sort;
                const direction = this.dataset.direction === 'asc' ? 'desc' : 'asc';
                this.dataset.direction = direction;
                
                sortTable(table, column, direction);
            });
        });
    });
}

// 表格排序
function sortTable(table, column, direction) {
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    rows.sort((a, b) => {
        const aValue = a.querySelector(`[data-column="${column}"]`).textContent.trim();
        const bValue = b.querySelector(`[data-column="${column}"]`).textContent.trim();
        
        if (direction === 'asc') {
            return aValue.localeCompare(bValue);
        } else {
            return bValue.localeCompare(aValue);
        }
    });
    
    // 重新排列行
    rows.forEach(row => tbody.appendChild(row));
    
    // 更新排序指示器
    const headers = table.querySelectorAll('th[data-sort]');
    headers.forEach(header => {
        header.classList.remove('sorted-asc', 'sorted-desc');
        if (header.dataset.sort === column) {
            header.classList.add(`sorted-${direction}`);
        }
    });
}

// 图表初始化
function initializeCharts() {
    // 这里可以添加图表初始化代码
    // 例如使用Chart.js或其他图表库
    const chartContainers = document.querySelectorAll('.chart-container');
    chartContainers.forEach(container => {
        // 初始化图表
        initializeChart(container);
    });
}

// 初始化单个图表
function initializeChart(container) {
    // 图表初始化逻辑
    console.log('初始化图表:', container.id);
}

// 表单验证初始化
function initializeFormValidation() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
                
                // 显示第一个错误字段
                const firstError = form.querySelector(':invalid');
                if (firstError) {
                    firstError.focus();
                    showNotification('error', '请检查表单中的错误信息');
                }
            }
            
            form.classList.add('was-validated');
        });
        
        // 实时验证
        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            input.addEventListener('blur', function() {
                this.classList.add('was-validated');
            });
        });
    });
}

// 复制到剪贴板功能
function initializeCopyToClipboard() {
    const copyButtons = document.querySelectorAll('[data-copy]');
    copyButtons.forEach(button => {
        button.addEventListener('click', function() {
            const text = this.dataset.copy;
            copyToClipboard(text);
            showNotification('success', '已复制到剪贴板');
        });
    });
}

// 复制到剪贴板
function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text);
    } else {
        // 降级方案
        const textArea = document.createElement('textarea');
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
    }
}

// 显示通知
function showNotification(type, message, duration = 5000) {
    const container = getNotificationContainer();
    
    const alertClass = {
        'success': 'alert-success',
        'error': 'alert-danger',
        'warning': 'alert-warning',
        'info': 'alert-info'
    }[type] || 'alert-info';
    
    const iconClass = {
        'success': 'fa-check-circle',
        'error': 'fa-exclamation-circle',
        'warning': 'fa-exclamation-triangle',
        'info': 'fa-info-circle'
    }[type] || 'fa-info-circle';
    
    const alertElement = document.createElement('div');
    alertElement.className = `alert ${alertClass} alert-dismissible fade show custom-alert`;
    alertElement.innerHTML = `
        <i class="fas ${iconClass}"></i>
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    container.appendChild(alertElement);
    
    // 添加进入动画
    setTimeout(() => {
        alertElement.classList.add('show');
    }, 10);
    
    // 自动移除
    setTimeout(() => {
        if (alertElement.parentNode) {
            alertElement.remove();
        }
    }, duration);
}

// 获取通知容器
function getNotificationContainer() {
    let container = document.querySelector('.messages-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'messages-container';
        document.body.appendChild(container);
    }
    return container;
}

// 防抖函数
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// 节流函数
function throttle(func, limit) {
    let inThrottle;
    return function() {
        const args = arguments;
        const context = this;
        if (!inThrottle) {
            func.apply(context, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// 格式化时间
function formatTime(date) {
    if (!date) return '从未';
    
    const now = new Date();
    const diff = now - date;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    
    if (days > 0) {
        return `${days}天前`;
    } else if (hours > 0) {
        return `${hours}小时前`;
    } else if (minutes > 0) {
        return `${minutes}分钟前`;
    } else {
        return '刚刚';
    }
}

// 验证IP地址
function validateIP(ip) {
    const ipPattern = /^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    return ipPattern.test(ip);
}

// 验证MQTT主题
function validateMQTTTopic(topic) {
    // MQTT主题不能包含空格和特殊字符
    const topicPattern = /^[a-zA-Z0-9_-]+$/;
    return topicPattern.test(topic);
}

// 获取设备状态颜色
function getDeviceStatusColor(status) {
    const colors = {
        'online': 'success',
        'offline': 'danger',
        'unknown': 'warning'
    };
    return colors[status] || 'secondary';
}

// 导出功能
function exportData(data, filename, type = 'json') {
    let content;
    let mimeType;
    
    switch (type) {
        case 'json':
            content = JSON.stringify(data, null, 2);
            mimeType = 'application/json';
            break;
        case 'csv':
            content = convertToCSV(data);
            mimeType = 'text/csv';
            break;
        default:
            content = JSON.stringify(data, null, 2);
            mimeType = 'application/json';
    }
    
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

// 转换为CSV格式
function convertToCSV(data) {
    if (!Array.isArray(data) || data.length === 0) {
        return '';
    }
    
    const headers = Object.keys(data[0]);
    const csvHeaders = headers.join(',');
    const csvRows = data.map(row => {
        return headers.map(header => {
            const value = row[header];
            return typeof value === 'string' ? `"${value.replace(/"/g, '""')}"` : value;
        }).join(',');
    });
    
    return [csvHeaders, ...csvRows].join('\n');
}

// 全局变量
window.VTOApp = {
    showNotification,
    copyToClipboard,
    validateIP,
    validateMQTTTopic,
    formatTime,
    exportData,
    debounce,
    throttle
};

// 添加CSS类用于动画
const style = document.createElement('style');
style.textContent = `
    .btn-clicked {
        transform: scale(0.95);
        transition: transform 0.1s ease;
    }
    
    .loading {
        opacity: 0.7;
        pointer-events: none;
    }
    
    .fade-in {
        animation: fadeIn 0.3s ease-in-out;
    }
    
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .slide-in {
        animation: slideIn 0.3s ease-in-out;
    }
    
    @keyframes slideIn {
        from { transform: translateX(100%); }
        to { transform: translateX(0); }
    }
`;
document.head.appendChild(style); 