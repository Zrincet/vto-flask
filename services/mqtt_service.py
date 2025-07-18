"""
MQTT服务模块
管理MQTT客户端连接和消息处理
"""

import logging
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTClient:
    """单个MQTT客户端连接"""
    
    def __init__(self, client_id, mqtt_host="bemfa.com", mqtt_port=9501):
        """
        初始化MQTT客户端
        
        Args:
            client_id (str): 客户端ID
            mqtt_host (str): MQTT服务器地址，默认'bemfa.com'
            mqtt_port (int): MQTT服务器端口，默认9501
        """
        self.client_id = client_id
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.client = None
        self.is_connected = False
        self.is_running = False
        self.subscribed_topics = set()
        self._app = None  # Flask应用实例，启动时设置
        
    def set_app(self, app):
        """设置Flask应用实例"""
        self._app = app
    
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
        """MQTT连接回调"""
        if rc == 0:
            self.is_connected = True
            logger.info(f"MQTT客户端 {self.client_id} 已连接到服务器")
            
            # 在Flask应用上下文中执行数据库查询
            if self._app:
                with self._app.app_context():
                    self._subscribe_device_topics(client)
        else:
            logger.error(f"MQTT客户端 {self.client_id} 连接服务器失败，返回码: {rc}")

    def _subscribe_device_topics(self, client):
        """订阅设备主题"""
        try:
            from models import Device
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
        except Exception as e:
            logger.error(f"订阅设备主题失败: {str(e)}")

    def on_message(self, client, userdata, msg):
        """MQTT消息接收回调"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            logger.info(f"客户端 {self.client_id} 收到消息 - 主题: {topic}, 内容: {payload}")

            # 在Flask应用上下文中执行数据库操作
            if self._app:
                with self._app.app_context():
                    self._handle_device_message(topic, payload)
                    
        except Exception as e:
            logger.error(f"处理MQTT消息时出错: {str(e)}")

    def _handle_device_message(self, topic, payload):
        """处理设备消息"""
        try:
            from models import Device, BemfaKey, db
            from services import DahuaService
            
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
                    dahua_client = DahuaService(
                        ip=device.ip,
                        username=device.username,
                        password=device.password
                    )
                    
                    result = dahua_client.execute_door_open_flow()
                    
                    if result["success"]:
                        device.last_unlock_time = datetime.utcnow()
                        db.session.commit()
                        logger.info(f"设备 {device.name} 开锁成功")
                        
                        # 发送状态推送消息
                        self._send_status_pushback(device)
                    else:
                        logger.error(f"设备 {device.name} 开锁失败: {result.get('message', '未知错误')}")
                        
                except Exception as e:
                    logger.error(f"处理设备 {device.name} 开锁请求时出错: {str(e)}")
                    
        except Exception as e:
            logger.error(f"处理设备消息失败: {str(e)}")

    def _send_status_pushback(self, device):
        """发送状态推送消息"""
        try:
            from models import BemfaKey
            from .bemfa_service import BemfaService
            
            # 开锁成功后，向所有启用的巴法云账号发送状态推送消息
            bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
            
            if not bemfa_keys:
                return
                
            # 准备推送消息内容
            status_msg = "off"  # 设备状态设为off
            wechat_msg = f"设备 {device.name} 开锁成功，当前状态：关闭"
            
            bemfa_service = BemfaService()
            
            # 向所有启用的巴法云账号发送状态推送
            for bemfa_key in bemfa_keys:
                push_result = bemfa_service.send_status_message(
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

    def on_disconnect(self, client, userdata, rc):
        """MQTT断连回调"""
        self.is_connected = False
        logger.info(f"MQTT客户端 {self.client_id} 已断开连接")

    def subscribe_device_topic(self, topic):
        """订阅设备主题"""
        if self.client and self.is_connected and topic not in self.subscribed_topics:
            self.client.subscribe(topic)
            self.subscribed_topics.add(topic)
            logger.info(f"客户端 {self.client_id} 已订阅新主题: {topic}")

    def unsubscribe_device_topic(self, topic):
        """取消订阅设备主题"""
        if self.client and self.is_connected and topic in self.subscribed_topics:
            self.client.unsubscribe(topic)
            self.subscribed_topics.remove(topic)
            logger.info(f"客户端 {self.client_id} 已取消订阅主题: {topic}")


class MQTTManager:
    """支持多个巴法云账号的MQTT管理器"""
    
    def __init__(self):
        self.clients = {}  # {client_id: MQTTClient}
        self.is_running = False
        self._app = None  # Flask应用实例

    def set_app(self, app):
        """设置Flask应用实例"""
        self._app = app
        # 为所有现有客户端设置app
        for client in self.clients.values():
            client.set_app(app)

    def start_mqtt_service(self, mqtt_host="bemfa.com", mqtt_port=9501, client_id=None):
        """启动单个MQTT客户端（向后兼容）"""
        if client_id:
            self.start_client(client_id, mqtt_host, mqtt_port)
        else:
            self.start_all_clients()

    def start_all_clients(self):
        """启动所有启用的巴法云密钥对应的MQTT客户端"""
        if not self._app:
            logger.error("Flask应用未设置，无法启动MQTT客户端")
            return
            
        with self._app.app_context():
            from models import BemfaKey
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
        if self._app:
            client.set_app(self._app)
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

    def init_mqtt_service(self):
        """程序启动时初始化MQTT服务"""
        if not self._app:
            logger.error("Flask应用未设置，无法初始化MQTT服务")
            return
            
        try:
            with self._app.app_context():
                from models import Config, BemfaKey
                
                # 检查MQTT是否已启用
                mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
                if not mqtt_config or mqtt_config.value != 'true':
                    logger.info("MQTT服务未启用")
                    return
                
                # 优先使用新的BemfaKey配置
                bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
                
                if bemfa_keys:
                    logger.info("正在启动多个巴法云账号的MQTT服务...")
                    self.start_all_clients()
                    logger.info("多账号MQTT服务启动完成")
                else:
                    # 回退到旧的配置方式
                    bemfa_key_config = Config.query.filter_by(key='bemfa_private_key').first()
                    if bemfa_key_config and bemfa_key_config.value:
                        logger.info("使用旧的巴法云私钥配置启动MQTT服务...")
                        self.start_mqtt_service("bemfa.com", 9501, bemfa_key_config.value)
                        logger.info("MQTT服务启动完成")
                    else:
                        logger.warning("MQTT服务已启用但未配置巴法云私钥")
                        return
                
        except Exception as e:
            logger.error(f"启动MQTT服务时出错: {str(e)}")

    def delayed_mqtt_init(self):
        """延迟启动MQTT服务，确保应用完全启动后再连接"""
        def start_mqtt():
            # 等待3秒让应用完全启动
            time.sleep(3)
            self.init_mqtt_service()

        # 在后台线程中启动
        mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
        mqtt_thread.start()


# 全局MQTT管理器实例
mqtt_manager = MQTTManager() 