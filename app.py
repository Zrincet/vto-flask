from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, Response
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, disconnect, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import hashlib
import requests
import json
import paho.mqtt.client as mqtt
import threading
import time
import subprocess
import signal
import base64
from datetime import datetime
import logging

# 导入自定义模块
from models import db, init_app, User, Device, Config, BemfaKey, HomeKitConfig, HomeKitDevice
from services import DahuaService, mqtt_manager, bemfa_service, bemfa_sync_service, homekit_service, format_homekit_pincode, parse_homekit_pincode
from routes import auth_bp, device_bp, homekit_bp, video_bp, settings_bp

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# 生成数据库绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, 'db')
DB_PATH = os.path.join(DB_DIR, 'vto.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化数据库
init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 注册蓝图
app.register_blueprint(auth_bp)
app.register_blueprint(device_bp)
app.register_blueprint(homekit_bp)
app.register_blueprint(video_bp)
app.register_blueprint(settings_bp)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 静态文件路由 - 提供doc文件夹下的文件访问
@app.route('/doc/<path:filename>')
def doc_files(filename):
    """提供文档文件的静态访问"""
    return app.send_static_file(f'../doc/{filename}')

# 数据库模型已迁移到 models/ 目录

# 大华VTO开锁类已迁移到 services/dahua_service.py

# MQTT客户端管理类已迁移到 services/mqtt_service.py

# MQTTManager类已迁移到 services/mqtt_service.py



# HomeKitManager类已迁移到 services/homekit_service.py

# DoorLockAccessory类已迁移到 services/homekit_service.py

# 巴法云API管理类已迁移到 services/bemfa_service.py

class VideoStreamManager:
    """视频流管理器"""
    
    def __init__(self):
        self.active_streams = {}  # 存储活跃的视频流进程
        self.stream_lock = threading.Lock()
        self.thumbnail_cache = {}  # 缩略图缓存
        self.thumbnail_dir = os.path.join(app.static_folder, 'thumbnails')
        
        # 确保缩略图目录存在
        os.makedirs(self.thumbnail_dir, exist_ok=True)
    
    def get_rtsp_url(self, device):
        """构建RTSP URL"""
        return f"rtsp://{device.username}:{device.password}@{device.ip}:554/cam/realmonitor?channel=1&subtype=1"
    
    def generate_thumbnail(self, device_id):
        """生成设备缩略图"""
        try:
            device = Device.query.get(device_id)
            if not device:
                return None
            
            rtsp_url = self.get_rtsp_url(device)
            thumbnail_path = os.path.join(self.thumbnail_dir, f"device_{device_id}.jpg")
            
            # 使用FFmpeg生成缩略图
            cmd = [
                'ffmpeg', '-y',
                '-i', rtsp_url,
                '-ss', '00:00:01',  # 跳过第一秒
                '-vframes', '1',
                '-s', '320x240',    # 缩略图尺寸
                '-f', 'image2',
                thumbnail_path
            ]
            
            # 超时设置：10秒
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            try:
                stdout, stderr = process.communicate(timeout=10)
                if process.returncode == 0:
                    self.thumbnail_cache[device_id] = thumbnail_path
                    return thumbnail_path
                else:
                    logger.error(f"FFmpeg生成缩略图失败: {stderr.decode()}")
                    return None
            except subprocess.TimeoutExpired:
                # 超时处理
                if os.name != 'nt':
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                else:
                    process.terminate()
                logger.error(f"生成缩略图超时: 设备 {device_id}")
                return None
                
        except Exception as e:
            logger.error(f"生成缩略图异常: {e}")
            return None
    
    def get_thumbnail_path(self, device_id):
        """获取缩略图路径"""
        if device_id in self.thumbnail_cache:
            path = self.thumbnail_cache[device_id]
            if os.path.exists(path):
                return path
        
        # 缓存中没有或文件不存在，重新生成
        return self.generate_thumbnail(device_id)
    
    def start_stream(self, device_id, client_id):
        """启动JPEG图片流"""
        try:
            device = Device.query.get(device_id)
            if not device:
                logger.error(f"设备 {device_id} 不存在")
                return False
            
            stream_key = f"{device_id}_{client_id}"
            
            with self.stream_lock:
                if stream_key in self.active_streams:
                    # 流已经存在，返回成功
                    logger.info(f"JPEG图片流 {stream_key} 已存在")
                    return True
                
                rtsp_url = self.get_rtsp_url(device)
                logger.info(f"正在启动JPEG图片流: 设备 {device_id}, RTSP URL: {rtsp_url}")
                
                # 启动图片流进程
                success = self._start_jpeg_stream(stream_key, rtsp_url, device_id, client_id)
                if success:
                    logger.info(f"JPEG图片流启动成功: 设备 {device_id}, 客户端 {client_id}")
                    return True
                else:
                    logger.error(f"JPEG图片流启动失败: 设备 {device_id}")
                    return False
                
        except Exception as e:
            logger.error(f"启动JPEG图片流失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return False
    
    def _start_jpeg_stream(self, stream_key, rtsp_url, device_id, client_id):
        """启动JPEG图片流和音频流"""
        logger.info(f"开始启动JPEG图片流和音频流: {stream_key}, RTSP URL: {rtsp_url}")
        
        try:
            # FFmpeg命令 - 输出MJPEG格式实现低延迟
            jpeg_cmd = [
                'ffmpeg', '-y',
                '-rtsp_transport', 'tcp',  # 使用TCP传输，更稳定
                '-i', rtsp_url,
                '-c:v', 'mjpeg',           # MJPEG编码，低延迟
                '-q:v', '3',               # 图片质量 (1-31，越小质量越好)
                '-s', '352x288',          # 720p分辨率
                '-r', '25',                # 25fps以获得更流畅的体验
                '-f', 'mjpeg',             # 输出MJPEG格式
                '-'                        # 输出到stdout
            ]
            
            logger.info(f"JPEG流FFmpeg命令: {' '.join(jpeg_cmd)}")
            
            # 启动JPEG图片流进程
            logger.info(f"启动JPEG图片流进程: {stream_key}")
            jpeg_process = subprocess.Popen(
                jpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            logger.info(f"JPEG图片流进程启动成功: {stream_key}, PID: {jpeg_process.pid}")
            
            # 启动音频流进程
            logger.info(f"准备启动音频流进程: {stream_key}")
            audio_process = self._start_audio_stream(rtsp_url, device_id, client_id)
            
            if audio_process:
                logger.info(f"音频流进程启动成功: {stream_key}, PID: {audio_process.pid}")
            else:
                logger.warning(f"音频流进程启动失败: {stream_key}")
            
            # 存储流信息
            logger.info(f"存储流信息到active_streams: {stream_key}")
            self.active_streams[stream_key] = {
                'jpeg_process': jpeg_process,
                'audio_process': audio_process,
                'device_id': device_id,
                'client_id': client_id,
                'start_time': time.time()
            }
            
            logger.info(f"当前活跃流数量: {len(self.active_streams)}")
            
            # 启动JPEG数据读取线程
            logger.info(f"启动JPEG数据读取线程: {stream_key}")
            threading.Thread(
                target=self._jpeg_stream_reader,
                args=(stream_key, jpeg_process),
                daemon=True
            ).start()
            
            logger.info(f"JPEG图片流和音频流启动完成: {stream_key}")
            return True
            
        except Exception as e:
            logger.error(f"启动JPEG图片流失败: {stream_key}, 错误: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return False
    
    def _start_audio_stream(self, rtsp_url, device_id, client_id):
        """启动音频流"""
        stream_key = f"{device_id}_{client_id}"
        logger.info(f"开始启动音频流: {stream_key}, RTSP URL: {rtsp_url}")
        
        try:
            # 首先检查音频流是否存在
            logger.info(f"检查RTSP流是否包含音频: {rtsp_url}")
            probe_cmd = [
                'ffprobe', '-v', 'quiet', '-select_streams', 'a:0',
                '-show_entries', 'stream=codec_name,sample_rate,channels',
                '-of', 'csv=p=0', rtsp_url
            ]
            
            try:
                probe_result = subprocess.run(
                    probe_cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
                
                if probe_result.returncode == 0 and probe_result.stdout.strip():
                    logger.info(f"音频流检查成功: {probe_result.stdout.strip()}")
                else:
                    logger.warning(f"音频流检查失败或无音频流: returncode={probe_result.returncode}, stdout={probe_result.stdout}, stderr={probe_result.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning(f"音频流检查超时: {rtsp_url}")
            except Exception as probe_error:
                logger.error(f"音频流检查异常: {probe_error}")
            
            # 简化的音频命令，使用更兼容的格式
            audio_cmd = [
                'ffmpeg', '-y',
                '-rtsp_transport', 'tcp',
                '-i', rtsp_url,
                '-vn',                     # 不包含视频
                '-c:a', 'pcm_s16le',       # 使用PCM格式，更稳定
                '-ar', '22050',            # 降低采样率减少数据量
                '-ac', '1',                # 单声道
                '-f', 'wav',               # WAV格式，兼容性更好
                '-'                        # 输出到stdout
            ]
            
            logger.info(f"音频流FFmpeg命令: {' '.join(audio_cmd)}")
            
            audio_process = subprocess.Popen(
                audio_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # 无缓冲，实时输出
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            logger.info(f"音频FFmpeg进程已启动: PID={audio_process.pid}, stream_key={stream_key}")
            
            # 短暂等待，检查进程是否正常启动
            time.sleep(0.5)
            
            if audio_process.poll() is not None:
                logger.error(f"音频FFmpeg进程启动后立即退出: PID={audio_process.pid}, returncode={audio_process.returncode}")
                stderr_output = audio_process.stderr.read().decode('utf-8')
                logger.error(f"音频FFmpeg错误输出: {stderr_output}")
                return None
            
            logger.info(f"音频FFmpeg进程状态检查通过: PID={audio_process.pid}")
            
            # 启动音频数据读取线程
            logger.info(f"启动音频数据读取线程: stream_key={stream_key}")
            threading.Thread(
                target=self._audio_stream_reader,
                args=(stream_key, audio_process, device_id, client_id),
                daemon=True
            ).start()
            
            logger.info(f"音频流启动成功: 设备 {device_id}, 进程PID={audio_process.pid}")
            return audio_process
            
        except Exception as e:
            logger.error(f"启动音频流失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return None
    
    def stop_stream(self, device_id, client_id):
        """停止JPEG图片流和音频流"""
        stream_key = f"{device_id}_{client_id}"
        
        with self.stream_lock:
            if stream_key in self.active_streams:
                stream_info = self.active_streams[stream_key]
                jpeg_process = stream_info.get('jpeg_process')
                audio_process = stream_info.get('audio_process')
                
                # 先从活跃流列表中移除，停止数据读取
                del self.active_streams[stream_key]
                logger.info(f"已从活跃流列表移除: {stream_key}")
                
                # 停止JPEG进程
                self._terminate_process(jpeg_process, "JPEG", stream_key)
                
                # 停止音频进程（如果存在）
                if audio_process:
                    self._terminate_process(audio_process, "音频", stream_key)
                else:
                    logger.info(f"设备 {device_id} 没有音频流进程")
                
                logger.info(f"停止JPEG图片流和音频流: 设备 {device_id}, 客户端 {client_id}")
                return True
        
        return False
    
    def _terminate_process(self, process, process_type, stream_key, timeout=2):
        """安全地终止进程"""
        if not process:
            return
            
        try:
            # 检查进程是否已经结束
            if process.poll() is not None:
                logger.info(f"{process_type}进程已经结束: {stream_key}")
                return
            
            logger.info(f"正在终止{process_type}进程: {stream_key}")
            
            # 发送SIGTERM信号
            if os.name != 'nt':
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
            
            # 等待进程结束
            try:
                process.wait(timeout=timeout)
                logger.info(f"{process_type}进程正常结束: {stream_key}")
            except subprocess.TimeoutExpired:
                logger.warning(f"{process_type}进程在{timeout}秒内未响应，强制终止: {stream_key}")
                # 强制杀死进程
                if os.name != 'nt':
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # 进程已经不存在
                else:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass  # 进程已经不存在
                        
                # 再次等待确认进程结束
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    logger.error(f"{process_type}进程强制终止失败: {stream_key}")
                    
        except Exception as e:
            logger.error(f"终止{process_type}进程时发生异常: {e}")
            # 尝试强制终止
            try:
                if os.name != 'nt':
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
            except:
                pass  # 忽略强制终止时的所有异常
    
    def _jpeg_stream_reader(self, stream_key, process):
        """读取JPEG图片流数据并通过WebSocket发送"""
        logger.info(f"开始读取JPEG图片流数据: {stream_key}")
        
        try:
            buffer = b''
            frame_count = 0
            
            while stream_key in self.active_streams:
                # 读取数据块
                chunk = process.stdout.read(8192)
                if not chunk:
                    logger.info(f"JPEG图片流数据读取完毕: {stream_key}")
                    break
                
                buffer += chunk
                
                # 检查FFmpeg进程状态
                if process.poll() is not None:
                    logger.warning(f"FFmpeg进程已结束: {stream_key}, 返回码: {process.returncode}")
                    stderr_output = process.stderr.read().decode('utf-8')
                    if stderr_output:
                        logger.error(f"FFmpeg错误输出: {stderr_output}")
                    break
                
                # 寻找JPEG图片边界
                while True:
                    # 查找JPEG起始标记 (FF D8)
                    start_idx = buffer.find(b'\xff\xd8')
                    if start_idx == -1:
                        break
                    
                    # 从起始位置开始查找JPEG结束标记 (FF D9)
                    end_idx = buffer.find(b'\xff\xd9', start_idx + 2)
                    if end_idx == -1:
                        # 没有找到结束标记，保留从起始位置到缓冲区末尾的数据
                        buffer = buffer[start_idx:]
                        break
                    
                    # 提取完整的JPEG图片数据
                    jpeg_data = buffer[start_idx:end_idx + 2]
                    buffer = buffer[end_idx + 2:]
                    
                    frame_count += 1
                    if frame_count % 5000 == 0:  # 每50帧记录一次
                        logger.info(f"已发送 {frame_count} 帧JPEG图片: {stream_key}")
                    
                    # 通过WebSocket发送JPEG图片数据
                    if stream_key in self.active_streams:
                        stream_info = self.active_streams[stream_key]
                        client_id = stream_info['client_id']
                        
                        socketio.emit('jpeg_frame', {
                            'data': base64.b64encode(jpeg_data).decode('utf-8'),
                            'device_id': stream_info['device_id'],
                            'frame_number': frame_count,
                            'frame_size': len(jpeg_data)
                        }, room=client_id)
                
        except Exception as e:
            logger.error(f"JPEG图片流数据读取错误: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            
            # 通知客户端发生错误
            if stream_key in self.active_streams:
                stream_info = self.active_streams[stream_key]
                client_id = stream_info['client_id']
                socketio.emit('video_error', {
                    'message': f'JPEG图片流数据读取错误: {str(e)}'
                }, room=client_id)
                
        finally:
            # 清理资源
            logger.info(f"清理JPEG图片流资源: {stream_key}")
            # 通知客户端流已停止
            if stream_key in self.active_streams:
                stream_info = self.active_streams[stream_key]
                socketio.emit('video_stream_stopped', {
                    'message': 'JPEG图片流已停止'
                }, room=stream_info['client_id'])
    
    def _audio_stream_reader(self, stream_key, process, device_id, client_id):
        """读取音频流数据并通过WebSocket发送"""
        logger.info(f"开始读取音频流数据: {stream_key}, 进程PID: {process.pid}")
        
        try:
            chunk_count = 0
            header_sent = False
            total_bytes_sent = 0
            last_log_time = time.time()
            
            # 检查进程初始状态
            if process.poll() is not None:
                logger.error(f"音频FFmpeg进程在开始读取前已退出: {stream_key}, 返回码: {process.returncode}")
                stderr_output = process.stderr.read().decode('utf-8')
                if stderr_output:
                    logger.error(f"音频FFmpeg错误输出: {stderr_output}")
                return
            
            logger.info(f"开始音频数据读取循环: {stream_key}")
            
            # 不依赖active_streams来判断是否继续运行，而是直接检查进程状态
            while True:
                try:
                    # 检查进程状态
                    poll_result = process.poll()
                    if poll_result is not None:
                        logger.warning(f"音频FFmpeg进程已结束: {stream_key}, 返回码: {poll_result}")
                        stderr_output = process.stderr.read().decode('utf-8')
                        if stderr_output:
                            logger.error(f"音频FFmpeg错误输出: {stderr_output}")
                        break
                    
                    # 检查stream_key是否在active_streams中（用于优雅停止）
                    # 增加启动后的等待时间，避免时序问题
                    if chunk_count > 0 and stream_key not in self.active_streams:
                        logger.info(f"stream_key已从active_streams中移除，准备停止: {stream_key}")
                        break
                    
                    # 读取音频数据块，WAV格式
                    logger.debug(f"尝试读取音频数据块: {stream_key}")
                    chunk = process.stdout.read(4096)  # 增大块大小
                    
                    if not chunk:
                        logger.warning(f"音频流数据读取完毕，收到空数据块: {stream_key}")
                        break
                    
                    chunk_count += 1
                    total_bytes_sent += len(chunk)
                    
                    logger.debug(f"读取到音频数据块: {stream_key}, 大小: {len(chunk)}, 总块数: {chunk_count}")
                    
                    # 发送WAV头部（只发送一次）
                    if not header_sent and chunk_count == 1:
                        logger.info(f"发送音频WAV头部: {stream_key}, 数据大小: {len(chunk)}")
                        header_data = chunk[:44] if len(chunk) >= 44 else chunk
                        
                        try:
                            socketio.emit('audio_header', {
                                'data': base64.b64encode(header_data).decode('utf-8'),
                                'device_id': device_id,
                                'sample_rate': 22050,
                                'channels': 1,
                                'bits_per_sample': 16
                            }, room=client_id)
                            logger.info(f"WAV头部发送成功: {stream_key}, 头部大小: {len(header_data)}")
                        except Exception as emit_error:
                            logger.error(f"发送WAV头部失败: {stream_key}, 错误: {emit_error}")
                        
                        header_sent = True
                        
                        # 如果第一个chunk大于44字节，发送剩余的音频数据
                        if len(chunk) > 44:
                            audio_data = chunk[44:]
                            logger.debug(f"发送首个音频数据块: {stream_key}, 大小: {len(audio_data)}")
                            try:
                                socketio.emit('audio_data', {
                                    'data': base64.b64encode(audio_data).decode('utf-8'),
                                    'device_id': device_id,
                                    'chunk_size': len(audio_data),
                                    'timestamp': time.time()
                                }, room=client_id)
                                logger.debug(f"首个音频数据块发送成功: {stream_key}")
                            except Exception as emit_error:
                                logger.error(f"发送首个音频数据块失败: {stream_key}, 错误: {emit_error}")
                    else:
                        # 发送音频数据
                        logger.debug(f"发送音频数据块: {stream_key}, 大小: {len(chunk)}")
                        try:
                            socketio.emit('audio_data', {
                                'data': base64.b64encode(chunk).decode('utf-8'),
                                'device_id': device_id,
                                'chunk_size': len(chunk),
                                'timestamp': time.time()
                            }, room=client_id)
                            logger.debug(f"音频数据块发送成功: {stream_key}")
                        except Exception as emit_error:
                            logger.error(f"发送音频数据块失败: {stream_key}, 错误: {emit_error}")
                    
                    # 定期记录统计信息
                    current_time = time.time()
                    if current_time - last_log_time >= 300:  # 每5秒记录一次
                        logger.info(f"音频流统计: {stream_key}, 已发送 {chunk_count} 个数据包, 总字节数: {total_bytes_sent}")
                        last_log_time = current_time
                    
                    # 每100个数据包的详细记录
                    if chunk_count % 5000 == 0:
                        logger.info(f"已发送 {chunk_count} 个音频数据包: {stream_key}, 总字节数: {total_bytes_sent}")
                        
                except Exception as read_error:
                    logger.error(f"读取音频数据块失败: {stream_key}, 错误: {read_error}")
                    import traceback
                    logger.error(f"读取错误详情: {traceback.format_exc()}")
                    continue  # 继续尝试读取下一个数据块
                
            logger.info(f"音频数据读取循环结束: {stream_key}, 最终chunk_count: {chunk_count}")
            
        except Exception as e:
            logger.error(f"音频流数据读取错误: {stream_key}, 错误: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            
            # 通知客户端发生错误
            try:
                socketio.emit('audio_error', {
                    'message': f'音频流数据读取错误: {str(e)}'
                }, room=client_id)
            except Exception as emit_error:
                logger.error(f"发送音频错误通知失败: {emit_error}")
            
        finally:
            # 清理资源
            logger.info(f"清理音频流资源: {stream_key}, 总计发送 {chunk_count} 个数据包, {total_bytes_sent} 字节")
            
            # 通知客户端音频流已停止
            try:
                socketio.emit('audio_stream_stopped', {
                    'message': '音频流已停止'
                }, room=client_id)
                logger.info(f"音频流停止通知已发送: {stream_key}")
            except Exception as emit_error:
                logger.error(f"发送音频流停止通知失败: {emit_error}")
    
    def cleanup_expired_streams(self):
        """清理过期的视频流"""
        current_time = time.time()
        expired_streams = []
        
        with self.stream_lock:
            for stream_key, stream_info in self.active_streams.items():
                # 超过30分钟的流视为过期
                if current_time - stream_info['start_time'] > 1800:
                    expired_streams.append(stream_key)
        
        for stream_key in expired_streams:
            device_id, client_id = stream_key.split('_')
            self.stop_stream(int(device_id), client_id)
    
    def get_active_streams_count(self):
        """获取活跃流数量"""
        with self.stream_lock:
            return len(self.active_streams)

    def generate_thumbnail_data(self, device_id):
        """动态生成设备缩略图数据"""
        try:
            device = Device.query.get(device_id)
            if not device:
                return None
            
            rtsp_url = self.get_rtsp_url(device)
            
            # 使用FFmpeg生成缩略图到内存
            cmd = [
                'ffmpeg', '-y',
                '-rtsp_transport', 'tcp',
                '-i', rtsp_url,
                '-ss', '00:00:01',  # 跳过第一秒
                '-vframes', '1',
                '-s', '480x360',    # 更大的缩略图尺寸，适合移动端
                '-q:v', '5',        # 图片质量
                '-f', 'image2pipe', # 输出到管道
                '-vcodec', 'mjpeg', # MJPEG编码
                '-'                 # 输出到stdout
            ]
            
            # 超时设置：8秒
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            try:
                stdout, stderr = process.communicate(timeout=8)
                if process.returncode == 0 and stdout:
                    # 返回缩略图的二进制数据
                    return stdout
                else:
                    logger.error(f"FFmpeg生成缩略图失败: {stderr.decode()}")
                    return None
            except subprocess.TimeoutExpired:
                # 超时处理
                if os.name != 'nt':
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                else:
                    process.terminate()
                logger.error(f"生成缩略图超时: 设备 {device_id}")
                return None
                
        except Exception as e:
            logger.error(f"生成缩略图异常: {e}")
            return None

# 全局巴法云API管理器
# 全局服务实例已迁移到 services/ 模块
# 设置MQTT管理器的Flask应用上下文
mqtt_manager.set_app(app)

# HomeKit管理器已迁移到 services/homekit_service.py

# 全局视频流管理器
video_manager = VideoStreamManager()

# 认证装饰器（供其他路由使用）
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查session中是否有用户ID
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        
        # 检查数据库中用户是否still存在
        user = User.query.get(session['user_id'])
        if not user:
            # 用户在数据库中不存在，清除session并重定向到登录页
            session.clear()
            flash('用户账户不存在，请重新登录', 'error')
            return redirect(url_for('auth.login'))
        
        # 更新session中的用户名（防止用户名被修改后session中的信息过期）
        session['username'] = user.username
        
        return f(*args, **kwargs)
    return decorated_function

# 路由定义

# 登录和登出路由已迁移到 routes/auth.py

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    return redirect(url_for('device.visible_devices'))

# dashboard路由已迁移到 routes/device.py

# 设备列表相关路由已迁移到 routes/device.py

# 设备管理相关路由已迁移到 routes/device.py

# 设备CRUD操作路由已迁移到 routes/device.py

# 设置和巴法云路由已迁移到 routes/settings.py

# HomeKit路由已迁移到 routes/homekit.py

# 密码修改路由已迁移到 routes/auth.py

# 用户管理路由已迁移到 routes/auth.py

# 初始化MQTT服务
def init_mqtt_service():
    """程序启动时初始化MQTT服务"""
    try:
        # 检查MQTT是否已启用
        mqtt_config = Config.query.filter_by(key='mqtt_enabled').first()
        if not mqtt_config or mqtt_config.value != 'true':
            logger.info("MQTT服务未启用")
            return
        
        # 优先使用新的BemfaKey配置
        bemfa_keys = BemfaKey.query.filter_by(enabled=True).all()
        
        if bemfa_keys:
            logger.info("正在启动多个巴法云账号的MQTT服务...")
            mqtt_manager.start_all_clients()
            logger.info("多账号MQTT服务启动完成")
        else:
            # 回退到旧的配置方式
            bemfa_key_config = Config.query.filter_by(key='bemfa_private_key').first()
            if bemfa_key_config and bemfa_key_config.value:
                logger.info("使用旧的巴法云私钥配置启动MQTT服务...")
                mqtt_manager.start_mqtt_service("bemfa.com", 9501, bemfa_key_config.value)
                logger.info("MQTT服务启动完成")
            else:
                logger.warning("MQTT服务已启用但未配置巴法云私钥")
                return
        
    except Exception as e:
        logger.error(f"启动MQTT服务时出错: {str(e)}")

# init_homekit_service函数已迁移到 services/homekit_service.py

# 延迟启动MQTT服务
def delayed_mqtt_init():
    """延迟启动MQTT服务，确保应用完全启动后再连接"""
    import threading
    import time

    # 这是主进程，启动MQTT服务
    def start_mqtt():
        # 等待3秒让应用完全启动
        time.sleep(3)
        with app.app_context():
            mqtt_manager.init_mqtt_service()

    # 在后台线程中启动
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()

# 初始化数据库
def init_db():
    with app.app_context():
        # 检查并创建数据库目录
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR)
            logger.info(f'已创建数据库目录: {DB_DIR}')
        
        # 检查并创建数据库文件
        if not os.path.exists(DB_PATH):
            # 创建空的SQLite数据库文件
            open(DB_PATH, 'a').close()
            logger.info(f'已创建数据库文件: {DB_PATH}')
        
        # 确保数据库表存在
        db.create_all()
        logger.info('数据库表已创建')
        
        # 不再自动创建默认用户，改为通过初始化流程创建
        # 预设设备已迁移到 doc/preset_devices.json，通过Web界面批量导入


# 视频流相关路由

@app.route('/get_device_thumbnail/<int:device_id>')
@login_required
def get_device_thumbnail(device_id):
    """获取设备缩略图 - 动态生成并返回二进制数据"""
    try:
        device = Device.query.filter_by(id=device_id, visible=True).first()
        if not device:
            return jsonify({'success': False, 'message': '设备不存在或不可见'})
        
        # 动态生成缩略图
        thumbnail_data = video_manager.generate_thumbnail_data(device_id)
        
        if thumbnail_data:
            # 直接返回二进制图片数据
            return Response(
                thumbnail_data,
                mimetype='image/jpeg',
                headers={
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
            )
        else:
            # 返回默认占位图
            return jsonify({'success': False, 'message': '缩略图生成失败'})
            
    except Exception as e:
        logger.error(f"获取设备缩略图失败: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/generate_thumbnail/<int:device_id>', methods=['POST'])
@login_required
def generate_thumbnail(device_id):
    """重新生成设备缩略图"""
    try:
        thumbnail_path = video_manager.generate_thumbnail(device_id)
        if thumbnail_path and os.path.exists(thumbnail_path):
            relative_path = os.path.relpath(thumbnail_path, app.static_folder)
            return jsonify({
                'success': True,
                'thumbnail_url': f'/static/{relative_path.replace(os.sep, "/")}'
            })
        else:
            return jsonify({
                'success': False,
                'message': '缩略图生成失败'
            })
    except Exception as e:
        logger.error(f"生成缩略图失败: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/video_stream/<int:device_id>')
@login_required
def video_stream(device_id):
    """提供设备视频流"""
    try:
        device = Device.query.filter_by(id=device_id, visible=True).first()
        if not device:
            return "设备不存在或不可见", 404
        
        def generate_video():
            rtsp_url = video_manager.get_rtsp_url(device)
            logger.info(f"开始视频流: 设备 {device_id}, RTSP URL: {rtsp_url}")
            
            # 简化的FFmpeg命令，直接输出HTTP流
            cmd = [
                'ffmpeg', '-y',
                '-rtsp_transport', 'tcp',
                '-i', rtsp_url,
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-tune', 'zerolatency',
                '-s', '352x288',
                '-r', '15',
                '-b:v', '800k',
                '-c:a', 'aac',
                '-b:a', '64k',
                '-f', 'mp4',
                '-movflags', 'frag_keyframe+empty_moov',
                '-'
            ]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            try:
                while True:
                    chunk = process.stdout.read(8192)
                    if not chunk:
                        break
                    yield chunk
            except GeneratorExit:
                # 客户端断开连接
                logger.info(f"客户端断开，停止视频流: 设备 {device_id}")
            finally:
                # 清理FFmpeg进程
                try:
                    if os.name != 'nt':
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    else:
                        process.terminate()
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name != 'nt':
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    else:
                        process.kill()
                except:
                    pass
        
        return Response(
            generate_video(),
            mimetype='video/mp4',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Content-Type': 'video/mp4'
            }
        )
        
    except Exception as e:
        logger.error(f"视频流处理失败: {e}")
        return str(e), 500

# WebSocket事件处理

@socketio.on('connect')
def handle_connect():
    """客户端连接事件"""
    if 'user_id' not in session:
        disconnect()
        return
    
    # 让客户端加入自己的房间
    join_room(request.sid)
    logger.info(f"客户端连接并加入房间: {request.sid}")
    emit('connected', {'status': 'success'})

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开连接事件"""
    logger.info(f"客户端断开连接: {request.sid}")
    
    # 停止该客户端的所有视频流
    with video_manager.stream_lock:
        streams_to_stop = []
        for stream_key, stream_info in video_manager.active_streams.items():
            if stream_info['client_id'] == request.sid:
                streams_to_stop.append(stream_key)
        
        for stream_key in streams_to_stop:
            device_id, client_id = stream_key.split('_')
            video_manager.stop_stream(int(device_id), client_id)
    
    # 离开房间
    leave_room(request.sid)

@socketio.on('start_video_stream')
def handle_start_video_stream(data):
    """开始视频流"""
    if 'user_id' not in session:
        disconnect()
        return
    
    try:
        device_id = int(data.get('device_id'))
        client_id = request.sid
        
        logger.info(f"收到启动视频流请求: 设备 {device_id}, 客户端 {client_id}")
        
        # 检查设备是否存在且可见
        device = Device.query.filter_by(id=device_id, visible=True).first()
        if not device:
            logger.error(f"设备 {device_id} 不存在或不可见")
            emit('video_error', {'message': '设备不存在或不可见'})
            return
        
        logger.info(f"设备验证通过: {device.name} ({device.ip})")
        
        # 启动视频流
        success = video_manager.start_stream(device_id, client_id)
        if success:
            logger.info(f"视频流启动成功: 设备 {device_id}")
            emit('video_stream_started', {
                'device_id': device_id,
                'message': '视频流启动成功'
            })
        else:
            logger.error(f"视频流启动失败: 设备 {device_id}")
            emit('video_error', {'message': '视频流启动失败'})
            
    except Exception as e:
        logger.error(f"启动视频流失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        emit('video_error', {'message': str(e)})

@socketio.on('stop_video_stream')
def handle_stop_video_stream(data):
    """停止视频流"""
    if 'user_id' not in session:
        disconnect()
        return
    
    try:
        device_id = int(data.get('device_id'))
        client_id = request.sid
        
        logger.info(f"收到停止视频流请求: 设备 {device_id}, 客户端 {client_id}")
        
        success = video_manager.stop_stream(device_id, client_id)
        if success:
            logger.info(f"视频流停止成功: 设备 {device_id}")
            emit('video_stream_stopped', {
                'device_id': device_id,
                'message': '视频流停止成功'
            })
        else:
            logger.warning(f"视频流停止失败: 设备 {device_id}")
            emit('video_error', {'message': '视频流停止失败'})
            
    except Exception as e:
        logger.error(f"停止视频流失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        emit('video_error', {'message': str(e)})

if __name__ == '__main__':
    init_db()
    # 启动延迟MQTT初始化
    mqtt_manager.delayed_mqtt_init()
    # 启动HomeKit服务
    with app.app_context():
        homekit_service.init_homekit_service()
    socketio.run(app, host='0.0.0.0', port=8998, debug=False, allow_unsafe_werkzeug=True)