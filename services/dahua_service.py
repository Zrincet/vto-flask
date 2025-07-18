"""
大华VTO门禁服务
提供大华设备的登录、开锁等功能
"""

import hashlib
import json
import requests
import logging

logger = logging.getLogger(__name__)


class DahuaService:
    """大华VTO门禁服务类"""
    
    def __init__(self, ip, username="admin", password="admin123", port=80):
        """
        初始化大华服务
        
        Args:
            ip (str): 设备IP地址
            username (str): 登录用户名，默认'admin'
            password (str): 登录密码，默认'admin123'
            port (int): 设备端口，默认80
        """
        self.ip = ip
        self.username = username
        self.password = password
        self.port = port
        self.session = None
        self.login_url = f"http://{ip}:{port}/RPC2_Login"
        self.rpc_url = f"http://{ip}:{port}/RPC2"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.request_id = 1000

    def _get_challenge(self):
        """获取登录挑战信息"""
        login_info = {
            "method": "global.login",
            "params": {
                "userName": self.username,
                "password": "",
                "clientType": "GUI"
            },
            "id": self._get_next_id(),
            "session": 0
        }

        try:
            response = requests.post(
                self.login_url,
                headers=self.headers,
                data=json.dumps(login_info),
                timeout=10
            )
            
            if response.status_code != 200:
                raise Exception(f"获取挑战信息失败，状态码：{response.status_code}")

            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求失败：{str(e)}")

    def _calculate_password_hash(self, challenge_info):
        """计算密码哈希值"""
        realm = challenge_info['params']['realm']
        random = challenge_info['params']['random']

        r_text = f"{self.username}:{realm}:{self.password}"
        r_md5 = hashlib.md5(r_text.encode("utf-8")).hexdigest().upper()

        s_text = f"{self.username}:{random}:{r_md5}"
        s_md5 = hashlib.md5(s_text.encode("utf-8")).hexdigest().upper()

        return s_md5, realm, random

    def login(self):
        """登录到大华设备"""
        try:
            challenge_info = self._get_challenge()
            self.session = challenge_info.get('session')

            # 如果已经登录成功
            if challenge_info.get('result'):
                logger.info(f"大华设备 {self.ip} 登录成功（无需密码）")
                return {
                    "success": True,
                    "session": self.session,
                    "data": challenge_info
                }

            # 需要密码验证
            password_hash, realm, random = self._calculate_password_hash(challenge_info)

            login_info = {
                "method": "global.login",
                "params": {
                    "userName": self.username,
                    "password": password_hash,
                    "clientType": "GUI",
                    "realm": realm,
                    "random": random,
                    "passwordType": "Default",
                    "authorityType": challenge_info['params']['encryption']
                },
                "id": self._get_next_id(),
                "session": self.session
            }

            response = requests.post(
                self.login_url,
                headers=self.headers,
                data=json.dumps(login_info),
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(f"登录失败，状态码：{response.status_code}")

            result = response.json()
            success = result.get('result', False)
            
            if success:
                logger.info(f"大华设备 {self.ip} 登录成功")
            else:
                logger.error(f"大华设备 {self.ip} 登录失败：{result.get('error', {}).get('message', '未知错误')}")

            return {
                "success": success,
                "session": self.session,
                "data": result
            }
            
        except Exception as e:
            logger.error(f"大华设备 {self.ip} 登录异常：{str(e)}")
            return {
                "success": False,
                "session": None,
                "error": str(e)
            }

    def _get_next_id(self):
        """获取下一个请求ID"""
        self.request_id += 1
        return self.request_id

    def get_door_instance(self):
        """获取门锁实例对象"""
        request_data = {
            "id": self._get_next_id(),
            "method": "accessControl.factory.instance",
            "params": {
                "channel": 0
            },
            "session": self.session
        }

        try:
            response = requests.post(
                self.rpc_url,
                headers=self.headers,
                data=json.dumps(request_data),
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(f"获取门锁对象失败，状态码：{response.status_code}")

            result = response.json()
            if "result" not in result:
                error_msg = result.get('error', {}).get('message', '未知错误')
                raise Exception(f"获取门锁对象失败：{error_msg}")

            return result["result"]
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求失败：{str(e)}")

    def open_door(self, door_handle, door_index=0, short_number="04001010001", open_type="Remote"):
        """
        开启门锁
        
        Args:
            door_handle: 门锁对象句柄
            door_index (int): 门索引，默认0
            short_number (str): 短号码，默认"04001010001"
            open_type (str): 开锁类型，默认"Remote"
        """
        request_data = {
            "id": self._get_next_id(),
            "method": "accessControl.openDoor",
            "object": door_handle,
            "params": {
                "DoorIndex": door_index,
                "ShortNumber": short_number,
                "Type": open_type
            },
            "session": self.session
        }

        try:
            response = requests.post(
                self.rpc_url,
                headers=self.headers,
                data=json.dumps(request_data),
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(f"开锁失败，状态码：{response.status_code}")

            result = response.json()
            return result.get("result", False)
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求失败：{str(e)}")

    def destroy_door_instance(self, door_handle):
        """销毁门锁实例对象"""
        request_data = {
            "id": self._get_next_id(),
            "method": "accessControl.destroy",
            "object": door_handle,
            "session": self.session
        }

        try:
            response = requests.post(
                self.rpc_url,
                headers=self.headers,
                data=json.dumps(request_data),
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(f"销毁门锁对象失败，状态码：{response.status_code}")

            result = response.json()
            return result.get("result", False)
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求失败：{str(e)}")

    def logout(self):
        """注销登录会话"""
        if not self.session:
            return True
            
        request_data = {
            "id": self._get_next_id(),
            "method": "global.logout",
            "session": self.session
        }

        try:
            response = requests.post(
                self.rpc_url,
                headers=self.headers,
                data=json.dumps(request_data),
                timeout=10
            )

            if response.status_code != 200:
                logger.warning(f"注销失败，状态码：{response.status_code}")
                return False

            result = response.json()
            success = result.get("result", False)
            
            if success:
                logger.info(f"大华设备 {self.ip} 注销成功")
            
            return success
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"注销请求失败：{str(e)}")
            return False

    def execute_door_open_flow(self, door_index=0, short_number="04001010001"):
        """
        执行完整的开门流程：登录 -> 获取门锁对象 -> 开锁 -> 销毁对象 -> 注销
        
        Args:
            door_index (int): 门索引，默认0
            short_number (str): 短号码，默认"04001010001"
            
        Returns:
            dict: 包含成功状态和详细结果的字典
        """
        # 步骤1：登录
        login_result = self.login()
        if not login_result["success"]:
            return {
                "success": False,
                "step": "login",
                "message": "登录失败",
                "data": login_result.get("data"),
                "error": login_result.get("error")
            }

        try:
            # 步骤2：获取门锁实例
            door_handle = self.get_door_instance()
            logger.info(f"获取门锁对象成功，句柄：{door_handle}")
            
            # 步骤3：开锁
            open_result = self.open_door(door_handle, door_index, short_number)
            logger.info(f"开锁结果：{open_result}")
            
            # 步骤4：销毁门锁对象
            destroy_result = self.destroy_door_instance(door_handle)
            logger.info(f"销毁门锁对象结果：{destroy_result}")
            
            # 步骤5：注销
            logout_result = self.logout()
            logger.info(f"注销结果：{logout_result}")

            return {
                "success": open_result,
                "door_handle": door_handle,
                "open_result": open_result,
                "destroy_result": destroy_result,
                "logout_result": logout_result,
                "message": "开锁成功" if open_result else "开锁失败"
            }

        except Exception as e:
            # 发生异常时尝试注销
            try:
                self.logout()
            except:
                pass

            error_msg = str(e)
            logger.error(f"开锁流程异常：{error_msg}")
            
            return {
                "success": False,
                "message": error_msg,
                "error": error_msg
            }


# 为了向后兼容，保留旧的类名
DahuaLogin = DahuaService 