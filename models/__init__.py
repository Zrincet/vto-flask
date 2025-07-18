"""
数据库模型模块
包含所有SQLAlchemy模型定义
"""

from flask_sqlalchemy import SQLAlchemy

# 创建数据库实例，将在app.py中初始化
db = SQLAlchemy()

def init_app(app):
    """初始化Flask应用的数据库"""
    db.init_app(app)

# 导入所有模型
from .user import User
from .device import Device
from .config import Config, BemfaKey
from .homekit import HomeKitConfig, HomeKitDevice

__all__ = [
    'db',
    'User',
    'Device', 
    'Config',
    'BemfaKey',
    'HomeKitConfig',
    'HomeKitDevice',
    'init_app'
]
