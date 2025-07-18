"""
视频流和缩略图相关路由
包含设备缩略图生成和视频流功能
"""

from flask import Blueprint, jsonify, Response
import subprocess
import signal
import os
import logging

# 延迟导入，避免循环导入
def get_models():
    from models.device import Device
    return Device

def get_video_manager():
    from app import video_manager
    return video_manager

def get_login_required():
    from app import login_required
    return login_required

# 创建视频蓝图
video_bp = Blueprint('video', __name__)
logger = logging.getLogger(__name__)

@video_bp.route('/get_device_thumbnail/<int:device_id>')
def get_device_thumbnail(device_id):
    """获取设备缩略图 - 动态生成并返回二进制数据"""
    login_required = get_login_required()
    Device = get_models()
    video_manager = get_video_manager()
    
    @login_required
    def _get_device_thumbnail():
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
    
    return _get_device_thumbnail()

@video_bp.route('/generate_thumbnail/<int:device_id>', methods=['POST'])
def generate_thumbnail(device_id):
    """重新生成设备缩略图"""
    login_required = get_login_required()
    video_manager = get_video_manager()
    
    @login_required
    def _generate_thumbnail():
        try:
            from app import app
            
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
    
    return _generate_thumbnail()

@video_bp.route('/video_stream/<int:device_id>')
def video_stream(device_id):
    """提供设备视频流"""
    login_required = get_login_required()
    Device = get_models()
    video_manager = get_video_manager()
    
    @login_required
    def _video_stream():
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
    
    return _video_stream() 