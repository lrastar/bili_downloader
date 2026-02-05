#!/usr/bin/env python3
"""
Bilibili 视频下载器
支持原画质下载（最高画质 + 最高音质）
支持杜比全景声、Hi-Res无损音频
"""
import argparse
import sys
from pathlib import Path

from bilibili_api import sync

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from config import DEFAULT_OUTPUT_DIR, VIDEO_QUALITY_MAP
from auth import AuthManager, qrcode_login
from download import download_video, check_ffmpeg


def do_login(auth_manager: AuthManager) -> bool:
    """执行二维码登录"""
    credential = qrcode_login()
    if credential:
        auth_manager.save_credential(credential)
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Bilibili 视频下载器 - 支持原画质 + 最高音质下载",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --login                          # 二维码登录
  %(prog)s --import-cookie "SESSDATA=xxx"   # 导入 Cookie
  %(prog)s --check                          # 检查登录状态
  %(prog)s "https://www.bilibili.com/video/BV1xx411c7mD"  # 下载视频
  %(prog)s "BV1xx411c7mD" -q 1080p          # 指定清晰度下载
  %(prog)s "BV1xx411c7mD" -o ./videos       # 指定输出目录
  %(prog)s "BV1xx411c7mD" -p 2              # 下载第2P

支持的清晰度: 240p, 360p, 480p, 720p, 720p60, 1080p, 1080p+, 1080p60, 4k, hdr, dolby_vision, 8k
音频自动选择最高质量: Hi-Res无损 > 杜比全景声 > 192K > 132K > 64K
        """
    )

    parser.add_argument("url", nargs="?", help="视频 URL 或 BV/AV 号")
    parser.add_argument("--login", action="store_true", help="二维码登录")
    parser.add_argument("--import-cookie", metavar="COOKIE", help="导入 Cookie 字符串")
    parser.add_argument("--check", action="store_true", help="检查登录状态")
    parser.add_argument("--logout", action="store_true", help="退出登录")
    parser.add_argument("-q", "--quality", default="max",
                        help="视频清晰度 (默认: max = 最高可用)")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="输出目录")
    parser.add_argument("-p", "--page", type=int, default=1, help="分P序号 (从1开始)")

    args = parser.parse_args()

    # 初始化认证管理器
    auth_manager = AuthManager()

    # 处理登录命令
    if args.login:
        success = do_login(auth_manager)
        sys.exit(0 if success else 1)

    if args.import_cookie:
        success = auth_manager.import_cookie_string(args.import_cookie)
        if success:
            print("Cookie 导入成功")
            sync(auth_manager.check_credential_valid())
        sys.exit(0 if success else 1)

    if args.check:
        if sync(auth_manager.check_credential_valid()):
            print("登录状态有效")
        else:
            print("未登录或登录已过期")
        sys.exit(0)

    if args.logout:
        auth_manager.clear_credential()
        sys.exit(0)

    # 下载视频
    if not args.url:
        parser.print_help()
        sys.exit(1)

    # 检查 ffmpeg
    if not check_ffmpeg():
        print("警告: 未检测到 ffmpeg，将无法合并音视频")
        print("请安装 ffmpeg 并添加到系统 PATH")
        print("下载地址: https://ffmpeg.org/download.html")
        sys.exit(1)

    # 获取凭证
    credential = auth_manager.credential

    if not credential:
        print("提示: 未登录，只能下载 480P 及以下清晰度")
        print("使用 --login 参数进行登录以获取更高清晰度\n")
    else:
        # 验证登录状态
        if not sync(auth_manager.check_credential_valid()):
            print("登录已过期，请重新登录")
            credential = None

    # 处理清晰度
    quality_str = args.quality.lower()
    if quality_str == "max":
        quality = 127  # 请求最高
    elif quality_str in VIDEO_QUALITY_MAP:
        quality = VIDEO_QUALITY_MAP[quality_str]
    else:
        print(f"未知的清晰度: {quality_str}")
        print(f"支持的清晰度: {', '.join(VIDEO_QUALITY_MAP.keys())}")
        sys.exit(1)

    # 创建输出目录
    args.output.mkdir(parents=True, exist_ok=True)

    # 下载
    success = download_video(
        url=args.url,
        output_dir=args.output,
        quality=quality,
        credential=credential,
        page=args.page
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
