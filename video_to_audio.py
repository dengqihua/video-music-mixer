# !/usr/bin/env python3
"""MP4 视频转音频工具：支持高质量 MP3、CBR MP3、原始音轨提取和 FLAC。"""

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

MODES = {
    "mp3": ("高质量 MP3（VBR -q:a 0）", ".mp3"),
    "cbr320": ("320 kbps 恒定比特率 MP3", ".mp3"),
    "copy": ("复制原始音轨，不重新编码", ""),
    "flac": ("转换为 FLAC 无损编码", ".flac"),
    "wav": ("转换为 WAV（PCM 16-bit）", ".wav"),
}

# 常见音频编码对应的推荐容器扩展名
CODEC_SUFFIXES = {
    "aac": ".m4a",
    "alac": ".m4a",
    "mp3": ".mp3",
    "flac": ".flac",
    "opus": ".opus",
    "vorbis": ".ogg",
    "ac3": ".ac3",
    "eac3": ".eac3",
    "wavpack": ".wv",
    "truehd": ".mka",
    "dts": ".dts",
    "pcm_s16le": ".wav",
    "pcm_s24le": ".wav",
    "pcm_s32le": ".wav",
    "pcm_f32le": ".wav",
}


def check_tools():
    """检查 ffmpeg 和 ffprobe 是否可用。"""
    missing = [
        name for name in ("ffmpeg", "ffprobe")
        if shutil.which(name) is None
    ]
    if missing:
        print(f"❌ 缺少程序：{', '.join(missing)}")
        print("macOS: brew install ffmpeg")
        print("Ubuntu/Debian: sudo apt install ffmpeg")
        print("Windows: winget install ffmpeg")
        return False

    for name in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run(
                [name, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=10,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"❌ {name} 无法正常运行：{exc}")
            return False

    return True


def probe_audio(input_file: Path):
    """读取第一条音轨的信息；无音轨或探测失败时返回 None。"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries",
        "stream=codec_name,bit_rate,sample_rate,channels",
        "-of", "json",
        str(input_file),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        return streams[0] if streams else None
    except (
            subprocess.SubprocessError,
            OSError,
            json.JSONDecodeError,
    ) as exc:
        print(f"❌ 音轨探测失败：{exc}")
        return None


def get_output_suffix(mode: str, info: dict) -> str:
    """根据模式和原始编码确定默认扩展名。"""
    if mode != "copy":
        return MODES[mode][1]

    codec = info.get("codec_name", "")
    return CODEC_SUFFIXES.get(codec, ".mka")


def build_cmd(mode: str, input_file: Path, output_file: Path):
    """构建 FFmpeg 命令，只处理第一条音轨。"""
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i", str(input_file),
        "-map", "0:a:0",
        "-vn",
        "-sn",
        "-dn",
    ]

    if mode == "copy":
        cmd += ["-c:a", "copy"]
    elif mode == "flac":
        cmd += ["-c:a", "flac"]
    elif mode == "wav":
        cmd += [
            "-c:a", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
        ]
    elif mode == "cbr320":
        cmd += [
            "-c:a", "libmp3lame",
            "-b:a", "320k",
        ]
    else:
        cmd += [
            "-c:a", "libmp3lame",
            "-q:a", "0",
        ]

    # 输出到唯一的临时文件，成功后再替换正式文件。
    # 这样转换失败时，不会直接破坏原有输出文件。
    return cmd + ["-n", str(output_file)]


def convert_audio(input_path: str, output_path: str = "", mode: str = "mp3", overwrite: bool = False) -> bool:
    """转换单个文件。"""
    if mode not in MODES:
        print(f"❌ 未知模式：{mode}")
        return False

    source = Path(input_path).expanduser()

    if not source.is_file():
        print(f"❌ 输入文件不存在：{source}")
        return False

    source = source.resolve()

    info = probe_audio(source)
    if not info:
        print(f"❌ 未找到可用音轨或无法读取音轨：{source.name}")
        return False

    suffix = get_output_suffix(mode, info)
    target = (
        Path(output_path).expanduser()
        if output_path
        else source.with_suffix(suffix)
    )

    if not target.is_absolute():
        target = target.absolute()

    # 防止输出路径与源文件相同。
    if target.resolve() == source:
        print("❌ 输出路径与输入文件相同，已取消。")
        return False

    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and not overwrite:
        print(f"⚠️ 输出文件已存在，跳过：{target}")
        print("   如需覆盖，请添加 --overwrite")
        return False

    # 临时文件保留原扩展名，确保 FFmpeg 能正确识别容器。
    temp = target.with_name(
        f"{target.stem}.tmp-{uuid.uuid4().hex}{target.suffix}"
    )

    bitrate = info.get("bit_rate")
    try:
        bitrate_text = (
            f"{int(bitrate) / 1000:.0f} kbps"
            if bitrate and str(bitrate).isdigit()
            else "比特率未知"
        )
    except (ValueError, TypeError):
        bitrate_text = "比特率未知"

    print(
        f"🔎 原始音轨：{info.get('codec_name', '?')} | "
        f"{bitrate_text} | "
        f"{info.get('sample_rate', '?')} Hz | "
        f"{info.get('channels', '?')} 声道"
    )
    print(f"🎬 模式：{MODES[mode][0]}")
    print(f"   {source.name} → {target.name}")

    try:
        cmd = build_cmd(mode, source, temp)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            print(f"❌ 转换失败：\n{result.stderr[-5000:]}")
            return False

        if not temp.is_file() or temp.stat().st_size == 0:
            print("❌ 转换失败：未生成有效输出文件。")
            return False

        # 检查最终路径，避免意外覆盖。
        if target.exists() and not overwrite:
            print(f"⚠️ 输出文件已出现，拒绝覆盖：{target}")
            return False

        # 临时文件与正式文件在同一目录，替换通常是原子操作。
        temp.replace(target)

        size_mb = target.stat().st_size / (1024 * 1024)
        print(f"✅ 转换成功：{target}（{size_mb:.2f} MB）\n")
        return True

    except OSError as exc:
        print(f"❌ 文件处理失败：{exc}")
        return False

    finally:
        # 清理转换失败后遗留的临时文件。
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def convert_directory(input_dir: str, output_dir: str = "", mode: str = "mp3", overwrite: bool = False, recursive: bool = False):
    """批量转换目录中的 MP4 文件。"""
    in_dir = Path(input_dir).expanduser()

    if not in_dir.is_dir():
        print(f"❌ 输入目录不存在：{in_dir}")
        return

    iterator = in_dir.rglob("*") if recursive else in_dir.iterdir()
    files = sorted(
        (
            path for path in iterator
            if path.is_file() and path.suffix.lower() == ".mp4"
        ),
        key=lambda path: str(path).lower(),
    )

    if not files:
        print(f"⚠️ 未找到 MP4 文件：{in_dir}")
        return

    out_dir = Path(output_dir).expanduser() if output_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    print(f"📁 找到 {len(files)} 个 MP4 文件，开始处理。\n")

    success = fail = 0

    for source in files:
        out = ""

        if out_dir:
            if recursive:
                # 保留相对目录结构，避免不同子目录中的同名文件冲突。
                relative = source.relative_to(in_dir)
                parent = out_dir / relative.parent
                parent.mkdir(parents=True, exist_ok=True)
                out = str(parent / (source.stem + MODES[mode][1]))
            else:
                out = str(out_dir / (source.stem + MODES[mode][1]))

            # copy 模式的扩展名取决于原始音轨，稍后单独确定。
            if mode == "copy":
                info = probe_audio(source)
                if not info:
                    print(f"❌ 无法读取音轨：{source}")
                    fail += 1
                    continue
                suffix = get_output_suffix(mode, info)
                out = str(Path(out).with_suffix(suffix))

        try:
            if convert_audio(str(source), out, mode, overwrite):
                success += 1
            else:
                fail += 1
        except Exception as exc:
            # 防止单个文件异常中断整个批次。
            print(f"❌ 处理异常：{source.name}：{exc}")
            fail += 1

    print(f"✨ 批量处理完成！成功：{success} 个，失败/跳过：{fail} 个。")


def main():
    parser = argparse.ArgumentParser(
        description="MP4 视频转音频工具（依赖 FFmpeg）"
    )
    parser.add_argument("input", help="输入 MP4 文件或目录")
    parser.add_argument("output", nargs="?", default="", help="输出文件或目录")
    parser.add_argument(
        "-m", "--mode",
        choices=list(MODES),
        default="mp3",
        help="转换模式，默认 mp3",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允许覆盖已存在的输出文件",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="递归扫描目录下的 MP4 文件",
    )

    args = parser.parse_args()

    if not check_tools():
        sys.exit(1)

    source = Path(args.input).expanduser()

    if source.is_dir():
        convert_directory(
            str(source),
            args.output,
            args.mode,
            args.overwrite,
            args.recursive,
        )
    elif source.is_file():
        if args.output and Path(args.output).is_dir():
            # 单文件输入、目录输出时，自动生成文件名。
            info = probe_audio(source)
            if not info:
                sys.exit(1)
            suffix = get_output_suffix(args.mode, info)
            output = str(Path(args.output) / (source.stem + suffix))
        else:
            output = args.output

        ok = convert_audio(
            str(source),
            output,
            args.mode,
            args.overwrite,
        )
        if not ok:
            sys.exit(1)
    else:
        print(f"❌ 输入路径无效：{source}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
1. 常用转换命令
    默认转换为高质量 MP3
    python video_to_audio.py ./data/output/test.mp4
    
    
    直接复制原始音轨，不重新编码
    python video_to_audio.py ./data/output/test.mp4 -m copy
    
    
    转为 FLAC
    python video_to_audio.py ./data/output/test.mp4 -m flac
    
    
    转为 320 kbps MP3
    python video_to_audio.py ./data/output/test.mp4 ./data/output/audio -m cbr320


2. 批量处理
    转换目录中的 MP4，输出到独立目录
    python video_to_audio.py ./data/output/ ./data/output/audio
    
    
    
    递归处理所有子目录，并保留目录结构
    python video_to_audio.py ./data/output/ ./data/output/audio -r
    
    
    
    允许覆盖已存在的音频文件
    python video_to_audio.py ./data/output/ ./data/output/audio --overwrite
"""
