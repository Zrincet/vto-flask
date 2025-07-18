"""
设备管理相关路由
包含设备列表、添加、编辑、删除、开锁等功能
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime
import logging

# 延迟导入，避免循环导入
def get_db():
    from app import db
    return db

def get_models():
    from models.device import Device
    from models.config import Config, BemfaKey
    from models.homekit import HomeKitDevice
    return Device, Config, BemfaKey, HomeKitDevice

def get_services():
    from services import DahuaService, mqtt_manager, bemfa_sync_service
    return DahuaService, mqtt_manager, bemfa_sync_service

def get_login_required():
    from app import login_required
    return login_required

# 创建设备蓝图
device_bp = Blueprint('device', __name__)
logger = logging.getLogger(__name__)

@device_bp.route('/visible_devices')
def visible_devices():
    """可见设备列表页面（新的主页）"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    DahuaService, mqtt_manager, bemfa_sync_service = get_services()
    
    @login_required
    def _visible_devices():
        devices = Device.query.filter_by(visible=True).all()
        device_count = len(devices)
        online_count = len([d for d in devices if d.status == 'online'])
        
        # 获取MQTT服务状态
        mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
        mqtt_enabled = mqtt_config.value == 'true' if mqtt_config else False
        
        return render_template('visible_devices.html', 
                             devices=devices,
                             device_count=device_count,
                             online_count=online_count,
                             mqtt_enabled=mqtt_enabled,
                             mqtt_connected=mqtt_manager.is_connected)
    
    return _visible_devices()

@device_bp.route('/devices')
def devices():
    """所有设备管理页面"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    
    @login_required
    def _devices():
        devices = Device.query.all()
        return render_template('devices.html', devices=devices)
    
    return _devices()

@device_bp.route('/dashboard')
def dashboard():
    """仪表盘页面"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    DahuaService, mqtt_manager, bemfa_sync_service = get_services()
    
    @login_required
    def _dashboard():
        # 只显示可见设备
        devices = Device.query.filter_by(visible=True).all()
        device_count = len(devices)
        online_count = len([d for d in devices if d.status == 'online'])
        
        # 获取MQTT服务状态
        mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
        mqtt_enabled = mqtt_config.value == 'true' if mqtt_config else False
        
        return render_template('dashboard.html', 
                             devices=devices,
                             device_count=device_count,
                             online_count=online_count,
                             mqtt_enabled=mqtt_enabled,
                             mqtt_connected=mqtt_manager.is_connected)
    
    return _dashboard()

@device_bp.route('/manage_visible_devices')
def manage_visible_devices():
    """可见设备管理页面"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    
    @login_required
    def _manage_visible_devices():
        # 获取所有设备，按区域和楼栋分组
        all_devices = Device.query.order_by(Device.section_number, Device.building_number, Device.position).all()
        visible_devices = Device.query.filter_by(visible=True).all()
        visible_device_ids = {d.id for d in visible_devices}
        
        # 按区域分组
        sections = {}
        for device in all_devices:
            section = device.section_number
            if section not in sections:
                sections[section] = {}
            
            building = device.building_number
            if building not in sections[section]:
                sections[section][building] = []
            
            sections[section][building].append(device)
        
        return render_template('manage_visible_devices.html', 
                             sections=sections, 
                             visible_device_ids=visible_device_ids)
    
    return _manage_visible_devices()

@device_bp.route('/update_visible_devices', methods=['POST'])
def update_visible_devices():
    """更新可见设备"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    DahuaService, mqtt_manager, bemfa_sync_service = get_services()
    db = get_db()
    
    @login_required
    def _update_visible_devices():
        try:
            selected_device_ids = request.json.get('device_ids', [])
            
            # 重置所有设备的可见性
            Device.query.update({Device.visible: False})
            
            # 设置选中设备为可见
            if selected_device_ids:
                Device.query.filter(Device.id.in_(selected_device_ids)).update(
                    {Device.visible: True}, synchronize_session=False
                )
            
            db.session.commit()
            
            # 同步到巴法云
            bemfa_sync_service.sync_visible_devices_to_bemfa()
            
            # 重新连接MQTT服务以更新订阅的主题
            if mqtt_manager.is_running:
                logger.info("可见设备更新，重新连接MQTT服务...")
                try:
                    # 检查是否有启用的巴法云密钥
                    enabled_keys = BemfaKey.query.filter_by(enabled=True).all()
                    
                    if enabled_keys:
                        # 停止当前所有连接
                        mqtt_manager.stop_mqtt_service()
                        # 重新启动所有启用的客户端连接
                        mqtt_manager.start_all_clients()
                        logger.info("MQTT服务重新连接成功")
                    else:
                        # 如果没有启用的密钥，检查是否有旧的配置作为回退
                        bemfa_key_config = Config.query.filter_by(key='bemfa_private_key').first()
                        if bemfa_key_config and bemfa_key_config.value:
                            # 停止当前连接
                            mqtt_manager.stop_mqtt_service()
                            # 使用旧配置重新启动连接
                            mqtt_manager.start_mqtt_service("bemfa.com", 9501, bemfa_key_config.value)
                            logger.info("MQTT服务使用旧配置重新连接成功")
                        else:
                            logger.warning("没有可用的巴法云密钥配置，无法重新连接MQTT服务")
                except Exception as mqtt_error:
                    logger.error(f"重新连接MQTT服务失败: {str(mqtt_error)}")
            
            return jsonify({"success": True, "message": "可见设备更新成功，MQTT订阅已刷新"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"更新可见设备失败: {str(e)}")
            return jsonify({"success": False, "message": str(e)})
    
    return _update_visible_devices()

# sync_bemfa_devices路由已迁移到 routes/settings.py

@device_bp.route('/import_devices', methods=['GET', 'POST'])
def import_devices():
    """批量导入设备"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    DahuaService, mqtt_manager, bemfa_sync_service = get_services()
    db = get_db()
    
    @login_required
    def _import_devices():
        if request.method == 'GET':
            return render_template('import_devices.html')
        
        # POST 处理文件上传
        try:
            # 检查是否有文件上传
            if 'device_file' not in request.files:
                flash('请选择要上传的设备文件', 'error')
                return redirect(url_for('device.import_devices'))
            
            file = request.files['device_file']
            if file.filename == '':
                flash('请选择要上传的设备文件', 'error')
                return redirect(url_for('device.import_devices'))
            
            # 检查文件格式
            if not file.filename.lower().endswith('.json'):
                flash('只支持JSON格式的设备文件', 'error')
                return redirect(url_for('device.import_devices'))
            
            # 读取和解析JSON文件
            import json
            try:
                file_content = file.read().decode('utf-8')
                device_data = json.loads(file_content)
            except json.JSONDecodeError as e:
                flash(f'JSON文件格式错误: {str(e)}', 'error')
                return redirect(url_for('device.import_devices'))
            except UnicodeDecodeError:
                flash('文件编码错误，请使用UTF-8编码的JSON文件', 'error')
                return redirect(url_for('device.import_devices'))
            
            # 验证JSON结构
            if not isinstance(device_data, dict) or 'devices' not in device_data:
                flash('JSON文件格式错误，缺少devices字段', 'error')
                return redirect(url_for('device.import_devices'))
            
            devices_list = device_data['devices']
            if not isinstance(devices_list, list):
                flash('devices字段必须是数组格式', 'error')
                return redirect(url_for('device.import_devices'))
            
            # 获取现有设备IP和名称，避免重复
            existing_ips = {device.ip for device in Device.query.all()}
            existing_names = {device.name for device in Device.query.all()}
            
            devices_to_add = []
            skipped_devices = []
            invalid_devices = []
            
            for i, device_info in enumerate(devices_list):
                try:
                    # 验证必要字段
                    if not isinstance(device_info, dict):
                        invalid_devices.append(f"第{i+1}行: 设备信息必须是对象格式")
                        continue
                    
                    ip = device_info.get('ip', '').strip()
                    section = device_info.get('section', '').strip()
                    building = device_info.get('building', '').strip()
                    position = device_info.get('position', '').strip()
                    
                    # 验证必要字段
                    if not ip or not section or not building:
                        invalid_devices.append(f"第{i+1}行: IP地址、区域、楼栋号不能为空")
                        continue
                    
                    # 验证IP格式
                    import ipaddress
                    try:
                        ipaddress.ip_address(ip)
                    except ValueError:
                        invalid_devices.append(f"第{i+1}行: IP地址格式无效 ({ip})")
                        continue
                    
                    # 检查IP是否已存在
                    if ip in existing_ips:
                        skipped_devices.append(f"{ip} (已存在)")
                        continue
                    
                    # 创建临时设备对象以生成名称
                    temp_device = Device(
                        section_number=section,
                        building_number=building,
                        position=position if position else None,
                        ip=ip
                    )
                    
                    # 生成设备名称
                    device_name = temp_device.generate_device_name(existing_names)
                    existing_names.add(device_name)
                    existing_ips.add(ip)
                    
                    # 生成MQTT主题
                    mqtt_topic = temp_device.generate_mqtt_topic()
                    
                    # 创建设备
                    device = Device(
                        name=device_name,
                        group_name=f"{section}区",
                        section_number=section,
                        building_number=building,
                        position=position if position else None,
                        ip=ip,
                        mqtt_topic=mqtt_topic,
                        visible=False  # 默认不可见，需要手动设置
                    )
                    
                    devices_to_add.append(device)
                    
                except Exception as e:
                    invalid_devices.append(f"第{i+1}行: 处理错误 - {str(e)}")
            
            # 批量添加设备
            added_count = 0
            if devices_to_add:
                try:
                    db.session.add_all(devices_to_add)
                    db.session.commit()
                    added_count = len(devices_to_add)
                    logger.info(f"批量导入 {added_count} 个设备成功")
                except Exception as e:
                    db.session.rollback()
                    flash(f'批量导入失败: {str(e)}', 'error')
                    return redirect(url_for('device.import_devices'))
            
            # 生成结果报告
            total_count = len(devices_list)
            skipped_count = len(skipped_devices)
            invalid_count = len(invalid_devices)
            
            result_message = f"导入完成！总计 {total_count} 条记录，"
            result_message += f"成功导入 {added_count} 个设备"
            
            if skipped_count > 0:
                result_message += f"，跳过 {skipped_count} 个重复设备"
            
            if invalid_count > 0:
                result_message += f"，{invalid_count} 条记录格式错误"
            
            flash(result_message, 'success' if added_count > 0 else 'warning')
            
            # 显示详细信息
            if skipped_devices:
                flash(f"跳过的重复设备: {', '.join(skipped_devices[:10])}" + 
                     ("..." if len(skipped_devices) > 10 else ""), 'info')
            
            if invalid_devices:
                flash(f"无效记录: {'; '.join(invalid_devices[:5])}" + 
                     ("..." if len(invalid_devices) > 5 else ""), 'warning')
            
            return redirect(url_for('device.devices'))
            
        except Exception as e:
            logger.error(f"批量导入设备失败: {str(e)}")
            flash(f'导入失败: {str(e)}', 'error')
            return redirect(url_for('device.import_devices'))
    
    return _import_devices()

@device_bp.route('/add_device', methods=['GET', 'POST'])
def add_device():
    """添加设备"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    DahuaService, mqtt_manager, bemfa_sync_service = get_services()
    db = get_db()
    
    @login_required
    def _add_device():
        if request.method == 'POST':
            name = request.form['name']
            group_name = request.form['group_name']
            section_number = request.form['section_number']
            building_number = request.form['building_number']
            position = request.form.get('position', '') or None
            ip = request.form['ip']
            username = request.form.get('username', 'admin')
            password = request.form.get('password', 'admin123')
            
            # 检查IP是否已存在
            existing_device = Device.query.filter_by(ip=ip).first()
            if existing_device:
                flash('该IP地址的设备已存在', 'error')
                return render_template('add_device.html')
            
            # 创建设备并自动生成MQTT主题
            device = Device(
                name=name,
                group_name=group_name,
                section_number=section_number,
                building_number=building_number,
                position=position,
                ip=ip,
                username=username,
                password=password
            )
            
            # 自动生成MQTT主题
            device.mqtt_topic = device.generate_mqtt_topic()
            
            db.session.add(device)
            db.session.commit()
            
            # 如果MQTT服务正在运行且设备有主题，则订阅
            if device.mqtt_topic and mqtt_manager.is_running:
                mqtt_manager.subscribe_device_topic(device.mqtt_topic)
            
            flash('设备添加成功', 'success')
            return redirect(url_for('device.devices'))
        
        return render_template('add_device.html')
    
    return _add_device()

@device_bp.route('/edit_device/<int:device_id>', methods=['GET', 'POST'])
def edit_device(device_id):
    """编辑设备"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    DahuaService, mqtt_manager, bemfa_sync_service = get_services()
    db = get_db()
    
    @login_required
    def _edit_device():
        device = Device.query.get_or_404(device_id)
        return_to = request.args.get('return_to', 'devices')
        
        if request.method == 'POST':
            old_topic = device.mqtt_topic
            old_ip = device.ip
            
            device.name = request.form['name']
            device.group_name = request.form['group_name']
            device.section_number = request.form['section_number']
            device.building_number = request.form['building_number']
            device.position = request.form.get('position', '') or None
            device.ip = request.form['ip']
            device.username = request.form.get('username', 'admin')
            device.password = request.form.get('password', 'admin123')
            
            # 如果IP地址改变，重新生成MQTT主题
            if device.ip != old_ip:
                device.mqtt_topic = device.generate_mqtt_topic()
            
            # 更新MQTT订阅
            if mqtt_manager.is_running:
                if old_topic and old_topic != device.mqtt_topic:
                    mqtt_manager.unsubscribe_device_topic(old_topic)
                if device.mqtt_topic:
                    mqtt_manager.subscribe_device_topic(device.mqtt_topic)
            
            db.session.commit()
            
            # 如果设备可见，同步到巴法云
            if device.visible:
                bemfa_sync_service.sync_visible_devices_to_bemfa()
            
            flash('设备信息更新成功', 'success')
            
            # 根据返回参数决定跳转位置
            if return_to == 'visible_devices':
                return redirect(url_for('device.visible_devices'))
            elif return_to == 'dashboard':
                return redirect(url_for('device.dashboard'))
            else:
                return redirect(url_for('device.devices'))
        
        return render_template('edit_device.html', device=device, return_to=return_to)
    
    return _edit_device()

@device_bp.route('/delete_device/<int:device_id>')
def delete_device(device_id):
    """删除设备"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    DahuaService, mqtt_manager, bemfa_sync_service = get_services()
    db = get_db()
    
    @login_required
    def _delete_device():
        device = Device.query.get_or_404(device_id)
        
        # 如果设备有MQTT主题，取消订阅
        if device.mqtt_topic and mqtt_manager.is_running:
            mqtt_manager.unsubscribe_device_topic(device.mqtt_topic)
        
        db.session.delete(device)
        db.session.commit()
        flash('设备删除成功', 'success')
        return redirect(url_for('device.devices'))
    
    return _delete_device()

@device_bp.route('/unlock_device/<int:device_id>')
def unlock_device(device_id):
    """开锁设备"""
    login_required = get_login_required()
    Device, Config, BemfaKey, HomeKitDevice = get_models()
    DahuaService, mqtt_manager, bemfa_sync_service = get_services()
    db = get_db()
    
    @login_required
    def _unlock_device():
        device = Device.query.get_or_404(device_id)
        
        try:
            dahua_client = DahuaService(
                ip=device.ip,
                username=device.username,
                password=device.password
            )
            
            result = dahua_client.execute_door_open_flow()
            
            if result["success"]:
                device.last_unlock_time = datetime.utcnow()
                db.session.commit()
                return jsonify({"success": True, "message": "开锁成功"})
            else:
                return jsonify({"success": False, "message": result.get('message', '开锁失败')})
                
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
    
    return _unlock_device() 