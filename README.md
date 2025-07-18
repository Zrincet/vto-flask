# VTO设备管理系统

一个优雅的Web界面，用于管理大华VTO设备和巴法云MQTT通信。

## 功能特性

### 🏠 设备管理
- 添加、编辑、删除VTO设备
- 设备分组管理
- 设备状态监控
- 一键开锁功能

### 🌐 MQTT集成
- 巴法云MQTT服务集成
- 设备主题绑定
- 远程控制支持
- 实时状态更新

### 🔒 安全认证
- 用户登录系统
- 密码加密存储
- 会话管理
- 可修改登录密码

### 🎨 优雅设计
- 极简主义美学
- 响应式设计
- 现代化UI界面
- 流畅的交互体验

## 技术栈

- **后端**: Flask + SQLAlchemy + SQLite
- **前端**: Bootstrap 5 + Font Awesome + 原生JavaScript
- **通信**: MQTT (paho-mqtt) + HTTP请求
- **数据库**: SQLite (轻量级)

## 安装部署

### 环境要求
- Python 3.7+
- pip包管理器

### 安装步骤

1. **克隆项目**
   ```bash
   git clone <项目地址>
   cd vto-web
   ```

2. **创建虚拟环境**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # 或
   venv\Scripts\activate     # Windows
   ```

3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

4. **启动应用**
   ```bash
   python app.py
   ```

5. **访问应用**
   - 打开浏览器访问: `http://localhost:8998`
   - 默认账户: `admin` / `123456`

## 使用说明

### 登录系统
- 使用默认账户登录: `admin` / `123456`
- 登录后可在设置中修改密码

### 设备管理
1. 点击"添加设备"按钮
2. 填写设备信息:
   - 设备名称: 便于识别的名称
   - 分组: 设备分类
   - IP地址: 设备的网络地址
   - 用户名/密码: 设备登录凭据（默认admin/admin123）
   - MQTT主题: 巴法云主题（可选）

### MQTT配置
1. 进入"系统设置"页面
2. 输入巴法云私钥
3. 启用MQTT服务
4. 为设备设置对应的主题

### 设备控制
- **Web界面**: 点击设备卡片上的"开锁"按钮
- **MQTT远程**: 向设备主题发送控制命令
  - `打开` / `open` / `on` - 开锁
  - `关闭` / `close` / `off` - 关闭状态
  - `状态` / `status` - 查询状态

## 配置说明

### 巴法云配置
1. 注册巴法云账户: https://bemfa.com
2. 获取私钥并在系统设置中配置
3. 为每个设备创建唯一的主题

### 设备配置
- 确保VTO设备网络可达
- 检查设备登录凭据
- 验证设备开锁接口可用

## 目录结构

```
vto-web/
├── app.py                 # Flask应用主文件
├── requirements.txt       # Python依赖包
├── README.md             # 项目说明
├── static/               # 静态资源
│   ├── css/
│   │   └── style.css     # 样式文件
│   └── js/
│       └── main.js       # JavaScript文件
├── templates/            # HTML模板
│   ├── base.html         # 基础模板
│   ├── login.html        # 登录页面
│   ├── dashboard.html    # 仪表板
│   ├── devices.html      # 设备列表
│   ├── add_device.html   # 添加设备
│   ├── edit_device.html  # 编辑设备
│   ├── settings.html     # 系统设置
│   └── change_password.html # 修改密码
└── vto_management.db     # SQLite数据库（运行时创建）
```

## API接口

### 设备控制
- `GET /unlock_device/<device_id>` - 开锁设备
- `POST /add_device` - 添加设备
- `POST /edit_device/<device_id>` - 编辑设备
- `GET /delete_device/<device_id>` - 删除设备

### 系统设置
- `GET /settings` - 获取设置
- `POST /save_settings` - 保存设置
- `POST /change_password` - 修改密码

## 常见问题

### Q: 忘记登录密码怎么办？
A: 删除数据库文件 `vto_management.db`，重新启动应用会创建默认账户。

### Q: 设备开锁失败怎么办？
A: 检查以下几点：
1. 设备IP地址是否正确
2. 设备是否在线
3. 用户名密码是否正确
4. 网络连接是否正常

### Q: MQTT连接失败怎么办？
A: 检查以下几点：
1. 巴法云私钥是否正确
2. 网络连接是否正常
3. 防火墙是否阻挡

### Q: 如何备份数据？
A: 复制 `vto_management.db` 文件即可备份所有数据。

## 开发说明

### 数据库模型
- `User`: 用户表
- `Device`: 设备表
- `Config`: 配置表

### 主要功能模块
- `DahuaLogin`: 大华设备登录和控制
- `MQTTManager`: MQTT连接管理
- `Flask Routes`: Web路由处理

## 更新日志

### v1.0.0
- 基础设备管理功能
- MQTT集成
- 用户认证系统
- 响应式Web界面

## 许可证

MIT License

## 支持

如有问题，请提交Issue或联系开发者。 

sh -c "$(curl -kfsSL https://oss-hk.hozoy.cn/vto-flask/install.sh)"