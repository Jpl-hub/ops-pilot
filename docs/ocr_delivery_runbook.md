# OCR 标准部署作业书

## 目标

把 `PaddleOCR-VL-1.5` 固化为 OpsPilot-X 的标准 OCR 能力，不再把 OCR 当成可选插件。

标准分工：

- `Colab / A100`：做模型验证、环境摸底、推理可用性确认。
- `Docker / 本地或企业服务器`：做正式交付运行。

## 为什么这样分

- Colab 适合快速验证显存、依赖和模型是否能跑通。
- 企业交付必须可复现、可运维、可审计，应该收敛到 Docker。
- 项目里的管理台已经把 OCR 作为正式运行时检查项；交付环境应满足 `OCR 标准引擎 = ready`。

## 你的资源判断

当前截图显示：

- GPU：`NVIDIA A100-SXM4-40GB`
- 显存：`40GB`
- CUDA：`13.0`

这套资源足够做 PaddleOCR-VL 标准链路验证。先用 Colab/A100 跑通，再把模型资产落到交付机的 `models/paddleocr-vl`。

## Colab 标准作业

### 1. 切 GPU

- 打开 Colab。
- 进入 `Runtime -> Change runtime type`。
- `Hardware accelerator` 选择 `GPU`。

### 2. 拉代码

```bash
!git clone https://github.com/PaddlePaddle/PaddleOCR.git
%cd PaddleOCR
```

### 3. 安装依赖

先按 PaddleOCR 官方文档使用其推荐安装方式，不要自己混装。

### 4. 跑最小验证

验证目标不是追求极致性能，而是确认三件事：

- 模型能加载
- 文档页能正常输出结构
- 表格/印章/图表不会在连续推理时出错

建议先拿 1 份赛题 PDF 做验证，保留输出样例。

### 5. 固化输出

你最终要带回本项目的，不是 Colab 环境本身，而是：

- 采用的 OCR 版本
- 依赖版本
- 模型资产目录
- 一组可复现的验证样例

## Docker 交付标准

项目当前 Docker 已支持以下 OCR 配置项：

- `OPS_PILOT_OCR_PROVIDER`
- `OPS_PILOT_OCR_MODEL`
- `OPS_PILOT_OCR_ASSETS_PATH`
- `OPS_PILOT_OCR_RUNTIME_ENABLED`

推荐交付配置：

```env
OPS_PILOT_OCR_PROVIDER=PaddleOCR-VL
OPS_PILOT_OCR_MODEL=PaddleOCR-VL-1.5
OPS_PILOT_OCR_ASSETS_PATH=models/paddleocr-vl
OPS_PILOT_OCR_RUNTIME_ENABLED=true
```

推荐目录：

```text
models/
└── paddleocr-vl/
```

启动：

```bash
docker compose up -d postgres api ui
```

验收：

1. 打开管理台。
2. 查看“运行时检查”。
3. 确认 `OCR 标准引擎` 为 `ready`。
4. 触发文档升级流水，确认 `cell_trace` 可稳定完成。

## 当前项目推进建议

下一阶段不要再讨论“要不要 OCR”，只做三件事：

1. 选定正式 OCR 版本并冻结。
2. 在 Docker 交付链路里把模型资产落盘。
3. 把真实 OCR 输出接入 `cell_trace` 生产链，而不是只用页块几何恢复。

## 你接下来只需要准备的资源

1. 你是否允许我把正式标准定为 `PaddleOCR-VL-1.5`。
2. Colab 里是否可以联网安装依赖并下载模型。
3. 交付机上模型目录准备放在哪里；如果没有特别要求，就用 `models/paddleocr-vl`。
