# Bilibili 视频下载器

一个 Python 工具，用于下载 Bilibili 视频，支持原画质下载（最高画质 + 最高音质）。提供命令行和图形界面两种使用方式。

## 功能特性

- 支持最高 8K 画质下载
- 支持杜比全景声、Hi-Res 无损音频
- 支持二维码登录 / Cookie 导入
- 支持分P下载
- 自动选择最高可用音画质量
- **图形界面 (GUI)**：简单易用的可视化操作界面

## 安装

### 依赖

- Python 3.8+
- FFmpeg

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/lrastar/bili_downloader.git
cd bili_downloader

# 创建虚拟环境（可选）
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 安装 FFmpeg

安装后确保 `ffmpeg` 命令在系统 PATH 中可用

## 使用方法

### 图形界面 (推荐)

```bash
python run_gui.py
```

启动后可以：
1. 输入视频链接，点击「获取信息」
2. 选择清晰度和分P
3. 选择保存目录
4. 点击「开始下载」

支持二维码扫码登录和 Cookie 导入，点击底部「登录」按钮即可。

### 命令行

#### 登录

```bash
# 二维码登录（推荐）
python main.py --login

# 导入 Cookie
python main.py --import-cookie "SESSDATA=xxx;bili_jct=xxx"

# 检查登录状态
python main.py --check

# 退出登录
python main.py --logout
```

#### 下载视频

```bash
# 下载视频（自动选择最高画质）
python main.py "https://www.bilibili.com/video/BV1xx411c7mD"

# 使用 BV 号下载
python main.py "BV1xx411c7mD"

# 指定清晰度
python main.py "BV1xx411c7mD" -q 1080p

# 指定输出目录
python main.py "BV1xx411c7mD" -o ./videos

# 下载指定分P
python main.py "BV1xx411c7mD" -p 2
```

### 支持的清晰度

`240p`, `360p`, `480p`, `720p`, `720p60`, `1080p`, `1080p+`, `1080p60`, `4k`, `hdr`, `dolby_vision`, `8k`

> 注意：未登录状态只能下载 480P 及以下清晰度。高清晰度需要登录，部分清晰度需要大会员。

## 音频质量

自动选择最高可用音质：

Hi-Res 无损 > 杜比全景声 > 192K > 132K > 64K
