# 成绩监测系统 - 宝塔面板部署指南

## 环境要求
- Python 3.8+
- 宝塔面板

## 快速部署步骤

### 1. 上传文件
将以下文件上传到宝塔面板的网站目录：
```
/app.py
/config.py
/login.py
/zfn_api.py
/mail_send.py
/requirements.txt
/templates/index.html
/templates/login.html
/templates/register.html
/templates/admin.html
/templates/admin_login.html
```

### 2. 安装Python依赖
在宝塔面板的终端中执行：
```bash
pip install -r requirements.txt
```

或者逐个安装：
```bash
pip install Flask==2.3.3
pip install requests==2.31.0
pip install rsa==4.9
pip install pyquery==2.0.0
```

### 3. 配置文件
编辑 `config.py` 文件，配置以下内容：

```python
# QQ邮箱配置
MAIL_CONFIG = {
    "smtp_server": "smtp.qq.com",
    "smtp_port": 587,
    "smtp_tls": True,
    "sender_email": "your_qq@qq.com",      # 你的QQ邮箱
    "sender_password": "your_auth_code"    # QQ邮箱授权码
}

# 教务系统配置
JIAOWU_CONFIG = {
    "base_url": "http://your-jiaowu-url",  # 教务系统URL
    "default_year": 2025,                  # 默认学年
    "default_term": 2                      # 默认学期（1/2）
}

# 应用配置
APP_CONFIG = {
    "secret_key": "your-secret-key",       # 会话密钥
    "admin_password": "admin-password",    # 管理员密码
    "admin_email": "admin@example.com",    # 管理员邮箱
    "monitoring_interval_minutes": 30,     # 监测间隔（分钟）
    "session_lifetime_seconds": 3600 * 24  # 会话有效期（秒）
}
```

> **QQ邮箱授权码获取方法**：登录QQ邮箱 → 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务 → 开启SMTP服务 → 获取授权码

### 4. 运行应用
```bash
python app.py
```

应用将在 `http://127.0.0.1:5002` 启动

### 5. 配置宝塔面板反向代理
1. 在宝塔面板创建站点
2. 设置反向代理：
   - 代理名称：成绩监测系统
   - 目标URL：`http://127.0.0.1:5002`
   - 发送域名：你的域名

### 6. 使用PM2守护进程（推荐）
安装PM2并守护进程：
```bash
npm install -g pm2
pm2 start app.py --name grade-monitor
pm2 save
pm2 startup
```

## 依赖说明

| 库名 | 版本 | 用途 |
|------|------|------|
| Flask | 2.3.3 | Web框架 |
| requests | 2.31.0 | HTTP请求 |
| rsa | 4.9 | RSA加密 |
| pyquery | 2.0.0 | HTML解析 |

## 注意事项

1. **端口配置**：默认使用5002端口，如需修改请编辑 `app.py` 最后的 `port` 参数
2. **数据文件**：`users_data.json`、`api_cookies.json` 和 `monitoring_tasks.json` 会自动创建，请确保目录有写权限
3. **邮件配置**：修改 `config.py` 中的 `MAIL_CONFIG` 配置
4. **管理员密码**：修改 `config.py` 中的 `APP_CONFIG["admin_password"]` 配置
5. **教务系统URL**：修改 `config.py` 中的 `JIAOWU_CONFIG["base_url"]` 配置

## 故障排查

### 端口被占用
```bash
# 查看端口占用
netstat -ano | findstr :5002
```

### 依赖安装失败
```bash
# 升级pip
pip install --upgrade pip
```

### 权限问题
```bash
# 给予目录写权限
chmod 755 /path/to/your/project
```

### 邮件发送失败
1. 确保QQ邮箱已开启SMTP服务
2. 确保使用授权码而非密码
3. 检查网络是否能访问 `smtp.qq.com:587`