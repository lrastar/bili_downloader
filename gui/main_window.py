"""
主窗口 - Bilibili 视频下载器
"""
import asyncio
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QProgressBar,
    QGroupBox, QFileDialog, QMessageBox, QStatusBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from bilibili_api import Credential

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DEFAULT_OUTPUT_DIR, VIDEO_QUALITY_NAME
from auth.auth_manager import get_auth_manager
from gui.login_dialog import LoginDialog
from gui.download_thread import DownloadThread, FetchInfoThread


class CheckCredentialThread(QThread):
    """检查凭证有效性的线程"""
    finished = pyqtSignal(bool, str)  # (is_valid, username)

    def __init__(self, auth_manager):
        super().__init__()
        self.auth_manager = auth_manager

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            is_valid, username = loop.run_until_complete(self._check())
            loop.close()
            self.finished.emit(is_valid, username)
        except Exception:
            self.finished.emit(False, "")

    async def _check(self):
        if not self.auth_manager.credential:
            return False, ""

        try:
            from bilibili_api import user
            if not await self.auth_manager.credential.check_valid():
                return False, ""

            me = user.User(
                self.auth_manager.credential.dedeuserid,
                credential=self.auth_manager.credential
            )
            info = await me.get_user_info()
            name = info.get("name", "未知")
            return True, name
        except Exception:
            return False, ""


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bilibili 视频下载器")
        self.setMinimumSize(550, 500)

        self._auth_manager = get_auth_manager()
        self._credential: Optional[Credential] = None
        self._video_info: dict = {}
        self._output_dir = DEFAULT_OUTPUT_DIR

        self._fetch_thread: Optional[FetchInfoThread] = None
        self._download_thread: Optional[DownloadThread] = None
        self._check_thread: Optional[CheckCredentialThread] = None

        self._init_ui()
        self._check_login_status()

    def _init_ui(self):
        """初始化界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # 视频链接输入区
        link_group = QGroupBox("视频链接")
        link_layout = QHBoxLayout(link_group)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("输入 Bilibili 视频链接或 BV/AV 号")
        self.url_edit.returnPressed.connect(self._fetch_video_info)
        link_layout.addWidget(self.url_edit)

        self.fetch_btn = QPushButton("获取信息")
        self.fetch_btn.setFixedWidth(80)
        self.fetch_btn.clicked.connect(self._fetch_video_info)
        link_layout.addWidget(self.fetch_btn)

        layout.addWidget(link_group)

        # 视频信息区
        info_group = QGroupBox("视频信息")
        info_layout = QGridLayout(info_group)

        info_layout.addWidget(QLabel("标题:"), 0, 0)
        self.title_label = QLabel("-")
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label, 0, 1, 1, 3)

        info_layout.addWidget(QLabel("UP主:"), 1, 0)
        self.owner_label = QLabel("-")
        info_layout.addWidget(self.owner_label, 1, 1)

        info_layout.addWidget(QLabel("时长:"), 1, 2)
        self.duration_label = QLabel("-")
        info_layout.addWidget(self.duration_label, 1, 3)

        info_layout.addWidget(QLabel("清晰度:"), 2, 0)
        self.quality_combo = QComboBox()
        self.quality_combo.setEnabled(False)
        info_layout.addWidget(self.quality_combo, 2, 1)

        info_layout.addWidget(QLabel("分P:"), 2, 2)
        self.page_combo = QComboBox()
        self.page_combo.setEnabled(False)
        info_layout.addWidget(self.page_combo, 2, 3)

        info_layout.addWidget(QLabel("保存目录:"), 3, 0)
        self.dir_edit = QLineEdit(str(self._output_dir))
        self.dir_edit.setReadOnly(True)
        info_layout.addWidget(self.dir_edit, 3, 1, 1, 2)

        self.browse_btn = QPushButton("浏览")
        self.browse_btn.setFixedWidth(60)
        self.browse_btn.clicked.connect(self._browse_directory)
        info_layout.addWidget(self.browse_btn, 3, 3)

        layout.addWidget(info_group)

        # 下载进度区
        progress_group = QGroupBox("下载进度")
        progress_layout = QVBoxLayout(progress_group)

        # 进度条
        progress_bar_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_bar_layout.addWidget(self.progress_bar)

        self.speed_label = QLabel("")
        self.speed_label.setFixedWidth(80)
        progress_bar_layout.addWidget(self.speed_label)

        progress_layout.addLayout(progress_bar_layout)

        # 状态标签
        self.status_label = QLabel("就绪")
        progress_layout.addWidget(self.status_label)

        layout.addWidget(progress_group)

        # 按钮区
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.download_btn = QPushButton("开始下载")
        self.download_btn.setFixedWidth(100)
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._start_download)
        btn_layout.addWidget(self.download_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_download)
        btn_layout.addWidget(self.cancel_btn)

        btn_layout.addStretch()
        layout.addWidget(QWidget())  # 占位
        layout.addLayout(btn_layout)

        # 状态栏
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        # 登录状态区域
        self.login_status_label = QLabel("登录状态: 未登录")
        status_bar.addWidget(self.login_status_label, 1)

        self.login_btn = QPushButton("登录")
        self.login_btn.setFixedWidth(60)
        self.login_btn.clicked.connect(self._show_login_dialog)
        status_bar.addPermanentWidget(self.login_btn)

        self.logout_btn = QPushButton("退出登录")
        self.logout_btn.setFixedWidth(70)
        self.logout_btn.clicked.connect(self._logout)
        self.logout_btn.setVisible(False)
        status_bar.addPermanentWidget(self.logout_btn)

    def _check_login_status(self):
        """检查登录状态"""
        self._credential = self._auth_manager.credential

        if self._credential:
            self.login_status_label.setText("登录状态: 检查中...")
            self._check_thread = CheckCredentialThread(self._auth_manager)
            self._check_thread.finished.connect(self._on_check_finished)
            self._check_thread.start()
        else:
            self._update_login_ui(False, "")

    def _on_check_finished(self, is_valid: bool, username: str):
        """凭证检查完成"""
        if is_valid:
            self._update_login_ui(True, username)
        else:
            self._credential = None
            self._update_login_ui(False, "")

    def _update_login_ui(self, logged_in: bool, username: str = ""):
        """更新登录状态 UI"""
        if logged_in:
            self.login_status_label.setText(f"登录状态: 已登录 ({username})")
            self.login_btn.setVisible(False)
            self.logout_btn.setVisible(True)
        else:
            self.login_status_label.setText("登录状态: 未登录")
            self.login_btn.setVisible(True)
            self.logout_btn.setVisible(False)

    def _show_login_dialog(self):
        """显示登录对话框"""
        dialog = LoginDialog(self)
        dialog.login_success.connect(self._on_login_success)
        dialog.exec()

    def _on_login_success(self, credential: Credential):
        """登录成功回调"""
        self._credential = credential
        self._check_login_status()

    def _logout(self):
        """退出登录"""
        reply = QMessageBox.question(
            self, "确认",
            "确定要退出登录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._auth_manager.clear_credential()
            self._credential = None
            self._update_login_ui(False)

    def _browse_directory(self):
        """浏览选择目录"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择保存目录",
            str(self._output_dir)
        )

        if dir_path:
            self._output_dir = Path(dir_path)
            self.dir_edit.setText(dir_path)

    def _fetch_video_info(self):
        """获取视频信息"""
        url = self.url_edit.text().strip()

        if not url:
            QMessageBox.warning(self, "错误", "请输入视频链接")
            return

        if self._fetch_thread and self._fetch_thread.isRunning():
            return

        self.fetch_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.status_label.setText("正在获取视频信息...")

        self._fetch_thread = FetchInfoThread(url, self._credential)
        self._fetch_thread.finished.connect(self._on_fetch_finished)
        self._fetch_thread.error.connect(self._on_fetch_error)
        self._fetch_thread.start()

    def _on_fetch_finished(self, success: bool, info: dict):
        """获取视频信息完成"""
        self.fetch_btn.setEnabled(True)

        if not success:
            self.status_label.setText("获取视频信息失败")
            return

        self._video_info = info
        self.status_label.setText("就绪")

        # 更新 UI
        self.title_label.setText(info.get("title", "-"))
        self.owner_label.setText(info.get("owner", "-"))

        duration = info.get("duration", 0)
        self.duration_label.setText(f"{duration // 60}:{duration % 60:02d}")

        # 更新清晰度下拉框
        self.quality_combo.clear()
        self.quality_combo.addItem("自动 (最高画质)", 0)
        for qid, name in info.get("available_qualities", []):
            self.quality_combo.addItem(name, qid)
        self.quality_combo.setEnabled(True)

        # 更新分P下拉框
        self.page_combo.clear()
        pages = info.get("pages", [])
        for page_num, part_name in pages:
            self.page_combo.addItem(f"P{page_num}: {part_name}", page_num)
        self.page_combo.setEnabled(len(pages) > 1)

        # 自动选择 URL 中的分P
        url_page = info.get("url_page", 1)
        if url_page > 0 and url_page <= len(pages):
            self.page_combo.setCurrentIndex(url_page - 1)

        self.download_btn.setEnabled(True)

    def _on_fetch_error(self, error: str):
        """获取视频信息错误"""
        self.fetch_btn.setEnabled(True)
        self.status_label.setText(f"错误: {error}")
        QMessageBox.warning(self, "错误", f"获取视频信息失败:\n{error}")

    def _start_download(self):
        """开始下载"""
        if not self._video_info:
            QMessageBox.warning(self, "错误", "请先获取视频信息")
            return

        if self._download_thread and self._download_thread.isRunning():
            return

        url = self.url_edit.text().strip()
        quality = self.quality_combo.currentData()
        page = self.page_combo.currentData() or 1

        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.fetch_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        self._download_thread = DownloadThread(
            url=url,
            output_dir=self._output_dir,
            credential=self._credential,
            page=page,
            quality=quality
        )
        self._download_thread.progress_updated.connect(self._on_progress_updated)
        self._download_thread.status_changed.connect(self._on_status_changed)
        self._download_thread.speed_updated.connect(self._on_speed_updated)
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.start()

    def _cancel_download(self):
        """取消下载"""
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.cancel()
            self.status_label.setText("正在取消...")
            self.cancel_btn.setEnabled(False)

    def _on_progress_updated(self, current: int, total: int):
        """进度更新"""
        if total > 0:
            percent = int(current * 100 / total)
            self.progress_bar.setValue(percent)
        else:
            self.progress_bar.setValue(0)

    def _on_status_changed(self, status: str):
        """状态变化"""
        self.status_label.setText(status)

    def _on_speed_updated(self, speed: str):
        """速度更新"""
        self.speed_label.setText(speed)

    def _on_download_finished(self, success: bool, message: str):
        """下载完成"""
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.fetch_btn.setEnabled(True)
        self.speed_label.setText("")

        if success:
            self.progress_bar.setValue(100)
            self.status_label.setText("下载完成！")
            QMessageBox.information(self, "完成", message)
        else:
            self.status_label.setText(f"下载失败: {message}")
            if "取消" not in message:
                QMessageBox.warning(self, "失败", message)

    def closeEvent(self, event):
        """关闭事件"""
        if self._download_thread and self._download_thread.isRunning():
            reply = QMessageBox.question(
                self, "确认",
                "下载正在进行中，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

            self._download_thread.cancel()
            self._download_thread.wait(3000)

        super().closeEvent(event)
