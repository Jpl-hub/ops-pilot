from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import requests

from opspilot.config import Settings


TABLE_HEADER_TERMS = (
    "项目",
    "本报告期",
    "上年同期",
    "年初至报告期末",
    "期末余额",
    "期初余额",
    "增减",
    "变动",
    "单位",
    "币种",
    "合并资产负债表",
    "合并利润表",
    "合并现金流量表",
    "续表",
)
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")


class DocumentPipelineBlockedError(RuntimeError):
    pass


def _settings_ocr_runtime(settings: Settings) -> dict[str, Any]:
    runtime_mode = str(getattr(settings, "ocr_runtime_mode", "local_assets") or "local_assets").strip().lower()
    if runtime_mode not in {"service", "local_assets"}:
        runtime_mode = "local_assets"
    return {
        "provider": getattr(settings, "ocr_provider", "PaddleOCR-VL"),
        "model": getattr(settings, "ocr_model", "PaddleOCR-VL-1.5"),
        "mode": runtime_mode,
        "service_url": str(getattr(settings, "ocr_service_url", "") or "").strip().rstrip("/"),
        "request_timeout_seconds": float(getattr(settings, "ocr_request_timeout_seconds", 120.0)),
        "assets_path": str(getattr(settings, "ocr_assets_path", Path("models/paddleocr-vl"))),
        "runtime_enabled": getattr(settings, "ocr_runtime_enabled", False),
        "layout_engine": getattr(settings, "doc_layout_engine", "PP-DocLayout-V3 + PyMuPDF"),
    }


def _run_document_pipeline_job(
    stage: str, job: dict[str, Any], settings: Settings
) -> tuple[dict[str, Any], Path]:
    page_json_path = Path(str(job["page_json_path"]).replace("\\", "/"))
    if not page_json_path.is_absolute():
        page_json_path = (Path.cwd() / page_json_path).resolve()
    with page_json_path.open("r", encoding="utf-8") as file:
        page_payload = json.load(file)

    if stage == "cross_page_merge":
        artifact_payload = _build_cross_page_merge_artifact(job, page_payload)
    elif stage == "title_hierarchy":
        artifact_payload = _build_title_hierarchy_artifact(job, page_payload)
    else:
        artifact_payload = _build_cell_trace_artifact(job, page_payload, settings=settings)
    artifact_path = _document_pipeline_artifact_path(settings, stage, job)
    _write_json(artifact_path, artifact_payload)
    return artifact_payload, artifact_path


def _build_cross_page_merge_artifact(job: dict[str, Any], page_payload: dict[str, Any]) -> dict[str, Any]:
    pages = page_payload.get("pages", [])
    candidates: list[dict[str, Any]] = []
    for previous_page, current_page in zip(pages, pages[1:]):
        tail_text = _last_meaningful_block_text(previous_page.get("blocks", []))
        head_text = _first_meaningful_block_text(current_page.get("blocks", []))
        if not tail_text or not head_text:
            continue
        if _looks_like_cross_page_continuation(tail_text, head_text):
            candidates.append(
                {
                    "from_page": previous_page.get("page"),
                    "to_page": current_page.get("page"),
                    "tail_text": tail_text,
                    "head_text": head_text,
                    "reason": "页尾未闭合且下一页延续正文/表格。",
                }
            )
    return {
        "report_id": job["report_id"],
        "company_name": job["company_name"],
        "summary": f"识别出 {len(candidates)} 组跨页续写候选。",
        "merge_candidates": candidates,
    }


def _build_title_hierarchy_artifact(job: dict[str, Any], page_payload: dict[str, Any]) -> dict[str, Any]:
    headings: list[dict[str, Any]] = []
    for page in page_payload.get("pages", []):
        for block in page.get("blocks", []):
            text = (block.get("text") or "").strip()
            level = _infer_heading_level(text)
            if level is None:
                continue
            headings.append(
                {
                    "page": page.get("page"),
                    "text": text,
                    "level": level,
                    "bbox": block.get("bbox"),
                }
            )
    return {
        "report_id": job["report_id"],
        "company_name": job["company_name"],
        "summary": f"恢复出 {len(headings)} 个标题节点。",
        "headings": headings,
    }


def _build_cell_trace_artifact(
    job: dict[str, Any], page_payload: dict[str, Any], *, settings: Settings
) -> dict[str, Any]:
    if ocr_payload := _load_standard_ocr_cell_trace(job, settings):
        return ocr_payload
    if ocr_payload := _materialize_standard_ocr_cell_trace(job, settings):
        return ocr_payload
    raise DocumentPipelineBlockedError("标准 OCR 结果未接通，cell_trace 已阻断。")


def _document_pipeline_artifact_path(settings: Settings, stage: str, record: dict[str, Any]) -> Path:
    security_code = record.get("security_code", "unknown")
    report_id = record.get("report_id", "unknown")
    return settings.bronze_data_path / "upgrades" / stage / security_code / f"{report_id}.json"


def _standard_ocr_artifact_path(settings: Settings, record: dict[str, Any]) -> Path:
    security_code = record.get("security_code", "unknown")
    report_id = record.get("report_id", "unknown")
    return settings.bronze_data_path / "upgrades" / "ocr_cell_trace" / security_code / f"{report_id}.json"


def _resolve_report_source_path(settings: Settings, value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(str(value).replace("\\", "/"))
    if candidate.is_absolute():
        return candidate if candidate.exists() else None

    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    project_root = getattr(settings, "official_data_path", None)
    if project_root is not None:
        project_root_path = Path(project_root)
        if len(project_root_path.parents) >= 3:
            root_candidate = (project_root_path.parents[2] / candidate).resolve()
            if root_candidate.exists():
                return root_candidate
    return None


def _load_parsed_periodic_report_record(settings: Settings, report_id: str) -> dict[str, Any] | None:
    path = settings.bronze_data_path / "manifests" / "parsed_periodic_reports_manifest.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError:
        return None
    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return None
    return next((item for item in records if item.get("report_id") == report_id), None)


def _resolve_source_document_path(settings: Settings, job: dict[str, Any]) -> Path | None:
    report = _load_parsed_periodic_report_record(settings, str(job.get("report_id") or ""))
    if report is None:
        return None
    for key in ("file_path", "local_path", "source_path"):
        resolved = _resolve_report_source_path(settings, report.get(key))
        if resolved is not None:
            return resolved
    return None


def _clean_markdown_context_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^\s*[#>\-\*\u2022]+\s*", "", cleaned)
    cleaned = re.sub(r"^\s*\d+[\.\)]\s*", "", cleaned)
    return cleaned.strip()


def _looks_like_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.count("|") >= 2 and not MARKDOWN_TABLE_SEPARATOR_RE.match(stripped)


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    if not stripped:
        return []
    return [part.replace("\\|", "|").strip() for part in re.split(r"(?<!\\)\|", stripped)]


def _infer_markdown_table_title(lines: list[str], table_start: int, *, page: int, index: int) -> str:
    for cursor in range(table_start - 1, max(-1, table_start - 6), -1):
        if cursor < 0:
            break
        candidate = _clean_markdown_context_line(lines[cursor])
        if not candidate:
            continue
        if _looks_like_markdown_table_row(candidate) or MARKDOWN_TABLE_SEPARATOR_RE.match(candidate):
            continue
        return candidate
    return f"表格 P{page}-{index:02d}"


def _extract_tables_from_markdown(
    markdown_text: str, *, page: int, report_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines = markdown_text.splitlines()
    tables: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    cursor = 0
    table_index = 0
    while cursor < len(lines):
        if cursor + 1 >= len(lines):
            break
        current = lines[cursor].rstrip()
        separator = lines[cursor + 1].rstrip()
        if not _looks_like_markdown_table_row(current) or not MARKDOWN_TABLE_SEPARATOR_RE.match(separator.strip()):
            cursor += 1
            continue
        header = _split_markdown_table_row(current)
        body_rows: list[list[str]] = []
        cursor += 2
        while cursor < len(lines) and _looks_like_markdown_table_row(lines[cursor]):
            body_rows.append(_split_markdown_table_row(lines[cursor]))
            cursor += 1
        rows = [header, *body_rows]
        if not rows or max((len(row) for row in rows), default=0) < 2:
            continue
        table_index += 1
        table_id = f"{report_id}-p{page}-ocr{table_index:02d}"
        title = _infer_markdown_table_title(lines, cursor - len(body_rows) - 2, page=page, index=table_index)
        column_count = max(len(row) for row in rows)
        tables.append(
            {
                "table_id": table_id,
                "page": page,
                "title": title,
                "continued": "续表" in title,
                "row_count": len(rows),
                "column_count": column_count,
                "bbox": None,
                "header_rows": 1,
            }
        )
        for row_index, row in enumerate(rows, start=1):
            for column_index, text in enumerate(row, start=1):
                cells.append(
                    {
                        "table_id": table_id,
                        "page": page,
                        "row_index": row_index,
                        "column_index": column_index,
                        "text": text,
                        "bbox": None,
                        "kind": "header" if row_index == 1 else "cell",
                        "source_block_indexes": [],
                    }
                )
    return tables, cells


def _build_standard_ocr_contract_from_layout_pages(
    job: dict[str, Any], layout_pages: list[dict[str, Any]]
) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for page_index, item in enumerate(layout_pages, start=1):
        markdown_text = (
            item.get("markdown_text")
            or ((item.get("markdown") or {}).get("text") if isinstance(item.get("markdown"), dict) else "")
            or ""
        )
        page_tables, page_cells = _extract_tables_from_markdown(
            markdown_text,
            page=page_index,
            report_id=job["report_id"],
        )
        tables.extend(page_tables)
        cells.extend(page_cells)
    return {
        "report_id": job["report_id"],
        "company_name": job["company_name"],
        "source": "standard_ocr",
        "summary": f"标准 OCR 服务输出 {len(tables)} 个表格片段、{len(cells)} 个单元格。",
        "tables": tables,
        "cells": cells,
    }


def _fetch_standard_ocr_layout_pages(source_path: Path, *, settings: Settings) -> list[dict[str, Any]]:
    ocr_runtime = _settings_ocr_runtime(settings)
    service_url = ocr_runtime["service_url"]
    if not service_url:
        raise RuntimeError("未配置 OPS_PILOT_OCR_SERVICE_URL，无法调用标准 OCR 服务。")
    suffix = source_path.suffix.lower()
    payload = {
        "file": base64.b64encode(source_path.read_bytes()).decode("utf-8"),
        "fileType": 0 if suffix == ".pdf" else 1,
    }
    response = requests.post(
        f"{service_url}/layout-parsing",
        json=payload,
        timeout=ocr_runtime["request_timeout_seconds"],
    )
    response.raise_for_status()
    data = response.json()
    layout_pages = data.get("result", {}).get("layoutParsingResults")
    if not isinstance(layout_pages, list):
        raise RuntimeError("标准 OCR 服务返回缺少 layoutParsingResults。")
    return layout_pages


def _materialize_standard_ocr_cell_trace(job: dict[str, Any], settings: Settings) -> dict[str, Any] | None:
    ocr_runtime = _settings_ocr_runtime(settings)
    if not ocr_runtime["runtime_enabled"] or ocr_runtime["mode"] != "service":
        return None
    source_path = _resolve_source_document_path(settings, job)
    if source_path is None:
        raise RuntimeError(f"未找到原始财报文件：{job.get('report_id')}")
    layout_pages = _fetch_standard_ocr_layout_pages(source_path, settings=settings)
    payload = _build_standard_ocr_contract_from_layout_pages(job, layout_pages)
    artifact_path = _standard_ocr_artifact_path(settings, job)
    _write_json(artifact_path, payload)
    return {
        **payload,
        "ocr_artifact_path": str(artifact_path),
    }


def _load_standard_ocr_cell_trace(settings_record: dict[str, Any], settings: Settings) -> dict[str, Any] | None:
    artifact_path = _standard_ocr_artifact_path(settings, settings_record)
    if not artifact_path.exists():
        return None
    try:
        with artifact_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError:
        return None
    tables = payload.get("tables")
    cells = payload.get("cells")
    if not isinstance(tables, list) or not isinstance(cells, list):
        return None
    if not _is_valid_standard_ocr_tables(tables) or not _is_valid_standard_ocr_cells(cells):
        return None
    return {
        "report_id": settings_record["report_id"],
        "company_name": settings_record["company_name"],
        "source": "standard_ocr",
        "summary": payload.get("summary")
        or f"读取标准 OCR 结构输出，获得 {len(tables)} 个表格片段、{len(cells)} 个单元格。",
        "tables": tables,
        "cells": cells,
        "ocr_artifact_path": str(artifact_path),
    }


def _is_valid_standard_ocr_tables(tables: list[Any]) -> bool:
    for item in tables:
        if not isinstance(item, dict):
            return False
        if not item.get("table_id"):
            return False
        if not isinstance(item.get("page"), int):
            return False
        if not item.get("title"):
            return False
    return True


def _is_valid_standard_ocr_cells(cells: list[Any]) -> bool:
    for item in cells:
        if not isinstance(item, dict):
            return False
        if not item.get("table_id"):
            return False
        if not isinstance(item.get("page"), int):
            return False
        if not isinstance(item.get("row_index"), int):
            return False
        if not isinstance(item.get("column_index"), int):
            return False
        if not isinstance(item.get("text"), str):
            return False
    return True


def _extract_page_table_traces(page: dict[str, Any]) -> list[dict[str, Any]]:
    lines = _group_blocks_into_lines(page.get("blocks", []))
    tables: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(lines):
        first_cells = _parse_line_cells(lines[cursor])
        if not _is_table_like_line(lines[cursor], first_cells):
            cursor += 1
            continue
        start = cursor
        rows: list[dict[str, Any]] = []
        while cursor < len(lines):
            parsed_cells = _parse_line_cells(lines[cursor])
            if not _is_table_like_line(lines[cursor], parsed_cells):
                break
            rows.append(
                {
                    "row_index": len(rows) + 1,
                    "bbox": _merge_bboxes([cell["bbox"] for cell in parsed_cells]),
                    "cells": parsed_cells,
                }
            )
            cursor += 1
        max_columns = max((len(row["cells"]) for row in rows), default=0)
        if len(rows) >= 2 and max_columns >= 2:
            table_title = _infer_table_title(lines, start)
            tables.append(
                {
                    "title": table_title,
                    "continued": "续表" in table_title,
                    "column_count": max_columns,
                    "header_rows": _count_header_rows(rows),
                    "rows": rows,
                    "bbox": _merge_bboxes([row["bbox"] for row in rows]),
                }
            )
    return tables


def _group_blocks_into_lines(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        text = (block.get("text") or "").strip()
        if not text:
            continue
        bbox = block.get("bbox") or [
            0.0,
            float(index) * 14.0,
            max(1.0, float(len(text))),
            float(index) * 14.0 + 10.0,
        ]
        normalized.append(
            {
                "block_index": block.get("block_index", index),
                "text": text,
                "bbox": [float(value) for value in bbox],
            }
        )
    normalized.sort(
        key=lambda item: (
            round((item["bbox"][1] + item["bbox"][3]) / 2, 1),
            round(item["bbox"][0], 1),
        )
    )

    lines: list[dict[str, Any]] = []
    for block in normalized:
        center_y = (block["bbox"][1] + block["bbox"][3]) / 2
        if lines and abs(lines[-1]["center_y"] - center_y) <= 8.0:
            lines[-1]["blocks"].append(block)
            lines[-1]["center_y"] = (lines[-1]["center_y"] + center_y) / 2
            continue
        lines.append({"center_y": center_y, "blocks": [block]})

    for line in lines:
        line["blocks"].sort(key=lambda item: item["bbox"][0])
        line["text"] = " ".join(block["text"] for block in line["blocks"])
        line["bbox"] = _merge_bboxes([block["bbox"] for block in line["blocks"]])
    return lines


def _parse_line_cells(line: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = line.get("blocks", [])
    if len(blocks) >= 2:
        return [
            {
                "column_index": index + 1,
                "text": block["text"],
                "bbox": block["bbox"],
                "kind": "value" if _contains_numeric(block["text"]) else "header",
                "source_block_indexes": [block["block_index"]],
            }
            for index, block in enumerate(blocks)
        ]

    text = (line.get("text") or "").strip()
    tokens = _split_table_tokens(text)
    if len(tokens) < 2:
        return []
    bbox = line.get("bbox") or [0.0, 0.0, float(len(text)), 10.0]
    width = max(float(bbox[2]) - float(bbox[0]), 1.0)
    total_chars = sum(max(len(token), 1) for token in tokens)
    cursor_x = float(bbox[0])
    source_index = blocks[0]["block_index"] if blocks else 0
    cells: list[dict[str, Any]] = []
    for index, token in enumerate(tokens):
        token_width = width * max(len(token), 1) / total_chars
        cells.append(
            {
                "column_index": index + 1,
                "text": token,
                "bbox": [cursor_x, float(bbox[1]), cursor_x + token_width, float(bbox[3])],
                "kind": "value" if _contains_numeric(token) else "header",
                "source_block_indexes": [source_index],
            }
        )
        cursor_x += token_width
    return cells


def _split_table_tokens(text: str) -> list[str]:
    parts = [part.strip() for part in text.split(" ") if part.strip()]
    if len(parts) < 2:
        return [text]
    numeric_parts = [part for part in parts if _contains_numeric(part)]
    if len(numeric_parts) >= 2:
        label: list[str] = []
        values: list[str] = []
        numeric_started = False
        for part in parts:
            if _contains_numeric(part):
                numeric_started = True
                values.append(part)
            elif numeric_started:
                values.append(part)
            else:
                label.append(part)
        tokens: list[str] = []
        if label:
            tokens.append(" ".join(label))
        tokens.extend(values)
        return tokens if len(tokens) >= 2 else [text]
    if len(parts) <= 6 and any(term in text for term in TABLE_HEADER_TERMS):
        return parts
    return [text]


def _is_table_like_line(line: dict[str, Any], cells: list[dict[str, Any]]) -> bool:
    text = (line.get("text") or "").strip()
    if not text or _infer_heading_level(text) is not None or len(cells) < 2:
        return False
    numeric_count = sum(1 for cell in cells if _contains_numeric(cell["text"]))
    if numeric_count >= 2:
        return True
    return any(term in text for term in TABLE_HEADER_TERMS)


def _infer_table_title(lines: list[dict[str, Any]], start_index: int) -> str:
    for offset in range(1, 4):
        candidate_index = start_index - offset
        if candidate_index < 0:
            break
        candidate_text = (lines[candidate_index].get("text") or "").strip()
        if not candidate_text:
            continue
        if _infer_heading_level(candidate_text) is not None:
            return candidate_text
        if any(term in candidate_text for term in ("单位", "币种")):
            continue
        return candidate_text[:48]
    return "未命名表格片段"


def _count_header_rows(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows[:3]:
        numeric_count = sum(1 for cell in row["cells"] if cell["kind"] == "value")
        if numeric_count <= max(1, len(row["cells"]) // 2):
            count += 1
        else:
            break
    return count


def _merge_bboxes(bboxes: list[list[float] | tuple[float, float, float, float]]) -> list[float]:
    if not bboxes:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        min(float(bbox[0]) for bbox in bboxes),
        min(float(bbox[1]) for bbox in bboxes),
        max(float(bbox[2]) for bbox in bboxes),
        max(float(bbox[3]) for bbox in bboxes),
    ]


def _contains_numeric(text: str) -> bool:
    return bool(re.search(r"[0-9]", text))


def _last_meaningful_block_text(blocks: list[dict[str, Any]]) -> str | None:
    for block in reversed(blocks):
        text = (block.get("text") or "").strip()
        if len(text) >= 8 and "证券代码" not in text and "第 " not in text:
            return text
    return None


def _first_meaningful_block_text(blocks: list[dict[str, Any]]) -> str | None:
    for block in blocks:
        text = (block.get("text") or "").strip()
        if len(text) >= 8 and "证券代码" not in text and "第 " not in text:
            return text
    return None


def _looks_like_cross_page_continuation(tail_text: str, head_text: str) -> bool:
    if tail_text.endswith(("。", "；", "：", "！", "？")):
        return False
    if head_text.startswith(("（", "公司", "本报告", "其中", "以及", "并", "的")):
        return True
    if tail_text.endswith(("、", "及", "与", "和", "为", "在", "是")):
        return True
    return bool(re.match(r"^[0-9一二三四五六七八九十]+", head_text))


def _infer_heading_level(text: str) -> int | None:
    if re.match(r"^第[一二三四五六七八九十0-9]+节", text):
        return 1
    if re.match(r"^[一二三四五六七八九十]+、", text):
        return 2
    if re.match(r"^（[一二三四五六七八九十0-9]+）", text):
        return 3
    if re.match(r"^[0-9]+(\.[0-9]+)*\s*", text):
        return 4
    if text in {"重要内容提示", "主要财务数据", "财务报表"}:
        return 2
    return None


def _normalize_report_period(title: str) -> str | None:
    match = re.search(r"(20\d{2})", title)
    if not match:
        return None
    year = match.group(1)
    if "三季度" in title:
        return f"{year}Q3"
    if "半年度" in title or "中报" in title:
        return f"{year}H1"
    if "年度报告" in title or "年报" in title:
        return f"{year}FY"
    if "一季度" in title:
        return f"{year}Q1"
    return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
