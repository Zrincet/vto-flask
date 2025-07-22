"""
设备模型
管理VTO门禁设备信息
"""

from datetime import datetime
from . import db


class Device(db.Model):
    """VTO门禁设备模型"""
    __tablename__ = 'device'
    
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

    def __repr__(self):
        return f'<Device {self.name} ({self.ip})>' 