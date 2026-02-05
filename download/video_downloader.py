"""
视频下载模块 - 使用 bilibili_api 库
支持最高画质和最高音质（杜比全景声、Hi-Res无损）
"""
import asyncio
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

from bilibili_api import video, Credential, HEADERS, sync, get_client
from tqdm import tqdm

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DEFAULT_OUTPUT_DIR, CACHE_DIR, VIDEO_QUALITY_NAME, AUDIO_QUALITY


# 音频质量优先级（从高到低）
AUDIO_QUALITY_PRIORITY = [
    30251,  # Hi-Res 无损
    30250,  # 杜比全景声
    30280,  # 192K
    30232,  # 132K
    30216,  # 64K
]

# 视频质量优先级（从高到低）
VIDEO_QUALITY_PRIORITY = [
    127,  # 8K
    126,  # 杜比视界
    125,  # HDR
    120,  # 4K
    116,  # 1080P60
    112,  # 1080P+
    80,   # 1080P
    74,   # 720P60
    64,   # 720P
    32,   # 480P
    16,   # 360P
]

# 编码优先级（从高到低）
CODEC_PRIORITY = ["hev", "av01", "avc"]


def select_best_video_stream(dash_data: Dict) -> Optional[Dict]:
    """
    从 DASH 数据中选择最佳视频流
    优先级：质量 > 编码（HEVC > AV1 > AVC）
    """
    video_streams = dash_data.get("video", [])
    if not video_streams:
        return None

    # 按质量和编码排序
    def sort_key(stream):
        quality = stream.get("id", 0)
        codecs = stream.get("codecs", "").lower()

        # 质量优先级
        try:
            quality_rank = VIDEO_QUALITY_PRIORITY.index(quality)
        except ValueError:
            quality_rank = 999

        # 编码优先级
        codec_rank = 999
        for i, codec in enumerate(CODEC_PRIORITY):
            if codec in codecs:
                codec_rank = i
                break

        return (quality_rank, codec_rank)

    sorted_streams = sorted(video_streams, key=sort_key)
    return sorted_streams[0] if sorted_streams else None


def select_best_audio_stream(dash_data: Dict) -> Optional[Dict]:
    """
    从 DASH 数据中选择最佳音频流
    优先级：Hi-Res > 杜比全景声 > 192K > 132K > 64K
    同时检查 flac 和 dolby 特殊音轨
    """
    best_audio = None
    best_priority = 999

    # 检查普通音频流
    audio_streams = dash_data.get("audio", [])
    for stream in audio_streams:
        audio_id = stream.get("id", 0)
        try:
            priority = AUDIO_QUALITY_PRIORITY.index(audio_id)
            if priority < best_priority:
                best_priority = priority
                best_audio = stream
        except ValueError:
            if best_audio is None:
                best_audio = stream

    # 检查 Hi-Res 无损 (flac)
    flac_data = dash_data.get("flac")
    if flac_data and flac_data.get("audio"):
        flac_audio = flac_data["audio"]
        flac_id = flac_audio.get("id", 30251)
        try:
            priority = AUDIO_QUALITY_PRIORITY.index(flac_id)
            if priority < best_priority:
                best_priority = priority
                best_audio = flac_audio
        except ValueError:
            pass

    # 检查杜比全景声 (dolby)
    dolby_data = dash_data.get("dolby")
    if dolby_data and dolby_data.get("audio"):
        dolby_audios = dolby_data["audio"]
        if dolby_audios:
            dolby_audio = dolby_audios[0]  # 取第一个
            dolby_id = dolby_audio.get("id", 30250)
            try:
                priority = AUDIO_QUALITY_PRIORITY.index(dolby_id)
                if priority < best_priority:
                    best_priority = priority
                    best_audio = dolby_audio
            except ValueError:
                pass

    return best_audio


def get_stream_url(stream: Dict) -> Optional[str]:
    """从流数据中获取下载 URL"""
    # 优先使用 base_url
    url = stream.get("base_url") or stream.get("baseUrl")
    if url:
        return url

    # 备用 URL
    backup_urls = stream.get("backup_url") or stream.get("backupUrl") or []
    if backup_urls:
        return backup_urls[0]

    return None


def check_ffmpeg() -> bool:
    """检查 ffmpeg 是否安装"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """清理文件名"""
    illegal_chars = r'[<>:"/\\|?*\x00-\x1f]'
    filename = re.sub(illegal_chars, '_', filename)
    filename = filename.strip(' .')
    if len(filename) > max_length:
        filename = filename[:max_length]
    return filename or "video"


def parse_video_url(url: str) -> Tuple[Optional[str], Optional[int], int]:
    """解析视频 URL"""
    url = url.strip()
    page = 1

    # 直接是 BV 号
    if url.upper().startswith("BV") and len(url) <= 12:
        return url, None, 1

    # 直接是 AV 号
    av_match = re.match(r'^av(\d+)$', url, re.IGNORECASE)
    if av_match:
        return None, int(av_match.group(1)), 1

    # 解析完整 URL
    from urllib.parse import urlparse, parse_qs

    try:
        parsed = urlparse(url)
        path = parsed.path

        # BV 号
        bv_match = re.search(r'(BV[a-zA-Z0-9]{10})', path, re.IGNORECASE)
        if bv_match:
            bvid = bv_match.group(1)
            query_params = parse_qs(parsed.query)
            if 'p' in query_params:
                page = int(query_params['p'][0])
            return bvid, None, page

        # AV 号
        av_match = re.search(r'av(\d+)', path, re.IGNORECASE)
        if av_match:
            aid = int(av_match.group(1))
            query_params = parse_qs(parsed.query)
            if 'p' in query_params:
                page = int(query_params['p'][0])
            return None, aid, page

    except Exception:
        pass

    return None, None, 1


async def download_stream(url: str, output_path: Path, desc: str = "下载中") -> bool:
    """下载流文件"""
    try:
        client = get_client()
        dwn_id = await client.download_create(url, HEADERS)
        total = client.download_content_length(dwn_id)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'wb') as f:
            with tqdm(total=total, unit='B', unit_scale=True,
                     unit_divisor=1024, desc=desc) as pbar:
                current = 0
                while current < total:
                    chunk = await client.download_chunk(dwn_id)
                    if not chunk:
                        break
                    f.write(chunk)
                    current += len(chunk)
                    pbar.update(len(chunk))

        return True

    except Exception as e:
        print(f"下载出错: {e}")
        import traceback
        traceback.print_exc()
        return False


def merge_video_audio(video_path: Path, audio_path: Path, output_path: Path) -> bool:
    """合并视频和音频"""
    if not check_ffmpeg():
        print("错误: 未找到 ffmpeg，请先安装")
        return False

    print("\n正在合并音视频...")

    try:
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "copy",
            "-y",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"ffmpeg 错误: {result.stderr}")
            return False

        # 删除临时文件
        video_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)

        return True

    except Exception as e:
        print(f"合并失败: {e}")
        return False


async def download_video_async(
    url: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    credential: Credential = None,
    page: int = 1
) -> bool:
    """
    下载视频（异步）

    自动选择最高画质和最高音质（包括杜比全景声、Hi-Res无损）
    """
    # 解析 URL
    bvid, aid, url_page = parse_video_url(url)

    if not bvid and not aid:
        print(f"无法解析视频地址: {url}")
        return False

    if url_page > 1:
        page = url_page

    # 创建视频对象
    if bvid:
        v = video.Video(bvid=bvid, credential=credential)
    else:
        v = video.Video(aid=aid, credential=credential)

    # 获取视频信息
    print("正在获取视频信息...")
    try:
        info = await v.get_info()
    except Exception as e:
        print(f"获取视频信息失败: {e}")
        return False

    # 显示视频信息
    title = info.get("title", "未知")
    owner = info.get("owner", {}).get("name", "未知")
    duration = info.get("duration", 0)
    pages = info.get("pages", [])
    bvid = info.get("bvid", bvid)

    print(f"\n{'='*50}")
    print(f"标题: {title}")
    print(f"UP主: {owner}")
    print(f"时长: {duration // 60}:{duration % 60:02d}")
    print(f"分P数: {len(pages)}")
    print(f"{'='*50}\n")

    # 检查分P
    if page > len(pages):
        print(f"分P {page} 不存在，共 {len(pages)} P")
        return False

    page_info = pages[page - 1]
    part_name = page_info.get("part", f"P{page}")

    print(f"正在下载: P{page} - {part_name}")

    # 获取下载地址
    print("正在获取视频流...")
    try:
        download_url_data = await v.get_download_url(page_index=page - 1)
    except Exception as e:
        print(f"获取下载地址失败: {e}")
        return False

    # 检查是否是 DASH 格式
    dash_data = download_url_data.get("dash")

    if not dash_data:
        # FLV/MP4 单流格式
        durl = download_url_data.get("durl", [])
        if not durl:
            print("错误: 未找到视频流")
            return False

        stream_url = durl[0].get("url")
        print(f"\n检测到单流格式")

        # 准备文件名
        if len(pages) > 1:
            filename = f"{title}_P{page}_{part_name}"
        else:
            filename = title
        filename = sanitize_filename(filename)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        final_output = output_dir / f"{filename}.mp4"

        # 下载
        print("\n正在下载视频...")
        if not await download_stream(stream_url, final_output, "视频"):
            return False

    else:
        # DASH 格式（视频+音频分离）
        # 手动选择最佳流（绕过库的 bug）
        video_stream = select_best_video_stream(dash_data)
        audio_stream = select_best_audio_stream(dash_data)

        if video_stream is None:
            print("错误: 未找到视频流")
            return False

        video_url = get_stream_url(video_stream)
        audio_url = get_stream_url(audio_stream) if audio_stream else None

        if not video_url:
            print("错误: 无法获取视频流 URL")
            return False

        # 显示选择结果
        video_quality = video_stream.get("id", 0)
        video_codecs = video_stream.get("codecs", "unknown")
        print(f"\n已选择:")
        print(f"  视频: {VIDEO_QUALITY_NAME.get(video_quality, f'qn={video_quality}')}")
        print(f"        {video_codecs} 编码")

        if audio_stream:
            audio_quality = audio_stream.get("id", 0)
            audio_name = AUDIO_QUALITY.get(audio_quality, f"qn={audio_quality}")
            print(f"  音频: {audio_name}")
        else:
            print("  音频: 无")

        # 准备文件名
        if len(pages) > 1:
            filename = f"{title}_P{page}_{part_name}"
        else:
            filename = title
        filename = sanitize_filename(filename)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 临时文件
        temp_video = CACHE_DIR / f"{uuid.uuid4()}.m4v"
        temp_audio = CACHE_DIR / f"{uuid.uuid4()}.m4a"
        final_output = output_dir / f"{filename}.mp4"

        # 下载视频
        print("\n正在下载视频流...")
        if not await download_stream(video_url, temp_video, "视频"):
            return False

        # 下载音频（如果有）
        if audio_url:
            print("\n正在下载音频流...")
            if not await download_stream(audio_url, temp_audio, "音频"):
                temp_video.unlink(missing_ok=True)
                return False

            # 合并
            if not merge_video_audio(temp_video, temp_audio, final_output):
                return False
        else:
            # 没有独立音频，直接重命名
            temp_video.rename(final_output)

    print(f"\n下载完成！")
    print(f"保存路径: {final_output}")

    if final_output.exists():
        size = final_output.stat().st_size
        if size > 1024 * 1024 * 1024:
            print(f"文件大小: {size / (1024**3):.2f} GB")
        else:
            print(f"文件大小: {size / (1024**2):.2f} MB")

    return True


def download_video(url: str, output_dir: Path = DEFAULT_OUTPUT_DIR,
                   quality: int = 127, credential: Credential = None,
                   page: int = 1) -> bool:
    """下载视频（同步）"""
    return sync(download_video_async(url, output_dir, credential, page))
