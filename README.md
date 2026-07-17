# Voice2

Voice2 是一个硬件自适应、本地优先的零样本音色克隆与实时语音平台。当前版本交付可运行的 Provider 架构、硬件画像、安全预算、性能档位、本地 REST/OpenAI 兼容 API、Web 控制台、Tauri 2 Windows 桌面壳和实时会话协议骨架。

> 当前默认 `demo` Provider 只生成开发测试信号，不是语音，也不会冒充克隆效果。真实音色克隆需显式安装并启用 VoxCPM；模型权重不会提交到仓库。

## 特性

- 本地音色库：上传 5–30 秒 WAV/MP3/FLAC，强制确认声音授权。
- 原生 `POST /api/v1/speech` 与 OpenAI 风格 `POST /v1/audio/speech`。
- 自动检测 CPU、RAM、磁盘、NVIDIA GPU、空闲显存、CUDA、PyTorch 和 ONNX Runtime。
- `Auto`、`Fast`、`Quality`、`Custom` 档位与统一有界推理队列。
- Provider entry point：TTS、VAD、ASR、LLM、Speech-to-Speech、Tool 和 Transport 可独立扩展。
- 统一实时事件、turn 取消与迟到事件隔离基础。
- 默认只监听回环地址，不自动上传参考音频，不自动调用远程语音服务。

## 快速开始

要求 Python 3.11–3.13、Node.js 22.13+。真实桌面安装包还需要 Rust stable 与 Windows WebView2/构建工具。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\voice2
```

另开终端启动界面：

```powershell
npm install
npm run dev
```

打开 `http://127.0.0.1:3000`。API 文档位于 `http://127.0.0.1:8765/docs`。

## 启用 VoxCPM

VoxCPM 是可选内核，不在基础安装中下载：

```powershell
.venv\Scripts\python -m pip install -e ".[voxcpm]"
$env:VOICE2_ENABLE_VOXCPM="1"
.venv\Scripts\voice2
```

首次使用会由上游运行时下载配置的模型。可用 `VOICE2_VOXCPM_MODEL` 指定本地目录或模型 ID。下载前请确认上游模型许可证及磁盘空间；在生产使用前必须执行真实设备基准。

## 启用 CosyVoice

CosyVoice 是可选的原生音频流 Provider，使用独立 Python 3.10 进程。源码、模型、
WeText 资源必须预先下载并固定版本；Voice2 不会在生成热路径中联网。

```powershell
$env:VOICE2_COSYVOICE_PYTHON="G:\Voice2Data\envs\cosyvoice\Scripts\python.exe"
$env:VOICE2_COSYVOICE_SOURCE="G:\Voice2Data\runtimes\CosyVoice"
$env:VOICE2_COSYVOICE_MODEL="G:\Voice2Data\models\CosyVoice-300M"
$env:VOICE2_ENABLE_COSYVOICE="1"
```

“已启用”不等于“当前硬件可选择”。资源清单和当前硬件指纹下的失败基准仍会阻止
不安全变体加载。RTX 3060 Laptop 6 GiB 的当前实测超过安全显存预算，因此继续使用
OpenVoice CPU 回退。

## Windows 桌面

```powershell
npm run desktop:dev
npm run desktop:build
```

桌面壳启动时会用 `VOICE2_PYTHON`（未设置时为 `python`）启动本地后端。打包发行时应将 Python 运行时和模型安装器作为签名 sidecar 纳入发行流程；当前仓库不提交二进制运行时或模型。

## 验证

```powershell
python -m pytest
python -m ruff check .
npm run lint
npm test
python .agents/skills/integrate-realtime-provider/scripts/provider_contract.py --provider demo
```

## 文档

- [架构](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [硬件与性能](docs/PERFORMANCE.md)
- [模型评测](docs/MODEL_EVALUATION.md)
- [安全与授权](docs/SECURITY.md)
- [路线图](docs/ROADMAP.md)
- [开发环境与磁盘布局](docs/DEVELOPMENT.md)
- [Agent 规则](AGENTS.md) 与 [实施计划规则](PLANS.md)

## 许可证

项目代码采用 Apache-2.0。模型权重和第三方运行时可能采用不同许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
