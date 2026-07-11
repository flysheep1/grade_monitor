# app.py
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import threading
import time
import json
from login import get_cookies
from zfn_api import Client
from mail_send import send_mail_success
from config import JIAOWU_CONFIG, APP_CONFIG
import os
import hashlib
from datetime import datetime

app = Flask(__name__)
app.secret_key = APP_CONFIG['secret_key']
app.config['PERMANENT_SESSION_LIFETIME'] = APP_CONFIG['session_lifetime_seconds']

ADMIN_PASSWORD = APP_CONFIG['admin_password']
ADMIN_EMAIL = APP_CONFIG['admin_email']
MONITORING_TASKS = {}
TASK_LOCK = threading.Lock()

# 数据文件路径
DATA_FILE = 'users_data.json'
MONITORING_FILE = 'monitoring_tasks.json'

# 加载用户数据
def load_users_data():
    """从JSON文件加载用户数据"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载数据文件失败: {e}")
            return {'users': {}, 'next_user_id': 1}
    return {'users': {}, 'next_user_id': 1}

# 保存用户数据
def save_users_data(data):
    """保存用户数据到JSON文件"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存数据文件失败: {e}")
        return False

# 加载监测任务
def load_monitoring_tasks():
    """从JSON文件加载监测任务"""
    if os.path.exists(MONITORING_FILE):
        try:
            with open(MONITORING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载监测任务文件失败: {e}")
            return {}
    return {}

# 保存监测任务
def save_monitoring_tasks(tasks):
    """保存监测任务到JSON文件"""
    try:
        with open(MONITORING_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存监测任务文件失败: {e}")
        return False

# 初始化用户数据
users_data = load_users_data()
USERS = users_data.get('users', {})
USER_ID_COUNTER = users_data.get('next_user_id', 1)

# 初始化监测任务（从文件加载）
MONITORING_TASKS = load_monitoring_tasks()

# 加密工具函数
def encrypt_password(password):
    """简单密码加密（生产环境建议用bcrypt）"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def encrypt_jw_password(password):
    """教务账号密码加密（使用base64编码，可逆）"""
    import base64
    return base64.b64encode(password.encode('utf-8')).decode('utf-8')

def decrypt_jw_password(encrypted_password):
    """教务账号密码解密"""
    import base64
    try:
        return base64.b64decode(encrypted_password.encode('utf-8')).decode('utf-8')
    except Exception as e:
        return None

class GradeMonitor:
    def __init__(self, username, password, email, user_id):
        self.username = username
        self.password = password
        self.email = email
        self.user_id = user_id
        self.client = None
        self.last_grades = {}
        self.is_monitoring = False
        
    def login(self):
        """登录教务系统"""
        try:
            cookies = get_cookies(self.username, self.password, use_saved=False)
            if cookies:
                self.client = Client(cookies=cookies, base_url=JIAOWU_CONFIG["base_url"])
                return True
            return False
        except Exception as e:
            print(f"登录失败: {str(e)}")
            return False
    
    def get_latest_grades(self, year=None, term=0):
        """获取最新成绩"""
        if not self.client:
            return None
            
        try:
            import datetime
            now = datetime.datetime.now()
            current_year = now.year
            current_term = 1 if now.month <= 7 else 2
            
            if year is None and term == 0:
                attempts = [
                    (current_year, current_term),
                    (current_year, 3-current_term),
                    (current_year, 0),
                    (current_year-1, current_term),
                    (current_year-1, 3-current_term),
                    (current_year-1, 0),
                ]
            else:
                attempts = [(year, term)]
            
            for attempt_year, attempt_term in attempts:
                result = self.client.get_grade(attempt_year, attempt_term)
                if result.get('code') == 1000:
                    if result.get('data', {}).get('courses'):
                        print(f"成功获取 {attempt_year} 学年第 {attempt_term} 学期成绩，共 {len(result['data']['courses'])} 门课程")
                        return result.get('data', {})
                    else:
                        print(f"学期 {attempt_year}-{attempt_term} 没有成绩数据，尝试其他学期")
                        continue
                else:
                    print(f"获取 {attempt_year} 学年第 {attempt_term} 学期成绩失败: {result.get('msg')}")
            
            print("所有尝试的学期都没有成绩数据")
            return None
        except Exception as e:
            print(f"获取成绩时出错: {str(e)}")
            return None
    
    def check_new_grades(self):
        """检查是否有新成绩"""
        current_grades = self.get_latest_grades()
        if not current_grades:
            return []
        
        new_grades = []
        current_grade_dict = {course['course_id']: course for course in current_grades.get('courses', [])}
        
        for course_id, course_data in current_grade_dict.items():
            if course_id not in self.last_grades:
                new_grades.append(course_data)
            elif self.last_grades[course_id]['grade'] != course_data['grade']:
                new_grades.append(course_data)
        
        self.last_grades = current_grade_dict
        return new_grades
    
    def send_grade_email(self, grades, year, term):
        """发送成绩邮件"""
        if not grades:
            return True
            
        subject = f"【新成绩通知】{year}学年第{term}学期新成绩发布"
        content = f"""
您好！检测到您的新成绩已发布：

{self.format_grades(grades)}

时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
如需取消监测，请登录网站修改设置。

飞翔的羊羊
"""
        
        try:
            result = send_mail_success(self.email, subject, content)
            return result.get('code') == 1000
        except Exception as e:
            print(f"发送邮件失败: {str(e)}")
            return False
    
    def format_grades(self, grades):
        """格式化成绩信息"""
        if not grades:
            return "暂无成绩"
        
        formatted = []
        for grade in grades:
            formatted.append(
                f"课程: {grade.get('title', '未知课程')}\n"
                f"成绩: {grade.get('grade', '未录入')}\n"
                f"学分: {grade.get('credit', '未设置')}\n"
                f"性质: {grade.get('nature', '未设置')}\n"
                f"类别: {grade.get('category', '未设置')}\n"
                f"-------------------"
            )
        return "\n".join(formatted)

def monitoring_worker(user_id, monitor_id):
    """监测工作线程（按用户隔离）"""
    while True:
        with TASK_LOCK:
            user_tasks = MONITORING_TASKS.get(user_id, {})
            monitor = user_tasks.get(monitor_id)
            if not monitor or not monitor.is_monitoring:
                break
        
        try:
            new_grades = monitor.check_new_grades()
            if new_grades:
                import datetime
                now = datetime.datetime.now()
                current_year = now.year
                current_term = 1 if now.month <= 7 else 2
                monitor.send_grade_email(new_grades, current_year, current_term)
                print(f"用户{user_id}：发现新成绩并已发送邮件通知: {monitor.email}")

            # 分段检查停止标志（每1分钟检查一次）
            for _ in range(APP_CONFIG['monitoring_interval_minutes']):
                with TASK_LOCK:
                    user_tasks = MONITORING_TASKS.get(user_id, {})
                    monitor = user_tasks.get(monitor_id)
                    if not monitor or not monitor.is_monitoring:
                        break
                time.sleep(60)
            else:
                continue
            break
        except Exception as e:
            print(f"用户{user_id}监测任务出错: {str(e)}")
            time.sleep(60)

# --------------- 页面路由 ---------------
@app.route('/grade/')
def index():
    """主页（需登录）"""
    if not session.get('user_logged_in'):
        return redirect(url_for('user_login'))
    
    username = session.get('username')
    saved_account = None
    
    # 获取保存的教务账号和密码
    if username in USERS:
        jw_accounts = USERS[username].get('jw_accounts', {})
        if jw_accounts:
            # 按最后使用时间排序，获取最新的账号
            latest_account = max(jw_accounts.items(), key=lambda x: x[1]['last_used'])
            jw_username = latest_account[0]
            encrypted_password = latest_account[1]['password']
            password = decrypt_jw_password(encrypted_password)
            
            if password:
                saved_account = {
                    'username': jw_username,
                    'password': password
                }
    
    return render_template('index.html', 
                         username=session.get('username'), 
                         user_email=session.get('user_email'),
                         saved_account=saved_account)

@app.route('/grade/admin')
def admin_index():
    """管理员主页"""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    # 获取所有用户的监测任务
    all_tasks = []
    with TASK_LOCK:
        for user_id, user_tasks in MONITORING_TASKS.items():
            for monitor_id, monitor in user_tasks.items():
                if monitor.is_monitoring:
                    all_tasks.append({
                        'user_id': user_id,
                        'monitor_id': monitor_id,
                        'username': monitor.username,
                        'email': monitor.email
                    })
    return render_template('admin.html', users=USERS, tasks=all_tasks)

# --------------- 用户认证 ---------------
@app.route('/grade/user/register', methods=['GET', 'POST'])
def user_register():
    """用户注册"""
    global USER_ID_COUNTER
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        
        if not all([username, password, email]):
            return render_template('register.html', error='请填写完整信息')
        
        if username in USERS:
            return render_template('register.html', error='用户名已存在')
        
        # 存储用户信息
        USERS[username] = {
            'password': encrypt_password(password),
            'email': email,
            'id': USER_ID_COUNTER,
            'jw_accounts': {},
            'grades_history': {}
        }
        USER_ID_COUNTER += 1
        
        # 保存到JSON文件
        users_data['users'] = USERS
        users_data['next_user_id'] = USER_ID_COUNTER
        save_users_data(users_data)
        
        return redirect(url_for('user_login', success='注册成功，请登录'))
    
    return render_template('register.html')

@app.route('/grade/user/login', methods=['GET', 'POST'])
def user_login():
    """用户登录"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username not in USERS:
            return render_template('login.html', error='用户名不存在')
        
        if USERS[username]['password'] != encrypt_password(password):
            return render_template('login.html', error='密码错误')
        
        # 设置用户Session
        session['user_logged_in'] = True
        session['username'] = username
        session['user_id'] = USERS[username]['id']
        session['user_email'] = USERS[username]['email']
        return redirect(url_for('index'))
    
    success_msg = request.args.get('success')
    return render_template('login.html', success=success_msg)

@app.route('/grade/user/logout')
def user_logout():
    """用户退出"""
    session.pop('user_logged_in', None)
    session.pop('username', None)
    session.pop('user_id', None)
    session.pop('user_email', None)
    return redirect(url_for('user_login'))

@app.route('/grade/admin/login', methods=['GET', 'POST'])
def admin_login():
    """管理员登录"""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_index'))
        else:
            return render_template('admin_login.html', error='密码错误')
    return render_template('admin_login.html')

@app.route('/grade/admin/logout')
def admin_logout():
    """管理员退出"""
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# --------------- 成绩操作接口 ---------------
@app.route('/grade/api/get_grades', methods=['POST'])
def api_get_grades():
    """用户获取成绩接口"""
    if not session.get('user_logged_in'):
        return jsonify({'success': False, 'message': '请先登录'})
    
    jw_username = request.form.get('jw_username')
    jw_password = request.form.get('jw_password')
    
    if not all([jw_username, jw_password]):
        return jsonify({'success': False, 'message': '请填写教务系统账号密码'})
    
    try:
        monitor = GradeMonitor(jw_username, jw_password, session['user_email'], session['user_id'])
        if not monitor.login():
            return jsonify({'success': False, 'message': '教务系统登录失败'})
        
        grades_data = monitor.get_latest_grades()
        if not grades_data:
            return jsonify({'success': False, 'message': '暂无成绩数据'})
        
        # 保存教务账号（加密密码）
        username = session['username']
        if username in USERS:
            if 'jw_accounts' not in USERS[username]:
                USERS[username]['jw_accounts'] = {}
            USERS[username]['jw_accounts'][jw_username] = {
                'password': encrypt_jw_password(jw_password),
                'email': session['user_email'],
                'last_used': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # 保存成绩历史
            if 'grades_history' not in USERS[username]:
                USERS[username]['grades_history'] = {}
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            USERS[username]['grades_history'][timestamp] = {
                'year': grades_data.get('year'),
                'term': grades_data.get('term'),
                'courses': grades_data.get('courses', [])
            }
            
            # 保存到JSON文件
            users_data['users'] = USERS
            save_users_data(users_data)
        
        # 获取历史成绩用于对比
        previous_grades = {}
        if username in USERS and 'grades_history' in USERS[username]:
            history = USERS[username]['grades_history']
            if len(history) > 1:
                # 获取倒数第二条记录作为对比
                timestamps = sorted(history.keys(), reverse=True)
                if len(timestamps) >= 2:
                    prev_timestamp = timestamps[1]
                    previous_grades = {c['course_id']: c for c in history[prev_timestamp].get('courses', [])}
        
        # 标记新成绩
        current_grades = grades_data.get('courses', [])
        for course in current_grades:
            course_id = course.get('course_id')
            if course_id in previous_grades:
                prev_grade = previous_grades[course_id].get('grade')
                curr_grade = course.get('grade')
                if prev_grade != curr_grade:
                    course['is_new'] = True
                    course['previous_grade'] = prev_grade
                else:
                    course['is_new'] = False
            else:
                course['is_new'] = True
        
        return jsonify({
            'success': True,
            'grades': current_grades,
            'year': grades_data.get('year'),
            'term': grades_data.get('term')
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取成绩失败: {str(e)}'})

@app.route('/grade/api/start_monitoring', methods=['POST'])
def api_start_monitoring():
    """用户启动监测"""
    if not session.get('user_logged_in'):
        return jsonify({'success': False, 'message': '请先登录'})
    
    user_id = session['user_id']
    jw_username = request.form.get('jw_username')
    jw_password = request.form.get('jw_password')
    email = request.form.get('email', session['user_email'])
    monitor_id = f"{jw_username}_{email}"
    
    # 检查是否已在监测
    with TASK_LOCK:
        user_tasks = MONITORING_TASKS.get(user_id, {})
        if monitor_id in user_tasks and user_tasks[monitor_id].is_monitoring:
            return jsonify({'success': False, 'message': '该教务账号已在监测中'})

    # 创建监测实例
    monitor = GradeMonitor(jw_username, jw_password, email, user_id)
    if not monitor.login():
        return jsonify({'success': False, 'message': '教务系统登录失败'})

    # 初始化成绩
    grades_data = monitor.get_latest_grades()
    if grades_data:
        monitor.last_grades = {course['course_id']: course for course in grades_data.get('courses', [])}

    monitor.is_monitoring = True

    # 保存教务账号到用户数据（加密密码）
    username = session['username']
    if username in USERS:
        if 'jw_accounts' not in USERS[username]:
            USERS[username]['jw_accounts'] = {}
        USERS[username]['jw_accounts'][jw_username] = {
            'password': encrypt_jw_password(jw_password),
            'email': email,
            'last_used': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 保存到JSON文件
        users_data['users'] = USERS
        save_users_data(users_data)

    # 保存任务（按用户ID隔离）
    with TASK_LOCK:
        if user_id not in MONITORING_TASKS:
            MONITORING_TASKS[user_id] = {}
        MONITORING_TASKS[user_id][monitor_id] = monitor

    # 保存监测任务到文件
    save_monitoring_tasks(MONITORING_TASKS)

    # 启动监测线程
    thread = threading.Thread(target=monitoring_worker, args=(user_id, monitor_id))
    thread.daemon = True
    thread.start()

    # 发送开启监测通知邮件
    try:
        subject = "【成绩监测已开启】飞翔的羊羊成绩监测系统"
        content = f"""
您好！

您的成绩监测已成功开启！

监测账号：{jw_username}
通知邮箱：{email}
监测频率：每{APP_CONFIG['monitoring_interval_minutes']}分钟检查一次

当检测到新成绩发布时，系统会自动发送邮件通知您。

如有任何问题，请登录系统查看或联系管理员。

飞翔的羊羊
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_mail_success(email, subject, content)
    except Exception as e:
        print(f"发送开启监测邮件失败: {str(e)}")

    # 发送通知给管理员
    try:
        admin_subject = f"【新监测任务】用户 {session.get('username')} 开启了监测"
        admin_content = f"""
管理员您好！

有新用户开启了成绩监测功能：

用户名：{session.get('username')}
用户ID：{user_id}
教务账号：{jw_username}
通知邮箱：{email}
开启时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

飞翔的羊羊成绩监测系统
"""
        send_mail_success(ADMIN_EMAIL, admin_subject, admin_content)
    except Exception as e:
        print(f"发送管理员通知邮件失败: {str(e)}")

    return jsonify({
        'success': True, 
        'message': f'监测已启动！每{APP_CONFIG["monitoring_interval_minutes"]}分钟检查一次新成绩，结果将发送到: {email}'
    })

@app.route('/grade/api/stop_monitoring', methods=['POST'])
def api_stop_monitoring():
    """用户停止监测"""
    if not session.get('user_logged_in'):
        return jsonify({'success': False, 'message': '请先登录'})
    
    user_id = session['user_id']
    email = request.form.get('email')
    
    if not email:
        return jsonify({'success': False, 'message': '请填写通知邮箱'})
    
    # 查找匹配的监测任务
    with TASK_LOCK:
        user_tasks = MONITORING_TASKS.get(user_id, {})
        found_monitor_id = None
        for monitor_id, monitor in user_tasks.items():
            if monitor.email == email and monitor.is_monitoring:
                found_monitor_id = monitor_id
                break
        
        if found_monitor_id:
            user_tasks[found_monitor_id].is_monitoring = False
            del user_tasks[found_monitor_id]
            # 如果用户无任务，删除空字典
            if not user_tasks:
                del MONITORING_TASKS[user_id]
            
            # 保存监测任务到文件
            save_monitoring_tasks(MONITORING_TASKS)
            
            return jsonify({'success': True, 'message': '监测已停止'})
        else:
            return jsonify({'success': False, 'message': '未找到该邮箱的监测任务'})

@app.route('/grade/api/download_schedule', methods=['POST'])
def api_download_schedule():
    """下载课程表PDF - 与调试脚本完全同步的实现"""
    if not session.get('user_logged_in'):
        return jsonify({'success': False, 'message': '请先登录'})
    
    # 获取表单数据
    jw_username = request.form.get('jw_username')
    jw_password = request.form.get('jw_password')
    
    if not jw_username or not jw_password:
        return jsonify({'success': False, 'message': '请先填写教务系统账号和密码'})
    
    try:
        import requests
        import time
        
        BASE_URL = JIAOWU_CONFIG["base_url"]
        
        # 先登录获取cookies
        from zfn_api import Client
        client = Client(base_url=BASE_URL)
        login_result = client.login(jw_username, jw_password)
        
        if login_result.get("code") != 1000:
            return jsonify({'success': False, 'message': f'登录失败: {login_result.get("msg")}'})
        
        cookies = client.cookies
        
        # 获取学生信息
        info_result = client.get_info()
        if info_result.get("code") == 1000:
            student_info = info_result.get("data", {})
            student_name = student_info.get("name", "未知")
            student_class = student_info.get("class_name", "未知")
        else:
            student_name = "未知"
            student_class = "未知"
        
        # 设置请求头
        headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,en-GB;q=0.6",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/jwglxt/kbcx/xskbcx_cxXskbcxIndex.html?gnmkdm=N2151&layout=default",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
            "X-Requested-With": "XMLHttpRequest",
        }
        
        # 策略请求数据
        default_year = JIAOWU_CONFIG["default_year"]
        default_term = JIAOWU_CONFIG["default_term"]
        xqm = str(default_term ** 2 * 3)
        
        policy_data = {
            "xnm": str(default_year),
            "xqm": xqm,
            "xnmc": f"{default_year}-{default_year + 1}",
            "xqmmc": str(default_term),
            "xm": student_name,
            "xxdm": "",
            "xszd.sj": "true",
            "xszd.cd": "true",
            "xszd.js": "true",
            "xszd.jszc": "false",
            "xszd.jxb": "true",
            "xszd.jxbzc": "true",
            "xszd.xkbz": "true",
            "xszd.kcxszc": "true",
            "xszd.zhxs": "true",
            "xszd.zxs": "true",
            "xszd.khfs": "true",
            "xszd.ksfs": "true",
            "xszd.xf": "true",
            "xszd.skfsmc": "false",
            "xszd.zfj": "false",
            "xszd.cxbj": "false",
            "xszd.kcxz": "false",
            "xszd.kcbj": "false",
            "xszd.kczxs": "false",
            "modelList[0].xnm": str(default_year),
            "modelList[0].xqm": xqm,
            "modelList[0].xnmc": f"{default_year}-{default_year + 1}",
            "modelList[0].xqmmc": str(default_term),
            "modelList[0].xh_id": jw_username,
            "modelList[0].xh": jw_username,
            "modelList[0].xm": student_name,
            "modelList[0].bjmc": student_class,
            "modelList[0].xsdm": "",
            "xsdm": "",
            "modelList[0].kclbdm": "",
            "modelList[0].kclxdm": "",
            "kclbdm": "",
            "kclxdm": "",
            "kzlx": "dy"
        }
        
        # 发送策略请求
        policy_url = f"{BASE_URL}/jwglxt/kbdy/bjkbdy_cxXnxqsfkz.html?gnmkdm=N2151"
        policy_response = requests.post(
            policy_url,
            headers=headers,
            cookies=cookies,
            data=policy_data,
            timeout=15
        )
        
        if policy_response.status_code == 200:
            time.sleep(1)
            
            # 发送PDF请求
            pdf_url = f"{BASE_URL}/jwglxt/kbcx/xskbcx_cxXsShcPdf.html?doType=table"
            pdf_response = requests.post(
                pdf_url,
                headers=headers,
                cookies=cookies,
                data=policy_data,
                timeout=15
            )
            
            if pdf_response.status_code == 200 and pdf_response.content:
                # 验证PDF文件
                if pdf_response.content.startswith(b'%PDF'):
                    
                    # 设置响应头，返回PDF文件
                    from flask import make_response
                    
                    # 确保使用二进制数据创建响应
                    response = make_response(pdf_response.content)
                    
                    # 设置正确的响应头
                    response.headers['Content-Type'] = 'application/pdf'
                    response.headers['Content-Length'] = str(len(pdf_response.content))
                    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                    response.headers['Pragma'] = 'no-cache'
                    response.headers['Expires'] = '0'
                    
                    # 处理中文文件名的编码问题
                    filename = f"课表_{student_name}_{student_class}_{default_year}学年第{default_term}学期.pdf"
                    try:
                        import urllib.parse
                        response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8''{urllib.parse.quote(filename)}'
                    except:
                        response.headers['Content-Disposition'] = 'attachment; filename="schedule.pdf"'
                    
                    # 保存教务账号（加密密码）
                    username = session['username']
                    if username in USERS:
                        if 'jw_accounts' not in USERS[username]:
                            USERS[username]['jw_accounts'] = {}
                        USERS[username]['jw_accounts'][jw_username] = {
                            'password': encrypt_jw_password(jw_password),
                            'email': session['user_email'],
                            'last_used': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        
                        # 保存到JSON文件
                        users_data['users'] = USERS
                        save_users_data(users_data)
                    
                    return response
                else:
                    return jsonify({'success': False, 'message': '下载的PDF文件内容不完整或损坏'})
            else:
                return jsonify({'success': False, 'message': f'PDF请求失败，状态码: {pdf_response.status_code}'})
        else:
            return jsonify({'success': False, 'message': f'策略请求失败，状态码: {policy_response.status_code}'})
    except Exception as e:
        print(f"下载过程中出现异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'获取课程表失败: {str(e)}'})

@app.route('/grade/api/monitoring_status')
def api_monitoring_status():
    """获取当前用户的监测状态"""
    if not session.get('user_logged_in'):
        return jsonify({'success': False, 'message': '请先登录'})
    
    user_id = session['user_id']
    active_tasks = []
    with TASK_LOCK:
        user_tasks = MONITORING_TASKS.get(user_id, {})
        for monitor_id, monitor in user_tasks.items():
            if monitor.is_monitoring:
                active_tasks.append({
                    'monitor_id': monitor_id,
                    'username': monitor.username,
                    'email': monitor.email
                })
    
    return jsonify({'success': True, 'tasks': active_tasks})

# --------------- 管理员控制监测接口 ---------------
@app.route('/grade/api/admin/start_monitor', methods=['POST'])
def api_admin_start_monitor():
    """管理员启动指定用户的监测"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '请先登录管理员'})
    
    user_id = request.form.get('user_id')
    monitor_id = request.form.get('monitor_id')
    
    if not user_id or not monitor_id:
        return jsonify({'success': False, 'message': '参数不完整'})
    
    # 查找用户信息
    target_user = None
    for username, user_data in USERS.items():
        if user_data.get('id') == int(user_id):
            target_user = user_data
            break
    
    if not target_user:
        return jsonify({'success': False, 'message': '用户不存在'})
    
    # 查找教务账号
    jw_username = monitor_id.split('_')[0] if '_' in monitor_id else monitor_id
    
    # 查找教务账号密码
    jw_password = None
    email = None
    if 'jw_accounts' in target_user and jw_username in target_user['jw_accounts']:
        account_info = target_user['jw_accounts'][jw_username]
        encrypted_password = account_info.get('password')
        jw_password = decrypt_jw_password(encrypted_password)
        email = account_info.get('email')
    
    if not jw_password or not email:
        return jsonify({'success': False, 'message': '未找到该用户的教务账号信息'})
    
    # 检查是否已在监测
    with TASK_LOCK:
        user_tasks = MONITORING_TASKS.get(int(user_id), {})
        if monitor_id in user_tasks and user_tasks[monitor_id].is_monitoring:
            return jsonify({'success': False, 'message': '该监测任务已在运行中'})
    
    # 创建监测实例
    monitor = GradeMonitor(jw_username, jw_password, email, int(user_id))
    if not monitor.login():
        return jsonify({'success': False, 'message': '教务系统登录失败'})
    
    # 初始化成绩
    grades_data = monitor.get_latest_grades()
    if grades_data:
        monitor.last_grades = {course['course_id']: course for course in grades_data.get('courses', [])}
    
    monitor.is_monitoring = True
    
    # 保存任务
    with TASK_LOCK:
        if int(user_id) not in MONITORING_TASKS:
            MONITORING_TASKS[int(user_id)] = {}
        MONITORING_TASKS[int(user_id)][monitor_id] = monitor
    
    # 保存到文件
    save_monitoring_tasks(MONITORING_TASKS)
    
    # 启动监测线程
    thread = threading.Thread(target=monitoring_worker, args=(int(user_id), monitor_id))
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': f'已启动用户 {user_id} 的监测任务'})

@app.route('/grade/api/admin/stop_monitor', methods=['POST'])
def api_admin_stop_monitor():
    """管理员停止指定用户的监测"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '请先登录管理员'})
    
    user_id = request.form.get('user_id')
    monitor_id = request.form.get('monitor_id')
    
    if not user_id or not monitor_id:
        return jsonify({'success': False, 'message': '参数不完整'})
    
    # 查找并停止监测
    with TASK_LOCK:
        user_tasks = MONITORING_TASKS.get(int(user_id), {})
        if monitor_id in user_tasks:
            user_tasks[monitor_id].is_monitoring = False
            del user_tasks[monitor_id]
            
            # 如果用户无任务，删除空字典
            if not user_tasks:
                del MONITORING_TASKS[int(user_id)]
            
            # 保存到文件
            save_monitoring_tasks(MONITORING_TASKS)
            
            return jsonify({'success': True, 'message': f'已停止用户 {user_id} 的监测任务'})
        else:
            return jsonify({'success': False, 'message': '未找到该监测任务'})

if __name__ == '__main__':
    # 创建templates目录（如果不存在）
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    # 恢复监测任务
    print("正在恢复监测任务...")
    restored_count = 0
    with TASK_LOCK:
        for user_id, user_tasks in MONITORING_TASKS.copy().items():
            for monitor_id, monitor in user_tasks.copy().items():
                try:
                    # 重置监测状态
                    monitor.is_monitoring = False
                    
                    # 查找用户信息
                    target_user = None
                    for username, user_data in USERS.items():
                        if user_data.get('id') == user_id:
                            target_user = user_data
                            break
                    
                    if not target_user:
                        print(f"用户 {user_id} 不存在，跳过恢复监测任务")
                        del MONITORING_TASKS[user_id][monitor_id]
                        continue
                    
                    # 查找教务账号密码
                    jw_username = monitor_id.split('_')[0] if '_' in monitor_id else monitor_id
                    jw_password = None
                    email = None
                    if 'jw_accounts' in target_user and jw_username in target_user['jw_accounts']:
                        account_info = target_user['jw_accounts'][jw_username]
                        encrypted_password = account_info.get('password')
                        jw_password = decrypt_jw_password(encrypted_password)
                        email = account_info.get('email')
                    
                    if not jw_password or not email:
                        print(f"用户 {user_id} 的教务账号 {jw_username} 信息不完整，跳过恢复")
                        del MONITORING_TASKS[user_id][monitor_id]
                        continue
                    
                    # 创建新的监测实例
                    new_monitor = GradeMonitor(jw_username, jw_password, email, user_id)
                    if new_monitor.login():
                        # 初始化成绩
                        grades_data = new_monitor.get_latest_grades()
                        if grades_data:
                            new_monitor.last_grades = {course['course_id']: course for course in grades_data.get('courses', [])}
                        
                        new_monitor.is_monitoring = True
                        MONITORING_TASKS[user_id][monitor_id] = new_monitor
                        
                        # 启动监测线程
                        thread = threading.Thread(target=monitoring_worker, args=(user_id, monitor_id))
                        thread.daemon = True
                        thread.start()
                        
                        restored_count += 1
                        print(f"已恢复用户 {user_id} 的监测任务: {monitor_id}")
                    else:
                        print(f"用户 {user_id} 的教务账号 {jw_username} 登录失败，跳过恢复")
                        del MONITORING_TASKS[user_id][monitor_id]
                except Exception as e:
                    print(f"恢复监测任务失败: {str(e)}")
                    del MONITORING_TASKS[user_id][monitor_id]
    
    # 清理空的用户任务
    with TASK_LOCK:
        for user_id in list(MONITORING_TASKS.keys()):
            if not MONITORING_TASKS[user_id]:
                del MONITORING_TASKS[user_id]
    
    # 保存更新后的监测任务
    save_monitoring_tasks(MONITORING_TASKS)
    
    print(f"监测任务恢复完成，共恢复 {restored_count} 个任务")
    
    app.run(debug=True, host='127.0.0.1', port=5002, use_reloader=False)