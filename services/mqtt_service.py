"""
MQTT服务模块
管理MQTT客户端连接和消息处理，包含完善的重连机制
"""

import logging
import threading
import time
from datetime import datetime, timedelta
import random
import socket

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTClient:
    """单个MQTT客户端连接，支持自动重连"""
    
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
        
        # 重连机制相关
        self.auto_reconnect = True
        self.reconnect_thread = None
        self.reconnect_interval = 3  # 初始重连间隔减少到3秒
        self.max_reconnect_interval = 60  # 最大重连间隔减少到60秒
        self.reconnect_backoff = 1.3  # 重连间隔递增因子调整为1.3
        self.current_reconnect_interval = self.reconnect_interval
        self.last_connect_time = None
        self.last_disconnect_time = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 0  # 0表示无限重试
        
        # 健康检查机制
        self.last_ping_time = None
        self.ping_interval = 30  # 心跳间隔（秒）
        self.ping_timeout = 15  # 心跳超时增加到15秒
        self.health_check_thread = None
        self.stop_event = threading.Event()
        
    def set_app(self, app):
        """设置Flask应用实例"""
        self._app = app
    
    def start(self):
        """启动MQTT客户端"""
        if self.is_running:
            logger.info(f"MQTT客户端 {self.client_id} 已在运行中")
            return

        self.stop_event.clear()
        self.is_running = True
        self.auto_reconnect = True
        
        # 启动连接
        self._connect()
        
        # 启动健康检查线程
        self._start_health_check()
        
    def stop(self):
        """停止MQTT客户端"""
        logger.info(f"正在停止MQTT客户端 {self.client_id}")
        
        self.auto_reconnect = False
        self.is_running = False
        self.stop_event.set()
        
        # 停止重连线程
        if self.reconnect_thread and self.reconnect_thread.is_alive():
            self.reconnect_thread.join(timeout=2)
            
        # 停止健康检查线程
        if self.health_check_thread and self.health_check_thread.is_alive():
            self.health_check_thread.join(timeout=2)
        
        # 断开MQTT连接
        if self.client:
            try:
                # 停止自定义loop（通过loop_stop）
                self.client.loop_stop()
                self.client.disconnect()
            except Exception as e:
                logger.error(f"断开MQTT客户端 {self.client_id} 时出错: {str(e)}")
            finally:
                self.client = None
                self.is_connected = False
        
        logger.info(f"MQTT客户端 {self.client_id} 已停止")

    def _connect(self):
        """建立MQTT连接"""
        try:
            # 清理旧连接
            if self.client:
                try:
                    self.client.loop_stop()
                    self.client.disconnect()
                except:
                    pass
                self.client = None

            # 创建新客户端
            try:
                # paho-mqtt 2.0+ 版本
                self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1, client_id=self.client_id)
            except AttributeError:
                # paho-mqtt 1.x 版本
                self.client = mqtt.Client(client_id=self.client_id)
            
            # 设置回调函数
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect
            self.client.on_ping = self._on_ping
            self.client.on_socket_close = self._on_socket_close
            self.client.on_socket_open = self._on_socket_open
            
            # 设置连接参数
            self.client.keepalive = 60
            
            # 设置套接字选项，增强网络超时处理
            self.client.socket_timeout = 30  # 套接字超时
            self.client.socket_keepalive = True  # 启用TCP keepalive
            
            # 设置超时重试参数
            self.client.max_inflight_messages = 20
            self.client.max_queued_messages = 0  # 不限制队列大小
            
            # 开始连接
            logger.info(f"正在连接MQTT服务器: {self.mqtt_host}:{self.mqtt_port} (客户端: {self.client_id})")
            
            # 使用非阻塞连接，并添加异常处理
            try:
                self.client.connect_async(self.mqtt_host, self.mqtt_port, 60)
                # 启动自定义的loop来处理网络异常
                self._start_custom_loop()
            except Exception as connect_error:
                logger.error(f"启动MQTT连接时出错 (客户端: {self.client_id}): {str(connect_error)}")
                if self.auto_reconnect and self.is_running:
                    self._schedule_reconnect()
            
        except Exception as e:
            logger.error(f"连接MQTT服务器失败 (客户端: {self.client_id}): {str(e)}")
            if self.auto_reconnect and self.is_running:
                self._schedule_reconnect()

    def _start_custom_loop(self):
        """启动自定义的MQTT循环，增强错误处理"""
        try:
            # 使用非阻塞的loop_start，而不是阻塞的loop_forever
            self.client.loop_start()
        except Exception as loop_error:
            logger.error(f"MQTT客户端 {self.client_id} 启动loop时出错: {str(loop_error)}")
            # 如果还在运行且需要重连，触发重连
            if self.auto_reconnect and self.is_running:
                self._schedule_reconnect()

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT连接回调"""
        if rc == 0:
            self.is_connected = True
            self.last_connect_time = datetime.now()
            self.reconnect_attempts = 0
            self.current_reconnect_interval = self.reconnect_interval  # 重置重连间隔
            
            logger.info(f"MQTT客户端 {self.client_id} 连接成功")
            
            # 在Flask应用上下文中执行数据库查询
            if self._app:
                with self._app.app_context():
                    self._subscribe_device_topics()
        else:
            error_messages = {
                1: "连接被拒绝 - 协议版本不正确",
                2: "连接被拒绝 - 无效的客户端标识符",
                3: "连接被拒绝 - 服务器不可用",
                4: "连接被拒绝 - 用户名或密码错误",
                5: "连接被拒绝 - 未授权"
            }
            error_msg = error_messages.get(rc, f"连接被拒绝 - 未知错误码: {rc}")
            logger.error(f"MQTT客户端 {self.client_id} 连接失败: {error_msg}")
            
            if self.auto_reconnect and self.is_running:
                self._schedule_reconnect()

    def _on_disconnect(self, client, userdata, rc):
        """MQTT断连回调"""
        self.is_connected = False
        self.last_disconnect_time = datetime.now()
        
        if rc != 0:
            logger.warning(f"MQTT客户端 {self.client_id} 意外断开连接 (返回码: {rc})")
            if self.auto_reconnect and self.is_running:
                self._schedule_reconnect()
        else:
            logger.info(f"MQTT客户端 {self.client_id} 正常断开连接")

    def _on_ping(self, client, userdata, mid):
        """MQTT心跳回调"""
        self.last_ping_time = datetime.now()
        logger.debug(f"MQTT客户端 {self.client_id} 心跳正常")
    
    def _on_socket_open(self, client, userdata, sock):
        """套接字打开回调"""
        logger.debug(f"MQTT客户端 {self.client_id} 套接字已打开")
    
    def _on_socket_close(self, client, userdata, sock):
        """套接字关闭回调"""
        logger.warning(f"MQTT客户端 {self.client_id} 套接字已关闭，可能需要重连")
        self.is_connected = False
        if self.auto_reconnect and self.is_running:
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        """安排重连"""
        if not self.auto_reconnect or not self.is_running:
            return
            
        if self.max_reconnect_attempts > 0 and self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"MQTT客户端 {self.client_id} 已达到最大重连次数 ({self.max_reconnect_attempts})")
            return
        
        # 如果重连线程还在运行，则不启动新的
        if self.reconnect_thread and self.reconnect_thread.is_alive():
            return
            
        self.reconnect_thread = threading.Thread(target=self._reconnect_worker, daemon=True)
        self.reconnect_thread.start()

    def _reconnect_worker(self):
        """重连工作线程"""
        while self.auto_reconnect and self.is_running and not self.is_connected:
            self.reconnect_attempts += 1
            
            # 添加随机抖动，避免大量客户端同时重连
            jitter = random.uniform(0.5, 1.5)
            wait_time = self.current_reconnect_interval * jitter
            
            logger.info(f"MQTT客户端 {self.client_id} 将在 {wait_time:.1f} 秒后进行第 {self.reconnect_attempts} 次重连")
            
            if self.stop_event.wait(wait_time):
                break  # 收到停止信号
            
            if not self.auto_reconnect or not self.is_running:
                break
            
            try:
                logger.info(f"MQTT客户端 {self.client_id} 正在进行第 {self.reconnect_attempts} 次重连...")
                
                # 检查网络连通性
                if not self._check_network_connectivity():
                    logger.warning(f"MQTT客户端 {self.client_id} 网络不通，跳过此次重连")
                    # 继续等待，不增加重连间隔
                    continue
                
                # 完全清理旧连接
                if self.client:
                    try:
                        self.client.loop_stop()
                        self.client.disconnect()
                    except Exception as cleanup_error:
                        logger.debug(f"清理旧连接时出错: {cleanup_error}")
                    self.client = None
                
                # 重新建立连接
                self._connect()
                
                # 等待连接结果，增加等待时间
                connection_timeout = 15  # 增加到15秒
                for i in range(connection_timeout):
                    if self.is_connected:
                        logger.info(f"MQTT客户端 {self.client_id} 重连成功")
                        return  # 成功后直接返回
                    if not self.is_running:
                        break
                    time.sleep(1)
                
                # 连接失败处理
                if not self.is_connected:
                    # 增加重连间隔
                    self.current_reconnect_interval = min(
                        self.current_reconnect_interval * self.reconnect_backoff,
                        self.max_reconnect_interval
                    )
                    logger.warning(f"MQTT客户端 {self.client_id} 重连失败，下次间隔: {self.current_reconnect_interval:.1f} 秒")
                    
            except Exception as reconnect_error:
                logger.error(f"MQTT客户端 {self.client_id} 重连过程出现异常: {str(reconnect_error)}")
                # 增加重连间隔
                self.current_reconnect_interval = min(
                    self.current_reconnect_interval * self.reconnect_backoff,
                    self.max_reconnect_interval
                )
                
        logger.info(f"MQTT客户端 {self.client_id} 重连工作线程结束")

    def _start_health_check(self):
        """启动健康检查"""
        if self.health_check_thread and self.health_check_thread.is_alive():
            return
            
        self.health_check_thread = threading.Thread(target=self._health_check_worker, daemon=True)
        self.health_check_thread.start()

    def _health_check_worker(self):
        """健康检查工作线程"""
        while self.is_running and not self.stop_event.is_set():
            try:
                if self.client:
                    # 检查连接状态
                    if self.is_connected:
                        # 检查心跳超时
                        if (self.last_ping_time and 
                            datetime.now() - self.last_ping_time > timedelta(seconds=self.ping_timeout + self.ping_interval)):
                            logger.warning(f"MQTT客户端 {self.client_id} 心跳超时，触发重连")
                            self.is_connected = False
                            if self.auto_reconnect:
                                self._schedule_reconnect()
                        
                        # 检查客户端内部状态
                        try:
                            if not self.client.is_connected():
                                logger.warning(f"MQTT客户端 {self.client_id} 内部状态显示未连接，触发重连")
                                self.is_connected = False
                                if self.auto_reconnect:
                                    self._schedule_reconnect()
                        except AttributeError:
                            # 旧版本paho-mqtt可能没有is_connected方法
                            pass
                    else:
                        # 如果标记为未连接但没有重连在进行，触发重连
                        if self.auto_reconnect and not (self.reconnect_thread and self.reconnect_thread.is_alive()):
                            logger.info(f"MQTT客户端 {self.client_id} 未连接且无重连进程，启动重连")
                            self._schedule_reconnect()
                
                # 每15秒检查一次，更频繁的监控
                if self.stop_event.wait(15):
                    break
                    
            except Exception as e:
                logger.error(f"MQTT客户端 {self.client_id} 健康检查出错: {str(e)}")
                # 健康检查出错也可能表示连接问题，触发重连
                if self.auto_reconnect and self.is_running:
                    self.is_connected = False
                    self._schedule_reconnect()

    def _subscribe_device_topics(self):
        """订阅设备主题"""
        try:
            from models import Device
            # 只订阅可见设备的主题
            devices = Device.query.filter(
                Device.visible == True,
                Device.mqtt_topic.isnot(None)
            ).all()
            
            for device in devices:
                if device.mqtt_topic and device.mqtt_topic not in self.subscribed_topics:
                    self.client.subscribe(device.mqtt_topic)
                    self.subscribed_topics.add(device.mqtt_topic)
                    logger.info(f"客户端 {self.client_id} 已订阅主题: {device.mqtt_topic}")
        except Exception as e:
            logger.error(f"订阅设备主题失败: {str(e)}")

    def _on_message(self, client, userdata, msg):
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

    def subscribe_device_topic(self, topic):
        """订阅设备主题"""
        if self.client and self.is_connected and topic not in self.subscribed_topics:
            try:
                self.client.subscribe(topic)
                self.subscribed_topics.add(topic)
                logger.info(f"客户端 {self.client_id} 已订阅新主题: {topic}")
            except Exception as e:
                logger.error(f"客户端 {self.client_id} 订阅主题 {topic} 失败: {str(e)}")

    def unsubscribe_device_topic(self, topic):
        """取消订阅设备主题"""
        if self.client and self.is_connected and topic in self.subscribed_topics:
            try:
                self.client.unsubscribe(topic)
                self.subscribed_topics.remove(topic)
                logger.info(f"客户端 {self.client_id} 已取消订阅主题: {topic}")
            except Exception as e:
                logger.error(f"客户端 {self.client_id} 取消订阅主题 {topic} 失败: {str(e)}")

    def get_status(self):
        """获取客户端状态信息"""
        return {
            'client_id': self.client_id,
            'connected': self.is_connected,
            'running': self.is_running,
            'auto_reconnect': self.auto_reconnect,
            'reconnect_attempts': self.reconnect_attempts,
            'current_reconnect_interval': self.current_reconnect_interval,
            'last_connect_time': self.last_connect_time.isoformat() if self.last_connect_time else None,
            'last_disconnect_time': self.last_disconnect_time.isoformat() if self.last_disconnect_time else None,
            'last_ping_time': self.last_ping_time.isoformat() if self.last_ping_time else None,
            'subscribed_topics': list(self.subscribed_topics)
        }

    def _check_network_connectivity(self):
        """检查网络连通性"""
        try:
            # 尝试连接到MQTT服务器的端口
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)  # 5秒超时
            result = sock.connect_ex((self.mqtt_host, self.mqtt_port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"网络连通性检查失败: {str(e)}")
            return False


class MQTTManager:
    """支持多个巴法云账号的MQTT管理器，包含完善的重连机制"""
    
    def __init__(self):
        self.clients = {}  # {client_id: MQTTClient}
        self.is_running = False
        self._app = None  # Flask应用实例
        self.monitor_thread = None
        self.stop_event = threading.Event()

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
        self._start_monitor()

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
        logger.info("正在停止所有MQTT客户端...")
        
        self.is_running = False
        self.stop_event.set()
        
        # 停止监控线程
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        # 停止所有客户端
        for client_id, client in list(self.clients.items()):
            client.stop()
        
        self.clients.clear()
        logger.info("所有MQTT客户端已停止")

    def stop_client(self, client_id):
        """停止指定的MQTT客户端"""
        if client_id in self.clients:
            self.clients[client_id].stop()
            del self.clients[client_id]
            logger.info(f"MQTT客户端 {client_id} 已停止")

    def _start_monitor(self):
        """启动监控线程"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
            
        self.monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self.monitor_thread.start()

    def _monitor_worker(self):
        """监控工作线程，定期检查客户端状态"""
        while self.is_running and not self.stop_event.is_set():
            try:
                if self._app:
                    with self._app.app_context():
                        self._check_clients_health()
                
                # 每60秒检查一次
                if self.stop_event.wait(60):
                    break
                    
            except Exception as e:
                logger.error(f"MQTT监控线程出错: {str(e)}")

    def _check_clients_health(self):
        """检查客户端健康状态"""
        try:
            from models import BemfaKey
            
            # 获取应该运行的客户端列表
            bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
            expected_clients = {bemfa_key.key for bemfa_key in bemfa_keys}
            
            # 停止不应该运行的客户端
            current_clients = set(self.clients.keys())
            for client_id in current_clients - expected_clients:
                logger.info(f"停止不需要的MQTT客户端: {client_id}")
                self.stop_client(client_id)
            
            # 启动缺失的客户端
            for client_id in expected_clients - current_clients:
                logger.info(f"启动缺失的MQTT客户端: {client_id}")
                self.start_client(client_id)
            
        except Exception as e:
            logger.error(f"检查MQTT客户端健康状态时出错: {str(e)}")

    @property
    def is_connected(self):
        """检查是否有任何客户端连接"""
        return any(client.is_connected for client in self.clients.values())

    def get_connection_status(self):
        """获取所有客户端的详细连接状态"""
        status = {}
        for client_id, client in self.clients.items():
            status[client_id] = client.get_status()
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
                
                # 在启动MQTT前先同步一遍巴法云设备信息
                logger.info("启动MQTT前，先同步巴法云设备信息...")
                try:
                    self._sync_bemfa_devices_before_mqtt()
                except Exception as sync_error:
                    logger.warning(f"同步巴法云设备信息时出错: {str(sync_error)}")
                
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

    def _sync_bemfa_devices_before_mqtt(self):
        """在启动MQTT前同步巴法云设备信息"""
        try:
            from .bemfa_service import BemfaSyncService
            
            bemfa_sync_service = BemfaSyncService()
            result = bemfa_sync_service.sync_visible_devices_to_bemfa()
            
            if result:
                created_count = result.get('created_count', 0)
                updated_count = result.get('updated_count', 0)
                deleted_count = result.get('deleted_count', 0)
                failed_count = result.get('failed_count', 0)
                total_devices = result.get('total_devices', 0)
                accounts = result.get('accounts', [])
                
                if created_count > 0 or updated_count > 0 or deleted_count > 0:
                    sync_summary = []
                    if created_count > 0:
                        sync_summary.append(f"创建 {created_count} 个主题")
                    if updated_count > 0:
                        sync_summary.append(f"更新 {updated_count} 个昵称")
                    if deleted_count > 0:
                        sync_summary.append(f"删除 {deleted_count} 个多余主题")
                    
                    logger.info(f"巴法云设备同步完成: {', '.join(sync_summary)}")
                    
                    if len(accounts) > 1:
                        logger.info(f"同步到 {len(accounts)} 个巴法云账号:")
                        for account in accounts:
                            if account.get('success', False):
                                logger.info(f"  - {account['name']}: 创建 {account['created']}, 更新 {account['updated']}, 删除 {account['deleted']}")
                            else:
                                logger.warning(f"  - {account['name']}: 同步失败 - {account.get('error', '未知错误')}")
                    
                    if failed_count > 0:
                        logger.warning(f"同步过程中有 {failed_count} 个操作失败")
                else:
                    if total_devices > 0:
                        logger.info(f"所有 {total_devices} 个可见设备的巴法云主题都已同步，无需更新")
                    else:
                        logger.info("没有可见设备需要同步到巴法云")
            else:
                logger.info("巴法云设备同步完成，但没有返回同步结果")
                
        except ImportError:
            logger.warning("巴法云同步服务模块未找到，跳过设备信息同步")
        except Exception as e:
            logger.error(f"同步巴法云设备信息失败: {str(e)}")
            # 不抛出异常，允许MQTT服务继续启动

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