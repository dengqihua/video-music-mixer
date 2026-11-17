# -*- coding: utf-8 -*-
"""批量 AI 人声分离与背景音乐合成工具。"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mpeg", ".mpg"}
PROJECT_ROOT = Path(__file__).resolve().parent
# Docker Compose 显式设置为 /data；本机运行默认使用项目目录下的 data/。
DATA_ROOT = Path(os.environ.get("VIDEO_MIXER_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser().resolve()
DEFAULT_INPUT_DIR = DATA_ROOT / "input"
DEFAULT_OUTPUT_DIR = DATA_ROOT / "output"
DEFAULT_MUSIC = DATA_ROOT / "background_music.mp3"
WORK_ROOT = DATA_ROOT / "work"
# 本机运行时把模型缓存放在项目目录，Docker 中则沿用 Compose 指定的缓存挂载。
os.environ.setdefault("TORCH_HOME", str(PROJECT_ROOT / "model-cache"))

env = os.environ.copy()
env["HF_HUB_OFFLINE"] = "1"


def run(cmd: Iterable[object]) -> subprocess.CompletedProcess:
    """执行外部命令；失败时保留完整异常供单个任务记录。"""
    command = [str(item) for item in cmd]
    display_command = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
    print("\n执行:", display_command, flush=True)
    return subprocess.run(command, check=True, env=env)


def probe(file_path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_format", "-show_streams",
            "-of", "json", str(file_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(result.stdout)


def get_duration(file_path: Path) -> float:
    metadata = probe(file_path)
    duration = float(metadata.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise RuntimeError(f"无法获取有效的视频时长：{file_path}")
    return duration


def validate_video(file_path: Path) -> None:
    metadata = probe(file_path)
    streams = metadata.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise RuntimeError("文件中没有视频流")
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise RuntimeError("原视频没有音轨，无法提取人声")


def validate_music(music: Path) -> None:
    if not music.is_file():
        raise FileNotFoundError(f"背景音乐不存在：{music}")
    metadata = probe(music)
    if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
        raise RuntimeError(f"背景音乐文件没有有效音轨：{music}")


def extract_audio(video: Path, wav_file: Path) -> None:
    print("\n[1/4] 正在提取原视频音频...", flush=True)
    run([
        "ffmpeg", "-y", "-i", video,
        "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "44100",
        "-c:a", "pcm_s16le", wav_file,
    ])


def separate_vocals_chunked(source_wav: Path, work_dir: Path, chunk_seconds: int = 300, model_segment: int = 5, ) -> Path:
    """分段运行 Demucs，完成后将人声片段无损拼接。"""
    chunks_dir = work_dir / "audio_chunks"
    demucs_dir = work_dir / "demucs_chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    demucs_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n正在将音频切分为每段约 {chunk_seconds} 秒...", flush=True)
    run([
        "ffmpeg", "-y", "-i", source_wav,
        "-map", "0:a:0", "-f", "segment",
        "-segment_time", chunk_seconds,
        "-reset_timestamps", "1",
        "-c:a", "pcm_s16le",
        chunks_dir / "chunk_%04d.wav",
    ])

    chunks = sorted(chunks_dir.glob("chunk_*.wav"))
    if not chunks:
        raise RuntimeError("音频切分失败，没有生成任何片段")

    print(f"共切分为 {len(chunks)} 段", flush=True)
    vocal_files = []

    for index, chunk in enumerate(chunks, 1):
        print(f"\n[2/4] [{index}/{len(chunks)}] AI 分离人声：{chunk.name}", flush=True)
        run([
            sys.executable, "-m", "demucs",
            "-d", "cpu",
            "-n", "htdemucs",
            "--two-stems=vocals",
            "--other-method", "none",
            "--shifts", "0",
            "--segment", model_segment,
            "--overlap", "0.25",
            "--out", demucs_dir,
            chunk,
        ])

        vocal_file = demucs_dir / "htdemucs" / chunk.stem / "vocals.wav"
        if not vocal_file.is_file() or vocal_file.stat().st_size == 0:
            raise RuntimeError(f"第 {index} 段没有生成有效的人声文件：{vocal_file}")
        vocal_files.append(vocal_file)

    concat_file = work_dir / "vocals_concat.txt"
    with concat_file.open("w", encoding="utf-8") as file:
        for vocal in vocal_files:
            # FFmpeg concat demuxer 使用反斜杠转义特殊字符。
            escaped_path = vocal.as_posix().replace("\\", "/").replace("'", "\\'")
            file.write(f"file '{escaped_path}'\n")

    output_vocals = work_dir / "vocals_full.wav"
    print("\n正在合并分离后的人声片段...", flush=True)
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file, "-c:a", "pcm_s16le", output_vocals,
    ])
    if not output_vocals.is_file() or output_vocals.stat().st_size == 0:
        raise RuntimeError("人声片段合并失败")
    return output_vocals


def mix_audio_and_video(video: Path, vocals: Path, music: Path, output: Path, duration: float, music_volume: float = 0.40, fade_seconds: float = 3) -> None:
    """循环背景音乐与分离人声混音，原视频画面直接复制。"""
    print("\n[3/4] 正在混合人声和背景音乐...", flush=True)

    fade = min(fade_seconds, duration / 2)
    music_filter = f"volume={music_volume}"
    if fade > 0:
        fade_start = max(0, duration - fade)
        music_filter += f",afade=t=in:st=0:d={fade},afade=t=out:st={fade_start}:d={fade}"

    filter_complex = (
        f"[1:a]volume=1.0[v];"
        f"[0:a]{music_filter}[m];"
        "[v][m]amix=inputs=2:duration=longest:"
        "dropout_transition=0:normalize=0,"
        "alimiter=limit=0.95[aout]"
    )

    run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", music,
        "-i", vocals,
        "-i", video,
        "-filter_complex", filter_complex,
        "-map", "2:v:0", "-map", "[aout]",
        # 保留原视频的全局元信息
        "-map_metadata", "2",
        # 保留原视频章节
        "-map_chapters", "2",
        "-t", f"{duration:.6f}",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-f", "mp4", output,
    ])


def process_video(video: Path, output: Path, music: Path, music_volume: float, fade_seconds: float, chunk_seconds: int, model_segment: int) -> None:
    """处理单个视频。临时目录在成功或失败后都会自动清理。"""
    print("\n" + "=" * 72, flush=True)
    print(f"开始处理：{video.name}", flush=True)
    print("=" * 72, flush=True)

    validate_video(video)
    duration = get_duration(video)
    print(f"视频时长：{duration:.2f} 秒", flush=True)

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    partial_output = output.with_name(f"{output.stem}.partial{output.suffix}")
    partial_output.unlink(missing_ok=True)

    try:
        # 每个视频使用独立临时目录，避免不同任务的片段互相覆盖。
        with tempfile.TemporaryDirectory(prefix="video-mixer-", dir=WORK_ROOT) as temp_dir:
            work_dir = Path(temp_dir)
            source_wav = work_dir / "source.wav"
            extract_audio(video, source_wav)

            vocals = separate_vocals_chunked(
                source_wav=source_wav,
                work_dir=work_dir,
                chunk_seconds=chunk_seconds,
                model_segment=model_segment,
            )

            mix_audio_and_video(
                video=video,
                vocals=vocals,
                music=music,
                output=partial_output,
                duration=duration,
                music_volume=music_volume,
                fade_seconds=fade_seconds,
            )

            if not partial_output.is_file() or partial_output.stat().st_size == 0:
                raise RuntimeError("FFmpeg 没有生成有效的临时输出文件")
            # 再次检查输出容器，确保文件可被 ffprobe 正常读取。
            probe(partial_output)
            os.replace(partial_output, output)

        print(f"\n[4/4] 转换完成：{output}", flush=True)
        print("本视频的音频分段、Demucs 输出及临时文件已清理。", flush=True)
    finally:
        partial_output.unlink(missing_ok=True)


def collect_videos(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入目录不存在：{input_dir}")
    return sorted(
        (p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda p: p.name.casefold(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"批量 AI 人声分离与背景音乐合成（默认扫描 {DEFAULT_INPUT_DIR}）")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help=f"批量输入目录，默认 {DEFAULT_INPUT_DIR}")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help=f"输出目录，默认 {DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--video", type=Path, help="可选：只处理指定的单个视频，覆盖批量模式")
    parser.add_argument("--output", type=Path, help="单视频模式的输出 MP4 路径；仅与 --video 配合使用")
    parser.add_argument("--music", type=Path, default=DEFAULT_MUSIC, help=f"背景音乐文件，默认 {DEFAULT_MUSIC}")
    parser.add_argument("--music-volume", type=float, default=0.40, help="背景音乐音量，范围 0～1，默认 0.40")
    parser.add_argument("--fade", type=float, default=1, help="背景音乐淡入和淡出秒数，默认 1")
    parser.add_argument("--chunk-seconds", type=int, default=300, help="每个音频分段的秒数，默认 300（5 分钟）")
    parser.add_argument("--segment", type=int, default=5, help="Demucs 模型推理窗口秒数，默认 5")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已经存在的输出文件；默认跳过已转换文件")
    return parser


def check_external_tools() -> None:
    """确认 FFmpeg 工具链已安装并可从 PATH 找到。"""
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(
            f"找不到外部程序：{joined}。请先安装 FFmpeg，并确保 ffmpeg、ffprobe 已加入系统 PATH。"
        )


def main() -> int:
    args = build_parser().parse_args()
    check_external_tools()
    music = args.music.resolve()

    if not 0 <= args.music_volume <= 1:
        raise ValueError("背景音乐音量必须在 0 到 1 之间")
    if args.fade < 0:
        raise ValueError("淡入淡出时间不能小于 0")
    if args.chunk_seconds <= 0:
        raise ValueError("音频分段时长必须大于 0")
    if args.segment <= 0:
        raise ValueError("Demucs 模型分段时长必须大于 0")

    validate_music(music)

    if args.video:
        video = args.video.resolve()
        if not video.is_file():
            raise FileNotFoundError(f"视频不存在：{video}")
        output = (args.output or (args.output_dir / f"{video.stem}.mp4")).resolve()
        if video == output or music == output:
            raise ValueError("输出文件不能覆盖输入视频或背景音乐")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and not args.overwrite:
            print(f"跳过：输出文件已存在：{output}")
            return 0
        process_video(video, output, music, args.music_volume, args.fade,
                      args.chunk_seconds, args.segment)
        return 0

    if args.output:
        raise ValueError("--output 仅能与 --video 一起使用")

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    videos = collect_videos(input_dir)

    print("=" * 72)
    print("AI 视频人声分离及背景音乐批量合成")
    print(f"输入目录：{input_dir}")
    print(f"输出目录：{output_dir}")
    print(f"背景音乐：{music}")
    print(f"发现视频：{len(videos)} 个")
    print("=" * 72)

    if not videos:
        print("输入目录中没有找到支持的视频文件。")
        return 0

    succeeded = 0
    skipped = 0
    failed = 0
    failures = []

    for index, video in enumerate(videos, 1):
        output = output_dir / f"{video.stem}.mp4"
        print(f"\n任务进度：{index}/{len(videos)}", flush=True)

        if output.exists() and not args.overwrite:
            print(f"跳过（输出文件已存在）：{output.name}", flush=True)
            skipped += 1
            continue

        try:
            process_video(video, output, music, args.music_volume, args.fade,
                          args.chunk_seconds, args.segment)
            succeeded += 1
        except Exception as error:
            failed += 1
            failures.append((video.name, str(error)))
            print(f"\n处理失败：{video.name}\n原因：{error}", file=sys.stderr, flush=True)
            # 单个文件失败不影响后续任务。
            continue

    print("\n" + "=" * 72)
    print("批量转换结束")
    print(f"总数：{len(videos)} | 成功：{succeeded} | 跳过：{skipped} | 失败：{failed}")
    if failures:
        print("\n失败清单：")
        for name, reason in failures:
            print(f"- {name}: {reason}")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        print(f"\n外部命令执行失败，退出码：{error.returncode}", file=sys.stderr)
        sys.exit(error.returncode or 1)
    except Exception as error:
        print(f"\n程序启动失败：{error}", file=sys.stderr)
        sys.exit(1)
