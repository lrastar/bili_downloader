"""
认证模块 - 使用 bilibili_api 库
"""
import json
import asyncio
from pathlib import Path
from typing import Optional

import qrcode
from bilibili_api import Credential, login_v2, sync, user

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import COOKIE_FILE


class AuthManager:
    """认证管理器"""

    def __init__(self, cookie_file: Path = COOKIE_FILE):
        self.cookie_file = Path(cookie_file)
        self._credential: Optional[Credential] = None

    @property
    def credential(self) -> Optional[Credential]:
        """获取当前凭证"""
        if self._credential is None:
            self._credential = self.load_credential()
        return self._credential

    def save_credential(self, credential: Credential) -> bool:
        """保存凭证到文件"""
        try:
            cookies = {
                "sessdata": credential.sessdata,
                "bili_jct": credential.bili_jct,
                "buvid3": credential.buvid3,
                "dedeuserid": credential.dedeuserid,
                "ac_time_value": credential.ac_time_value,
            }

            self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2)

            self._credential = credential
            print(f"凭证已保存到: {self.cookie_file}")
            return True

        except Exception as e:
            print(f"保存凭证失败: {e}")
            return False

    def load_credential(self) -> Optional[Credential]:
        """从文件加载凭证"""
        if not self.cookie_file.exists():
            return None

        try:
            with open(self.cookie_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)

            credential = Credential(
                sessdata=cookies.get("sessdata"),
                bili_jct=cookies.get("bili_jct"),
                buvid3=cookies.get("buvid3"),
                dedeuserid=cookies.get("dedeuserid"),
                ac_time_value=cookies.get("ac_time_value"),
            )

            return credential

        except Exception as e:
            print(f"加载凭证失败: {e}")
            return None

    def import_cookie_string(self, cookie_string: str) -> bool:
        """从浏览器复制的 cookie 字符串导入"""
        try:
            cookies = {}
            for item in cookie_string.split(';'):
                item = item.strip()
                if '=' in item:
                    key, value = item.split('=', 1)
                    cookies[key.strip().lower()] = value.strip()

            # 检查必要字段
            sessdata = cookies.get("sessdata")
            bili_jct = cookies.get("bili_jct")

            if not sessdata or not bili_jct:
                print("Cookie 字符串缺少必要字段 (SESSDATA, bili_jct)")
                return False

            credential = Credential(
                sessdata=sessdata,
                bili_jct=bili_jct,
                buvid3=cookies.get("buvid3"),
                dedeuserid=cookies.get("dedeuserid"),
                ac_time_value=cookies.get("ac_time_value"),
            )

            self._credential = credential
            return self.save_credential(credential)

        except Exception as e:
            print(f"导入 Cookie 失败: {e}")
            return False

    async def check_credential_valid(self) -> bool:
        """检查凭证是否有效"""
        if not self.credential:
            return False

        try:
            # 检查凭证是否有效
            if not await self.credential.check_valid():
                return False

            # 获取用户信息
            me = user.User(self.credential.dedeuserid, credential=self.credential)
            info = await me.get_user_info()

            name = info.get("name", "未知")
            vip_type = info.get("vip", {}).get("type", 0)
            vip_label = info.get("vip", {}).get("label", {}).get("text", "")

            if vip_type == 2:
                vip_status = f"年度大会员 ({vip_label})"
            elif vip_type == 1:
                vip_status = "月度大会员"
            else:
                vip_status = "普通用户"

            print(f"当前登录用户: {name} ({vip_status})")
            return True

        except Exception as e:
            print(f"验证凭证失败: {e}")
            return False

    def clear_credential(self):
        """清除保存的凭证"""
        self._credential = None
        if self.cookie_file.exists():
            try:
                self.cookie_file.unlink()
                print("已清除保存的凭证")
            except Exception as e:
                print(f"清除凭证失败: {e}")


def display_qrcode(url: str):
    """在终端显示二维码"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def qrcode_login_async() -> Optional[Credential]:
    """二维码登录（异步）"""
    print("正在生成登录二维码...")

    try:
        # 创建二维码登录实例
        qr_login = login_v2.QrCodeLogin()

        # 生成二维码
        await qr_login.generate_qrcode()

        print("\n请使用哔哩哔哩手机客户端扫描下方二维码登录：\n")

        # 在终端显示二维码
        qr_terminal = qr_login.get_qrcode_terminal()
        print(qr_terminal)

        print("\n二维码有效期 180 秒，请尽快扫描...\n")

        # 轮询登录状态
        # 枚举值: SCAN(已扫描), CONF(已确认), DONE(完成), TIMEOUT(超时)
        last_status = None
        while True:
            status = await qr_login.check_state()

            # 检查是否登录成功
            if status == login_v2.QrCodeLoginEvents.DONE or qr_login.has_done():
                print("\n登录成功！")
                return qr_login.get_credential()

            # 处理不同状态
            if status == login_v2.QrCodeLoginEvents.TIMEOUT:
                print("\n二维码已过期，请重新登录")
                return None
            elif status == login_v2.QrCodeLoginEvents.SCAN:
                if last_status != login_v2.QrCodeLoginEvents.SCAN:
                    print("已扫描，请在手机上确认登录...")
                    last_status = status
            elif status == login_v2.QrCodeLoginEvents.CONF:
                if last_status != login_v2.QrCodeLoginEvents.CONF:
                    print("已确认，正在登录...")
                    last_status = status

            await asyncio.sleep(2)

    except Exception as e:
        print(f"登录过程出错: {e}")
        import traceback
        traceback.print_exc()
        return None


def qrcode_login() -> Optional[Credential]:
    """二维码登录（同步）"""
    return sync(qrcode_login_async())


# 全局实例
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """获取全局 AuthManager 实例"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager
