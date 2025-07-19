"""
HomeKit服务模块
提供HomeKit桥接服务和设备管理功能
"""

import logging
import threading
import time
import os
from datetime import datetime

# 延迟导入，避免循环导入
def get_db():
    from app import db
    return db

def get_app():
    """获取Flask应用实例，处理循环导入"""
    try:
        from app import app
        return app
    except ImportError:
        # 如果直接导入失败，尝试从Flask上下文获取
        try:
            from flask import current_app
            return current_app._get_current_object()
        except Exception:
            # 如果都失败了，返回None并记录错误
            logger.error("无法获取Flask应用实例")
            return None

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
                        app = get_app()
                        if not app:
                            logger.error("无法获取Flask应用实例，无法设置锁状态")
                            return
                        
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
                                        app = get_app()
                                        if not app:
                                            logger.error("无法获取Flask应用实例，无法执行自动锁定")
                                            return
                                        
                                        with app.app_context():
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
            
            app = get_app()
            if not app:
                logger.error("无法获取Flask应用实例，无法启动HomeKit服务")
                return False
            
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
                
                # 生成稳定的MAC地址和状态文件
                bridge_mac = self._generate_stable_bridge_mac(homekit_config)
                state_file = self._get_homekit_state_file(homekit_config)
                
                # 检查配置变化，只在必要时清理状态文件
                self._check_and_clean_if_needed(homekit_config, bridge_mac)
                
                self.driver = AccessoryDriver(
                    port=homekit_config.bridge_port,
                    pincode=formatted_pin.encode(),
                    persist_file=state_file,
                    mac=bridge_mac  # 直接在driver中设置MAC地址
                )
                
                # 创建桥接器，传入driver
                self.bridge = Bridge(
                    driver=self.driver,
                    display_name=homekit_config.bridge_name
                )
                
                # 添加设备配件到桥接器
                self._add_device_accessories()
                
                # 使用官方推荐的方式设置accessory
                self.driver.add_accessory(accessory=self.bridge)
                
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
            logger.info("正在停止HomeKit桥接服务...")
            
            # 设置停止标志
            self.is_running = False
            
            # 停止驱动器
            if self.driver:
                try:
                    self.driver.stop()
                    logger.info("HomeKit驱动器已停止")
                except Exception as e:
                    logger.warning(f"停止驱动器时出错: {str(e)}")
                finally:
                    self.driver = None
            
            # 等待HomeKit线程结束
            if self._homekit_thread and self._homekit_thread.is_alive():
                logger.info("等待HomeKit线程结束...")
                self._homekit_thread.join(timeout=10)
                if self._homekit_thread.is_alive():
                    logger.warning("HomeKit线程未能在10秒内结束")
            
            # 清理资源
            self.bridge = None
            self.accessories.clear()
            self._homekit_thread = None
            
            logger.info("HomeKit桥接服务已完全停止")
            return True
            
        except Exception as e:
            logger.error(f"停止HomeKit服务失败: {str(e)}")
            return False
    
    def restart_homekit_service(self):
        """重启HomeKit桥接服务"""
        self.stop_homekit_service()
        time.sleep(2)  # 等待完全停止
        return self.start_homekit_service()
    
    def reset_homekit_service(self):
        """重置HomeKit服务（清理所有状态）"""
        try:
            logger.info("正在重置HomeKit服务...")
            
            # 停止服务
            self.stop_homekit_service()
            
            # 清理所有状态文件
            self._cleanup_homekit_files()
            
            # 等待一段时间确保完全清理
            time.sleep(3)
            
            logger.info("HomeKit服务重置完成")
            return True
            
        except Exception as e:
            logger.error(f"重置HomeKit服务失败: {str(e)}")
            return False
    
    def _get_homekit_state_file(self, homekit_config):
        """生成固定的HomeKit状态文件路径"""
        # 使用固定的文件名，确保重启后能正确加载状态
        return "vto_homekit.state"
    
    def _generate_stable_bridge_mac(self, homekit_config):
        """生成稳定的桥接器MAC地址"""
        import hashlib
        
        # 使用桥接器配置生成稳定的MAC地址
        bridge_id = f"{homekit_config.bridge_name}_{homekit_config.bridge_port}_{homekit_config.bridge_pin}"
        hash_obj = hashlib.md5(bridge_id.encode())
        hash_bytes = hash_obj.digest()
        
        # 生成MAC地址格式 (XX:XX:XX:XX:XX:XX)
        # 确保第一个字节的最低位为0（单播地址）且第二位为1（本地管理地址）
        mac_bytes = list(hash_bytes[:6])
        mac_bytes[0] = (mac_bytes[0] & 0xFC) | 0x02  # 设置为本地管理地址
        
        mac_address = ':'.join(f'{b:02X}' for b in mac_bytes)
        logger.debug(f"生成稳定的桥接器MAC地址: {mac_address}")
        return mac_address
    
    def _check_and_clean_if_needed(self, homekit_config, bridge_mac):
        """检查配置变化，必要时清理状态文件"""
        import os
        
        try:
            metadata_file = 'vto_homekit_metadata.json'
            state_file = 'vto_homekit.state'
            
            if os.path.exists(metadata_file):
                # 检查关键配置是否变化
                if self._critical_config_changed(metadata_file, homekit_config, bridge_mac):
                    logger.info("检测到关键配置变化，清理状态文件")
                    # 清理状态文件，让pyhap重新生成
                    if os.path.exists(state_file):
                        os.remove(state_file)
                        logger.info(f"已删除状态文件: {state_file}")
                    # 删除元数据文件
                    os.remove(metadata_file)
                else:
                    logger.debug("配置无关键变化，保持现有状态")
            
            # 保存当前配置到元数据
            self._save_simple_metadata(metadata_file, homekit_config, bridge_mac)
            
        except Exception as e:
            logger.warning(f"配置检查时出错: {str(e)}")
            # 出错时保守处理，清理状态文件
            try:
                if os.path.exists('vto_homekit.state'):
                    os.remove('vto_homekit.state')
            except:
                pass
    
    def _critical_config_changed(self, metadata_file, homekit_config, bridge_mac):
        """检查关键配置是否变化（只检查影响配对的配置）"""
        import json
        
        try:
            with open(metadata_file, 'r') as f:
                stored_metadata = json.load(f)
            
            # 只检查影响HomeKit配对的关键配置
            critical_changed = (
                stored_metadata.get('bridge_name') != homekit_config.bridge_name or
                stored_metadata.get('bridge_port') != homekit_config.bridge_port or
                stored_metadata.get('bridge_pin') != homekit_config.bridge_pin or
                stored_metadata.get('bridge_mac') != bridge_mac
            )
            
            if critical_changed:
                logger.info("关键配置发生变化:")
                if stored_metadata.get('bridge_name') != homekit_config.bridge_name:
                    logger.info(f"  桥接器名称: {stored_metadata.get('bridge_name')} -> {homekit_config.bridge_name}")
                if stored_metadata.get('bridge_port') != homekit_config.bridge_port:
                    logger.info(f"  端口: {stored_metadata.get('bridge_port')} -> {homekit_config.bridge_port}")
                if stored_metadata.get('bridge_pin') != homekit_config.bridge_pin:
                    logger.info(f"  PIN码: {stored_metadata.get('bridge_pin')} -> {homekit_config.bridge_pin}")
                if stored_metadata.get('bridge_mac') != bridge_mac:
                    logger.info(f"  MAC地址: {stored_metadata.get('bridge_mac')} -> {bridge_mac}")
            
            return critical_changed
            
        except Exception as e:
            logger.error(f"检查关键配置时出错: {str(e)}")
            return True  # 出错时认为有变化，清理状态
    
    def _save_simple_metadata(self, metadata_file, homekit_config, bridge_mac):
        """保存简化的元数据"""
        import json
        
        try:
            metadata = {
                'bridge_name': homekit_config.bridge_name,
                'bridge_port': homekit_config.bridge_port,
                'bridge_pin': homekit_config.bridge_pin,
                'bridge_mac': bridge_mac,
                'last_update': time.time()
            }
            
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.debug(f"已保存简化元数据到: {metadata_file}")
            
        except Exception as e:
            logger.error(f"保存简化元数据时出错: {str(e)}")


    
    def _cleanup_homekit_files(self):
        """清理HomeKit相关文件"""
        import os
        import glob
        
        try:
            # 清理HomeKit相关文件
            files_to_clean = [
                "vto_homekit.state",        # 固定的状态文件
                "vto_homekit_metadata.json", # 固定的元数据文件
                "accessory.state",          # 旧版状态文件
            ]
            
            # 添加通配符模式清理（用于清理旧的动态命名文件）
            patterns_to_clean = [
                "vto_homekit_*.state",      # 旧的动态状态文件
                "vto_homekit_*_metadata.json",  # 旧的动态元数据文件
                "homekit_state*.json",      # 旧的状态文件（兼容清理）
                "homekit_state*_metadata.json",  # 旧的元数据文件
                "*.hap",                    # HAP缓存文件
                ".homekit_*"               # 隐藏的HomeKit文件
            ]
            
            # 清理固定文件
            for file in files_to_clean:
                if os.path.exists(file):
                    try:
                        os.remove(file)
                        logger.info(f"已清理文件: {file}")
                    except Exception as e:
                        logger.warning(f"清理文件 {file} 时出错: {str(e)}")
            
            # 清理通配符文件
            
            for pattern in patterns_to_clean:
                files = glob.glob(pattern)
                for file in files:
                    try:
                        os.remove(file)
                        logger.info(f"已清理文件: {file}")
                    except Exception as e:
                        logger.warning(f"清理文件 {file} 时出错: {str(e)}")
                        
        except Exception as e:
            logger.error(f"清理HomeKit文件时出错: {str(e)}")

    def _add_device_accessories(self):
        """添加设备配件到桥接器"""
        try:
            from pyhap.accessory import Accessory
            from pyhap.const import CATEGORY_DOOR_LOCK
            
            HomeKitConfig, HomeKitDevice, Device = get_models()
            
            # 获取启用HomeKit的设备，并按ID排序确保稳定的添加顺序
            homekit_devices = HomeKitDevice.query.filter_by(enabled=True).order_by(HomeKitDevice.device_id).all()
            
            for hk_device in homekit_devices:
                device = hk_device.device
                if device and device.visible:
                    # 生成稳定的AID（基于设备ID）
                    stable_aid = self._generate_stable_aid(device.id)
                    
                    # 创建门锁配件
                    accessory = DoorLockAccessory(
                        driver=self.driver,
                        display_name=hk_device.homekit_name,
                        device_id=device.id
                    )
                    
                    # 设置稳定的AID
                    accessory.accessory.aid = stable_aid
                    
                    # 添加到桥接器
                    self.bridge.add_accessory(accessory.accessory)
                    self.accessories[device.id] = accessory
                    
                    logger.info(f"添加HomeKit设备: {hk_device.homekit_name} (ID: {device.id}, AID: {stable_aid})")
            
        except Exception as e:
            logger.error(f"添加设备配件失败: {str(e)}")
    
    def _generate_stable_aid(self, device_id):
        """生成稳定的Accessory ID"""
        # 使用设备ID生成稳定的AID
        # AID必须在2-255之间，且不能是7（pyhap的限制）
        base_aid = (device_id % 254) + 2  # 确保在2-255范围内
        if base_aid == 7:
            base_aid = 8  # 避免使用AID=7
        return base_aid
    
    def add_device_accessory(self, device_id):
        """动态添加设备配件"""
        try:
            app = get_app()
            if not app:
                logger.error("无法获取Flask应用实例，无法添加设备配件")
                return False
            
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
                    
                    # 生成稳定的AID
                    stable_aid = self._generate_stable_aid(device.id)
                    
                    accessory = DoorLockAccessory(
                        driver=self.driver,
                        display_name=hk_device.homekit_name,
                        device_id=device.id
                    )
                    
                    # 设置稳定的AID
                    accessory.accessory.aid = stable_aid
                    
                    self.bridge.add_accessory(accessory.accessory)
                    self.accessories[device.id] = accessory
                    
                    logger.info(f"动态添加HomeKit设备: {hk_device.homekit_name} (AID: {stable_aid})")
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
            app = get_app()
            if not app:
                logger.error("无法获取Flask应用实例，无法初始化HomeKit服务")
                return
            
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
    
    def reset_service(self):
        """重置HomeKit服务（清理所有状态）"""
        return self.manager.reset_homekit_service()
    
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