"""
路由模块
包含各种业务路由
"""

from .auth import auth_bp
from .device import device_bp
from .homekit import homekit_bp
from .video import video_bp
from .settings import settings_bp

__all__ = [
    'auth_bp',
    'device_bp',
    'homekit_bp',
    'video_bp',
    'settings_bp'
] 