"""
配置模型
管理系统配置和巴法云密钥
"""

from datetime import datetime
from . import db


class Config(db.Model):
    """系统配置模型"""
    __tablename__ = 'config'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Config {self.key}>'


class BemfaKey(db.Model):
    """巴法云密钥模型"""
    __tablename__ = 'bemfa_key'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # 密钥名称/描述
    key = db.Column(db.String(100), nullable=False)  # 巴法云私钥
    enabled = db.Column(db.Boolean, default=True)  # 是否启用
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<BemfaKey {self.name}>' 