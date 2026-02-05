"""
登录对话框 - 支持二维码登录和 Cookie 导入
"""
import asyncio
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QPushButton, QTextEdit, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage

import qrcode
from PIL.ImageQt import ImageQt
from bilibili_api import login_v2, Credential

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth.auth_manager import AuthManager, get_auth_manager


class QRCodeLoginThread(QThread):
    """二维码登录线程"""

    qrcode_ready = pyqtSignal(str)  # 二维码 URL
    status_changed = pyqtSignal(str)  # 状态变化
    login_success = pyqtSignal(object)  # Credential
    login_failed = pyqtSignal(str)  # 错误信息

    def __init__(self):
        super().__init__()
        self._cancelled = False
        self._qr_login = None

    def cancel(self):
        """取消登录"""
        self._cancelled = True

    def run(self):
        """执行二维码登录"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._login())
            loop.close()
        except Exception as e:
            self.login_failed.emit(str(e))

    async def _login(self):
        """异步执行登录"""
        try:
            self._qr_login = login_v2.QrCodeLogin()
            await self._qr_login.generate_qrcode()

            # 获取二维码 URL
            qr_url = self._qr_login.get_qrcode_url()
            self.qrcode_ready.emit(qr_url)

            self.status_changed.emit("等待扫描...")

            last_status = None
            while not self._cancelled:
                status = await self._qr_login.check_state()

                if status == login_v2.QrCodeLoginEvents.DONE or self._qr_login.has_done():
                    credential = self._qr_login.get_credential()
                    self.login_success.emit(credential)
                    return

                if status == login_v2.QrCodeLoginEvents.TIMEOUT:
                    self.login_failed.emit("二维码已过期")
                    return

                if status == login_v2.QrCodeLoginEvents.SCAN:
                    if last_status != status:
                        self.status_changed.emit("已扫描，请在手机上确认...")
                        last_status = status

                elif status == login_v2.QrCodeLoginEvents.CONF:
                    if last_status != status:
                        self.status_changed.emit("已确认，正在登录...")
                        last_status = status

                await asyncio.sleep(1)

            if self._cancelled:
                self.login_failed.emit("登录已取消")

        except Exception as e:
            self.login_failed.emit(f"登录出错: {str(e)}")


class LoginDialog(QDialog):
    """登录对话框"""

    login_success = pyqtSignal(object)  # Credential

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录 Bilibili")
        self.setFixedSize(400, 450)
        self._login_thread: Optional[QRCodeLoginThread] = None
        self._auth_manager = get_auth_manager()

        self._init_ui()

    def _init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)

        # 标签页
        tab_widget = QTabWidget()

        # 二维码登录页
        qrcode_tab = self._create_qrcode_tab()
        tab_widget.addTab(qrcode_tab, "二维码登录")

        # Cookie 导入页
        cookie_tab = self._create_cookie_tab()
        tab_widget.addTab(cookie_tab, "Cookie 导入")

        layout.addWidget(tab_widget)

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    def _create_qrcode_tab(self) -> QWidget:
        """创建二维码登录标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 二维码显示区域
        self.qr_label = QLabel("点击下方按钮生成二维码")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setStyleSheet("border: 1px solid #ccc; background: white;")

        qr_container = QHBoxLayout()
        qr_container.addStretch()
        qr_container.addWidget(self.qr_label)
        qr_container.addStretch()
        layout.addLayout(qr_container)

        # 状态标签
        self.qr_status_label = QLabel("请使用哔哩哔哩手机 App 扫码登录")
        self.qr_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.qr_status_label)

        # 生成按钮
        self.generate_btn = QPushButton("生成二维码")
        self.generate_btn.clicked.connect(self._start_qrcode_login)
        layout.addWidget(self.generate_btn)

        layout.addStretch()

        return widget

    def _create_cookie_tab(self) -> QWidget:
        """创建 Cookie 导入标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 说明文字
        info_label = QLabel(
            "请从浏览器中复制 Cookie 字符串粘贴到下方：\n"
            "（需要包含 SESSDATA 和 bili_jct）"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Cookie 输入框
        self.cookie_edit = QTextEdit()
        self.cookie_edit.setPlaceholderText(
            "SESSDATA=xxx; bili_jct=xxx; ..."
        )
        layout.addWidget(self.cookie_edit)

        # 导入按钮
        import_btn = QPushButton("导入 Cookie")
        import_btn.clicked.connect(self._import_cookie)
        layout.addWidget(import_btn)

        layout.addStretch()

        return widget

    def _start_qrcode_login(self):
        """开始二维码登录"""
        if self._login_thread and self._login_thread.isRunning():
            return

        self.generate_btn.setEnabled(False)
        self.qr_status_label.setText("正在生成二维码...")
        self.qr_label.setText("生成中...")

        self._login_thread = QRCodeLoginThread()
        self._login_thread.qrcode_ready.connect(self._on_qrcode_ready)
        self._login_thread.status_changed.connect(self._on_status_changed)
        self._login_thread.login_success.connect(self._on_login_success)
        self._login_thread.login_failed.connect(self._on_login_failed)
        self._login_thread.start()

    def _on_qrcode_ready(self, url: str):
        """二维码生成完成"""
        # 生成二维码图片
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=5,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # 转换为 QPixmap
        img = img.convert("RGB")
        qimage = ImageQt(img)
        pixmap = QPixmap.fromImage(QImage(qimage))
        pixmap = pixmap.scaled(
            200, 200,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.qr_label.setPixmap(pixmap)
        self.qr_status_label.setText("请使用哔哩哔哩手机 App 扫码")

    def _on_status_changed(self, status: str):
        """状态变化"""
        self.qr_status_label.setText(status)

    def _on_login_success(self, credential: Credential):
        """登录成功"""
        self._auth_manager.save_credential(credential)
        self.generate_btn.setEnabled(True)
        self.qr_status_label.setText("登录成功！")

        QMessageBox.information(self, "成功", "登录成功！")
        self.login_success.emit(credential)
        self.accept()

    def _on_login_failed(self, error: str):
        """登录失败"""
        self.generate_btn.setEnabled(True)
        self.qr_status_label.setText(f"登录失败: {error}")
        self.qr_label.setText("点击重新生成")

    def _import_cookie(self):
        """导入 Cookie"""
        cookie_string = self.cookie_edit.toPlainText().strip()

        if not cookie_string:
            QMessageBox.warning(self, "错误", "请输入 Cookie 字符串")
            return

        if self._auth_manager.import_cookie_string(cookie_string):
            QMessageBox.information(self, "成功", "Cookie 导入成功！")
            self.login_success.emit(self._auth_manager.credential)
            self.accept()
        else:
            QMessageBox.warning(
                self, "错误",
                "Cookie 导入失败，请检查格式是否正确\n"
                "需要包含 SESSDATA 和 bili_jct"
            )

    def closeEvent(self, event):
        """关闭事件"""
        if self._login_thread and self._login_thread.isRunning():
            self._login_thread.cancel()
            self._login_thread.wait(2000)
        super().closeEvent(event)

    def reject(self):
        """取消"""
        if self._login_thread and self._login_thread.isRunning():
            self._login_thread.cancel()
            self._login_thread.wait(2000)
        super().reject()
