"""
Bilibili 下载器配置文件
"""
import os
from pathlib import Path

# 项目目录
PROJECT_DIR = Path(__file__).parent

# Cookie 存储路径
COOKIE_FILE = PROJECT_DIR / "cookies.json"

# 下载配置
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "downloads"
CACHE_DIR = PROJECT_DIR / "cache"

# 确保目录存在
DEFAULT_OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# 视频清晰度映射
VIDEO_QUALITY_MAP = {
    "240p": 6,
    "360p": 16,
    "480p": 32,
    "720p": 64,
    "720p60": 74,
    "1080p": 80,
    "1080p+": 112,
    "1080p60": 116,
    "4k": 120,
    "hdr": 125,
    "dolby_vision": 126,
    "8k": 127,
}

# 视频清晰度代码到名称映射
VIDEO_QUALITY_NAME = {
    6: "240P 极速",
    16: "360P 流畅",
    32: "480P 清晰",
    64: "720P 高清",
    74: "720P60 高帧率",
    80: "1080P 高清",
    112: "1080P+ 高码率",
    116: "1080P60 高帧率",
    120: "4K 超清",
    125: "HDR 真彩色",
    126: "杜比视界",
    127: "8K 超高清",
}

# 音频质量代码
AUDIO_QUALITY = {
    30216: "64K",
    30232: "132K",
    30280: "192K",
    30250: "杜比全景声",
    30251: "Hi-Res无损",
}

# 音频质量优先级（从高到低）
AUDIO_QUALITY_PRIORITY = [30251, 30250, 30280, 30232, 30216]

# 视频编码偏好
VIDEO_CODECS = {
    7: "AVC (H.264)",
    12: "HEVC (H.265)",
    13: "AV1",
}

# 编码优先级（从高到低）：HEVC > AV1 > AVC
CODEC_PRIORITY = [12, 13, 7]
