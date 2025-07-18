"""
业务服务模块
包含各种业务逻辑服务
"""

from .dahua_service import DahuaService
from .mqtt_service import MQTTClient, MQTTManager, mqtt_manager
from .bemfa_service import BemfaService, BemfaSyncService, bemfa_service, bemfa_sync_service, BemfaAPI
from .homekit_service import HomeKitService, HomeKitManager, DoorLockAccessory, format_homekit_pincode, parse_homekit_pincode

# 创建全局HomeKit服务实例
homekit_service = HomeKitService()

__all__ = [
    'DahuaService',
    'MQTTClient',
    'MQTTManager', 
    'mqtt_manager',
    'BemfaService',
    'BemfaSyncService',
    'bemfa_service',
    'bemfa_sync_service',
    'BemfaAPI',  # 向后兼容别名
    'HomeKitService',
    'HomeKitManager',
    'DoorLockAccessory',
    'homekit_service',
    'format_homekit_pincode',
    'parse_homekit_pincode'
]
