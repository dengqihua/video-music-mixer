# AI 视频人声分离与背景音乐批量合成工具

本项目使用 **Python + Docker + Demucs + FFmpeg**，在本地 CPU 环境中处理视频：尽量保留原视频中的人声，分离原背景音乐，再混入指定的 MP3 背景音乐，最终输出 MP4。

项目针对 Apple Silicon Mac mini（例如 16GB 统一内存）做了偏保守的 CPU / 内存配置。无需 NVIDIA GPU，也不使用 CUDA。

## 1. 功能

- **批量转换**：将多个视频放入 `data/input/`，运行一次命令后按文件名顺序逐个处理。
- **自动跳过**：如果 `data/output/` 中已经存在同名 MP4，默认跳过，不重复消耗计算资源。
- **单文件失败不影响队列**：某个视频处理失败会记录原因，然后继续处理下一个视频。
- **分段人声分离**：先把长音频切成小段，再逐段运行 Demucs，降低长视频推理时的峰值内存。
- **自动清理**：每个视频使用独立临时工作目录。无论成功还是失败，音频切片、Demucs 中间结果、拼接清单和临时 WAV 都会在该视频任务结束后清理。
- **安全输出**：先生成 `.partial.mp4` 临时文件，检查文件可读取后再改名为正式输出，避免失败时留下看似完成的 MP4。
- **保留原视频画面**：FFmpeg 使用 `-c:v copy`，不重新编码视频流；音频重新编码为 AAC。
- **背景音乐循环**：指定 MP3 自动循环到视频结束，可设置音量和淡入淡出时间。

## 2. 处理逻辑

每个视频依次执行以下步骤：

1. 使用 `ffprobe` 检查视频流、音轨和视频时长。
2. 使用 FFmpeg 将原视频第一条音轨提取为双声道、44.1kHz、16-bit PCM WAV。
3. 将 WAV 按默认每段 300 秒（5 分钟）切片。
4. 对每个切片独立运行 Demucs：`htdemucs`、CPU 模式、`shifts=0`、模型推理窗口默认 5 秒。
5. 收集各片段的 `vocals.wav`，使用 FFmpeg concat demuxer 合并为完整人声 WAV。
6. 将人声与循环播放的背景 MP3 混音，默认背景音乐音量为 30%，淡入和淡出各 3 秒，并使用 limiter 控制峰值。
7. 将混合音轨与原视频画面封装为 MP4。视频流直接复制，音频编码为 AAC 192kbps。
8. 验证输出文件后，将临时文件原子替换为正式文件，并清理本视频的全部临时工作文件。

### 为什么采用两层分段？

- **音频文件分段（默认 300 秒）**：避免一次将整段几十分钟音频交给 Demucs，降低整段音频加载和处理带来的内存压力。
- **Demucs 模型窗口（默认 5 秒）**：控制每次模型推理处理的音频窗口，进一步降低推理阶段的峰值内存。

分段拼接可能在边界处出现轻微音色变化或接缝。当前版本优先保证内存稳定和处理流程可靠，未对分段边界做重叠交叉淡化。

## 3. 项目目录

```text
video-music-mixer/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── main.py
├── README.MD
├── .dockerignore
├── model-cache/                 # Demucs / PyTorch 模型缓存，不必每次重新下载
└── data/
    ├── background_music.mp3     # 默认背景音乐，可替换为自己的 MP3
    ├── input/                   # 待处理视频放这里
    ├── output/                  # 转换完成的视频
    └── work/                    # 运行时临时目录；每个任务结束自动清理
```

`data/work/` 不需要手工创建。程序会自动创建，并在每个视频任务结束后删除对应临时目录。

## 4. 环境要求

- Docker Desktop（Mac 建议使用 Apple Silicon 对应版本）。
- Apple Silicon Mac 可使用 CPU 模式运行；无需 NVIDIA GPU。
- 建议 Mac mini 16GB 内存时，将 Docker Desktop Memory 设为约 8GB，给 macOS 和其他程序留出余量。
- Compose 默认限制容器使用 4 个 CPU 和 7GB 内存。若 Mac 同时运行其他高内存程序，可将 `docker-compose.yml` 中的 `mem_limit` 下调到 `6g`。
- 首次构建需要下载 PyTorch、Demucs 及模型文件；模型缓存保存在 `model-cache/`。

> 实际处理速度取决于 Mac 芯片型号、视频时长和音频内容。纯 CPU 分离可能明显慢于视频本身的播放时长。

## 5. 首次启动

在项目根目录执行：

```bash
docker compose build
```

检查依赖是否正常：

```bash
docker compose run --rm --entrypoint python video-mixer -c \
"import numpy, torch, demucs, sphn; print('NumPy:', numpy.__version__); print('PyTorch:', torch.__version__); print('Demucs OK'); print('Sphn OK'); print('CUDA:', torch.cuda.is_available())"
```

CPU 环境显示 `CUDA: False` 是正常的。

## 6. 批量转换（默认用法）

### 第一步：放入视频

将待处理的视频放入：

```text
data/input/
```

支持扩展名：`.mp4`、`.mov`、`.mkv`、`.avi`、`.m4v`、`.webm`、`.mpeg`、`.mpg`。

程序只扫描 `data/input/` 当前目录，不递归扫描子目录。

### 第二步：准备背景音乐

默认读取：

```text
data/background_music.mp3
```

可以直接替换这个文件，但请保持文件名不变；也可以通过 `--music` 指定其他 MP3 文件。

### 第三步：运行

```bash
docker compose run --rm video-mixer
```

程序会按文件名排序逐个转换，结果放在：

```text
data/output/
```

例如：

```text
data/input/
├── movie-a.mp4
└── movie-b.mov

data/output/
├── movie-a.mp4
└── movie-b.mp4
```

输出统一为 MP4，因此输入 MOV / MKV 等格式时，输出文件使用相同主文件名和 `.mp4` 扩展名。

### 跳过规则

如果目标文件已存在，例如 `data/output/movie-a.mp4`，程序默认跳过该视频。**只要目标路径已存在就会跳过**，不会自动判断文件是否完整。

如果希望重新转换，可先手动删除对应输出文件，或使用覆盖参数：

```bash
docker compose run --rm video-mixer --overwrite
```

## 7. 常用参数

批量模式：

```bash
docker compose run --rm video-mixer \
  --input-dir /data/input \
  --output-dir /data/output \
  --music /data/background_music.mp3 \
  --music-volume 0.25 \
  --fade 3 \
  --chunk-seconds 300 \
  --segment 5
```

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--input-dir` | `/data/input` | 批量输入目录 |
| `--output-dir` | `/data/output` | 输出目录 |
| `--music` | `/data/background_music.mp3` | 背景音乐文件 |
| `--music-volume` | `0.30` | 背景音乐音量，范围 0～1 |
| `--fade` | `3` | 淡入和淡出秒数；设为 0 可关闭淡入淡出 |
| `--chunk-seconds` | `300` | 每个音频切片长度，单位秒 |
| `--segment` | `5` | Demucs 模型推理窗口，单位秒 |
| `--overwrite` | 关闭 | 覆盖已存在的输出文件，不再跳过 |

### 只转换一个视频

```bash
docker compose run --rm video-mixer \
  --video /data/input/example.mp4 \
  --output /data/output/example.mp4
```

单文件模式也支持 `--music`、`--music-volume`、`--fade`、`--chunk-seconds` 和 `--segment`。

## 8. 查看资源占用

转换期间可在另一个终端执行：

```bash
docker stats video-mixer
```

如果通过 `docker compose run --rm` 启动，容器退出后会自动删除；需要保留容器检查退出状态时，可以这样运行：

```bash
docker compose run --name video-mixer-check video-mixer
```

检查是否因内存不足被系统杀掉：

```bash
docker inspect video-mixer-check \
  --format 'OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}}'
```

检查后删除容器：

```bash
docker rm video-mixer-check
```

## 9. 故障排查

### 9.1 进程退出码为 -9 或 137

通常意味着进程被强制终止，可能与内存不足有关。建议：

1. 检查 Docker Desktop 的 Memory 分配和 `docker stats`。
2. 关闭其他占用大量内存的程序。
3. 将 `docker-compose.yml` 的 `mem_limit` 调低到 `6g`，并观察是否仍发生 OOM。
4. 将 `--chunk-seconds` 从 `300` 调低到 `180` 或 `120`。
5. 将 `--segment` 从 `5` 调低到 `4`。

### 9.2 某个视频失败

批量任务会继续处理后续视频。终端末尾会列出失败文件和错误原因。失败视频不会生成正式输出文件，其临时分段文件会自动清理；修复原因后重新运行即可。

### 9.3 输出文件已存在但怀疑不完整

默认策略按文件是否存在判断是否跳过。若文件不完整，请手动删除它，或重新运行时加 `--overwrite`。

## 10. 注意事项与限制

- AI 人声分离无法保证 100% 去除原背景音乐，也可能损失部分人声或伴奏细节；效果取决于原始混音质量。
- 背景音乐音量是线性增益参数，不是响度百分比。建议从 `0.15`～`0.30` 之间试听调整。
- 视频画面使用流复制，不进行画面重新编码；最终音频会重新编码为 AAC。
- 输出统一为 MP4。某些特殊视频编码即使封装为 MP4，也可能存在播放器兼容性差异。
- 当前分段方案按时间切片后直接拼接人声，未做片段边界交叉淡化。
- 模型首次运行时需要下载；后续会复用 `model-cache/` 中的缓存。

## 11. 常用命令速查

```bash
# 构建镜像
docker compose build

# 批量转换（自动跳过已有输出）
docker compose run --rm video-mixer

# 强制覆盖已有输出
docker compose run --rm video-mixer --overwrite

# 指定背景音乐和音量
docker compose run --rm video-mixer --music /data/custom.mp3 --music-volume 0.20

# 只转换一个视频
docker compose run --rm video-mixer --video /data/input/one.mp4 --output /data/output/one.mp4
```
