"""
HomeKit模型
管理HomeKit配置和设备桥接
"""

from datetime import datetime
from . import db


class HomeKitConfig(db.Model):
    """HomeKit配置模型"""
    __tablename__ = 'homekit_config'
    
    id = db.Column(db.Integer, primary_key=True)
    bridge_name = db.Column(db.String(100), default='VTO门禁桥接器')  # 桥接器名称
    bridge_pin = db.Column(db.String(20), nullable=False)  # 配对PIN码
    bridge_port = db.Column(db.Integer, default=51827)  # HomeKit服务端口
    enabled = db.Column(db.Boolean, default=False)  # 是否启用HomeKit服务
    manufacturer = db.Column(db.String(100), default='VTO Systems')  # 制造商
    model = db.Column(db.String(100), default='Door Lock Bridge')  # 型号
    firmware_version = db.Column(db.String(50), default='1.0.0')  # 固件版本
    serial_number = db.Column(db.String(100), nullable=True)  # 序列号
    setup_id = db.Column(db.String(4), nullable=True)  # HomeKit设置ID
    category = db.Column(db.Integer, default=2)  # HomeKit类别（2=桥接器）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<HomeKitConfig {self.bridge_name}>'


class HomeKitDevice(db.Model):
    """HomeKit设备桥接模型"""
    __tablename__ = 'homekit_device'
    
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False)  # 关联的VTO设备
    homekit_aid = db.Column(db.Integer, unique=True, nullable=True)  # HomeKit配件ID
    homekit_name = db.Column(db.String(100), nullable=False)  # HomeKit中显示的名称
    enabled = db.Column(db.Boolean, default=True)  # 是否启用HomeKit集成
    lock_current_state = db.Column(db.Integer, default=1)  # 锁当前状态 (0=未知, 1=锁定, 0=解锁)
    lock_target_state = db.Column(db.Integer, default=1)  # 锁目标状态 (0=解锁, 1=锁定)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联到Device表
    device = db.relationship('Device', backref='homekit_device', lazy=True)

    def __repr__(self):
        return f'<HomeKitDevice {self.homekit_name}>' 