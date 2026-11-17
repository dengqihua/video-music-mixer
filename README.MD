# AI 视频人声分离与背景音乐批量合成工具

本项目使用 **Python + Demucs + FFmpeg**，对视频原音轨进行 AI 人声分离，再与指定的 MP3 背景音乐混合，输出 MP4。支持两种运行方式：

1. **本机 Python 虚拟环境**：不需要 Docker，优先推荐 Apple Silicon Mac mini；同时提供 Linux、Windows 安装脚本。
2. **Docker / Docker Compose**：保留原有容器化部署方式。

项目不要求 NVIDIA GPU。当前程序明确使用 `-d cpu`，即使 macOS 上 PyTorch 能识别 Apple MPS，也不会自动切换到 MPS。

## 1. 功能

- 批量处理 `data/input/` 中的视频，按文件名顺序逐个转换。
- 如果 `data/output/` 已存在同名 MP4，默认跳过；使用 `--overwrite` 可覆盖。
- 单个视频失败后继续处理队列中的下一个视频。
- 先按默认 300 秒切分音频，再逐段调用 Demucs，降低长视频一次性推理的内存压力。
- 每个视频使用独立临时目录；正常成功或异常退出后自动清理分段文件和中间文件。
- 先生成临时 MP4 并验证，再替换正式输出文件。
- 视频画面使用 FFmpeg `-c:v copy`，不重新编码视频流；音频重新编码为 AAC。
- 背景音乐循环播放，可调整音量、淡入和淡出时间。

## 2. 处理逻辑

每个视频依次执行：

1. 使用 `ffprobe` 检查视频流、音轨和时长。
2. 使用 FFmpeg 提取第一条音轨，转换为双声道、44.1kHz、16-bit PCM WAV。
3. 将 WAV 按默认每段 300 秒（5 分钟）切片。
4. 对每个切片运行 Demucs `htdemucs`，CPU 模式，`shifts=0`，模型窗口默认 5 秒。
5. 将每段分离出的人声 WAV 拼接为完整人声音轨。
6. 将人声与循环播放的背景音乐混音，默认背景音乐音量 40%，淡入淡出各 1 秒，并使用 limiter 控制峰值。
7. 将混合音轨与原视频画面封装为 MP4。
8. 验证临时输出后替换为正式文件，并清理当前视频的临时工作目录。

### 两种分段参数

- `--chunk-seconds 300`：外部分段长度，即每次启动 Demucs 处理的音频文件长度。
- `--segment 5`：Demucs 模型内部推理窗口长度。

两者用途不同。缩短外部分段可能降低单次任务的内存压力，但会增加 Demucs 启动次数和拼接边界；增大分段不保证音质或速度一定改善。

## 3. 项目目录

```text
video-music-mixer/
├── main.py
├── requirements.txt
├── setup.sh                 # macOS / Linux 虚拟环境安装
├── run.sh                   # macOS / Linux 运行入口
├── setup.ps1                # Windows PowerShell 虚拟环境安装
├── run.ps1                  # Windows PowerShell 运行入口
├── Dockerfile
├── docker-compose.yml
├── README.MD
├── .gitignore
├── .dockerignore
├── model-cache/              # 本机 PyTorch / Demucs 模型缓存
└── data/
    ├── background_music.mp3  # 默认背景音乐
    ├── input/                # 待处理视频
    ├── output/               # 转换结果
    └── work/                 # 临时文件，任务结束后自动清理
```

## 4. 本机运行：macOS（优先推荐）

### 4.1 安装系统依赖

推荐使用 Python 3.11。先确认：

```bash
python3 --version
```

安装 FFmpeg（同时提供 `ffmpeg` 和 `ffprobe`）：

```bash
brew install ffmpeg
```

如果尚未安装 Homebrew，请先按照 [Homebrew 官方说明](https://brew.sh/) 安装。FFmpeg 也可通过其他可信发行渠道安装，但必须确保 `ffmpeg`、`ffprobe` 都能在终端 PATH 中找到。

验证：

```bash
ffmpeg -version
ffprobe -version
```

### 4.2 创建虚拟环境并安装依赖

在项目根目录运行：

```bash
chmod +x setup.sh run.sh
./setup.sh
```

脚本会：

1. 创建项目内 `.venv/` 虚拟环境。
2. 安装 PyTorch 和 TorchAudio 的 macOS wheel。
3. 安装 `requirements.txt` 中的 Demucs、NumPy。
4. 检查关键 Python 依赖。

Apple Silicon Mac 使用官方 macOS ARM64 wheel。虽然 PyTorch 可能报告 MPS 可用，但本项目为了保持与现有 Docker 结果和资源策略一致，仍然通过 `-d cpu` 使用 CPU 推理。

### 4.3 放入视频并运行

将视频放到 `data/input/`，默认背景音乐放在 `data/background_music.mp3`，然后执行：

```bash
./run.sh
```

结果输出到 `data/output/`。

覆盖已有结果：

```bash
./run.sh --overwrite
```

只转换一个视频：

```bash
./run.sh --video "data/input/example.mp4" --output "data/output/example.mp4"
```

指定音乐和参数：

```bash
./run.sh \
  --music "data/background_music.mp3" \
  --music-volume 0.30 \
  --fade 2 \
  --chunk-seconds 300 \
  --segment 5
```

### 4.4 手动激活虚拟环境（可选）

如果不想使用 `run.sh`：

```bash
source .venv/bin/activate
python main.py
```

退出虚拟环境：

```bash
deactivate
```

## 5. 本机运行：Linux

需要 Python 3.10～3.12（推荐 3.11）、FFmpeg 和可用的 pip。以 Ubuntu / Debian 为例：

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv ffmpeg
```

在项目根目录：

```bash
chmod +x setup.sh run.sh
./setup.sh
./run.sh
```

Linux 安装脚本会从 [PyTorch 官方 CPU wheel 源](https://pytorch.org/get-started/locally/) 安装 `torch`、`torchaudio`，避免误装 CUDA 运行时。其他发行版请使用对应包管理器安装 Python 和 FFmpeg；如果系统 Python 不是 3.10～3.12，请安装合适版本后确保 `python3` 指向该版本。

## 6. 本机运行：Windows 10 / 11

### 6.1 安装系统依赖

- 安装 Python 3.11，并勾选添加到 PATH；建议同时安装 Python Launcher。
- 安装 FFmpeg，并将包含 `ffmpeg.exe`、`ffprobe.exe` 的 `bin` 目录加入 PATH。
- 重新打开 PowerShell，确认：

```powershell
py -3.11 --version
ffmpeg -version
ffprobe -version
```

FFmpeg 可从 [FFmpeg 官方下载页](https://www.ffmpeg.org/download.html) 的 Windows builds 链接获取；也可使用已配置好 winget 的环境安装可信构建。Windows 脚本按常见 x64 Python 环境准备；Windows ARM64 的 PyTorch wheel 可用性需按 PyTorch 官方安装页面单独确认。

### 6.2 创建环境并运行

在项目根目录打开 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.ps1
```

覆盖已有结果：

```powershell
.\run.ps1 --overwrite
```

单文件转换：

```powershell
.\run.ps1 --video "data\input\example.mp4" --output "data\output\example.mp4"
```

Windows 安装脚本安装 PyTorch CPU wheel。若 PowerShell 禁止执行脚本，可只对当前窗口临时执行上面的 `Set-ExecutionPolicy`，不需要修改整台电脑的执行策略。

## 7. Docker 运行（保留原方式）

需要 Docker Engine / Docker Desktop 和 Docker Compose。

构建：

```bash
docker compose build
```

批量转换：

```bash
docker compose run --rm video-mixer
```

覆盖已有结果：

```bash
docker compose run --rm video-mixer --overwrite
```

单文件转换：

```bash
docker compose run --rm video-mixer \
  --video /data/input/example.mp4 \
  --output /data/output/example.mp4
```

Compose 通过 `VIDEO_MIXER_DATA_DIR=/data` 将数据目录明确指定为容器路径；本机运行不设置该变量时，程序默认使用项目目录下的 `data/`。Docker 的 CPU、内存、共享内存限制仍由 `docker-compose.yml` 控制。

## 8. 参数说明

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--input-dir` | 项目 `data/input`（Docker 为 `/data/input`） | 批量输入目录 |
| `--output-dir` | 项目 `data/output`（Docker 为 `/data/output`） | 输出目录 |
| `--video` | 无 | 指定单个视频，启用单文件模式 |
| `--output` | 自动生成 | 单文件模式的输出 MP4 路径，仅与 `--video` 配合 |
| `--music` | 项目 `data/background_music.mp3`（Docker 为 `/data/background_music.mp3`） | 背景音乐文件 |
| `--music-volume` | `0.40` | 背景音乐线性音量，范围 0～1 |
| `--fade` | `1` | 淡入和淡出秒数；0 表示关闭 |
| `--chunk-seconds` | `300` | 每个外部分段的秒数 |
| `--segment` | `5` | Demucs 模型推理窗口秒数 |
| `--overwrite` | 关闭 | 覆盖已存在输出；默认跳过 |

本机可直接指定绝对路径，也可以使用相对于当前工作目录的路径。建议从项目根目录运行 `run.sh` / `run.ps1`。

## 9. 模型缓存

本机运行时默认缓存到项目的 `model-cache/`，Docker 运行时沿用 Compose 中的 `/root/.cache/torch` 挂载。首次运行需要下载 Demucs 模型，之后复用缓存。不要把模型缓存目录提交到 Git。

## 10. 资源与性能建议

- M4 Mac mini 首次本机运行建议先保持 `OMP_NUM_THREADS=4`、`MKL_NUM_THREADS=4`，再按温度和速度测试调整。
- 本机运行没有 Docker 的 `cpus` / `mem_limit` 配额；线程环境变量是计算库的线程提示，不等同于严格 CPU 限制。
- 对长视频优先保留 `--chunk-seconds 300`、`--segment 5` 作为基准；若遇到内存不足，可尝试将 `--chunk-seconds` 调低到 180 或 120。
- CPU-only 人声分离可能比视频播放时长慢很多，处理期间 CPU 长时间高负载属于预期现象。

## 11. 故障排查

### 找不到 ffmpeg / ffprobe

安装 FFmpeg，并确认两个可执行文件都在 PATH 中。重新打开终端后执行 `ffmpeg -version`、`ffprobe -version` 验证。

### PyTorch / Demucs 安装失败

确认当前终端使用的是项目虚拟环境：

macOS / Linux：

```bash
.venv/bin/python -m pip --version
```

Windows：

```powershell
.\.venv\Scripts\python.exe -m pip --version
```

如果依赖安装中断，可在虚拟环境中重新运行对应平台的安装脚本。不要将 Docker 的 Linux CPU wheel 安装到 macOS 虚拟环境。

### 模型首次下载失败

检查网络连接和模型缓存目录写入权限。下载完成后模型会缓存在 `model-cache/`（本机）或 Docker 挂载缓存中。

### 某个视频转换失败

批量模式会继续处理下一个视频，并在末尾打印失败清单。检查报错中的 FFmpeg / Demucs 命令和输入文件。失败任务的临时目录会在 Python 正常退出或捕获异常后自动清理；如果系统强制杀进程或断电，可能残留 `data/work/video-mixer-*` 目录，可在确认没有任务运行后手动删除。

### 输出文件已存在但不完整

默认只根据目标路径是否存在来跳过，不会自动检测文件完整性。删除该文件或使用 `--overwrite` 重新生成。

## 12. 注意事项

- AI 人声分离无法保证 100% 去除原背景音乐，也可能损失部分人声或伴奏细节。
- 当前分段方案直接拼接人声片段，未对片段边界做重叠交叉淡化，接缝处可能出现轻微音色变化。
- 输出统一为 MP4。视频流直接复制，因此个别特殊编码的视频流即使封装为 MP4，也可能存在播放器兼容性问题。
- 当前程序要求输入视频包含至少一条音轨；没有音轨的视频无法执行人声分离。
- 本机运行与 Docker 运行使用同一份 `main.py`，但 PyTorch wheel、FFmpeg 和系统路径由各自环境负责。PyTorch 安装命令和支持的 Python / OS 版本可能随官方发行版变化，安装前可查看 [PyTorch 本地安装说明](https://pytorch.org/get-started/locally/)；Demucs 项目也提供了 [Windows、macOS、Linux 平台说明](https://github.com/facebookresearch/demucs)。
