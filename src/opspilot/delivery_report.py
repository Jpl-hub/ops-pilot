from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any
import json

from opspilot.application.services import OpsPilotService
from opspilot.config import get_settings
from opspilot.infra.repository_factory import build_repository


def build_delivery_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['app_name']} 运行周报",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 环境：{report['env']}",
        f"- 主评估周期：{report['preferred_period'] or '-'}",
        f"- 总体状态：{report['overall_label']}",
        "",
        "## 执行摘要",
    ]
    lines.extend(f"- {item}" for item in report.get("executive_summary", []))
    lines.extend(
        [
            "",
            "## 运行概况",
            f"- 公司池：{report['summary_cards']['pool_companies']} 家",
            f"- 稳定可用：{report['summary_cards']['ready_company_count']} 家",
            f"- 待治理：{report['summary_cards']['blocked_company_count']} 家",
            f"- 运行阻断：{report['summary_cards']['runtime_blocked_count']} 项",
            f"- 关键检查通过：{report['summary_cards']['acceptance_passed']}/{report['summary_cards']['acceptance_total']}",
            "",
            "## 系统就绪度",
            f"- 当前阶段：{report['delivery_readiness']['stage_label']}",
            f"- 主周期覆盖：{report['delivery_readiness']['coverage_ratio']}%",
            f"- 银层就绪：{report['delivery_readiness']['silver_ratio']}%",
            f"- 研报就绪：{report['delivery_readiness']['research_ratio']}%",
            f"- OCR Contract：{report['delivery_readiness']['contract_ratio']}%",
            "",
            "## 智能体执行审计",
            f"- 审计状态：{report['workspace_runtime_audit']['label']}",
            f"- 审计窗口：{report['workspace_runtime_audit']['window_size']} 条",
            f"- 强支撑占比：{report['workspace_runtime_audit']['summary_cards']['grounded_ratio']}%",
            f"- 完整轨迹占比：{report['workspace_runtime_audit']['summary_cards']['trace_ratio']}%",
            f"- 平均执行耗时：{report['workspace_runtime_audit']['summary_cards']['avg_execution_ms'] or '-'} ms",
            "",
            "## 运行阻断",
        ]
    )
    blocked_checks = report["runtime_readiness"].get("blocked_checks", [])
    if blocked_checks:
        lines.extend(
            f"- {item['label']}：{item['summary']} 修复动作：{item.get('remediation') or '无'}"
            for item in blocked_checks
        )
    else:
        lines.append("- 无")
    lines.extend(["", "## 关键检查阻断"])
    blocked_items = report["acceptance_checklist"].get("blocked_items", [])
    if blocked_items:
        lines.extend(f"- {item['label']}：{item['detail']}" for item in blocked_items)
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "## OCR Contract",
            f"- 达标：{report['ocr_contract']['ready']}/{report['ocr_contract']['total']}",
            f"- 缺失：{report['ocr_contract']['missing']}",
            f"- 不合格：{report['ocr_contract']['invalid']}",
            "",
            "## 优先治理动作",
        ]
    )
    priority_actions = report["delivery_readiness"].get("priority_actions", [])
    if priority_actions:
        lines.extend(f"- {item['title']}：{item['summary']}" for item in priority_actions)
    else:
        lines.append("- 无")
    lines.extend(["", "## 最近治理轨迹"])
    runs = report.get("recent_remediation_runs", [])
    if runs:
        lines.extend(
            f"- {item['created_at']} {item['title']}：{item.get('headline') or '已执行'}"
            for item in runs
        )
    else:
        lines.append("- 暂无治理记录")
    lines.extend(["", "## 最近智能体样本"])
    audited_runs = report.get("workspace_runtime_audit", {}).get("recent_runs", [])
    if audited_runs:
        lines.extend(
            f"- {item['created_at']} {item['company_name'] or '-'} {item['query_type_label']}：模型 {item.get('model') or '-'}，工具 {item.get('tool_call_count', 0)} 次，轨迹 {item.get('trace_status_label')}"
            for item in audited_runs[:5]
        )
    else:
        lines.append("- 暂无智能体样本")
    return "\n".join(lines) + "\n"


def _build_service() -> OpsPilotService:
    settings = get_settings()
    return OpsPilotService(build_repository(settings), settings)


def main() -> None:
    parser = ArgumentParser(description="导出 OpsPilot-X 运行周报")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", default="", help="输出文件路径；默认直接打印到标准输出。")
    args = parser.parse_args()

    report = _build_service().delivery_report()
    content = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.format == "json"
        else build_delivery_report_markdown(report)
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        print(str(output_path))
        return
    print(content)
