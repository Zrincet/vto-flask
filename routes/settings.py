"""
设置与巴法云相关路由
包含系统设置和巴法云密钥管理功能
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
import logging
from datetime import datetime

# 延迟导入，避免循环导入
def get_db():
    from app import db
    return db

def get_models():
    from models import Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice
    return Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice

def get_services():
    from services import mqtt_manager, bemfa_sync_service, homekit_service
    return mqtt_manager, bemfa_sync_service, homekit_service

def get_login_required():
    from app import login_required
    return login_required

# 创建设置蓝图
settings_bp = Blueprint('settings', __name__)
logger = logging.getLogger(__name__)

@settings_bp.route('/settings')
def settings():
    """系统设置页面"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice = get_models()
    mqtt_manager, bemfa_sync_service, homekit_service = get_services()
    
    @login_required
    def _settings():
        # 获取配置信息
        mqtt_enabled = Config.query.filter_by(key='mqtt_enabled').first()
        
        # 获取所有巴法云密钥
        bemfa_keys = BemfaKey.query.all()
        
        # 获取MQTT连接状态
        mqtt_status = mqtt_manager.get_connection_status()
        
        # 获取HomeKit配置
        homekit_config = HomeKitConfig.query.first()
        
        # 获取HomeKit服务状态
        homekit_status = homekit_service.get_service_status()
        
        return render_template('settings.html',
                             mqtt_enabled=mqtt_enabled.value == 'true' if mqtt_enabled else False,
                             mqtt_connected=mqtt_manager.is_connected,
                             bemfa_keys=bemfa_keys,
                             mqtt_status=mqtt_status,
                             homekit_config=homekit_config,
                             homekit_status=homekit_status)
    
    return _settings()

@settings_bp.route('/save_settings', methods=['POST'])
def save_settings():
    """保存系统设置"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice = get_models()
    mqtt_manager, bemfa_sync_service, homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _save_settings():
        mqtt_enabled = request.form.get('mqtt_enabled') == 'on'
        
        # 保存MQTT服务状态
        config = Config.query.filter_by(key='mqtt_enabled').first()
        if config:
            config.value = 'true' if mqtt_enabled else 'false'
            config.updated_at = datetime.utcnow()
        else:
            config = Config(key='mqtt_enabled', value='true' if mqtt_enabled else 'false')
            db.session.add(config)
        
        db.session.commit()
        
        # 管理MQTT服务
        try:
            if mqtt_enabled and not mqtt_manager.is_running:
                # 获取启用的巴法云密钥
                enabled_keys = BemfaKey.query.filter_by(enabled=True).all()
                if enabled_keys:
                    mqtt_manager.start_mqtt_service()
                else:
                    flash('请先添加并启用巴法云密钥', 'warning')
                    return redirect(url_for('settings.settings'))
            elif not mqtt_enabled and mqtt_manager.is_running:
                mqtt_manager.stop_mqtt_service()
        except Exception as e:
            flash(f'MQTT服务操作失败: {str(e)}', 'error')
            return redirect(url_for('settings.settings'))
        
        flash('设置保存成功', 'success')
        return redirect(url_for('settings.settings'))
    
    return _save_settings()

@settings_bp.route('/add_bemfa_key_api', methods=['POST'])
def add_bemfa_key_api():
    """添加巴法云密钥 API"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice = get_models()
    mqtt_manager, bemfa_sync_service, homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _add_bemfa_key_api():
        try:
            name = request.form.get('name', '').strip()
            key = request.form.get('key', '').strip()
            enabled = request.form.get('enabled') == 'on'
            
            # 验证输入
            if not name or not key:
                return jsonify({'success': False, 'message': '请填写所有必填字段'})
            
            # 验证密钥格式
            if len(key) != 32:
                return jsonify({'success': False, 'message': '巴法云私钥必须是32位字符'})
            
            # 验证密钥是否已存在
            existing_key = BemfaKey.query.filter_by(key=key).first()
            if existing_key:
                return jsonify({'success': False, 'message': '该密钥已存在'})
            
            # 创建新密钥
            new_key = BemfaKey(
                name=name,
                key=key,
                enabled=enabled
            )
            db.session.add(new_key)
            db.session.commit()
            
            # 如果密钥启用，执行后续操作
            if enabled:
                # 检查MQTT服务是否已启用
                mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
                if mqtt_config and mqtt_config.value == 'true':
                    try:
                        # 启动新的MQTT客户端
                        mqtt_manager.start_client(key)
                        logger.info(f"为新密钥 {name} 启动MQTT客户端")
                        
                        # 同步设备到巴法云
                        sync_result = bemfa_sync_service.sync_visible_devices_to_bemfa()
                        if sync_result:
                            created_count = sync_result.get('created_count', 0)
                            updated_count = sync_result.get('updated_count', 0)
                            deleted_count = sync_result.get('deleted_count', 0)
                            
                            if created_count > 0 or updated_count > 0 or deleted_count > 0:
                                message = f'巴法云密钥 {name} 添加成功'
                                if created_count > 0:
                                    message += f'，同步创建了 {created_count} 个设备主题'
                                if updated_count > 0:
                                    message += f'，更新了 {updated_count} 个设备昵称'
                                if deleted_count > 0:
                                    message += f'，删除了 {deleted_count} 个多余主题'
                                
                                logger.info(f"新密钥 {name} 设备同步完成: 创建 {created_count}, 更新 {updated_count}, 删除 {deleted_count}")
                            else:
                                message = f'巴法云密钥 {name} 添加成功，设备主题已同步'
                        else:
                            message = f'巴法云密钥 {name} 添加成功，但没有可见设备需要同步'
                            
                    except Exception as sync_error:
                        logger.error(f"新密钥 {name} 同步失败: {str(sync_error)}")
                        message = f'巴法云密钥 {name} 添加成功，但同步设备失败: {str(sync_error)}'
                else:
                    message = f'巴法云密钥 {name} 添加成功，但MQTT服务未启用'
            else:
                message = f'巴法云密钥 {name} 添加成功（已禁用）'
            
            return jsonify({'success': True, 'message': message})
            
        except Exception as e:
            return jsonify({'success': False, 'message': f'添加失败: {str(e)}'})
    
    return _add_bemfa_key_api()

@settings_bp.route('/edit_bemfa_key_api/<int:key_id>', methods=['POST'])
def edit_bemfa_key_api(key_id):
    """编辑巴法云密钥 API"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice = get_models()
    mqtt_manager, bemfa_sync_service, homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _edit_bemfa_key_api():
        try:
            bemfa_key = BemfaKey.query.get_or_404(key_id)
            old_key = bemfa_key.key
            old_enabled = bemfa_key.enabled
            
            name = request.form.get('name', '').strip()
            key = request.form.get('key', '').strip()
            enabled = request.form.get('enabled') == 'on'
            
            # 验证输入
            if not name or not key:
                return jsonify({'success': False, 'message': '请填写所有必填字段'})
            
            # 验证密钥格式
            if len(key) != 32:
                return jsonify({'success': False, 'message': '巴法云私钥必须是32位字符'})
            
            # 验证密钥是否已存在（排除自己）
            existing_key = BemfaKey.query.filter(BemfaKey.key == key, BemfaKey.id != key_id).first()
            if existing_key:
                return jsonify({'success': False, 'message': '该密钥已存在'})
            
            # 更新密钥信息
            bemfa_key.name = name
            bemfa_key.key = key
            bemfa_key.enabled = enabled
            
            db.session.commit()
            
            # 处理MQTT连接变化
            mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
            if mqtt_config and mqtt_config.value == 'true':
                try:
                    # 如果密钥改变，停止旧的客户端
                    if old_key != key:
                        mqtt_manager.stop_client(old_key)
                        logger.info(f"停止旧密钥 {old_key[:8]}... 的MQTT客户端")
                    
                    # 如果新密钥启用，启动新的客户端
                    if enabled:
                        mqtt_manager.start_client(key)
                        logger.info(f"为更新后的密钥 {name} 启动MQTT客户端")
                        
                        # 同步设备到巴法云
                        sync_result = bemfa_sync_service.sync_visible_devices_to_bemfa()
                        if sync_result:
                            created_count = sync_result.get('created_count', 0)
                            updated_count = sync_result.get('updated_count', 0)
                            deleted_count = sync_result.get('deleted_count', 0)
                            
                            if created_count > 0 or updated_count > 0 or deleted_count > 0:
                                message = f'巴法云密钥 {name} 更新成功'
                                if created_count > 0:
                                    message += f'，同步创建了 {created_count} 个设备主题'
                                if updated_count > 0:
                                    message += f'，更新了 {updated_count} 个设备昵称'
                                if deleted_count > 0:
                                    message += f'，删除了 {deleted_count} 个多余主题'
                            else:
                                message = f'巴法云密钥 {name} 更新成功，设备主题已同步'
                        else:
                            message = f'巴法云密钥 {name} 更新成功，但没有可见设备需要同步'
                    else:
                        # 如果密钥被禁用，停止客户端
                        mqtt_manager.stop_client(key)
                        logger.info(f"密钥 {name} 被禁用，停止MQTT客户端")
                        message = f'巴法云密钥 {name} 更新成功（已禁用）'
                        
                except Exception as sync_error:
                    logger.error(f"更新密钥 {name} 后处理MQTT连接失败: {str(sync_error)}")
                    message = f'巴法云密钥 {name} 更新成功，但处理MQTT连接失败: {str(sync_error)}'
            else:
                message = f'巴法云密钥 {name} 更新成功'
            
            return jsonify({'success': True, 'message': message})
            
        except Exception as e:
            return jsonify({'success': False, 'message': f'更新失败: {str(e)}'})
    
    return _edit_bemfa_key_api()

@settings_bp.route('/get_bemfa_key_api/<int:key_id>')
def get_bemfa_key_api(key_id):
    """获取巴法云密钥信息 API"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice = get_models()
    
    @login_required
    def _get_bemfa_key_api():
        try:
            bemfa_key = BemfaKey.query.get_or_404(key_id)
            
            return jsonify({
                'success': True,
                'key': {
                    'id': bemfa_key.id,
                    'name': bemfa_key.name,
                    'key': bemfa_key.key,
                    'enabled': bemfa_key.enabled
                }
            })
            
        except Exception as e:
            return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})
    
    return _get_bemfa_key_api()

@settings_bp.route('/toggle_bemfa_key_api/<int:key_id>', methods=['POST'])
def toggle_bemfa_key_api(key_id):
    """切换巴法云密钥启用状态 API"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice = get_models()
    mqtt_manager, bemfa_sync_service, homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _toggle_bemfa_key_api():
        try:
            bemfa_key = BemfaKey.query.get_or_404(key_id)
            old_enabled = bemfa_key.enabled
            
            bemfa_key.enabled = not bemfa_key.enabled
            db.session.commit()
            
            status = "启用" if bemfa_key.enabled else "禁用"
            
            # 处理MQTT连接变化
            mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
            if mqtt_config and mqtt_config.value == 'true':
                try:
                    if bemfa_key.enabled:
                        # 启用密钥，启动MQTT客户端
                        mqtt_manager.start_client(bemfa_key.key)
                        logger.info(f"启用密钥 {bemfa_key.name}，启动MQTT客户端")
                        
                        # 同步设备到巴法云
                        sync_result = bemfa_sync_service.sync_visible_devices_to_bemfa()
                        if sync_result:
                            created_count = sync_result.get('created_count', 0)
                            updated_count = sync_result.get('updated_count', 0)
                            deleted_count = sync_result.get('deleted_count', 0)
                            
                            if created_count > 0 or updated_count > 0 or deleted_count > 0:
                                message = f'巴法云密钥 {bemfa_key.name} 已{status}'
                                if created_count > 0:
                                    message += f'，同步创建了 {created_count} 个设备主题'
                                if updated_count > 0:
                                    message += f'，更新了 {updated_count} 个设备昵称'
                                if deleted_count > 0:
                                    message += f'，删除了 {deleted_count} 个多余主题'
                            else:
                                message = f'巴法云密钥 {bemfa_key.name} 已{status}，设备主题已同步'
                        else:
                            message = f'巴法云密钥 {bemfa_key.name} 已{status}，但没有可见设备需要同步'
                    else:
                        # 禁用密钥，停止MQTT客户端
                        mqtt_manager.stop_client(bemfa_key.key)
                        logger.info(f"禁用密钥 {bemfa_key.name}，停止MQTT客户端")
                        message = f'巴法云密钥 {bemfa_key.name} 已{status}'
                        
                except Exception as sync_error:
                    logger.error(f"切换密钥 {bemfa_key.name} 状态后处理MQTT连接失败: {str(sync_error)}")
                    message = f'巴法云密钥 {bemfa_key.name} 已{status}，但处理MQTT连接失败: {str(sync_error)}'
            else:
                message = f'巴法云密钥 {bemfa_key.name} 已{status}'
            
            return jsonify({'success': True, 'message': message})
            
        except Exception as e:
            return jsonify({'success': False, 'message': f'操作失败: {str(e)}'})
    
    return _toggle_bemfa_key_api()

@settings_bp.route('/delete_bemfa_key_api/<int:key_id>', methods=['POST'])
def delete_bemfa_key_api(key_id):
    """删除巴法云密钥 API"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice = get_models()
    mqtt_manager, bemfa_sync_service, homekit_service = get_services()
    db = get_db()
    
    @login_required
    def _delete_bemfa_key_api():
        try:
            bemfa_key = BemfaKey.query.get_or_404(key_id)
            
            key_name = bemfa_key.name
            key_value = bemfa_key.key
            was_enabled = bemfa_key.enabled
            
            db.session.delete(bemfa_key)
            db.session.commit()
            
            # 如果密钥是启用的，停止对应的MQTT客户端
            if was_enabled:
                mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
                if mqtt_config and mqtt_config.value == 'true':
                    try:
                        mqtt_manager.stop_client(key_value)
                        logger.info(f"删除密钥 {key_name}，停止对应的MQTT客户端")
                        message = f'巴法云密钥 {key_name} 删除成功，已断开MQTT连接'
                    except Exception as mqtt_error:
                        logger.error(f"停止已删除密钥 {key_name} 的MQTT客户端失败: {str(mqtt_error)}")
                        message = f'巴法云密钥 {key_name} 删除成功，但停止MQTT连接失败: {str(mqtt_error)}'
                else:
                    message = f'巴法云密钥 {key_name} 删除成功'
            else:
                message = f'巴法云密钥 {key_name} 删除成功'
            
            return jsonify({'success': True, 'message': message})
            
        except Exception as e:
            return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})
    
    return _delete_bemfa_key_api()

@settings_bp.route('/sync_bemfa_devices', methods=['POST'])
def sync_bemfa_devices():
    """手动同步可见设备到巴法云"""
    login_required = get_login_required()
    mqtt_manager, bemfa_sync_service, homekit_service = get_services()
    
    @login_required
    def _sync_bemfa_devices():
        try:
            result = bemfa_sync_service.sync_visible_devices_to_bemfa()
            
            if result:
                created_count = result.get('created_count', 0)
                updated_count = result.get('updated_count', 0)
                deleted_count = result.get('deleted_count', 0)
                failed_count = result.get('failed_count', 0)
                accounts = result.get('accounts', [])
                
                if created_count > 0 or updated_count > 0 or deleted_count > 0:
                    message_parts = []
                    if created_count > 0:
                        message_parts.append(f"创建 {created_count} 个主题")
                    if updated_count > 0:
                        message_parts.append(f"更新 {updated_count} 个昵称")
                    if deleted_count > 0:
                        message_parts.append(f"删除 {deleted_count} 个多余主题")
                    
                    message = f"同步成功：{', '.join(message_parts)}，MQTT订阅已刷新"
                    if failed_count > 0:
                        message += f"，{failed_count} 个失败"
                        
                    # 如果是多账号，显示详细信息
                    if len(accounts) > 1:
                        message += f"（共 {len(accounts)} 个账号）"
                elif failed_count > 0:
                    message = f"同步失败：{failed_count} 个主题操作失败"
                else:
                    message = "所有设备主题都已同步，无需更新"
            else:
                message = "没有可见设备需要同步"
            
            return jsonify({
                "success": True, 
                "message": message,
                "accounts": accounts
            })
        except Exception as e:
            logger.error(f"手动同步巴法云失败: {str(e)}")
            return jsonify({"success": False, "message": f"同步失败: {str(e)}"})
    
    return _sync_bemfa_devices() 