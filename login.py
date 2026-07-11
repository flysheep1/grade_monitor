# login.py
import base64
import json
import os
import requests
import rsa
import binascii
from urllib.parse import urljoin
from pyquery import PyQuery as pq
from config import JIAOWU_CONFIG


class APILogin:
    def __init__(self, base_url: str = None):
        self.base_url = base_url if base_url else JIAOWU_CONFIG["base_url"]
        self.sess = requests.Session()
        self.sess.keep_alive = False
        self.cookies = {}
        
        # 设置请求头
        self.headers = requests.utils.default_headers()
        self.login_url = urljoin(self.base_url, "jwglxt/xtgl/login_slogin.html")
        self.headers["Referer"] = self.login_url
        self.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
        self.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    
    def encrypt_password(self, pwd, n, e):
        """对密码base64编码"""
        message = str(pwd).encode()
        rsa_n = binascii.b2a_hex(binascii.a2b_base64(n))
        rsa_e = binascii.b2a_hex(binascii.a2b_base64(e))
        key = rsa.PublicKey(int(rsa_n, 16), int(rsa_e, 16))
        encropy_pwd = rsa.encrypt(message, key)
        result = binascii.b2a_base64(encropy_pwd)
        return result

    def login(self, username: str, password: str) -> dict:
        """
        使用API登录教务系统
        :param username: 用户名
        :param password: 密码
        :return: 登录结果字典
        """
        try:
            # 获取登录页面
            login_page_url = urljoin(self.base_url, "jwglxt/xtgl/login_slogin.html")
            req_csrf = self.sess.get(login_page_url, headers=self.headers, timeout=10)
            
            if req_csrf.status_code != 200:
                return {
                    "code": 2333,
                    "msg": "教务系统挂了",
                    "status_code": req_csrf.status_code,
                    "response_text": req_csrf.text[:500] if req_csrf.text else ""
                }
            
            # 获取csrf_token
            doc = pq(req_csrf.text)
            csrf_token = doc("#csrftoken").attr("value")
            
            # 获取公钥信息
            key_url = urljoin(self.base_url, "jwglxt/xtgl/login_getPublicKey.html")
            req_pubkey = self.sess.get(key_url, headers=self.headers, timeout=10).json()
            modulus = req_pubkey["modulus"]
            exponent = req_pubkey["exponent"]
            
            # 检查是否需要验证码
            if str(doc("input#yzm")) == "":
                # 不需要验证码，直接登录
                encrypt_password = self.encrypt_password(password, modulus, exponent)
                
                import time
                timestamp = str(int(time.time() * 1000))
                
                login_data = {
                    "csrftoken": csrf_token,
                    "yhm": username,
                    "mm": encrypt_password,
                    "language": "zh_CN",
                    "time": timestamp
                }
                
                # 发送登录请求
                req_login = self.sess.post(
                    f"{login_page_url}?time={timestamp}",
                    headers=self.headers,
                    data=login_data,
                    timeout=10,
                )
                
                doc = pq(req_login.text)
                tips = doc("p#tips")
                
                if str(tips) != "":
                    if "用户名或密码" in tips.text():
                        return {"code": 1002, "msg": "用户名或密码不正确"}
                    return {"code": 998, "msg": tips.text()}
                
                self.cookies = self.sess.cookies.get_dict()
                return {"code": 1000, "msg": "登录成功", "data": {"cookies": self.cookies}}
            else:
                # 需要验证码
                kaptcha_url = urljoin(self.base_url, "jwglxt/kaptcha")
                req_kaptcha = self.sess.get(kaptcha_url, headers=self.headers, timeout=10)
                kaptcha_pic = base64.b64encode(req_kaptcha.content).decode()
                
                return {
                    "code": 1001,
                    "msg": "需要验证码",
                    "data": {
                        "username": username,
                        "csrf_token": csrf_token,
                        "password": password,
                        "modulus": modulus,
                        "exponent": exponent,
                        "kaptcha_pic": kaptcha_pic,
                        "pre_cookies": self.sess.cookies.get_dict()
                    }
                }
                
        except Exception as e:
            return {"code": 999, "msg": f"登录时发生错误: {str(e)}"}
    
    def login_with_kaptcha(self, username: str, csrf_token: str, pre_cookies: dict, 
                          password: str, modulus: str, exponent: str, kaptcha: str) -> dict:
        """
        使用验证码登录
        """
        try:
            self.sess.cookies.update(pre_cookies)
            encrypt_password = self.encrypt_password(password, modulus, exponent)
            
            import time
            timestamp = str(int(time.time() * 1000))
            
            login_data = {
                "csrftoken": csrf_token,
                "yhm": username,
                "mm": encrypt_password,
                "yzm": kaptcha,
                "language": "zh_CN",
                "time": timestamp
            }
            
            login_page_url = urljoin(self.base_url, "jwglxt/xtgl/login_slogin.html")
            req_login = self.sess.post(
                f"{login_page_url}?time={timestamp}",
                headers=self.headers,
                data=login_data,
                timeout=10,
            )
            
            if req_login.status_code != 200:
                return {"code": 2333, "msg": "教务系统挂了"}
            
            doc = pq(req_login.text)
            tips = doc("p#tips")
            
            if str(tips) != "":
                if "验证码" in tips.text():
                    return {"code": 1004, "msg": "验证码输入错误"}
                if "用户名或密码" in tips.text():
                    return {"code": 1002, "msg": "用户名或密码不正确"}
                return {"code": 998, "msg": tips.text()}
            
            self.cookies = self.sess.cookies.get_dict()
            return {"code": 1000, "msg": "登录成功", "data": {"cookies": self.cookies}}
            
        except Exception as e:
            return {"code": 999, "msg": f"验证码登录时发生错误: {str(e)}"}
    
    def get_cookies(self) -> dict:
        """
        获取当前会话的Cookie
        """
        return self.cookies
    
    def save_cookies_to_file(self, filename: str = "api_cookies.json"):
        """
        将Cookie保存到文件
        """
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.cookies, f, ensure_ascii=False, indent=2)
        print(f"Cookie已保存到 {filename}")
    
    def load_cookies_from_file(self, filename: str = "api_cookies.json") -> bool:
        """
        从文件加载Cookie
        """
        if not os.path.exists(filename):
            return False
        
        with open(filename, 'r', encoding='utf-8') as f:
            self.cookies = json.load(f)
        
        # 更新Session中的Cookie
        for name, value in self.cookies.items():
            self.sess.cookies.set(name, value)
        
        print(f"Cookie已从 {filename} 加载")
        return True


def get_cookies(username: str, password: str, use_saved: bool = True) -> dict:
    """
    动态传入账号密码，使用API登录教务系统并返回Cookie
    :param username: 教务系统账号
    :param password: 教务系统密码
    :param use_saved: 是否使用已保存的Cookie
    :return: Cookie字典，失败返回None
    """
    api_login = APILogin()
    
    # 尝试加载已保存的Cookie
    if use_saved and api_login.load_cookies_from_file():
        print("尝试使用已保存的Cookie...")
        # 这里可以添加一个验证Cookie是否有效的请求
        try:
            test_url = urljoin(api_login.base_url, "jwglxt/xsxxxggl/xsxxwh_cxCkDgxsxx.html?gnmkdm=N100801")
            response = api_login.sess.get(test_url, timeout=5)
            if "用户登录" not in response.text:
                print("使用已保存的Cookie成功")
                return api_login.get_cookies()
            else:
                print("已保存的Cookie已失效")
        except:
            print("验证已保存Cookie时出错")
    
    # 执行登录
    login_result = api_login.login(username, password)
    
    if login_result.get("code") == 1000:
        # 登录成功，保存Cookie
        api_login.save_cookies_to_file()
        return api_login.get_cookies()
    elif login_result.get("code") == 1001:
        # 需要验证码 - Web应用不支持验证码输入
        print("登录需要验证码，但Web应用不支持验证码输入")
        print("请稍后重试，或使用教务系统官网登录")
        return None
    else:
        print(f"登录失败: {login_result.get('msg')}")
        return None


# 保留兼容性，但不再使用Selenium
def get_cookies_legacy(username: str, password: str) -> list:
    """
    旧版Selenium登录函数（已弃用）
    """
    print("警告: 旧版Selenium登录函数已被弃用，请使用新的API登录方式")
    return None


if __name__ == "__main__":
    # 测试API登录
    username = input("请输入用户名: ")
    password = input("请输入密码: ")
    
    cookies = get_cookies(username, password)
    
    if cookies:
        print("登录成功!")
        print("获取到的Cookie:")
        for key, value in cookies.items():
            print(f"  {key}: {value}")
    else:
        print("登录失败!")