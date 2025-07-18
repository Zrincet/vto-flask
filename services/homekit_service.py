"""
HomeKit服务模块
提供HomeKit桥接服务和设备管理功能
"""

import logging
import threading
import time
import os
from datetime import datetime
from flask import current_app as app

# 延迟导入，避免循环导入
def get_db():
    from app import db
    return db

def get_models():
    from models.homekit import HomeKitConfig, HomeKitDevice
    from models.device import Device
    return HomeKitConfig, HomeKitDevice, Device

def get_dahua_service():
    from services.dahua_service import DahuaService
    return DahuaService

logger = logging.getLogger(__name__)

# HomeKit工具函数
def format_homekit_pincode(pin_digits):
    """将8位数字PIN码转换为HomeKit格式 (xxx-xx-xxx)"""
    if not pin_digits or len(pin_digits) != 8:
        raise ValueError("PIN码必须是8位数字")
    
    return f"{pin_digits[:3]}-{pin_digits[3:5]}-{pin_digits[5:]}"

def parse_homekit_pincode(formatted_pin):
    """从HomeKit格式PIN码提取8位数字"""
    if not formatted_pin:
        return None
    
    return formatted_pin.replace('-', '')

# 门锁配件类
class DoorLockAccessory:
    """HomeKit门锁配件"""
    def __init__(self, driver, display_name, device_id):
        try:
            from pyhap.accessory import Accessory
            from pyhap.const import CATEGORY_DOOR_LOCK
            
            # 继承Accessory类
            class LockAccessory(Accessory):
                category = CATEGORY_DOOR_LOCK
                
                def __init__(self, driver, display_name, device_id):
                    super().__init__(driver, display_name)
                    self.device_id = device_id
                    
                    # 添加锁定机制服务
                    serv_lock = driver.loader.get_service('LockMechanism')
                    self.add_service(serv_lock)
                    
                    # 锁定当前状态特征 (只读)
                    self.char_lock_current_state = serv_lock.get_characteristic('LockCurrentState')
                    
                    # 锁定目标状态特征 (可读写)
                    self.char_lock_target_state = serv_lock.get_characteristic('LockTargetState')
                    self.char_lock_target_state.setter_callback = self.set_lock_state
                    
                    # 设置初始状态
                    self.char_lock_current_state.set_value(1)  # 1=锁定
                    self.char_lock_target_state.set_value(1)  # 1=锁定
                
                def set_lock_state(self, value):
                    """设置锁状态"""
                    try:
                        with app.app_context():
                            # 如果目标状态是解锁 (0)
                            if value == 0:
                                logger.info(f"HomeKit请求解锁设备 ID: {self.device_id}")
                                
                                # 执行开锁操作
                                result = self._execute_unlock()
                                
                                if result:
                                    # 开锁成功，更新状态
                                    self.char_lock_current_state.set_value(0)  # 解锁
                                    logger.info(f"HomeKit设备 {self.device_id} 解锁成功")
                                    
                                    # 延迟自动锁定（模拟门锁行为）
                                    def auto_lock():
                                        time.sleep(5)  # 5秒后自动锁定
                                        self.char_lock_current_state.set_value(1)
                                        self.char_lock_target_state.set_value(1)
                                        logger.info(f"HomeKit设备 {self.device_id} 自动锁定")
                                    
                                    threading.Thread(target=auto_lock, daemon=True).start()
                                else:
                                    # 开锁失败，保持锁定状态
                                    logger.error(f"HomeKit设备 {self.device_id} 解锁失败")
                                    self.char_lock_target_state.set_value(1)  # 重置为锁定
                            else:
                                # 目标状态是锁定 (1)，直接设置
                                self.char_lock_current_state.set_value(1)
                                logger.info(f"HomeKit设备 {self.device_id} 设置为锁定状态")
                    
                    except Exception as e:
                        logger.error(f"HomeKit设置锁状态失败: {str(e)}")
                        # 出错时重置为锁定状态
                        self.char_lock_current_state.set_value(1)
                        self.char_lock_target_state.set_value(1)
                
                def _execute_unlock(self):
                    """执行实际的开锁操作"""
                    try:
                        HomeKitConfig, HomeKitDevice, Device = get_models()
                        DahuaService = get_dahua_service()
                        db = get_db()
                        
                        device = Device.query.get(self.device_id)
                        if not device:
                            logger.error(f"设备不存在: {self.device_id}")
                            return False
                        
                        # 使用DahuaService执行开锁
                        dahua_client = DahuaService(
                            ip=device.ip,
                            username=device.username,
                            password=device.password
                        )
                        
                        result = dahua_client.execute_door_open_flow()
                        
                        if result["success"]:
                            # 更新数据库中的开锁时间
                            device.last_unlock_time = datetime.utcnow()
                            db.session.commit()
                            return True
                        else:
                            logger.error(f"开锁失败: {result.get('message', '未知错误')}")
                            return False
                    
                    except Exception as e:
                        logger.error(f"执行开锁操作失败: {str(e)}")
                        return False
            
            # 创建配件实例
            self.accessory = LockAccessory(driver, display_name, device_id)
            
        except Exception as e:
            logger.error(f"创建门锁配件失败: {str(e)}")
            raise

# HomeKit桥接服务管理类
class HomeKitManager:
    """HomeKit桥接服务管理器"""
    def __init__(self):
        self.bridge = None
        self.accessories = {}  # {device_id: accessory}
        self.is_running = False
        self.driver = None
        self._homekit_thread = None
        
    def start_homekit_service(self):
        """启动HomeKit桥接服务"""
        try:
            # 动态导入HAP-python相关模块
            from pyhap.accessory import Bridge
            from pyhap.accessory_driver import AccessoryDriver
            from pyhap.const import CATEGORY_BRIDGE
            import pyhap.loader as loader
            
            with app.app_context():
                HomeKitConfig, HomeKitDevice, Device = get_models()
                
                # 获取HomeKit配置
                homekit_config = HomeKitConfig.query.first()
                if not homekit_config or not homekit_config.enabled:
                    logger.info("HomeKit服务未启用")
                    return False
                
                # 检查PIN码格式
                if not homekit_config.bridge_pin or len(homekit_config.bridge_pin) != 8:
                    logger.error("HomeKit PIN码格式错误，必须是8位数字")
                    return False
                
                # 创建临时AccessoryDriver用于初始化Bridge
                from pyhap.accessory_driver import AccessoryDriver
                from pyhap.loader import get_loader
                
                # 先创建一个AccessoryDriver（暂不传入accessory）
                # 将8位数字PIN码转换为HAP-python要求的格式 (xxx-xx-xxx)
                formatted_pin = format_homekit_pincode(homekit_config.bridge_pin)
                self.driver = AccessoryDriver(
                    port=homekit_config.bridge_port,
                    pincode=formatted_pin.encode(),
                    persist_file='homekit_state.json'
                )
                
                # 创建桥接器，传入driver
                self.bridge = Bridge(
                    driver=self.driver,
                    display_name=homekit_config.bridge_name
                )
                
                # 将Bridge设置为driver的accessory
                self.driver.accessory = self.bridge
                
                # 添加设备配件
                self._add_device_accessories()
                
                # 在单独的线程中启动HomeKit服务
                def run_homekit():
                    try:
                        logger.info(f"HomeKit桥接器正在启动，端口: {homekit_config.bridge_port}")
                        logger.info(f"配对PIN码: {formatted_pin}")
                        self.driver.start()
                    except Exception as e:
                        logger.error(f"HomeKit服务运行错误: {str(e)}")
                
                self._homekit_thread = threading.Thread(target=run_homekit, daemon=True)
                self._homekit_thread.start()
                
                self.is_running = True
                logger.info("HomeKit桥接服务启动成功")
                return True
                
        except ImportError as e:
            logger.error(f"HomeKit依赖包未安装: {str(e)}")
            return False
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"启动HomeKit服务失败: {str(e)}")
            return False
    
    def stop_homekit_service(self):
        """停止HomeKit桥接服务"""
        try:
            if self.driver:
                self.driver.stop()
                self.driver = None
            
            if self._homekit_thread and self._homekit_thread.is_alive():
                # 等待线程结束（最多等待5秒）
                self._homekit_thread.join(timeout=5)
            
            self.bridge = None
            self.accessories.clear()
            self.is_running = False
            logger.info("HomeKit桥接服务已停止")
            return True
            
        except Exception as e:
            logger.error(f"停止HomeKit服务失败: {str(e)}")
            return False
    
    def restart_homekit_service(self):
        """重启HomeKit桥接服务"""
        self.stop_homekit_service()
        time.sleep(2)  # 等待完全停止
        return self.start_homekit_service()
    
    def _add_device_accessories(self):
        """添加设备配件到桥接器"""
        try:
            from pyhap.accessory import Accessory
            from pyhap.const import CATEGORY_DOOR_LOCK
            
            HomeKitConfig, HomeKitDevice, Device = get_models()
            
            # 获取启用HomeKit的设备
            homekit_devices = HomeKitDevice.query.filter_by(enabled=True).all()
            
            for hk_device in homekit_devices:
                device = hk_device.device
                if device and device.visible:
                    # 创建门锁配件
                    accessory = DoorLockAccessory(
                        driver=self.driver,
                        display_name=hk_device.homekit_name,
                        device_id=device.id
                    )
                    
                    # 添加到桥接器
                    self.bridge.add_accessory(accessory.accessory)
                    self.accessories[device.id] = accessory
                    
                    logger.info(f"添加HomeKit设备: {hk_device.homekit_name} (ID: {device.id})")
            
        except Exception as e:
            logger.error(f"添加设备配件失败: {str(e)}")
    
    def add_device_accessory(self, device_id):
        """动态添加设备配件"""
        try:
            with app.app_context():
                HomeKitConfig, HomeKitDevice, Device = get_models()
                
                hk_device = HomeKitDevice.query.filter_by(device_id=device_id, enabled=True).first()
                if not hk_device:
                    return False
                
                device = hk_device.device
                if not device or not device.visible:
                    return False
                
                # 如果服务正在运行且设备未添加
                if self.is_running and device_id not in self.accessories:
                    from pyhap.accessory import Accessory
                    from pyhap.const import CATEGORY_DOOR_LOCK
                    
                    accessory = DoorLockAccessory(
                        driver=self.driver,
                        display_name=hk_device.homekit_name,
                        device_id=device.id
                    )
                    
                    self.bridge.add_accessory(accessory.accessory)
                    self.accessories[device.id] = accessory
                    
                    logger.info(f"动态添加HomeKit设备: {hk_device.homekit_name}")
                    return True
                
            return False
            
        except Exception as e:
            logger.error(f"动态添加设备配件失败: {str(e)}")
            return False
    
    def remove_device_accessory(self, device_id):
        """动态移除设备配件"""
        try:
            if device_id in self.accessories:
                # HAP-python目前不支持动态移除配件，建议重启服务
                logger.info(f"移除HomeKit设备 (ID: {device_id})，建议重启HomeKit服务")
                del self.accessories[device_id]
                return True
            return False
            
        except Exception as e:
            logger.error(f"移除设备配件失败: {str(e)}")
            return False
    
    def get_service_status(self):
        """获取HomeKit服务状态"""
        return {
            'running': self.is_running,
            'device_count': len(self.accessories),
            'bridge_name': self.bridge.display_name if self.bridge else None,
            'port': self.driver.state.port if self.driver else None
        }
    
    def get_pairing_qr_code(self):
        """获取配对二维码数据"""
        try:
            if not self.is_running or not self.bridge:
                return None
            
            # 生成XHM URI
            from pyhap import SUPPORT_QR_CODE
            if SUPPORT_QR_CODE:
                import base64
                import io
                from pyqrcode import QRCode
                
                xhm_uri = self.bridge.xhm_uri()
                
                # 生成二维码
                qr = QRCode(xhm_uri)
                buffer = io.BytesIO()
                qr.png(buffer, scale=4)
                qr_data = base64.b64encode(buffer.getvalue()).decode()
                
                return {
                    'qr_code_data': qr_data,
                    'setup_code': self.driver.state.pincode.decode(),
                    'xhm_uri': xhm_uri
                }
            else:
                return {
                    'setup_code': self.driver.state.pincode.decode() if self.driver else None
                }
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"生成配对二维码失败: {str(e)}")
            return None

class HomeKitService:
    """HomeKit服务封装类"""
    
    def __init__(self):
        self.manager = HomeKitManager()
    
    def init_homekit_service(self):
        """程序启动时初始化HomeKit服务"""
        try:
            with app.app_context():
                HomeKitConfig, _, _ = get_models()
                
                # 获取HomeKit配置
                homekit_config = HomeKitConfig.query.first()
                if not homekit_config or not homekit_config.enabled:
                    logger.info("HomeKit服务未启用")
                    return
                
                logger.info("正在启动HomeKit桥接服务...")
                success = self.manager.start_homekit_service()
                
                if success:
                    logger.info("HomeKit桥接服务启动完成")
                else:
                    logger.error("HomeKit桥接服务启动失败")
                    
        except Exception as e:
            logger.error(f"启动HomeKit服务时出错: {str(e)}")
    
    def start_service(self):
        """启动HomeKit服务"""
        return self.manager.start_homekit_service()
    
    def stop_service(self):
        """停止HomeKit服务"""
        return self.manager.stop_homekit_service()
    
    def restart_service(self):
        """重启HomeKit服务"""
        return self.manager.restart_homekit_service()
    
    def get_service_status(self):
        """获取服务状态"""
        return self.manager.get_service_status()
    
    def get_pairing_qr_code(self):
        """获取配对二维码"""
        return self.manager.get_pairing_qr_code()
    
    def add_device_accessory(self, device_id):
        """添加设备配件"""
        return self.manager.add_device_accessory(device_id)
    
    def remove_device_accessory(self, device_id):
        """移除设备配件"""
        return self.manager.remove_device_accessory(device_id) 