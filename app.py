from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import hashlib
import requests
import json
import paho.mqtt.client as mqtt
import threading
import time
from datetime import datetime
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vto_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 数据库模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    group_name = db.Column(db.String(100), nullable=False)
    section_number = db.Column(db.String(10), nullable=False)  # 区域编号
    building_number = db.Column(db.String(10), nullable=False)  # 楼栋编号
    position = db.Column(db.String(10), nullable=True)  # 位置编号
    ip = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), default='admin')
    password = db.Column(db.String(50), default='admin123')
    mqtt_topic = db.Column(db.String(100), nullable=True)  # 自动生成，不再手动设置
    visible = db.Column(db.Boolean, default=False)  # 可见属性
    status = db.Column(db.String(20), default='online')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_unlock_time = db.Column(db.DateTime, nullable=True)
    
    def generate_mqtt_topic(self):
        """自动生成MQTT主题：vto + IP去除点 + 006"""
        if self.ip:
            clean_ip = self.ip.replace('.', '')
            return f"vto{clean_ip}006"
        return None
    
    def generate_device_name(self, existing_names=None):
        """自动生成设备名称：区域区楼栋幢位置号"""
        if existing_names is None:
            existing_names = set()
        
        base_name = f"{self.section_number}区{self.building_number}幢"
        if self.position:
            base_name += f"{self.position}号"
        
        # 检查重复并添加后缀
        final_name = base_name
        counter = 1
        while final_name in existing_names:
            final_name = f"{base_name}-{counter}"
            counter += 1
        
        return final_name

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class BemfaKey(db.Model):
    """巴法云密钥模型"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # 密钥名称/描述
    key = db.Column(db.String(100), nullable=False)  # 巴法云私钥
    enabled = db.Column(db.Boolean, default=True)  # 是否启用
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 大华VTO开锁类
class DahuaLogin:
    def __init__(self, ip, username="admin", password="admin123", port=80):
        self.ip = ip
        self.username = username
        self.password = password
        self.port = port
        self.session = None
        self.login_url = f"http://{ip}:{port}/RPC2_Login"
        self.rpc_url = f"http://{ip}:{port}/RPC2"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.request_id = 1000

    def _get_challenge(self):
        login_info = {
            "method": "global.login",
            "params": {
                "userName": self.username,
                "password": "",
                "clientType": "GUI"
            },
            "id": self._get_next_id(),
            "session": 0
        }

        response = requests.post(
            self.login_url,
            headers=self.headers,
            data=json.dumps(login_info)
        )

        if response.status_code != 200:
            raise Exception(f"获取挑战信息失败，状态码：{response.status_code}")

        return response.json()

    def _calculate_password_hash(self, challenge_info):
        realm = challenge_info['params']['realm']
        random = challenge_info['params']['random']

        r_text = f"{self.username}:{realm}:{self.password}"
        r_md5 = hashlib.md5(r_text.encode("utf-8")).hexdigest().upper()

        s_text = f"{self.username}:{random}:{r_md5}"
        s_md5 = hashlib.md5(s_text.encode("utf-8")).hexdigest().upper()

        return s_md5, realm, random

    def login(self):
        challenge_info = self._get_challenge()
        self.session = challenge_info.get('session')

        if challenge_info.get('result'):
            return {
                "success": True,
                "session": self.session,
                "data": challenge_info
            }

        password_hash, realm, random = self._calculate_password_hash(challenge_info)

        login_info = {
            "method": "global.login",
            "params": {
                "userName": self.username,
                "password": password_hash,
                "clientType": "GUI",
                "realm": realm,
                "random": random,
                "passwordType": "Default",
                "authorityType": challenge_info['params']['encryption']
            },
            "id": self._get_next_id(),
            "session": self.session
        }

        response = requests.post(
            self.login_url,
            headers=self.headers,
            data=json.dumps(login_info)
        )

        if response.status_code != 200:
            raise Exception(f"登录失败，状态码：{response.status_code}")

        result = response.json()
        success = result.get('result', False)

        return {
            "success": success,
            "session": self.session,
            "data": result
        }

    def _get_next_id(self):
        self.request_id += 1
        return self.request_id

    def get_door_instance(self):
        request_data = {
            "id": self._get_next_id(),
            "method": "accessControl.factory.instance",
            "params": {
                "channel": 0
            },
            "session": self.session
        }

        response = requests.post(
            self.rpc_url,
            headers=self.headers,
            data=json.dumps(request_data)
        )

        if response.status_code != 200:
            raise Exception(f"获取门锁对象失败，状态码：{response.status_code}")

        result = response.json()
        if "result" not in result:
            raise Exception(f"获取门锁对象失败：{result.get('error', {}).get('message', '未知错误')}")

        return result["result"]

    def open_door(self, door_handle, door_index=0, short_number="04001013502", open_type="Remote"):
        request_data = {
            "id": self._get_next_id(),
            "method": "accessControl.openDoor",
            "object": door_handle,
            "params": {
                "DoorIndex": door_index,
                "ShortNumber": short_number,
                "Type": open_type
            },
            "session": self.session
        }

        response = requests.post(
            self.rpc_url,
            headers=self.headers,
            data=json.dumps(request_data)
        )

        if response.status_code != 200:
            raise Exception(f"开锁失败，状态码：{response.status_code}")

        result = response.json()
        return result.get("result", False)

    def destroy_door_instance(self, door_handle):
        request_data = {
            "id": self._get_next_id(),
            "method": "accessControl.destroy",
            "object": door_handle,
            "session": self.session
        }

        response = requests.post(
            self.rpc_url,
            headers=self.headers,
            data=json.dumps(request_data)
        )

        if response.status_code != 200:
            raise Exception(f"销毁门锁对象失败，状态码：{response.status_code}")

        result = response.json()
        return result.get("result", False)

    def logout(self):
        request_data = {
            "id": self._get_next_id(),
            "method": "global.logout",
            "session": self.session
        }

        response = requests.post(
            self.rpc_url,
            headers=self.headers,
            data=json.dumps(request_data)
        )

        if response.status_code != 200:
            raise Exception(f"注销失败，状态码：{response.status_code}")

        result = response.json()
        return result.get("result", False)

    def execute_door_open_flow(self, door_index=0, short_number="04001013502"):
        login_result = self.login()
        if not login_result["success"]:
            return {
                "success": False,
                "step": "login",
                "message": "登录失败",
                "data": login_result["data"]
            }

        try:
            door_handle = self.get_door_instance()
            open_result = self.open_door(door_handle, door_index, short_number)
            destroy_result = self.destroy_door_instance(door_handle)
            logout_result = self.logout()

            return {
                "success": open_result,
                "door_handle": door_handle,
                "open_result": open_result,
                "destroy_result": destroy_result,
                "logout_result": logout_result
            }

        except Exception as e:
            try:
                self.logout()
            except:
                pass

            return {
                "success": False,
                "message": str(e)
            }

# MQTT客户端管理
class MQTTClient:
    """单个MQTT客户端连接"""
    def __init__(self, client_id, mqtt_host="bemfa.com", mqtt_port=9501):
        self.client_id = client_id
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.client = None
        self.is_connected = False
        self.is_running = False
        self.subscribed_topics = set()
    
    def start(self):
        """启动MQTT客户端"""
        if self.is_running and self.is_connected:
            logger.info(f"MQTT客户端 {self.client_id} 已在运行中，跳过重复启动")
            return

        # 如果之前有连接，先清理
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except:
                pass
            self.client = None

        # 兼容不同版本的paho-mqtt
        try:
            # paho-mqtt 2.0+ 版本
            self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1, client_id=self.client_id)
        except AttributeError:
            # paho-mqtt 1.x 版本
            self.client = mqtt.Client(client_id=self.client_id)
        
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        try:
            self.client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.client.loop_start()
            self.is_running = True
            logger.info(f"MQTT客户端 {self.client_id} 已启动，连接到 {self.mqtt_host}:{self.mqtt_port}")
        except Exception as e:
            logger.error(f"启动MQTT客户端 {self.client_id} 失败: {str(e)}")
            raise

    def stop(self):
        """停止MQTT客户端"""
        if self.client and self.is_running:
            self.client.loop_stop()
            self.client.disconnect()
            self.is_running = False
            self.is_connected = False
            logger.info(f"MQTT客户端 {self.client_id} 已停止")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.is_connected = True
            logger.info(f"MQTT客户端 {self.client_id} 已连接到服务器")
            # 在Flask应用上下文中执行数据库查询
            with app.app_context():
                # 只订阅可见设备的主题
                devices = Device.query.filter(
                    Device.visible == True,
                    Device.mqtt_topic.isnot(None)
                ).all()
                for device in devices:
                    if device.mqtt_topic:
                        client.subscribe(device.mqtt_topic)
                        self.subscribed_topics.add(device.mqtt_topic)
                        logger.info(f"客户端 {self.client_id} 已订阅主题: {device.mqtt_topic}")
        else:
            logger.error(f"MQTT客户端 {self.client_id} 连接服务器失败，返回码: {rc}")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            logger.info(f"客户端 {self.client_id} 收到消息 - 主题: {topic}, 内容: {payload}")

            # 在Flask应用上下文中执行数据库操作
            with app.app_context():
                # 查找对应的设备
                device = Device.query.filter_by(mqtt_topic=topic).first()
                if not device:
                    logger.warning(f"未找到主题 {topic} 对应的设备")
                    return

                payload_lower = payload.lower()
                
                # 处理开锁命令
                if "打开" in payload or payload_lower in ["open", "on"]:
                    logger.info(f"收到设备 {device.name} 的开锁指令")
                    try:
                        dahua_client = DahuaLogin(
                            ip=device.ip,
                            username=device.username,
                            password=device.password
                        )
                        
                        result = dahua_client.execute_door_open_flow()
                        
                        if result["success"]:
                            device.last_unlock_time = datetime.utcnow()
                            db.session.commit()
                            logger.info(f"设备 {device.name} 开锁成功")
                            
                            # 开锁成功后，向所有启用的巴法云账号发送状态推送消息
                            try:
                                bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
                                
                                # 准备推送消息内容
                                status_msg = "off"  # 设备状态设为off
                                wechat_msg = f"设备 {device.name} 开锁成功，当前状态：关闭"
                                
                                # 向所有启用的巴法云账号发送状态推送
                                for bemfa_key in bemfa_keys:
                                    push_result = bemfa_api.send_status_message(
                                        uid=bemfa_key.key,
                                        topic=device.mqtt_topic,
                                        msg=status_msg,
                                        wemsg=wechat_msg
                                    )
                                    
                                    if push_result.get("code") == 0:
                                        logger.info(f"向巴法云账号 {bemfa_key.name} 发送状态推送成功")
                                    else:
                                        logger.error(f"向巴法云账号 {bemfa_key.name} 发送状态推送失败: {push_result.get('message', '未知错误')}")
                                        
                            except Exception as push_error:
                                logger.error(f"发送状态推送消息时出错: {str(push_error)}")
                        else:
                            logger.error(f"设备 {device.name} 开锁失败: {result.get('message', '未知错误')}")
                            
                    except Exception as e:
                        logger.error(f"处理设备 {device.name} 开锁请求时出错: {str(e)}")

        except Exception as e:
            logger.error(f"处理MQTT消息时出错: {str(e)}")

    def on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        logger.info(f"MQTT客户端 {self.client_id} 已断开连接")

    def subscribe_device_topic(self, topic):
        if self.client and self.is_connected and topic not in self.subscribed_topics:
            self.client.subscribe(topic)
            self.subscribed_topics.add(topic)
            logger.info(f"客户端 {self.client_id} 已订阅新主题: {topic}")

    def unsubscribe_device_topic(self, topic):
        if self.client and self.is_connected and topic in self.subscribed_topics:
            self.client.unsubscribe(topic)
            self.subscribed_topics.remove(topic)
            logger.info(f"客户端 {self.client_id} 已取消订阅主题: {topic}")

class MQTTManager:
    """支持多个巴法云账号的MQTT管理器"""
    def __init__(self):
        self.clients = {}  # {client_id: MQTTClient}
        self.is_running = False

    def start_mqtt_service(self, mqtt_host="bemfa.com", mqtt_port=9501, client_id=None):
        """启动单个MQTT客户端（向后兼容）"""
        if client_id:
            self.start_client(client_id, mqtt_host, mqtt_port)
        else:
            self.start_all_clients()

    def start_all_clients(self):
        """启动所有启用的巴法云密钥对应的MQTT客户端"""
        with app.app_context():
            bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
            
            if not bemfa_keys:
                logger.info("没有启用的巴法云密钥，跳过MQTT连接")
                return
            
            for bemfa_key in bemfa_keys:
                self.start_client(bemfa_key.key)
        
        self.is_running = True

    def start_client(self, client_id, mqtt_host="bemfa.com", mqtt_port=9501):
        """启动指定的MQTT客户端"""
        if client_id in self.clients:
            logger.info(f"MQTT客户端 {client_id} 已存在，停止旧连接")
            self.clients[client_id].stop()
        
        client = MQTTClient(client_id, mqtt_host, mqtt_port)
        self.clients[client_id] = client
        
        try:
            client.start()
            logger.info(f"MQTT客户端 {client_id} 启动成功")
        except Exception as e:
            logger.error(f"启动MQTT客户端 {client_id} 失败: {str(e)}")
            # 移除失败的客户端
            if client_id in self.clients:
                del self.clients[client_id]

    def stop_mqtt_service(self):
        """停止所有MQTT客户端"""
        for client_id, client in self.clients.items():
            client.stop()
        self.clients.clear()
        self.is_running = False
        logger.info("所有MQTT客户端已停止")

    def stop_client(self, client_id):
        """停止指定的MQTT客户端"""
        if client_id in self.clients:
            self.clients[client_id].stop()
            del self.clients[client_id]
            logger.info(f"MQTT客户端 {client_id} 已停止")

    @property
    def is_connected(self):
        """检查是否有任何客户端连接"""
        return any(client.is_connected for client in self.clients.values())

    def get_connection_status(self):
        """获取所有客户端的连接状态"""
        status = {}
        for client_id, client in self.clients.items():
            status[client_id] = {
                'connected': client.is_connected,
                'running': client.is_running,
                'subscribed_topics': len(client.subscribed_topics)
            }
        return status

    def subscribe_device_topic(self, topic):
        """在所有客户端上订阅设备主题"""
        if not topic:
            return
        
        for client_id, client in self.clients.items():
            try:
                client.subscribe_device_topic(topic)
            except Exception as e:
                logger.error(f"客户端 {client_id} 订阅主题 {topic} 失败: {str(e)}")

    def unsubscribe_device_topic(self, topic):
        """在所有客户端上取消订阅设备主题"""
        if not topic:
            return
        
        for client_id, client in self.clients.items():
            try:
                client.unsubscribe_device_topic(topic)
            except Exception as e:
                logger.error(f"客户端 {client_id} 取消订阅主题 {topic} 失败: {str(e)}")

# 巴法云API管理类
class BemfaAPI:
    def __init__(self):
        self.base_url = "https://apis.bemfa.com"
        self.pro_url = "https://pro.bemfa.com"
    
    def get_all_topics(self, uid):
        """获取所有主题信息"""
        try:
            url = f"{self.base_url}/va/alltopic"
            params = {
                "uid": uid,
                "type": 1  # MQTT协议
            }
            response = requests.get(url, params=params)
            return response.json()
        except Exception as e:
            logger.error(f"获取巴法云主题失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def create_topic(self, uid, topic, name=None, type=1):
        """创建单个主题"""
        try:
            url = "https://pro.bemfa.com/v1/createTopic"
            data = {
                "uid": uid,
                "topic": topic,
                "type": type  # 1=MQTT协议设备, 3=TCP协议设备, 5=MQTT协议设备V2版本, 7=TCP协议设备V2版本
            }
            
            # 如果提供了昵称，在创建时就设置
            if name:
                data["name"] = name
            
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=data, headers=headers)
            return response.json()
        except Exception as e:
            logger.error(f"创建巴法云主题失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def create_topics(self, uid, topics):
        """创建多个主题（批量创建方法，保留向后兼容）"""
        try:
            url = f"{self.pro_url}/vs/web/v1/addTopics"
            data = {
                "openID": uid,
                "type": 1,  # MQTT协议
                "topics": topics,
                "group": "VTO设备",
                "adminID": 0
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=data, headers=headers)
            return response.json()
        except Exception as e:
            logger.error(f"创建巴法云主题失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def modify_topic_name(self, uid, topic, name):
        """修改主题昵称"""
        try:
            url = f"{self.base_url}/va/modifyName"
            data = {
                "uid": uid,
                "topic": topic,
                "type": 1,  # MQTT协议
                "name": name
            }
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response = requests.post(url, json=data, headers=headers)
            return response.json()
        except Exception as e:
            logger.error(f"修改巴法云主题名称失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def send_status_message(self, uid, topic, msg, wemsg=None):
        """发送状态推送消息"""
        try:
            url = f"{self.base_url}/va/postJsonMsg"
            data = {
                "uid": uid,
                "topic": topic,
                "type": 1,  # MQTT协议
                "msg": msg
            }
            
            # 如果有微信消息，添加到请求中
            if wemsg:
                data["wemsg"] = wemsg
                
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response = requests.post(url, json=data, headers=headers)
            return response.json()
        except Exception as e:
            logger.error(f"发送巴法云状态消息失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def delete_topic(self, uid, topic, type=1):
        """删除主题"""
        try:
            url = f"{self.pro_url}/v1/deleteTopic"
            data = {
                "uid": uid,
                "topic": topic,
                "type": type  # 1=MQTT协议设备, 3=TCP协议设备, 5=MQTT协议设备V2版本, 7=TCP协议设备V2版本
            }
            
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response = requests.post(url, json=data, headers=headers)
            return response.json()
        except Exception as e:
            logger.error(f"删除巴法云主题失败: {str(e)}")
            return {"code": -1, "message": str(e)}

# 全局巴法云API管理器
bemfa_api = BemfaAPI()

# 全局MQTT管理器
mqtt_manager = MQTTManager()

# 认证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 路由定义

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('登录成功', 'success')
            return redirect(url_for('visible_devices'))
        else:
            flash('用户名或密码错误', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('visible_devices'))

@app.route('/dashboard')
@login_required
def dashboard():
    # 只显示可见设备
    devices = Device.query.filter_by(visible=True).all()
    device_count = len(devices)
    online_count = len([d for d in devices if d.status == 'online'])
    
    # 获取MQTT服务状态
    mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
    mqtt_enabled = mqtt_config.value == 'true' if mqtt_config else False
    
    return render_template('dashboard.html', 
                         devices=devices,
                         device_count=device_count,
                         online_count=online_count,
                         mqtt_enabled=mqtt_enabled,
                         mqtt_connected=mqtt_manager.is_connected)

@app.route('/visible_devices')
@login_required
def visible_devices():
    """可见设备列表页面（新的主页）"""
    devices = Device.query.filter_by(visible=True).all()
    device_count = len(devices)
    online_count = len([d for d in devices if d.status == 'online'])
    
    # 获取MQTT服务状态
    mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
    mqtt_enabled = mqtt_config.value == 'true' if mqtt_config else False
    
    return render_template('visible_devices.html', 
                         devices=devices,
                         device_count=device_count,
                         online_count=online_count,
                         mqtt_enabled=mqtt_enabled,
                         mqtt_connected=mqtt_manager.is_connected)

@app.route('/devices')
@login_required
def devices():
    """所有设备管理页面"""
    devices = Device.query.all()
    return render_template('devices.html', devices=devices)

@app.route('/manage_visible_devices')
@login_required
def manage_visible_devices():
    """可见设备管理页面"""
    # 获取所有设备，按区域和楼栋分组
    all_devices = Device.query.order_by(Device.section_number, Device.building_number, Device.position).all()
    visible_devices = Device.query.filter_by(visible=True).all()
    visible_device_ids = {d.id for d in visible_devices}
    
    # 按区域分组
    sections = {}
    for device in all_devices:
        section = device.section_number
        if section not in sections:
            sections[section] = {}
        
        building = device.building_number
        if building not in sections[section]:
            sections[section][building] = []
        
        sections[section][building].append(device)
    
    return render_template('manage_visible_devices.html', 
                         sections=sections, 
                         visible_device_ids=visible_device_ids)

@app.route('/update_visible_devices', methods=['POST'])
@login_required
def update_visible_devices():
    """更新可见设备"""
    try:
        selected_device_ids = request.json.get('device_ids', [])
        
        # 重置所有设备的可见性
        Device.query.update({Device.visible: False})
        
        # 设置选中设备为可见
        if selected_device_ids:
            Device.query.filter(Device.id.in_(selected_device_ids)).update(
                {Device.visible: True}, synchronize_session=False
            )
        
        db.session.commit()
        
        # 同步到巴法云
        sync_visible_devices_to_bemfa()
        
        # 重新连接MQTT服务以更新订阅的主题
        if mqtt_manager.is_running:
            logger.info("可见设备更新，重新连接MQTT服务...")
            try:
                # 检查是否有启用的巴法云密钥
                enabled_keys = BemfaKey.query.filter_by(enabled=True).all()
                
                if enabled_keys:
                    # 停止当前所有连接
                    mqtt_manager.stop_mqtt_service()
                    # 重新启动所有启用的客户端连接
                    mqtt_manager.start_all_clients()
                    logger.info("MQTT服务重新连接成功")
                else:
                    # 如果没有启用的密钥，检查是否有旧的配置作为回退
                    bemfa_key_config = Config.query.filter_by(key='bemfa_private_key').first()
                    if bemfa_key_config and bemfa_key_config.value:
                        # 停止当前连接
                        mqtt_manager.stop_mqtt_service()
                        # 使用旧配置重新启动连接
                        mqtt_manager.start_mqtt_service("bemfa.com", 9501, bemfa_key_config.value)
                        logger.info("MQTT服务使用旧配置重新连接成功")
                    else:
                        logger.warning("没有可用的巴法云密钥配置，无法重新连接MQTT服务")
            except Exception as mqtt_error:
                logger.error(f"重新连接MQTT服务失败: {str(mqtt_error)}")
        
        return jsonify({"success": True, "message": "可见设备更新成功，MQTT订阅已刷新"})
    except Exception as e:
        db.session.rollback()
        logger.error(f"更新可见设备失败: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/add_device', methods=['GET', 'POST'])
@login_required
def add_device():
    if request.method == 'POST':
        name = request.form['name']
        group_name = request.form['group_name']
        section_number = request.form['section_number']
        building_number = request.form['building_number']
        position = request.form.get('position', '') or None
        ip = request.form['ip']
        username = request.form.get('username', 'admin')
        password = request.form.get('password', 'admin123')
        
        # 检查IP是否已存在
        existing_device = Device.query.filter_by(ip=ip).first()
        if existing_device:
            flash('该IP地址的设备已存在', 'error')
            return render_template('add_device.html')
        
        # 创建设备并自动生成MQTT主题
        device = Device(
            name=name,
            group_name=group_name,
            section_number=section_number,
            building_number=building_number,
            position=position,
            ip=ip,
            username=username,
            password=password
        )
        
        # 自动生成MQTT主题
        device.mqtt_topic = device.generate_mqtt_topic()
        
        db.session.add(device)
        db.session.commit()
        
        # 如果MQTT服务正在运行且设备有主题，则订阅
        if device.mqtt_topic and mqtt_manager.is_running:
            mqtt_manager.subscribe_device_topic(device.mqtt_topic)
        
        flash('设备添加成功', 'success')
        return redirect(url_for('devices'))
    
    return render_template('add_device.html')

@app.route('/edit_device/<int:device_id>', methods=['GET', 'POST'])
@login_required
def edit_device(device_id):
    device = Device.query.get_or_404(device_id)
    return_to = request.args.get('return_to', 'devices')
    
    if request.method == 'POST':
        old_topic = device.mqtt_topic
        old_ip = device.ip
        
        device.name = request.form['name']
        device.group_name = request.form['group_name']
        device.section_number = request.form['section_number']
        device.building_number = request.form['building_number']
        device.position = request.form.get('position', '') or None
        device.ip = request.form['ip']
        device.username = request.form.get('username', 'admin')
        device.password = request.form.get('password', 'admin123')
        
        # 如果IP地址改变，重新生成MQTT主题
        if device.ip != old_ip:
            device.mqtt_topic = device.generate_mqtt_topic()
        
        # 更新MQTT订阅
        if mqtt_manager.is_running:
            if old_topic and old_topic != device.mqtt_topic:
                mqtt_manager.unsubscribe_device_topic(old_topic)
            if device.mqtt_topic:
                mqtt_manager.subscribe_device_topic(device.mqtt_topic)
        
        db.session.commit()
        
        # 如果设备可见，同步到巴法云
        if device.visible:
            sync_visible_devices_to_bemfa()
        
        flash('设备信息更新成功', 'success')
        
        # 根据返回参数决定跳转位置
        if return_to == 'visible_devices':
            return redirect(url_for('visible_devices'))
        elif return_to == 'dashboard':
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('devices'))
    
    return render_template('edit_device.html', device=device, return_to=return_to)

@app.route('/delete_device/<int:device_id>')
@login_required
def delete_device(device_id):
    device = Device.query.get_or_404(device_id)
    
    # 如果设备有MQTT主题，取消订阅
    if device.mqtt_topic and mqtt_manager.is_running:
        mqtt_manager.unsubscribe_device_topic(device.mqtt_topic)
    
    db.session.delete(device)
    db.session.commit()
    flash('设备删除成功', 'success')
    return redirect(url_for('devices'))

@app.route('/unlock_device/<int:device_id>')
@login_required
def unlock_device(device_id):
    device = Device.query.get_or_404(device_id)
    
    try:
        dahua_client = DahuaLogin(
            ip=device.ip,
            username=device.username,
            password=device.password
        )
        
        result = dahua_client.execute_door_open_flow()
        
        if result["success"]:
            device.last_unlock_time = datetime.utcnow()
            db.session.commit()
            return jsonify({"success": True, "message": "开锁成功"})
        else:
            return jsonify({"success": False, "message": result.get('message', '开锁失败')})
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/settings')
@login_required
def settings():
    # 获取配置信息
    mqtt_enabled = Config.query.filter_by(key='mqtt_enabled').first()
    
    # 获取所有巴法云密钥
    bemfa_keys = BemfaKey.query.all()
    
    # 获取MQTT连接状态
    mqtt_status = mqtt_manager.get_connection_status()
    
    return render_template('settings.html',
                         mqtt_enabled=mqtt_enabled.value == 'true' if mqtt_enabled else False,
                         mqtt_connected=mqtt_manager.is_connected,
                         bemfa_keys=bemfa_keys,
                         mqtt_status=mqtt_status)

@app.route('/save_settings', methods=['POST'])
@login_required
def save_settings():
    mqtt_enabled = request.form.get('mqtt_enabled') == 'on'
    
    # 保存MQTT服务状态
    config = Config.query.filter_by(key='mqtt_enabled').first()
    if config:
        config.value = 'true' if mqtt_enabled else 'false'
        config.updated_at = datetime.utcnow()
    else:
        config = Config(key='mqtt_enabled', value='true' if mqtt_enabled else 'false')
        db.session.add(config)
    
    db.session.commit()
    
    # 管理MQTT服务
    try:
        if mqtt_enabled and not mqtt_manager.is_running:
            # 获取启用的巴法云密钥
            enabled_keys = BemfaKey.query.filter_by(enabled=True).all()
            if enabled_keys:
                mqtt_manager.start_mqtt_service()
            else:
                flash('请先添加并启用巴法云密钥', 'warning')
                return redirect(url_for('settings'))
        elif not mqtt_enabled and mqtt_manager.is_running:
            mqtt_manager.stop_mqtt_service()
    except Exception as e:
        flash(f'MQTT服务操作失败: {str(e)}', 'error')
        return redirect(url_for('settings'))
    
    flash('设置保存成功', 'success')
    return redirect(url_for('settings'))

# 巴法云密钥管理 API 路由
@app.route('/add_bemfa_key_api', methods=['POST'])
@login_required
def add_bemfa_key_api():
    """添加巴法云密钥 API"""
    try:
        name = request.form.get('name', '').strip()
        key = request.form.get('key', '').strip()
        enabled = request.form.get('enabled') == 'on'
        
        # 验证输入
        if not name or not key:
            return jsonify({'success': False, 'message': '请填写所有必填字段'})
        
        # 验证密钥格式
        if len(key) != 32:
            return jsonify({'success': False, 'message': '巴法云私钥必须是32位字符'})
        
        # 验证密钥是否已存在
        existing_key = BemfaKey.query.filter_by(key=key).first()
        if existing_key:
            return jsonify({'success': False, 'message': '该密钥已存在'})
        
        # 创建新密钥
        new_key = BemfaKey(
            name=name,
            key=key,
            enabled=enabled
        )
        db.session.add(new_key)
        db.session.commit()
        
        # 如果密钥启用，执行后续操作
        if enabled:
            # 检查MQTT服务是否已启用
            mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
            if mqtt_config and mqtt_config.value == 'true':
                try:
                    # 启动新的MQTT客户端
                    mqtt_manager.start_client(key)
                    logger.info(f"为新密钥 {name} 启动MQTT客户端")
                    
                    # 同步设备到巴法云
                    sync_result = sync_visible_devices_to_bemfa()
                    if sync_result:
                        created_count = sync_result.get('created_count', 0)
                        updated_count = sync_result.get('updated_count', 0)
                        deleted_count = sync_result.get('deleted_count', 0)
                        
                        if created_count > 0 or updated_count > 0 or deleted_count > 0:
                            message = f'巴法云密钥 {name} 添加成功'
                            if created_count > 0:
                                message += f'，同步创建了 {created_count} 个设备主题'
                            if updated_count > 0:
                                message += f'，更新了 {updated_count} 个设备昵称'
                            if deleted_count > 0:
                                message += f'，删除了 {deleted_count} 个多余主题'
                            
                            logger.info(f"新密钥 {name} 设备同步完成: 创建 {created_count}, 更新 {updated_count}, 删除 {deleted_count}")
                        else:
                            message = f'巴法云密钥 {name} 添加成功，设备主题已同步'
                    else:
                        message = f'巴法云密钥 {name} 添加成功，但没有可见设备需要同步'
                        
                except Exception as sync_error:
                    logger.error(f"新密钥 {name} 同步失败: {str(sync_error)}")
                    message = f'巴法云密钥 {name} 添加成功，但同步设备失败: {str(sync_error)}'
            else:
                message = f'巴法云密钥 {name} 添加成功，但MQTT服务未启用'
        else:
            message = f'巴法云密钥 {name} 添加成功（已禁用）'
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'添加失败: {str(e)}'})

@app.route('/edit_bemfa_key_api/<int:key_id>', methods=['POST'])
@login_required
def edit_bemfa_key_api(key_id):
    """编辑巴法云密钥 API"""
    try:
        bemfa_key = BemfaKey.query.get_or_404(key_id)
        old_key = bemfa_key.key
        old_enabled = bemfa_key.enabled
        
        name = request.form.get('name', '').strip()
        key = request.form.get('key', '').strip()
        enabled = request.form.get('enabled') == 'on'
        
        # 验证输入
        if not name or not key:
            return jsonify({'success': False, 'message': '请填写所有必填字段'})
        
        # 验证密钥格式
        if len(key) != 32:
            return jsonify({'success': False, 'message': '巴法云私钥必须是32位字符'})
        
        # 验证密钥是否已存在（排除自己）
        existing_key = BemfaKey.query.filter(BemfaKey.key == key, BemfaKey.id != key_id).first()
        if existing_key:
            return jsonify({'success': False, 'message': '该密钥已存在'})
        
        # 更新密钥信息
        bemfa_key.name = name
        bemfa_key.key = key
        bemfa_key.enabled = enabled
        
        db.session.commit()
        
        # 处理MQTT连接变化
        mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
        if mqtt_config and mqtt_config.value == 'true':
            try:
                # 如果密钥改变，停止旧的客户端
                if old_key != key:
                    mqtt_manager.stop_client(old_key)
                    logger.info(f"停止旧密钥 {old_key[:8]}... 的MQTT客户端")
                
                # 如果新密钥启用，启动新的客户端
                if enabled:
                    mqtt_manager.start_client(key)
                    logger.info(f"为更新后的密钥 {name} 启动MQTT客户端")
                    
                    # 同步设备到巴法云
                    sync_result = sync_visible_devices_to_bemfa()
                    if sync_result:
                        created_count = sync_result.get('created_count', 0)
                        updated_count = sync_result.get('updated_count', 0)
                        deleted_count = sync_result.get('deleted_count', 0)
                        
                        if created_count > 0 or updated_count > 0 or deleted_count > 0:
                            message = f'巴法云密钥 {name} 更新成功'
                            if created_count > 0:
                                message += f'，同步创建了 {created_count} 个设备主题'
                            if updated_count > 0:
                                message += f'，更新了 {updated_count} 个设备昵称'
                            if deleted_count > 0:
                                message += f'，删除了 {deleted_count} 个多余主题'
                        else:
                            message = f'巴法云密钥 {name} 更新成功，设备主题已同步'
                    else:
                        message = f'巴法云密钥 {name} 更新成功，但没有可见设备需要同步'
                else:
                    # 如果密钥被禁用，停止客户端
                    mqtt_manager.stop_client(key)
                    logger.info(f"密钥 {name} 被禁用，停止MQTT客户端")
                    message = f'巴法云密钥 {name} 更新成功（已禁用）'
                    
            except Exception as sync_error:
                logger.error(f"更新密钥 {name} 后处理MQTT连接失败: {str(sync_error)}")
                message = f'巴法云密钥 {name} 更新成功，但处理MQTT连接失败: {str(sync_error)}'
        else:
            message = f'巴法云密钥 {name} 更新成功'
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'})

@app.route('/get_bemfa_key_api/<int:key_id>')
@login_required
def get_bemfa_key_api(key_id):
    """获取巴法云密钥信息 API"""
    try:
        bemfa_key = BemfaKey.query.get_or_404(key_id)
        
        return jsonify({
            'success': True,
            'key': {
                'id': bemfa_key.id,
                'name': bemfa_key.name,
                'key': bemfa_key.key,
                'enabled': bemfa_key.enabled
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/toggle_bemfa_key_api/<int:key_id>', methods=['POST'])
@login_required
def toggle_bemfa_key_api(key_id):
    """切换巴法云密钥启用状态 API"""
    try:
        bemfa_key = BemfaKey.query.get_or_404(key_id)
        old_enabled = bemfa_key.enabled
        
        bemfa_key.enabled = not bemfa_key.enabled
        db.session.commit()
        
        status = "启用" if bemfa_key.enabled else "禁用"
        
        # 处理MQTT连接变化
        mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
        if mqtt_config and mqtt_config.value == 'true':
            try:
                if bemfa_key.enabled:
                    # 启用密钥，启动MQTT客户端
                    mqtt_manager.start_client(bemfa_key.key)
                    logger.info(f"启用密钥 {bemfa_key.name}，启动MQTT客户端")
                    
                    # 同步设备到巴法云
                    sync_result = sync_visible_devices_to_bemfa()
                    if sync_result:
                        created_count = sync_result.get('created_count', 0)
                        updated_count = sync_result.get('updated_count', 0)
                        deleted_count = sync_result.get('deleted_count', 0)
                        
                        if created_count > 0 or updated_count > 0 or deleted_count > 0:
                            message = f'巴法云密钥 {bemfa_key.name} 已{status}'
                            if created_count > 0:
                                message += f'，同步创建了 {created_count} 个设备主题'
                            if updated_count > 0:
                                message += f'，更新了 {updated_count} 个设备昵称'
                            if deleted_count > 0:
                                message += f'，删除了 {deleted_count} 个多余主题'
                        else:
                            message = f'巴法云密钥 {bemfa_key.name} 已{status}，设备主题已同步'
                    else:
                        message = f'巴法云密钥 {bemfa_key.name} 已{status}，但没有可见设备需要同步'
                else:
                    # 禁用密钥，停止MQTT客户端
                    mqtt_manager.stop_client(bemfa_key.key)
                    logger.info(f"禁用密钥 {bemfa_key.name}，停止MQTT客户端")
                    message = f'巴法云密钥 {bemfa_key.name} 已{status}'
                    
            except Exception as sync_error:
                logger.error(f"切换密钥 {bemfa_key.name} 状态后处理MQTT连接失败: {str(sync_error)}")
                message = f'巴法云密钥 {bemfa_key.name} 已{status}，但处理MQTT连接失败: {str(sync_error)}'
        else:
            message = f'巴法云密钥 {bemfa_key.name} 已{status}'
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'操作失败: {str(e)}'})

@app.route('/delete_bemfa_key_api/<int:key_id>', methods=['POST'])
@login_required
def delete_bemfa_key_api(key_id):
    """删除巴法云密钥 API"""
    try:
        bemfa_key = BemfaKey.query.get_or_404(key_id)
        
        key_name = bemfa_key.name
        key_value = bemfa_key.key
        was_enabled = bemfa_key.enabled
        
        db.session.delete(bemfa_key)
        db.session.commit()
        
        # 如果密钥是启用的，停止对应的MQTT客户端
        if was_enabled:
            mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
            if mqtt_config and mqtt_config.value == 'true':
                try:
                    mqtt_manager.stop_client(key_value)
                    logger.info(f"删除密钥 {key_name}，停止对应的MQTT客户端")
                    message = f'巴法云密钥 {key_name} 删除成功，已断开MQTT连接'
                except Exception as mqtt_error:
                    logger.error(f"停止已删除密钥 {key_name} 的MQTT客户端失败: {str(mqtt_error)}")
                    message = f'巴法云密钥 {key_name} 删除成功，但停止MQTT连接失败: {str(mqtt_error)}'
            else:
                message = f'巴法云密钥 {key_name} 删除成功'
        else:
            message = f'巴法云密钥 {key_name} 删除成功'
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})

@app.route('/sync_bemfa_devices', methods=['POST'])
@login_required
def sync_bemfa_devices():
    """手动同步可见设备到巴法云"""
    try:
        result = sync_visible_devices_to_bemfa()
        
        if result:
            created_count = result.get('created_count', 0)
            updated_count = result.get('updated_count', 0)
            deleted_count = result.get('deleted_count', 0)
            failed_count = result.get('failed_count', 0)
            accounts = result.get('accounts', [])
            
            if created_count > 0 or updated_count > 0 or deleted_count > 0:
                message_parts = []
                if created_count > 0:
                    message_parts.append(f"创建 {created_count} 个主题")
                if updated_count > 0:
                    message_parts.append(f"更新 {updated_count} 个昵称")
                if deleted_count > 0:
                    message_parts.append(f"删除 {deleted_count} 个多余主题")
                
                message = f"同步成功：{', '.join(message_parts)}"
                if failed_count > 0:
                    message += f"，{failed_count} 个失败"
                    
                # 如果是多账号，显示详细信息
                if len(accounts) > 1:
                    message += f"（共 {len(accounts)} 个账号）"
            elif failed_count > 0:
                message = f"同步失败：{failed_count} 个主题操作失败"
            else:
                message = "所有设备主题都已同步，无需更新"
        else:
            message = "没有可见设备需要同步"
        
        return jsonify({
            "success": True, 
            "message": message,
            "accounts": accounts
        })
    except Exception as e:
        logger.error(f"手动同步巴法云失败: {str(e)}")
        return jsonify({"success": False, "message": f"同步失败: {str(e)}"})

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        user = User.query.get(session['user_id'])
        
        if not check_password_hash(user.password_hash, current_password):
            flash('当前密码错误', 'error')
            return render_template('change_password.html')
        
        if new_password != confirm_password:
            flash('新密码与确认密码不匹配', 'error')
            return render_template('change_password.html')
        
        if len(new_password) < 6:
            flash('密码长度至少6位', 'error')
            return render_template('change_password.html')
        
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        
        flash('密码修改成功', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('change_password.html')

# 用户管理路由
@app.route('/user_management')
@login_required
def user_management():
    """用户管理页面"""
    users = User.query.all()
    return render_template('user_management.html', users=users)

@app.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    """添加用户"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # 验证用户名是否已存在
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('用户名已存在', 'error')
            return render_template('add_user.html')
        
        # 验证密码长度
        if len(password) < 6:
            flash('密码长度至少6位', 'error')
            return render_template('add_user.html')
        
        # 创建新用户
        new_user = User(
            username=username,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        
        flash(f'用户 {username} 添加成功', 'success')
        return redirect(url_for('user_management'))
    
    return render_template('add_user.html')

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    """编辑用户"""
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form.get('password', '')
        
        # 验证用户名是否已存在（排除自己）
        existing_user = User.query.filter(User.username == username, User.id != user_id).first()
        if existing_user:
            flash('用户名已存在', 'error')
            return render_template('edit_user.html', user=user)
        
        # 更新用户名
        user.username = username
        
        # 如果提供了新密码，则更新密码
        if password:
            if len(password) < 6:
                flash('密码长度至少6位', 'error')
                return render_template('edit_user.html', user=user)
            user.password_hash = generate_password_hash(password)
        
        db.session.commit()
        flash(f'用户 {username} 更新成功', 'success')
        return redirect(url_for('user_management'))
    
    return render_template('edit_user.html', user=user)

@app.route('/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    """删除用户"""
    user = User.query.get_or_404(user_id)
    
    # 不能删除自己
    if user.id == session['user_id']:
        flash('不能删除当前登录用户', 'error')
        return redirect(url_for('user_management'))
    
    # 不能删除最后一个用户
    if User.query.count() <= 1:
        flash('至少需要保留一个用户', 'error')
        return redirect(url_for('user_management'))
    
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    flash(f'用户 {username} 删除成功', 'success')
    return redirect(url_for('user_management'))

# 预设设备数据
PRESET_DEVICES = [
    ("172.16.11.4", "01", "001", "1"),
    ("172.16.11.1", "01", "001", "1"),
    ("172.16.11.2", "01", "001", "2"),
    ("172.16.11.5", "01", "001", "2"),
    ("172.16.11.3", "01", "001", "3"),
    ("172.16.11.6", "01", "001", "3"),
    ("172.16.12.1", "01", "002", "1"),
    ("172.16.12.2", "01", "002", "2"),
    ("172.16.12.3", "01", "002", "3"),
    ("172.16.13.1", "01", "003", "1"),
    ("172.16.13.2", "01", "003", "2"),
    ("172.16.13.3", "01", "003", "3"),
    ("172.16.14.2", "01", "004", "1"),
    ("172.16.14.1", "01", "004", "1"),
    ("172.16.14.3", "01", "004", "2"),
    ("172.16.14.5", "01", "004", "2"),
    ("172.16.14.6", "01", "004", "3"),
    ("172.16.14.4", "01", "004", "3"),
    ("172.16.15.1", "01", "005", "1"),
    ("172.16.15.2", "01", "005", "2"),
    ("172.16.15.3", "01", "005", "3"),
    ("172.16.16.1", "01", "006", "1"),
    ("172.16.16.2", "01", "006", "2"),
    ("172.16.17.1", "01", "007", "1"),
    ("172.16.17.2", "01", "007", "2"),
    ("172.16.17.3", "01", "007", "3"),
    ("172.16.111.49", "01", "999", ""),
    ("172.16.18.2", "01", "999", "1"),
    ("172.16.18.5", "01", "999", "1"),
    ("172.16.18.11", "01", "999", "1"),
    ("172.16.18.8", "01", "999", "1"),
    ("172.16.18.7", "01", "999", "1"),
    ("172.16.18.9", "01", "999", "1"),
    ("172.16.18.10", "01", "999", "1"),
    ("172.16.18.6", "01", "999", "1"),
    ("172.16.18.4", "01", "999", "1"),
    ("172.16.18.1", "01", "999", "1"),
    ("172.16.18.3", "01", "999", "1"),
    ("172.16.106.8", "02", "001", "1"),
    ("172.16.106.7", "02", "001", "2"),
    ("172.16.106.6", "02", "001", "3"),
    ("172.16.107.137", "02", "002", "1"),
    ("172.16.107.136", "02", "002", "1"),
    ("172.16.107.138", "02", "002", "1"),
    ("172.16.107.135", "02", "002", "3"),
    ("172.16.108.60", "02", "003", "1"),
    ("172.16.108.58", "02", "003", "2"),
    ("172.16.108.57", "02", "003", "3"),
    ("172.16.108.153", "02", "004", "1"),
    ("172.16.108.152", "02", "004", "2"),
    ("172.16.108.151", "02", "004", "3"),
    ("172.16.107.240", "02", "005", "1"),
    ("172.16.107.239", "02", "005", "2"),
    ("172.16.107.238", "02", "005", "3"),
    ("172.16.101.8", "02", "999", "1"),
    ("172.16.101.9", "02", "999", "3"),
    ("172.16.104.236", "03", "001", "1"),
    ("172.16.104.235", "03", "001", "2"),
    ("172.16.104.233", "03", "001", "3"),
    ("172.16.104.234", "03", "001", "3"),
    ("172.16.101.12", "04", "001", "1"),
    ("172.16.101.11", "04", "001", "2"),
    ("172.16.101.10", "04", "001", "3"),
    ("172.16.102.131", "04", "002", "1"),
    ("172.16.102.129", "04", "002", "1"),
    ("172.16.102.130", "04", "002", "1"),
    ("172.16.102.209", "04", "003", "1"),
    ("172.16.102.210", "04", "003", "1"),
    ("172.16.102.207", "04", "003", "1"),
    ("172.16.102.208", "04", "003", "2"),
    ("172.16.102.205", "04", "003", "3"),
    ("172.16.104.120", "04", "004", "1"),
    ("172.16.104.115", "04", "004", "1"),
    ("172.16.104.119", "04", "004", "1"),
    ("172.16.104.117", "04", "004", "1"),
    ("172.16.104.118", "04", "004", "2"),
    ("172.16.104.116", "04", "004", "3"),
    ("172.16.101.7", "04", "999", "1"),
    ("172.16.101.6", "04", "999", "1"),
]

def init_preset_devices():
    """初始化预设设备数据"""
    existing_ips = {device.ip for device in Device.query.all()}
    existing_names = {device.name for device in Device.query.all()}
    
    devices_to_add = []
    
    for ip, section, building, position in PRESET_DEVICES:
        if ip in existing_ips:
            continue  # 跳过已存在的设备
        
        # 创建临时设备对象以生成名称
        temp_device = Device(
            section_number=section,
            building_number=building,
            position=position if position else None,
            ip=ip
        )
        
        # 生成设备名称
        device_name = temp_device.generate_device_name(existing_names)
        existing_names.add(device_name)
        
        # 生成MQTT主题
        mqtt_topic = temp_device.generate_mqtt_topic()
        
        # 创建设备
        device = Device(
            name=device_name,
            group_name=f"{section}区",
            section_number=section,
            building_number=building,
            position=position if position else None,
            ip=ip,
            mqtt_topic=mqtt_topic,
            visible=False  # 默认不可见
        )
        
        devices_to_add.append(device)
    
    if devices_to_add:
        db.session.add_all(devices_to_add)
        db.session.commit()
        logger.info(f"已添加 {len(devices_to_add)} 个预设设备")

# 同步可见设备到巴法云
def sync_visible_devices_to_bemfa():
    """同步可见设备到所有启用的巴法云账号"""
    bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
    
    # 如果没有新的BemfaKey，则回退到旧的Config方式
    if not bemfa_keys:
        old_bemfa_key = Config.query.filter_by(key='bemfa_private_key').first()
        if old_bemfa_key and old_bemfa_key.value:
            logger.info("使用旧的巴法云私钥配置")
            result = sync_single_bemfa_account(old_bemfa_key.value)
            # 为了保持返回格式一致，添加accounts字段
            result['accounts'] = [{
                'name': '默认账号',
                'key': old_bemfa_key.value[:8] + '...',
                'created': result['created_count'],
                'updated': result['updated_count'],
                'deleted': result['deleted_count'],
                'failed': result['failed_count'],
                'success': True
            }]
            return result
        else:
            logger.warning("未配置巴法云私钥，跳过同步")
            return {
                'created_count': 0,
                'updated_count': 0,
                'deleted_count': 0,
                'failed_count': 0,
                'total_devices': 0,
                'accounts': []
            }
    
    visible_devices = Device.query.filter_by(visible=True).all()
    if not visible_devices:
        logger.info("没有可见设备需要同步")
        return {
            'created_count': 0,
            'updated_count': 0,
            'deleted_count': 0,
            'failed_count': 0,
            'total_devices': 0,
            'accounts': []
        }
    
    # 对所有启用的巴法云账号执行同步
    total_created = 0
    total_updated = 0
    total_deleted = 0
    total_failed = 0
    account_results = []
    
    for bemfa_key in bemfa_keys:
        logger.info(f"同步到巴法云账号：{bemfa_key.name}")
        try:
            result = sync_single_bemfa_account(bemfa_key.key)
            account_results.append({
                'name': bemfa_key.name,
                'key': bemfa_key.key[:8] + '...',  # 只显示前8位
                'created': result['created_count'],
                'updated': result['updated_count'],
                'deleted': result['deleted_count'],
                'failed': result['failed_count'],
                'success': True
            })
            total_created += result['created_count']
            total_updated += result['updated_count']
            total_deleted += result['deleted_count']
            total_failed += result['failed_count']
        except Exception as e:
            logger.error(f"同步到巴法云账号 {bemfa_key.name} 失败: {str(e)}")
            account_results.append({
                'name': bemfa_key.name,
                'key': bemfa_key.key[:8] + '...',
                'created': 0,
                'updated': 0,
                'deleted': 0,
                'failed': 0,
                'success': False,
                'error': str(e)
            })
    
    logger.info(f"多账号同步完成：总创建 {total_created}，总更新 {total_updated}，总删除 {total_deleted}，总失败 {total_failed}")
    
    return {
        'created_count': total_created,
        'updated_count': total_updated,
        'deleted_count': total_deleted,
        'failed_count': total_failed,
        'total_devices': len(visible_devices),
        'accounts': account_results
    }

def sync_single_bemfa_account(bemfa_key_value):
    """同步可见设备到单个巴法云账号"""
    visible_devices = Device.query.filter_by(visible=True).all()
    
    try:
        # 获取现有主题
        topics_response = bemfa_api.get_all_topics(bemfa_key_value)
        existing_topics = set()
        topic_names = {}
        
        if topics_response.get("code") == 0:
            for topic_data in topics_response.get("data", []):
                existing_topics.add(topic_data["topic"])
                topic_names[topic_data["topic"]] = topic_data.get("name", "")
        
        # 获取当前需要同步的设备主题
        current_device_topics = set()
        for device in visible_devices:
            topic = device.mqtt_topic
            if topic:
                current_device_topics.add(topic)
        
        # 查找需要删除的主题（以vto开头但不在当前设备列表中）
        topics_to_delete = []
        for existing_topic in existing_topics:
            if existing_topic.startswith('vto') and existing_topic not in current_device_topics:
                topics_to_delete.append(existing_topic)
        
        # 删除不需要的vto主题
        deleted_count = 0
        for topic in topics_to_delete:
            delete_response = bemfa_api.delete_topic(
                uid=bemfa_key_value,
                topic=topic,
                type=1  # MQTT协议设备
            )
            
            if delete_response.get("code") == 0:
                logger.info(f"成功删除多余的主题 {topic}")
                deleted_count += 1
            else:
                logger.error(f"删除主题 {topic} 失败: {delete_response.get('message', '未知错误')}")
        
        # 需要创建和更新的主题
        topics_to_create = []
        topics_to_update = []
        
        for device in visible_devices:
            topic = device.mqtt_topic
            if not topic:
                continue
                
            if topic not in existing_topics:
                topics_to_create.append((topic, device.name))
            elif topic_names.get(topic) != device.name:
                topics_to_update.append((topic, device.name))
        
        # 逐个创建主题，在创建时就设置昵称
        created_count = 0
        failed_count = 0
        for topic, device_name in topics_to_create:
            create_response = bemfa_api.create_topic(
                uid=bemfa_key_value, 
                topic=topic, 
                name=device_name,
                type=1  # MQTT协议设备
            )
            
            if create_response.get("code") == 0:
                logger.info(f"成功创建主题 {topic}，昵称：{device_name}")
                created_count += 1
            elif create_response.get("code") == 40006:
                # 设备已存在，记录警告但不算失败
                logger.warning(f"主题 {topic} 已存在，跳过创建")
            else:
                logger.error(f"创建主题 {topic} 失败: {create_response.get('message', '未知错误')}")
                failed_count += 1
        
        # 更新已存在主题的名称（如果昵称不匹配）
        updated_count = 0
        for topic, name in topics_to_update:
            update_response = bemfa_api.modify_topic_name(bemfa_key_value, topic, name)
            if update_response.get("code") == 0:
                logger.info(f"成功更新主题 {topic} 的名称为 {name}")
                updated_count += 1
            else:
                logger.error(f"更新主题 {topic} 名称失败: {update_response.get('message')}")
        
        return {
            'created_count': created_count,
            'updated_count': updated_count,
            'deleted_count': deleted_count,
            'failed_count': failed_count,
            'total_devices': len(visible_devices)
        }
                
    except Exception as e:
        logger.error(f"同步巴法云设备失败: {str(e)}")
        raise

# 初始化MQTT服务
def init_mqtt_service():
    """程序启动时初始化MQTT服务"""
    try:
        # 检查MQTT是否已启用
        mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
        if not mqtt_config or mqtt_config.value != 'true':
            logger.info("MQTT服务未启用")
            return
        
        # 优先使用新的BemfaKey配置
        bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
        
        if bemfa_keys:
            logger.info("正在启动多个巴法云账号的MQTT服务...")
            mqtt_manager.start_all_clients()
            logger.info("多账号MQTT服务启动完成")
        else:
            # 回退到旧的配置方式
            bemfa_key_config = Config.query.filter_by(key='bemfa_private_key').first()
            if bemfa_key_config and bemfa_key_config.value:
                logger.info("使用旧的巴法云私钥配置启动MQTT服务...")
                mqtt_manager.start_mqtt_service("bemfa.com", 9501, bemfa_key_config.value)
                logger.info("MQTT服务启动完成")
            else:
                logger.warning("MQTT服务已启用但未配置巴法云私钥")
                return
        
    except Exception as e:
        logger.error(f"启动MQTT服务时出错: {str(e)}")

# 延迟启动MQTT服务
def delayed_mqtt_init():
    """延迟启动MQTT服务，确保应用完全启动后再连接"""
    import threading
    import time
    
    # 检查是否是Flask的重载进程（调试模式下会重启应用）
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        # 这是主进程，启动MQTT服务
        def start_mqtt():
            # 等待3秒让应用完全启动
            time.sleep(3)
            with app.app_context():
                init_mqtt_service()
        
        # 在后台线程中启动
        mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
        mqtt_thread.start()
    else:
        # 这是重载进程，不启动MQTT服务
        logger.info("检测到Flask重载进程，跳过MQTT服务启动")

# 初始化数据库
def init_db():
    with app.app_context():
        db.create_all()
        
        # 创建默认管理员账户
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                password_hash=generate_password_hash('123456')
            )
            db.session.add(admin)
            db.session.commit()
            logger.info('默认管理员账户已创建 (admin/123456)')
        
        # 初始化预设设备
        init_preset_devices()
        
        # 迁移旧的巴法云配置到新的BemfaKey表
        migrate_bemfa_config()

def migrate_bemfa_config():
    """迁移旧的巴法云配置到新的BemfaKey表"""
    try:
        # 检查是否已经有BemfaKey记录
        if BemfaKey.query.count() > 0:
            logger.info("已存在BemfaKey记录，跳过迁移")
            return
        
        # 获取旧的巴法云配置
        old_bemfa_config = Config.query.filter_by(key='bemfa_private_key').first()
        if old_bemfa_config and old_bemfa_config.value:
            # 创建新的BemfaKey记录
            new_bemfa_key = BemfaKey(
                name="默认账号",
                key=old_bemfa_config.value,
                enabled=True
            )
            db.session.add(new_bemfa_key)
            db.session.commit()
            logger.info("成功迁移旧的巴法云配置到新的BemfaKey表")
        else:
            logger.info("未找到旧的巴法云配置，跳过迁移")
    except Exception as e:
        logger.error(f"迁移巴法云配置时出错: {str(e)}")
        db.session.rollback()

if __name__ == '__main__':
    init_db()
    # 启动延迟MQTT初始化
    delayed_mqtt_init()
    app.run(host='0.0.0.0', port=8998, debug=False) 