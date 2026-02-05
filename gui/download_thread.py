"""
下载线程模块 - 使用 QThread 处理耗时操作
"""
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from PyQt6.QtCore import QThread, pyqtSignal

from bilibili_api import video, Credential, HEADERS, get_client

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DEFAULT_OUTPUT_DIR, CACHE_DIR, VIDEO_QUALITY_NAME, AUDIO_QUALITY
from download.video_downloader import (
    parse_video_url, select_best_video_stream, select_best_audio_stream,
    get_stream_url, sanitize_filename, merge_video_audio,
    VIDEO_QUALITY_PRIORITY, AUDIO_QUALITY_PRIORITY
)


class FetchInfoThread(QThread):
    """获取视频信息的线程"""

    # 信号
    finished = pyqtSignal(bool, dict)  # (success, info_dict)
    error = pyqtSignal(str)

    def __init__(self, url: str, credential: Optional[Credential] = None):
        super().__init__()
        self.url = url
        self.credential = credential
        self._video_info = {}

    def run(self):
        """执行获取视频信息"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._fetch_info())
            loop.close()

            if result:
                self.finished.emit(True, self._video_info)
            else:
                self.finished.emit(False, {})

        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit(False, {})

    async def _fetch_info(self) -> bool:
        """异步获取视频信息"""
        bvid, aid, page = parse_video_url(self.url)

        if not bvid and not aid:
            self.error.emit(f"无法解析视频地址: {self.url}")
            return False

        # 创建视频对象
        if bvid:
            v = video.Video(bvid=bvid, credential=self.credential)
        else:
            v = video.Video(aid=aid, credential=self.credential)

        # 获取视频信息
        info = await v.get_info()

        # 获取下载地址以获取可用清晰度
        download_url_data = await v.get_download_url(page_index=0)

        # 解析可用清晰度
        available_qualities = []
        dash_data = download_url_data.get("dash")
        if dash_data:
            video_streams = dash_data.get("video", [])
            quality_ids = set()
            for stream in video_streams:
                qid = stream.get("id", 0)
                if qid not in quality_ids:
                    quality_ids.add(qid)
                    name = VIDEO_QUALITY_NAME.get(qid, f"qn={qid}")
                    available_qualities.append((qid, name))
            # 按质量排序
            available_qualities.sort(key=lambda x: VIDEO_QUALITY_PRIORITY.index(x[0])
                                     if x[0] in VIDEO_QUALITY_PRIORITY else 999)

        # 构建信息字典
        pages = info.get("pages", [])
        self._video_info = {
            "title": info.get("title", "未知"),
            "owner": info.get("owner", {}).get("name", "未知"),
            "duration": info.get("duration", 0),
            "pages": [(i+1, p.get("part", f"P{i+1}")) for i, p in enumerate(pages)],
            "bvid": info.get("bvid", bvid),
            "aid": info.get("aid", aid),
            "available_qualities": available_qualities,
            "url_page": page,
        }

        return True


class DownloadThread(QThread):
    """下载视频的线程"""

    # 信号
    progress_updated = pyqtSignal(int, int)  # (current, total)
    status_changed = pyqtSignal(str)
    speed_updated = pyqtSignal(str)  # 下载速度
    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(
        self,
        url: str,
        output_dir: Path,
        credential: Optional[Credential] = None,
        page: int = 1,
        quality: int = 0  # 0 表示自动选择最高
    ):
        super().__init__()
        self.url = url
        self.output_dir = Path(output_dir)
        self.credential = credential
        self.page = page
        self.quality = quality
        self._cancelled = False
        self._current_download_id = None

    def cancel(self):
        """取消下载"""
        self._cancelled = True

    def run(self):
        """执行下载"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success, message = loop.run_until_complete(self._download())
            loop.close()
            self.finished.emit(success, message)
        except Exception as e:
            self.finished.emit(False, f"下载出错: {str(e)}")

    async def _download(self) -> tuple[bool, str]:
        """异步下载视频"""
        if self._cancelled:
            return False, "下载已取消"

        self.status_changed.emit("正在解析视频地址...")

        bvid, aid, url_page = parse_video_url(self.url)
        if not bvid and not aid:
            return False, f"无法解析视频地址: {self.url}"

        if url_page > 1:
            self.page = url_page

        # 创建视频对象
        if bvid:
            v = video.Video(bvid=bvid, credential=self.credential)
        else:
            v = video.Video(aid=aid, credential=self.credential)

        self.status_changed.emit("正在获取视频信息...")

        try:
            info = await v.get_info()
        except Exception as e:
            return False, f"获取视频信息失败: {e}"

        if self._cancelled:
            return False, "下载已取消"

        title = info.get("title", "未知")
        pages = info.get("pages", [])

        if self.page > len(pages):
            return False, f"分P {self.page} 不存在，共 {len(pages)} P"

        page_info = pages[self.page - 1]
        part_name = page_info.get("part", f"P{self.page}")

        self.status_changed.emit("正在获取视频流...")

        try:
            download_url_data = await v.get_download_url(page_index=self.page - 1)
        except Exception as e:
            return False, f"获取下载地址失败: {e}"

        if self._cancelled:
            return False, "下载已取消"

        dash_data = download_url_data.get("dash")

        if not dash_data:
            # FLV/MP4 单流格式
            durl = download_url_data.get("durl", [])
            if not durl:
                return False, "未找到视频流"

            stream_url = durl[0].get("url")

            if len(pages) > 1:
                filename = f"{title}_P{self.page}_{part_name}"
            else:
                filename = title
            filename = sanitize_filename(filename)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            final_output = self.output_dir / f"{filename}.mp4"

            self.status_changed.emit("正在下载视频...")
            success = await self._download_stream_with_progress(
                stream_url, final_output, "视频"
            )

            if not success:
                return False, "下载视频失败"

        else:
            # DASH 格式
            video_stream = self._select_video_stream(dash_data)
            audio_stream = select_best_audio_stream(dash_data)

            if video_stream is None:
                return False, "未找到视频流"

            video_url = get_stream_url(video_stream)
            audio_url = get_stream_url(audio_stream) if audio_stream else None

            if not video_url:
                return False, "无法获取视频流 URL"

            # 准备文件名
            if len(pages) > 1:
                filename = f"{title}_P{self.page}_{part_name}"
            else:
                filename = title
            filename = sanitize_filename(filename)
            self.output_dir.mkdir(parents=True, exist_ok=True)

            import uuid
            temp_video = CACHE_DIR / f"{uuid.uuid4()}.m4v"
            temp_audio = CACHE_DIR / f"{uuid.uuid4()}.m4a"
            final_output = self.output_dir / f"{filename}.mp4"

            # 下载视频
            self.status_changed.emit("正在下载视频流...")
            success = await self._download_stream_with_progress(
                video_url, temp_video, "视频"
            )

            if not success:
                temp_video.unlink(missing_ok=True)
                return False, "下载视频流失败"

            if self._cancelled:
                temp_video.unlink(missing_ok=True)
                return False, "下载已取消"

            # 下载音频
            if audio_url:
                self.status_changed.emit("正在下载音频流...")
                success = await self._download_stream_with_progress(
                    audio_url, temp_audio, "音频"
                )

                if not success:
                    temp_video.unlink(missing_ok=True)
                    temp_audio.unlink(missing_ok=True)
                    return False, "下载音频流失败"

                if self._cancelled:
                    temp_video.unlink(missing_ok=True)
                    temp_audio.unlink(missing_ok=True)
                    return False, "下载已取消"

                # 合并
                self.status_changed.emit("正在合并音视频...")
                self.progress_updated.emit(0, 0)  # 显示无进度状态

                if not merge_video_audio(temp_video, temp_audio, final_output):
                    return False, "合并音视频失败"
            else:
                temp_video.rename(final_output)

        self.status_changed.emit("下载完成！")

        if final_output.exists():
            size = final_output.stat().st_size
            if size > 1024 * 1024 * 1024:
                size_str = f"{size / (1024**3):.2f} GB"
            else:
                size_str = f"{size / (1024**2):.2f} MB"
            return True, f"下载完成！\n保存路径: {final_output}\n文件大小: {size_str}"

        return True, f"下载完成！\n保存路径: {final_output}"

    def _select_video_stream(self, dash_data: Dict) -> Optional[Dict]:
        """选择视频流，支持指定质量"""
        if self.quality == 0:
            return select_best_video_stream(dash_data)

        video_streams = dash_data.get("video", [])

        # 按指定质量筛选
        matching_streams = [s for s in video_streams if s.get("id") == self.quality]

        if matching_streams:
            # 按编码优先级排序
            from download.video_downloader import CODEC_PRIORITY

            def codec_rank(stream):
                codecs = stream.get("codecs", "").lower()
                for i, codec in enumerate(CODEC_PRIORITY):
                    if codec in codecs:
                        return i
                return 999

            matching_streams.sort(key=codec_rank)
            return matching_streams[0]

        # 找不到指定质量，使用最高质量
        return select_best_video_stream(dash_data)

    async def _download_stream_with_progress(
        self,
        url: str,
        output_path: Path,
        desc: str
    ) -> bool:
        """带进度回调的下载"""
        import time

        try:
            client = get_client()
            dwn_id = await client.download_create(url, HEADERS)
            self._current_download_id = dwn_id
            total = client.download_content_length(dwn_id)

            output_path.parent.mkdir(parents=True, exist_ok=True)

            current = 0
            last_time = time.time()
            last_bytes = 0

            with open(output_path, 'wb') as f:
                while current < total:
                    if self._cancelled:
                        return False

                    chunk = await client.download_chunk(dwn_id)
                    if not chunk:
                        break

                    f.write(chunk)
                    current += len(chunk)

                    # 更新进度
                    self.progress_updated.emit(current, total)

                    # 计算速度
                    now = time.time()
                    elapsed = now - last_time
                    if elapsed >= 0.5:  # 每0.5秒更新一次速度
                        bytes_diff = current - last_bytes
                        speed = bytes_diff / elapsed

                        if speed > 1024 * 1024:
                            speed_str = f"{speed / (1024*1024):.1f} MB/s"
                        elif speed > 1024:
                            speed_str = f"{speed / 1024:.1f} KB/s"
                        else:
                            speed_str = f"{speed:.0f} B/s"

                        self.speed_updated.emit(speed_str)
                        last_time = now
                        last_bytes = current

            return True

        except Exception as e:
            print(f"下载出错: {e}")
            import traceback
            traceback.print_exc()
            return False
