"""
巴法云服务模块
管理巴法云API调用和设备同步
"""

import logging
import requests

logger = logging.getLogger(__name__)


class BemfaService:
    """巴法云API服务类"""
    
    def __init__(self):
        self.base_url = "https://apis.bemfa.com"
        self.pro_url = "https://pro.bemfa.com"
    
    def get_all_topics(self, uid):
        """获取所有主题信息"""
        try:
            url = f"{self.base_url}/va/alltopic"
            params = {
                "uid": uid,
                "type": 1  # MQTT协议
            }
            response = requests.get(url, params=params, timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"获取巴法云主题失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def create_topic(self, uid, topic, name=None, type=1):
        """创建单个主题"""
        try:
            url = "https://pro.bemfa.com/v1/createTopic"
            data = {
                "uid": uid,
                "topic": topic,
                "type": type  # 1=MQTT协议设备, 3=TCP协议设备, 5=MQTT协议设备V2版本, 7=TCP协议设备V2版本
            }
            
            # 如果提供了昵称，在创建时就设置
            if name:
                data["name"] = name
            
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=data, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"创建巴法云主题失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def create_topics(self, uid, topics):
        """创建多个主题（批量创建方法，保留向后兼容）"""
        try:
            url = f"{self.pro_url}/vs/web/v1/addTopics"
            data = {
                "openID": uid,
                "type": 1,  # MQTT协议
                "topics": topics,
                "group": "VTO设备",
                "adminID": 0
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=data, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"创建巴法云主题失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def modify_topic_name(self, uid, topic, name):
        """修改主题昵称"""
        try:
            url = f"{self.base_url}/va/modifyName"
            data = {
                "uid": uid,
                "topic": topic,
                "type": 1,  # MQTT协议
                "name": name
            }
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response = requests.post(url, json=data, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"修改巴法云主题名称失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def send_status_message(self, uid, topic, msg, wemsg=None):
        """发送状态推送消息"""
        try:
            url = f"{self.base_url}/va/postJsonMsg"
            data = {
                "uid": uid,
                "topic": topic,
                "type": 1,  # MQTT协议
                "msg": msg
            }
            
            # 如果有微信消息，添加到请求中
            if wemsg:
                data["wemsg"] = wemsg
                
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response = requests.post(url, json=data, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"发送巴法云状态消息失败: {str(e)}")
            return {"code": -1, "message": str(e)}
    
    def delete_topic(self, uid, topic, type=1):
        """删除主题"""
        try:
            url = f"{self.pro_url}/v1/deleteTopic"
            data = {
                "uid": uid,
                "topic": topic,
                "type": type  # 1=MQTT协议设备, 3=TCP协议设备, 5=MQTT协议设备V2版本, 7=TCP协议设备V2版本
            }
            
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response = requests.post(url, json=data, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"删除巴法云主题失败: {str(e)}")
            return {"code": -1, "message": str(e)}


class BemfaSyncService:
    """巴法云设备同步服务"""
    
    def __init__(self):
        self.bemfa_service = BemfaService()
    
    def sync_visible_devices_to_bemfa(self):
        """同步可见设备到所有启用的巴法云账号"""
        from models import BemfaKey, Config, Device
        
        bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
        
        # 如果没有新的BemfaKey，则回退到旧的Config方式
        if not bemfa_keys:
            old_bemfa_key = Config.query.filter_by(key='bemfa_private_key').first()
            if old_bemfa_key and old_bemfa_key.value:
                logger.info("使用旧的巴法云私钥配置")
                result = self.sync_single_bemfa_account(old_bemfa_key.value)
                # 为了保持返回格式一致，添加accounts字段
                result['accounts'] = [{
                    'name': '默认账号',
                    'key': old_bemfa_key.value[:8] + '...',
                    'created': result['created_count'],
                    'updated': result['updated_count'],
                    'deleted': result['deleted_count'],
                    'failed': result['failed_count'],
                    'success': True
                }]
                
                # 如果有任何更改，自动重启MQTT服务
                if ((result['created_count'] > 0 or result['updated_count'] > 0 or result['deleted_count'] > 0)):
                    self._restart_mqtt_if_needed(old_bemfa_key.value)
                
                return result
            else:
                logger.warning("未配置巴法云私钥，跳过同步")
                return {
                    'created_count': 0,
                    'updated_count': 0,
                    'deleted_count': 0,
                    'failed_count': 0,
                    'total_devices': 0,
                    'accounts': []
                }
        
        visible_devices = Device.query.filter_by(visible=True).all()
        if not visible_devices:
            logger.info("没有可见设备需要同步")
            return {
                'created_count': 0,
                'updated_count': 0,
                'deleted_count': 0,
                'failed_count': 0,
                'total_devices': 0,
                'accounts': []
            }
        
        # 对所有启用的巴法云账号执行同步
        total_created = 0
        total_updated = 0
        total_deleted = 0
        total_failed = 0
        account_results = []
        
        for bemfa_key in bemfa_keys:
            logger.info(f"同步到巴法云账号：{bemfa_key.name}")
            try:
                result = self.sync_single_bemfa_account(bemfa_key.key)
                account_results.append({
                    'name': bemfa_key.name,
                    'key': bemfa_key.key[:8] + '...',  # 只显示前8位
                    'created': result['created_count'],
                    'updated': result['updated_count'],
                    'deleted': result['deleted_count'],
                    'failed': result['failed_count'],
                    'success': True
                })
                total_created += result['created_count']
                total_updated += result['updated_count']
                total_deleted += result['deleted_count']
                total_failed += result['failed_count']
            except Exception as e:
                logger.error(f"同步到巴法云账号 {bemfa_key.name} 失败: {str(e)}")
                account_results.append({
                    'name': bemfa_key.name,
                    'key': bemfa_key.key[:8] + '...',
                    'created': 0,
                    'updated': 0,
                    'deleted': 0,
                    'failed': 0,
                    'success': False,
                    'error': str(e)
                })
        
        logger.info(f"多账号同步完成：总创建 {total_created}，总更新 {total_updated}，总删除 {total_deleted}，总失败 {total_failed}")
        
        # 如果有任何更改，自动重启MQTT服务
        if (total_created > 0 or total_updated > 0 or total_deleted > 0):
            self._restart_mqtt_multi_account()
        
        return {
            'created_count': total_created,
            'updated_count': total_updated,
            'deleted_count': total_deleted,
            'failed_count': total_failed,
            'total_devices': len(visible_devices),
            'accounts': account_results
        }

    def sync_single_bemfa_account(self, bemfa_key_value):
        """同步可见设备到单个巴法云账号"""
        from models import Device
        
        visible_devices = Device.query.filter_by(visible=True).all()
        
        try:
            # 获取现有主题
            topics_response = self.bemfa_service.get_all_topics(bemfa_key_value)
            existing_topics = set()
            topic_names = {}
            
            if topics_response.get("code") == 0:
                for topic_data in topics_response.get("data", []):
                    existing_topics.add(topic_data["topic"])
                    topic_names[topic_data["topic"]] = topic_data.get("name", "")
            
            # 获取当前需要同步的设备主题
            current_device_topics = set()
            for device in visible_devices:
                topic = device.mqtt_topic
                if topic:
                    current_device_topics.add(topic)
            
            # 查找需要删除的主题（以vto开头但不在当前设备列表中）
            topics_to_delete = []
            for existing_topic in existing_topics:
                if existing_topic.startswith('vto') and existing_topic not in current_device_topics:
                    topics_to_delete.append(existing_topic)
            
            # 删除不需要的vto主题
            deleted_count = 0
            for topic in topics_to_delete:
                delete_response = self.bemfa_service.delete_topic(
                    uid=bemfa_key_value,
                    topic=topic,
                    type=1  # MQTT协议设备
                )
                
                if delete_response.get("code") == 0:
                    logger.info(f"成功删除多余的主题 {topic}")
                    deleted_count += 1
                else:
                    logger.error(f"删除主题 {topic} 失败: {delete_response.get('message', '未知错误')}")
            
            # 需要创建和更新的主题
            topics_to_create = []
            topics_to_update = []
            
            for device in visible_devices:
                topic = device.mqtt_topic
                if not topic:
                    continue
                    
                if topic not in existing_topics:
                    topics_to_create.append((topic, device.name))
                elif topic_names.get(topic) != device.name:
                    topics_to_update.append((topic, device.name))
            
            # 逐个创建主题，在创建时就设置昵称
            created_count = 0
            failed_count = 0
            for topic, device_name in topics_to_create:
                create_response = self.bemfa_service.create_topic(
                    uid=bemfa_key_value, 
                    topic=topic, 
                    name=device_name,
                    type=1  # MQTT协议设备
                )
                
                if create_response.get("code") == 0:
                    logger.info(f"成功创建主题 {topic}，昵称：{device_name}")
                    created_count += 1
                elif create_response.get("code") == 40006:
                    # 设备已存在，记录警告但不算失败
                    logger.warning(f"主题 {topic} 已存在，跳过创建")
                else:
                    logger.error(f"创建主题 {topic} 失败: {create_response.get('message', '未知错误')}")
                    failed_count += 1
            
            # 更新已存在主题的名称（如果昵称不匹配）
            updated_count = 0
            for topic, name in topics_to_update:
                update_response = self.bemfa_service.modify_topic_name(bemfa_key_value, topic, name)
                if update_response.get("code") == 0:
                    logger.info(f"成功更新主题 {topic} 的名称为 {name}")
                    updated_count += 1
                else:
                    logger.error(f"更新主题 {topic} 名称失败: {update_response.get('message')}")
            
            return {
                'created_count': created_count,
                'updated_count': updated_count,
                'deleted_count': deleted_count,
                'failed_count': failed_count,
                'total_devices': len(visible_devices)
            }
                    
        except Exception as e:
            logger.error(f"同步巴法云设备失败: {str(e)}")
            raise

    def _restart_mqtt_if_needed(self, bemfa_key_value):
        """重启MQTT服务（单账号模式）"""
        try:
            from .mqtt_service import mqtt_manager
            
            if mqtt_manager.is_running:
                logger.info("巴法云设备同步完成（使用旧配置），重新连接MQTT服务...")
                mqtt_manager.stop_mqtt_service()
                mqtt_manager.start_mqtt_service("bemfa.com", 9501, bemfa_key_value)
                logger.info("MQTT服务重新连接成功")
        except Exception as mqtt_error:
            logger.error(f"重新连接MQTT服务失败: {str(mqtt_error)}")

    def _restart_mqtt_multi_account(self):
        """重启MQTT服务（多账号模式）"""
        try:
            from .mqtt_service import mqtt_manager
            
            if mqtt_manager.is_running:
                logger.info("巴法云设备同步完成，重新连接MQTT服务...")
                # 停止当前所有连接
                mqtt_manager.stop_mqtt_service()
                # 重新启动所有启用的客户端连接
                mqtt_manager.start_all_clients()
                logger.info("MQTT服务重新连接成功")
        except Exception as mqtt_error:
            logger.error(f"重新连接MQTT服务失败: {str(mqtt_error)}")

    def migrate_bemfa_config(self):
        """迁移旧的巴法云配置到新的BemfaKey表"""
        try:
            from models import BemfaKey, Config, db
            
            # 检查是否已经有BemfaKey记录
            if BemfaKey.query.count() > 0:
                logger.info("已存在BemfaKey记录，跳过迁移")
                return
            
            # 获取旧的巴法云配置
            old_bemfa_config = Config.query.filter_by(key='bemfa_private_key').first()
            if old_bemfa_config and old_bemfa_config.value:
                # 创建新的BemfaKey记录
                new_bemfa_key = BemfaKey(
                    name="默认账号",
                    key=old_bemfa_config.value,
                    enabled=True
                )
                db.session.add(new_bemfa_key)
                db.session.commit()
                logger.info("成功迁移旧的巴法云配置到新的BemfaKey表")
            else:
                logger.info("未找到旧的巴法云配置，跳过迁移")
        except Exception as e:
            logger.error(f"迁移巴法云配置时出错: {str(e)}")
            from models import db
            db.session.rollback()


# 全局巴法云服务实例
bemfa_service = BemfaService()
bemfa_sync_service = BemfaSyncService()

# 向后兼容的别名
BemfaAPI = BemfaService 