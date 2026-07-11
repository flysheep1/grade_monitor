import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from config import MAIL_CONFIG


def send_mail_success(to_email, subject, content):
    try:
        msg = MIMEMultipart()
        msg['From'] = f"飞翔的羊羊<{MAIL_CONFIG['sender_email']}>"
        msg['To'] = to_email
        msg['Subject'] = Header(subject, 'utf-8')

        msg.attach(MIMEText(content, 'plain', 'utf-8'))

        server = smtplib.SMTP(MAIL_CONFIG['smtp_server'], MAIL_CONFIG['smtp_port'])
        if MAIL_CONFIG['smtp_tls']:
            server.starttls()

        server.login(MAIL_CONFIG['sender_email'], MAIL_CONFIG['sender_password'])
        server.sendmail(MAIL_CONFIG['sender_email'], to_email, msg.as_string())
        server.quit()

        print(f"邮件发送成功：{to_email}")
        return {"code": 1000, "msg": "发送成功"}

    except smtplib.SMTPException as e:
        error_info = f"SMTP错误：{str(e)}"
        print(f"邮件发送失败：{error_info}")
        return {"error": error_info}
    except Exception as e:
        error_info = f"未知错误：{str(e)}"
        print(f"邮件发送失败：{error_info}")
        return {"error": error_info}