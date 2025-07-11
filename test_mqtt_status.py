#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MQTT服务状态检查脚本
用于测试和诊断MQTT自动启动功能
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, Config, Device, mqtt_manager
import time

def check_mqtt_status():
    """检查MQTT服务状态"""
    with app.app_context():
        print("=== VTO MQTT服务状态检查 ===")
        print()
        
        # 检查配置
        print("1. 检查配置信息:")
        mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
        bemfa_config = Config.query.filter_by(key='bemfa_private_key').first()
        
        mqtt_enabled = mqtt_config.value == 'true' if mqtt_config else False
        bemfa_key = bemfa_config.value if bemfa_config else None
        
        print(f"   MQTT已启用: {mqtt_enabled}")
        print(f"   巴法云私钥: {'已配置' if bemfa_key else '未配置'}")
        if bemfa_key:
            print(f"   私钥长度: {len(bemfa_key)} 字符")
        print()
        
        # 检查设备
        print("2. 检查设备信息:")
        total_devices = Device.query.count()
        visible_devices = Device.query.filter_by(visible=True).count()
        devices_with_topics = Device.query.filter(Device.mqtt_topic.isnot(None)).count()
        
        print(f"   总设备数: {total_devices}")
        print(f"   可见设备数: {visible_devices}")
        print(f"   有MQTT主题的设备: {devices_with_topics}")
        print()
        
        # 检查MQTT服务状态
        print("3. 检查MQTT服务状态:")
        print(f"   服务运行中: {mqtt_manager.is_running}")
        print(f"   连接状态: {mqtt_manager.is_connected}")
        print(f"   已订阅主题数: {len(mqtt_manager.subscribed_topics)}")
        
        if mqtt_manager.subscribed_topics:
            print("   已订阅的主题:")
            for topic in sorted(mqtt_manager.subscribed_topics):
                print(f"     - {topic}")
        print()
        
        # 诊断建议
        print("4. 诊断建议:")
        if not mqtt_enabled:
            print("   ⚠️  MQTT服务未启用，请在设置页面启用MQTT服务")
        elif not bemfa_key:
            print("   ⚠️  未配置巴法云私钥，请在设置页面配置私钥")
        elif not mqtt_manager.is_running:
            print("   ⚠️  MQTT服务未运行，可能需要手动启动或检查网络连接")
        elif not mqtt_manager.is_connected:
            print("   ⚠️  MQTT服务已启动但未连接，请检查网络和私钥是否正确")
        elif visible_devices == 0:
            print("   ⚠️  没有可见设备，请在设备配置页面设置可见设备")
        elif len(mqtt_manager.subscribed_topics) == 0:
            print("   ⚠️  没有订阅任何主题，请检查可见设备的MQTT主题配置")
        else:
            print("   ✅ MQTT服务运行正常")
        
        print()
        
        # 显示可见设备详情
        if visible_devices > 0:
            print("5. 可见设备详情:")
            visible_device_list = Device.query.filter_by(visible=True).all()
            for device in visible_device_list:
                print(f"   {device.name} ({device.ip}) - {device.mqtt_topic}")
        
        print("=== 检查完成 ===")

def test_mqtt_connection():
    """测试MQTT连接"""
    with app.app_context():
        bemfa_config = Config.query.filter_by(key='bemfa_private_key').first()
        if not bemfa_config or not bemfa_config.value:
            print("❌ 无法测试：未配置巴法云私钥")
            return
        
        print("正在测试MQTT连接...")
        
        if not mqtt_manager.is_running:
            print("启动MQTT服务...")
            try:
                mqtt_manager.start_mqtt_service("bemfa.com", 9501, bemfa_config.value)
                time.sleep(3)  # 等待连接
            except Exception as e:
                print(f"❌ 启动失败: {e}")
                return
        
        if mqtt_manager.is_connected:
            print("✅ MQTT连接成功")
        else:
            print("❌ MQTT连接失败")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_mqtt_connection()
    else:
        check_mqtt_status() 