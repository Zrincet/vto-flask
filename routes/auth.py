"""
账户认证相关路由
包含登录、登出、密码修改、用户管理等功能
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# 延迟导入，避免循环导入
def get_db():
    from app import db
    return db

def get_models():
    from models.user import User
    return User

# 创建认证蓝图
auth_bp = Blueprint('auth', __name__)

# 认证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        User = get_models()
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('登录成功', 'success')
            return redirect(url_for('visible_devices'))
        else:
            flash('用户名或密码错误', 'error')
    
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    """用户登出"""
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改密码"""
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        User = get_models()
        user = User.query.get(session['user_id'])
        
        if not check_password_hash(user.password_hash, current_password):
            flash('当前密码错误', 'error')
            return render_template('change_password.html')
        
        if new_password != confirm_password:
            flash('新密码与确认密码不匹配', 'error')
            return render_template('change_password.html')
        
        if len(new_password) < 6:
            flash('密码长度至少6位', 'error')
            return render_template('change_password.html')
        
        user.password_hash = generate_password_hash(new_password)
        db = get_db()
        db.session.commit()
        
        flash('密码修改成功', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('change_password.html')

@auth_bp.route('/user_management')
@login_required
def user_management():
    """用户管理页面"""
    User = get_models()
    users = User.query.all()
    return render_template('user_management.html', users=users)

@auth_bp.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    """添加用户"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        User = get_models()
        db = get_db()
        
        # 验证用户名是否已存在
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('用户名已存在', 'error')
            return render_template('add_user.html')
        
        # 验证密码长度
        if len(password) < 6:
            flash('密码长度至少6位', 'error')
            return render_template('add_user.html')
        
        # 创建新用户
        new_user = User(
            username=username,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        
        flash(f'用户 {username} 添加成功', 'success')
        return redirect(url_for('auth.user_management'))
    
    return render_template('add_user.html')

@auth_bp.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    """编辑用户"""
    User = get_models()
    db = get_db()
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form.get('password', '')
        
        # 验证用户名是否已存在（排除自己）
        existing_user = User.query.filter(User.username == username, User.id != user_id).first()
        if existing_user:
            flash('用户名已存在', 'error')
            return render_template('edit_user.html', user=user)
        
        # 更新用户名
        user.username = username
        
        # 如果提供了新密码，则更新密码
        if password:
            if len(password) < 6:
                flash('密码长度至少6位', 'error')
                return render_template('edit_user.html', user=user)
            user.password_hash = generate_password_hash(password)
        
        db.session.commit()
        flash(f'用户 {username} 更新成功', 'success')
        return redirect(url_for('auth.user_management'))
    
    return render_template('edit_user.html', user=user)

@auth_bp.route('/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    """删除用户"""
    User = get_models()
    db = get_db()
    user = User.query.get_or_404(user_id)
    
    # 不能删除自己
    if user.id == session['user_id']:
        flash('不能删除当前登录用户', 'error')
        return redirect(url_for('auth.user_management'))
    
    # 不能删除最后一个用户
    if User.query.count() <= 1:
        flash('至少需要保留一个用户', 'error')
        return redirect(url_for('auth.user_management'))
    
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    flash(f'用户 {username} 删除成功', 'success')
    return redirect(url_for('auth.user_management')) 