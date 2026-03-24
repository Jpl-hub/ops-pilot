# Colab 快速验证

## 目标

用你的 Colab A100 资源，最小成本验证 `PaddleOCR-VL-1.5` 是否能在真实 PDF 上跑通。

这一步只做验证，不做正式交付。正式交付仍然走 Docker。

## 第一步：打开 GPU

1. 打开 Colab。
2. 进入 `Runtime -> Change runtime type`。
3. `Hardware accelerator` 选 `GPU`。

## 第二步：上传项目或拉代码

最简单做法：

```python
!git clone <你的仓库地址>
%cd ops-pilot
```

如果你暂时不想配置仓库，也可以直接把这两个文件上传到 Colab：

- [colab_verify_paddleocr_vl.py](/D:/code/ops-pilot/scripts/colab_verify_paddleocr_vl.py)
- [ocr_delivery_runbook.md](/D:/code/ops-pilot/docs/ocr_delivery_runbook.md)

## 第三步：上传一份 PDF

建议先传 1 份赛题里的真实年报或季报 PDF，不要拿图片截图冒充。

假设你上传后的路径是：

```text
/content/sample_report.pdf
```

## 第四步：运行最小验证

```python
!python scripts/colab_verify_paddleocr_vl.py \
  --pdf /content/sample_report.pdf \
  --output-dir /content/ocr_verify \
  --install
```

验证输出会落到：

```text
/content/ocr_verify/
├── verify_meta.json
└── verify_result.json
```

## 第五步：看结果

看 `verify_result.json` 里三件事：

1. `status` 是否为 `ok`
2. `page_count` 是否大于 0
3. `preview` 是否包含真实结构输出，而不是空内容或报错

## 第六步：把结论带回项目

你验证通过后，正式交付环境要配置：

```env
OPS_PILOT_OCR_PROVIDER=PaddleOCR-VL
OPS_PILOT_OCR_MODEL=PaddleOCR-VL-1.5
OPS_PILOT_OCR_ASSETS_PATH=models/paddleocr-vl
OPS_PILOT_OCR_RUNTIME_ENABLED=true
```

然后走：

```bash
docker compose up -d postgres api ui
```

## 你不熟 Colab 时最小操作法

你只需要做三件事：

1. 打开 GPU
2. 上传 PDF
3. 粘贴运行上面的命令

跑完以后，把 `verify_result.json` 发给我，我就继续帮你把正式 OCR 接进项目主链路。
