"""
HomeKit设备管理相关路由
包含HomeKit配置和设备管理功能
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
import logging
from datetime import datetime

# 延迟导入，避免循环导入
def get_db():
    from app import db
    return db

def get_models():
    from models.device import Device
    from models.homekit import HomeKitConfig, HomeKitDevice
    return Device, HomeKitConfig, HomeKitDevice

def get_services():
    from services import homekit_service
    return homekit_service

def get_login_required():
    from app import login_required
    return login_required

# 创建HomeKit蓝图
homekit_bp = Blueprint('homekit', __name__)
logger = logging.getLogger(__name__)

@homekit_bp.route('/homekit_config')
def homekit_config():
    """HomeKit配置页面"""
    login_required = get_login_required()
    Device, HomeKitConfig, HomeKitDevice = get_models()
    homekit_service = get_services()
    
    @login_required
    def _homekit_config():
        homekit_config = HomeKitConfig.query.first()
        homekit_devices = HomeKitDevice.query.all()
        available_devices = Device.query.filter_by(visible=True).all()
        homekit_status = homekit_service.get_service_status()
        
        return render_template('homekit_config.html',
                             homekit_config=homekit_config,
                             homekit_devices=homekit_devices,
                             available_devices=available_devices,
                             homekit_status=homekit_status)
    
    return _homekit_config()

@homekit_bp.route('/save_homekit_config', methods=['POST'])
def save_homekit_config():
    """保存HomeKit配置"""
    login_required = get_login_required()
    Device, HomeKitConfig, HomeKitDevice = get_models()
    homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _save_homekit_config():
        try:
            bridge_name = request.form.get('bridge_name', 'VTO Bridge').strip()
            bridge_pin = request.form.get('bridge_pin', '').strip()
            bridge_port = int(request.form.get('bridge_port', 51827))
            enabled = request.form.get('enabled') == 'on'
            
            # 验证PIN码格式
            if not bridge_pin.isdigit() or len(bridge_pin) != 8:
                flash('HomeKit PIN码必须是8位数字', 'error')
                return redirect(url_for('homekit.homekit_config'))
            
            # 验证端口范围
            if not (1024 <= bridge_port <= 65535):
                flash('端口号必须在1024-65535范围内', 'error')
                return redirect(url_for('homekit.homekit_config'))
            
            # 获取或创建配置
            homekit_config = HomeKitConfig.query.first()
            old_enabled = False
            
            if homekit_config:
                old_enabled = homekit_config.enabled
                homekit_config.bridge_name = bridge_name
                homekit_config.bridge_pin = bridge_pin
                homekit_config.bridge_port = bridge_port
                homekit_config.enabled = enabled
                homekit_config.updated_at = datetime.utcnow()
            else:
                import secrets
                homekit_config = HomeKitConfig(
                    bridge_name=bridge_name,
                    bridge_pin=bridge_pin,
                    bridge_port=bridge_port,
                    enabled=enabled,
                    serial_number=secrets.token_hex(6).upper()  # 生成随机序列号
                )
                db.session.add(homekit_config)
            
            db.session.commit()
            
            # 管理HomeKit服务
            if enabled and not homekit_service.manager.is_running:
                success = homekit_service.start_service()
                if success:
                    flash('HomeKit配置保存成功，服务已启动', 'success')
                else:
                    flash('HomeKit配置保存成功，但服务启动失败，请检查配置', 'warning')
            elif not enabled and homekit_service.manager.is_running:
                success = homekit_service.stop_service()
                if success:
                    flash('HomeKit配置保存成功，服务已停止', 'success')
                else:
                    flash('HomeKit配置保存成功，但服务停止失败', 'warning')
            elif enabled and homekit_service.manager.is_running and old_enabled:
                # 配置有变化，重启服务
                success = homekit_service.restart_service()
                if success:
                    flash('HomeKit配置保存成功，服务已重启', 'success')
                else:
                    flash('HomeKit配置保存成功，但服务重启失败', 'warning')
            else:
                flash('HomeKit配置保存成功', 'success')
            
            return redirect(url_for('homekit.homekit_config'))
            
        except ValueError:
            flash('端口号必须是数字', 'error')
            return redirect(url_for('homekit.homekit_config'))
        except Exception as e:
            flash(f'保存配置失败: {str(e)}', 'error')
            return redirect(url_for('homekit.homekit_config'))
    
    return _save_homekit_config()

@homekit_bp.route('/add_homekit_device', methods=['POST'])
def add_homekit_device():
    """添加HomeKit设备"""
    login_required = get_login_required()
    Device, HomeKitConfig, HomeKitDevice = get_models()
    homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _add_homekit_device():
        try:
            device_id = int(request.form.get('device_id'))
            homekit_name = request.form.get('homekit_name', '').strip()
            
            # 检查设备是否存在
            device = Device.query.get(device_id)
            if not device:
                flash('设备不存在', 'error')
                return redirect(url_for('homekit.homekit_config'))
            
            # 检查是否已添加
            existing = HomeKitDevice.query.filter_by(device_id=device_id).first()
            if existing:
                flash('该设备已添加到HomeKit', 'warning')
                return redirect(url_for('homekit.homekit_config'))
            
            # 如果没有提供名称，使用设备名称
            if not homekit_name:
                homekit_name = device.name
            
            # 生成唯一的AID
            max_aid = db.session.query(db.func.max(HomeKitDevice.homekit_aid)).scalar() or 1
            new_aid = max_aid + 1
            
            # 创建HomeKit设备
            homekit_device = HomeKitDevice(
                device_id=device_id,
                homekit_aid=new_aid,
                homekit_name=homekit_name,
                enabled=True
            )
            
            db.session.add(homekit_device)
            db.session.commit()
            
            # 如果HomeKit服务正在运行，动态添加设备
            if homekit_service.manager.is_running:
                success = homekit_service.add_device_accessory(device_id)
                if success:
                    flash(f'设备 "{homekit_name}" 已添加到HomeKit并生效', 'success')
                else:
                    flash(f'设备 "{homekit_name}" 已添加到HomeKit，请重启服务生效', 'warning')
            else:
                flash(f'设备 "{homekit_name}" 已添加到HomeKit', 'success')
            
            return redirect(url_for('homekit.homekit_config'))
            
        except ValueError:
            flash('设备ID格式错误', 'error')
            return redirect(url_for('homekit.homekit_config'))
        except Exception as e:
            flash(f'添加设备失败: {str(e)}', 'error')
            return redirect(url_for('homekit.homekit_config'))
    
    return _add_homekit_device()

@homekit_bp.route('/remove_homekit_device/<int:homekit_device_id>', methods=['POST'])
def remove_homekit_device(homekit_device_id):
    """移除HomeKit设备"""
    login_required = get_login_required()
    Device, HomeKitConfig, HomeKitDevice = get_models()
    homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _remove_homekit_device():
        try:
            homekit_device = HomeKitDevice.query.get_or_404(homekit_device_id)
            device_name = homekit_device.homekit_name
            device_id = homekit_device.device_id
            
            db.session.delete(homekit_device)
            db.session.commit()
            
            # 如果HomeKit服务正在运行，尝试移除设备
            if homekit_service.manager.is_running:
                homekit_service.remove_device_accessory(device_id)
                flash(f'设备 "{device_name}" 已从HomeKit移除，建议重启服务完全生效', 'warning')
            else:
                flash(f'设备 "{device_name}" 已从HomeKit移除', 'success')
            
            return redirect(url_for('homekit.homekit_config'))
            
        except Exception as e:
            flash(f'移除设备失败: {str(e)}', 'error')
            return redirect(url_for('homekit.homekit_config'))
    
    return _remove_homekit_device()

@homekit_bp.route('/toggle_homekit_device/<int:homekit_device_id>', methods=['POST'])
def toggle_homekit_device(homekit_device_id):
    """切换HomeKit设备启用状态"""
    login_required = get_login_required()
    Device, HomeKitConfig, HomeKitDevice = get_models()
    homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _toggle_homekit_device():
        try:
            homekit_device = HomeKitDevice.query.get_or_404(homekit_device_id)
            homekit_device.enabled = not homekit_device.enabled
            homekit_device.updated_at = datetime.utcnow()
            status = "启用" if homekit_device.enabled else "禁用"
            
            db.session.commit()
            
            # 如果服务正在运行，建议重启
            if homekit_service.manager.is_running:
                flash(f'设备 "{homekit_device.homekit_name}" 已{status}，建议重启HomeKit服务生效', 'warning')
            else:
                flash(f'设备 "{homekit_device.homekit_name}" 已{status}', 'success')
            
            return redirect(url_for('homekit.homekit_config'))
            
        except Exception as e:
            flash(f'切换设备状态失败: {str(e)}', 'error')
            return redirect(url_for('homekit.homekit_config'))
    
    return _toggle_homekit_device()

@homekit_bp.route('/restart_homekit_service', methods=['POST'])
def restart_homekit_service():
    """重启HomeKit服务"""
    login_required = get_login_required()
    homekit_service = get_services()
    
    @login_required
    def _restart_homekit_service():
        try:
            success = homekit_service.restart_service()
            if success:
                flash('HomeKit服务重启成功', 'success')
            else:
                flash('HomeKit服务重启失败', 'error')
        except Exception as e:
            flash(f'重启服务失败: {str(e)}', 'error')
        
        return redirect(url_for('homekit.homekit_config'))
    
    return _restart_homekit_service()

@homekit_bp.route('/reset_homekit_service', methods=['POST'])
def reset_homekit_service():
    """重置HomeKit服务（清理所有状态）"""
    login_required = get_login_required()
    homekit_service = get_services()
    
    @login_required
    def _reset_homekit_service():
        try:
            success = homekit_service.reset_service()
            if success:
                flash('HomeKit服务重置成功，所有配对信息已清理', 'success')
            else:
                flash('HomeKit服务重置失败', 'error')
        except Exception as e:
            flash(f'重置服务失败: {str(e)}', 'error')
        
        return redirect(url_for('homekit.homekit_config'))
    
    return _reset_homekit_service()

@homekit_bp.route('/generate_homekit_pin', methods=['POST'])
def generate_homekit_pin():
    """生成新的HomeKit PIN码"""
    import random
    
    login_required = get_login_required()
    
    @login_required
    def _generate_homekit_pin():
        try:
            # 生成8位数字PIN码，避免以0开头
            pin = f"{random.randint(10000000, 99999999)}"
            
            return jsonify({
                'success': True,
                'pin': pin
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'生成PIN码失败: {str(e)}'
            })
    
    return _generate_homekit_pin()

@homekit_bp.route('/homekit_qr_code')
def homekit_qr_code():
    """获取HomeKit配对二维码"""
    login_required = get_login_required()
    homekit_service = get_services()
    
    @login_required
    def _homekit_qr_code():
        try:
            qr_data = homekit_service.get_pairing_qr_code()
            
            if qr_data:
                return jsonify({
                    'success': True,
                    'data': qr_data
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'HomeKit服务未运行或二维码生成失败'
                })
                
        except Exception as e:
            logger.error(f"获取HomeKit二维码失败: {str(e)}")
            return jsonify({
                'success': False,
                'message': f'获取二维码失败: {str(e)}'
            })
    
    return _homekit_qr_code() 