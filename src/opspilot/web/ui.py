from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote_plus

from fastapi import Request
from opspilot.api.routes import get_service


HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --op-bg: #f4efe6;
    --op-surface: rgba(255, 252, 246, 0.92);
    --op-surface-strong: #fff9f0;
    --op-ink: #1f2933;
    --op-muted: #5b6670;
    --op-border: rgba(31, 41, 51, 0.08);
    --op-accent: #0f766e;
    --op-accent-soft: #d6f2ee;
    --op-risk: #b42318;
    --op-opportunity: #1d7a4a;
    --op-shadow: 0 18px 45px rgba(31, 41, 51, 0.08);
  }

  body {
    font-family: "Space Grotesk", "Noto Sans SC", sans-serif;
    color: var(--op-ink);
    background:
      radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 32%),
      radial-gradient(circle at top right, rgba(180, 35, 24, 0.08), transparent 26%),
      linear-gradient(180deg, #f7f2e9 0%, #efe6d6 100%);
  }

  .nicegui-content {
    background: transparent;
  }

  .op-shell {
    width: min(1240px, calc(100vw - 32px));
    margin: 0 auto;
    padding: 28px 0 40px;
  }

  .op-hero,
  .op-panel,
  .op-stat-card,
  .op-mini-card {
    border: 1px solid var(--op-border);
    border-radius: 24px;
    box-shadow: var(--op-shadow);
  }

  .op-hero {
    background:
      linear-gradient(135deg, rgba(15, 118, 110, 0.95), rgba(14, 116, 144, 0.82)),
      linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0));
    color: #f5fffd;
    padding: 28px;
  }

  .op-panel,
  .op-stat-card,
  .op-mini-card {
    background: var(--op-surface);
    backdrop-filter: blur(10px);
  }

  .op-panel {
    padding: 18px;
  }

  .op-stat-card {
    min-width: 180px;
    padding: 18px;
    background: linear-gradient(180deg, var(--op-surface-strong), rgba(255, 250, 241, 0.92));
  }

  .op-mini-card {
    min-width: 280px;
    flex: 1 1 340px;
    padding: 18px;
  }

  .op-label-card {
    min-width: 280px;
    flex: 1 1 320px;
    padding: 18px;
    border: 1px solid rgba(31, 41, 51, 0.08);
    border-radius: 24px;
    background: linear-gradient(180deg, rgba(255, 251, 244, 0.96), rgba(250, 245, 236, 0.92));
    box-shadow: var(--op-shadow);
  }

  .op-kicker {
    letter-spacing: 0.14em;
    text-transform: uppercase;
    font-size: 12px;
    opacity: 0.78;
  }

  .op-title {
    font-size: 34px;
    line-height: 1.05;
    font-weight: 700;
  }

  .op-subtitle {
    font-size: 15px;
    color: var(--op-muted);
  }

  .op-hero .op-subtitle {
    color: rgba(245, 255, 253, 0.82);
  }

  .op-stat-label {
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--op-muted);
  }

  .op-stat-value {
    font-size: 30px;
    line-height: 1.1;
    font-weight: 700;
  }

  .op-stat-hint {
    font-size: 13px;
    color: var(--op-muted);
  }

  .op-section-title {
    font-size: 20px;
    font-weight: 700;
  }

  .op-formula {
    font-family: "Space Grotesk", monospace;
    background: rgba(15, 118, 110, 0.08);
    border-radius: 14px;
    padding: 10px 12px;
    font-size: 13px;
  }

  .op-detail-row {
    padding: 8px 0;
    border-bottom: 1px solid rgba(31, 41, 51, 0.06);
  }

  .op-detail-row:last-child {
    border-bottom: none;
  }

  .op-pill {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 500;
  }

  .op-pill-risk {
    background: rgba(180, 35, 24, 0.12);
    color: var(--op-risk);
  }

  .op-pill-opportunity {
    background: rgba(29, 122, 74, 0.12);
    color: var(--op-opportunity);
  }

  .op-pill-neutral {
    background: rgba(15, 118, 110, 0.12);
    color: var(--op-accent);
  }

  .op-evidence-link {
    color: var(--op-accent);
    text-decoration: none;
    font-size: 12px;
    font-weight: 500;
    padding: 4px 8px;
    border-radius: 999px;
    background: rgba(15, 118, 110, 0.08);
  }

  .op-evidence-link:hover {
    background: rgba(15, 118, 110, 0.16);
  }

  .op-evidence-excerpt {
    font-size: 13px;
    line-height: 1.55;
    color: var(--op-muted);
  }

  .op-select {
    min-width: 240px;
  }

  .op-note {
    font-size: 13px;
    color: var(--op-muted);
  }

  .op-highlight {
    background: rgba(15, 118, 110, 0.18);
    color: #0f5d56;
    padding: 0 3px;
    border-radius: 4px;
  }
 </style>
"""


def run_ui_app() -> None:
    try:
        from nicegui import ui
    except ImportError as exc:
        raise RuntimeError("未安装 nicegui，请先执行 `pip install -e .`。") from exc

    ui.add_head_html(HEAD_HTML)

    service = get_service()
    default_company = service.list_company_names()[0]
    initial_score = service.score_company(default_company)
    initial_risk = service.risk_scan()
    initial_claim_company = default_company
    initial_claim_reports: list[dict[str, Any]] = []
    initial_claim = None
    for company_name in service.list_company_names():
        try:
            initial_claim = service.verify_claim(company_name)
            initial_claim_company = company_name
            initial_claim_reports = service.list_research_reports(company_name)
            break
        except ValueError:
            continue
    if initial_claim is None:
        initial_claim = {
            "claim_cards": [],
            "report_period": initial_score["report_period"],
            "available_reports": [],
        }

    @ui.page("/")
    def landing() -> None:
        with ui.column().classes("op-shell gap-6"):
            with ui.card().classes("op-hero w-full"):
                ui.label("OpsPilot-X").classes("op-kicker")
                ui.label("新能源运营体检与证据分析平台").classes("op-title")
                ui.label(
                    "基于真实财报提供评分、风险识别、公式解释与证据追溯。"
                ).classes("op-subtitle")
                with ui.row().classes("gap-3 wrap"):
                    ui.link("进入企业体检页", "/score")
                    ui.link("进入行业风险页", "/risk")
                    ui.link("进入研报核验页", "/verify")
                    ui.link("打开证据查看器", f"/evidence/{initial_score['evidence'][0]['chunk_id']}")

            with ui.row().classes("w-full gap-4 wrap"):
                _render_stat_card(
                    ui,
                    label="默认主周期",
                    value=initial_score["report_period"],
                    hint=f"公司池 {len(service.list_company_names())} 家",
                )
                _render_stat_card(
                    ui,
                    label="风险扫描",
                    value=str(len(initial_risk["risk_board"])),
                    hint="支持行业风险横向巡检",
                )
                _render_stat_card(
                    ui,
                    label="公式回放",
                    value=str(len(initial_score.get("formula_cards", []))),
                    hint="当前展示 C3 / S3 关键公式",
                )
                _render_stat_card(
                    ui,
                    label="研报核验",
                    value=str(len(initial_claim.get("claim_cards", []))),
                    hint="最新研报中的可核验观点数",
                )

    @ui.page("/score")
    def score_page() -> None:
        with ui.column().classes("op-shell gap-6"):
            with ui.row().classes("items-end justify-between w-full gap-4 wrap"):
                with ui.column().classes("gap-1"):
                    ui.label("企业运营体检页").classes("op-section-title")
                    ui.label("真实财报评分、公式回放与证据链一体展示").classes("op-subtitle")
                with ui.row().classes("gap-3 items-center wrap"):
                    company_select = ui.select(
                        options=service.list_company_names(),
                        value=default_company,
                        label="选择公司",
                    ).classes("op-select")
                    ui.button("刷新评分", on_click=lambda: refresh()).props("unelevated color=teal-7")

            summary_section = ui.column().classes("w-full gap-4")
            label_section = ui.column().classes("w-full gap-4")
            charts_section = ui.row().classes("w-full gap-4 wrap items-stretch")
            formula_section = ui.column().classes("w-full gap-4")
            evidence_section = ui.column().classes("w-full gap-4")

            def refresh() -> None:
                payload = service.score_company(company_select.value)
                _render_score_summary(ui, summary_section, payload)
                _render_label_section(ui, label_section, payload)
                _render_charts(ui, charts_section, payload)
                _render_formula_section(ui, formula_section, payload)
                _render_evidence_section(ui, evidence_section, payload)

            refresh()

    @ui.page("/risk")
    def risk_page() -> None:
        with ui.column().classes("op-shell gap-6"):
            with ui.row().classes("items-end justify-between w-full gap-4 wrap"):
                with ui.column().classes("gap-1"):
                    ui.label("行业风险与机会大屏").classes("op-section-title")
                    ui.label("按主周期横向观察公司风险标签命中情况。").classes("op-subtitle")
                _render_stat_card(
                    ui,
                    label="高风险公司数",
                    value=str(sum(1 for item in initial_risk["risk_board"] if item["risk_count"] > 0)),
                    hint="主周期下风险标签命中数大于 0",
                )

            with ui.card().classes("op-panel w-full"):
                ui.echart(initial_risk["charts"][0]["options"]).classes("w-full").style("height: 380px;")

            with ui.row().classes("w-full gap-4 wrap items-stretch"):
                for item in initial_risk["risk_board"]:
                    with ui.card().classes("op-mini-card"):
                        ui.label(item["company_name"]).classes("text-lg font-semibold")
                        ui.label(f"风险数 {item['risk_count']}").classes("op-stat-hint")
                        with ui.row().classes("gap-2 wrap"):
                            labels = item["risk_labels"] or ["暂无高风险标签"]
                        for label in labels:
                            _render_pill(ui, label, tone="risk" if label != "暂无高风险标签" else "neutral")

    @ui.page("/verify")
    def verify_page() -> None:
        with ui.column().classes("op-shell gap-6"):
            with ui.row().classes("items-end justify-between w-full gap-4 wrap"):
                with ui.column().classes("gap-1"):
                    ui.label("研报观点核验").classes("op-section-title")
                    ui.label("把研报里的关键数字观点和真实财报指标放在一屏对照。").classes("op-subtitle")
                with ui.row().classes("gap-3 items-center wrap"):
                    company_select = ui.select(
                        options=service.list_company_names(),
                        value=initial_claim_company,
                        label="选择公司",
                    ).classes("op-select")
                    report_select = ui.select(
                        options=_build_report_options(initial_claim_reports),
                        value=initial_claim.get("report_meta", {}).get("title"),
                        label="选择研报",
                    ).classes("op-select")
                    ui.button("刷新核验", on_click=lambda: refresh()).props("unelevated color=teal-7")

            summary_section = ui.column().classes("w-full gap-4")
            evidence_section = ui.column().classes("w-full gap-4")

            def sync_report_options() -> None:
                reports = service.list_research_reports(company_select.value)
                report_select.options = _build_report_options(reports)
                report_select.value = reports[0]["title"] if reports else None
                report_select.update()

            def refresh() -> None:
                try:
                    payload = service.verify_claim(
                        company_select.value,
                        report_title=report_select.value,
                    )
                except ValueError as exc:
                    summary_section.clear()
                    evidence_section.clear()
                    with summary_section:
                        with ui.card().classes("op-panel w-full"):
                            ui.label("研报观点核验").classes("op-section-title")
                            ui.label(str(exc)).classes("op-note")
                    return
                summary_section.clear()
                with summary_section:
                    with ui.row().classes("w-full gap-4 wrap"):
                        _render_stat_card(
                            ui,
                            label="核验报期",
                            value=payload["report_period"],
                            hint=payload["company_name"],
                        )
                        _render_stat_card(
                            ui,
                            label="匹配观点",
                            value=str(next(item["value"] for item in payload["key_numbers"] if item["label"] == "匹配观点")),
                            hint=payload["report_meta"]["title"],
                        )
                        _render_stat_card(
                            ui,
                            label="偏差观点",
                            value=str(next(item["value"] for item in payload["key_numbers"] if item["label"] == "偏差观点")),
                            hint=payload["report_meta"]["publish_date"],
                        )
                        _render_stat_card(
                            ui,
                            label="投资评级",
                            value=_format_rating_text(payload["report_meta"]),
                            hint=payload["report_meta"].get("source_name") or "研报来源",
                        )
                    with ui.card().classes("op-panel w-full"):
                        ui.markdown(payload["answer_markdown"])
                    with ui.card().classes("op-panel w-full"):
                        ui.label("研报元信息").classes("op-section-title")
                        with ui.row().classes("w-full gap-4 wrap"):
                            _render_stat_card(
                                ui,
                                label="研究机构",
                                value=payload["report_meta"].get("source_name") or "未披露",
                                hint=payload["report_meta"].get("researcher") or "分析师未披露",
                            )
                            _render_stat_card(
                                ui,
                                label="原文附件",
                                value="已挂接" if payload["report_meta"].get("attachment_url") else "未挂接",
                                hint="支持跳转原始 PDF",
                            )
                        if payload["report_meta"].get("attachment_url"):
                            ui.link(
                                "打开研报附件 PDF",
                                payload["report_meta"]["attachment_url"],
                                new_tab=True,
                            ).classes("op-evidence-link")
                    with ui.card().classes("op-panel w-full"):
                        ui.label("观点对照").classes("op-section-title")
                        ui.echart(payload["charts"][0]["options"]).classes("w-full").style("height: 320px;")
                        with ui.row().classes("w-full gap-4 wrap items-stretch"):
                            for card in payload.get("claim_cards", []):
                                with ui.card().classes("op-mini-card"):
                                    ui.label(card["label"]).classes("text-lg font-semibold")
                                    tone = "neutral"
                                    if card["status"] == "match":
                                        tone = "opportunity"
                                    elif card["status"] == "mismatch":
                                        tone = "risk"
                                    _render_pill(
                                        ui,
                                        {
                                            "match": "匹配",
                                            "mismatch": "偏差",
                                            "insufficient_data": "待补充",
                                        }[card["status"]],
                                        tone=tone,
                                    )
                                    with ui.column().classes("w-full gap-0"):
                                        for label, value in (
                                            ("研报值", _format_signal_value(card["claimed_value"])),
                                            ("系统值", _format_signal_value(card["actual_value"])),
                                            ("差值", _format_signal_value(card["delta"])),
                                        ):
                                            with ui.row().classes("op-detail-row w-full items-center justify-between gap-3"):
                                                ui.label(label).classes("text-sm")
                                                ui.label(value).classes("text-sm font-medium")
                                    ui.label(card["excerpt"]).classes("op-evidence-excerpt")
                    if payload.get("forecast_cards"):
                        with ui.card().classes("op-panel w-full"):
                            ui.label("盈利预测与评级").classes("op-section-title")
                            ui.label("研报中的未来年度利润预测会单独展开，和历史实际值核验分开展示。").classes("op-note")
                            with ui.row().classes("w-full gap-4 wrap items-stretch"):
                                for card in payload["forecast_cards"]:
                                    with ui.card().classes("op-mini-card"):
                                        ui.label(card["label"]).classes("text-lg font-semibold")
                                        _render_pill(
                                            ui,
                                            _format_rating_text(
                                                {
                                                    "rating_action": card.get("rating_action"),
                                                    "rating_label": card.get("rating_label"),
                                                }
                                            ),
                                            tone="neutral",
                                        )
                                        with ui.column().classes("w-full gap-0"):
                                            for label, value in (
                                                ("预测利润", _format_forecast_value(card["forecast_value"], unit="亿元")),
                                                ("同比预测", _format_forecast_value(card.get("yoy_value"), unit="%")),
                                                ("对应 PE", _format_forecast_value(card.get("pe_value"), unit="x")),
                                            ):
                                                with ui.row().classes("op-detail-row w-full items-center justify-between gap-3"):
                                                    ui.label(label).classes("text-sm")
                                                    ui.label(value).classes("text-sm font-medium")
                                        ui.label(card["excerpt"]).classes("op-evidence-excerpt")
                _render_evidence_section(ui, evidence_section, payload)

            company_select.on_value_change(lambda _: sync_report_options())
            refresh()

    @ui.page("/evidence/{chunk_id}")
    def evidence_page(chunk_id: str, request: Request) -> None:
        evidence_item = service.get_evidence(chunk_id)
        context = request.query_params.get("context", "")
        anchors = [
            item
            for item in request.query_params.get("anchors", "").split("|")
            if item
        ]
        with ui.column().classes("op-shell gap-6"):
            with ui.card().classes("op-panel w-full"):
                ui.label("证据查看器").classes("op-section-title")
                ui.label(context or chunk_id).classes("op-subtitle")
                if context and context != chunk_id:
                    ui.label(chunk_id).classes("op-note")
                with ui.row().classes("gap-4 wrap"):
                    _render_stat_card(ui, label="来源", value=evidence_item["source_title"], hint=evidence_item["source_type"])
                    _render_stat_card(ui, label="页码", value=f"p.{evidence_item['page']}", hint=evidence_item["report_period"])
                    _render_stat_card(ui, label="公司", value=evidence_item["company_name"], hint=evidence_item["fingerprint"])
            with ui.card().classes("op-panel w-full"):
                ui.label("重点片段").classes("op-section-title")
                if anchors:
                    ui.label("已按当前上下文高亮关键词。").classes("op-note")
                ui.html(_highlight_excerpt(evidence_item["excerpt"], anchors)).classes("op-evidence-excerpt")
            with ui.card().classes("op-panel w-full"):
                ui.label("原始数据").classes("op-section-title")
                ui.json_editor({"content": {"json": evidence_item}})

    ui.run(title="OpsPilot-X", reload=False, host="0.0.0.0", port=8080)


def _render_score_summary(ui: Any, container: Any, payload: dict[str, Any]) -> None:
    container.clear()
    scorecard = payload["scorecard"]
    with container:
        with ui.row().classes("w-full gap-4 wrap"):
            _render_stat_card(
                ui,
                label="总分",
                value=f"{scorecard['total_score']} 分",
                hint=f"等级 {scorecard['grade']}",
            )
            _render_stat_card(
                ui,
                label="报告期",
                value=payload["report_period"],
                hint=payload["company_name"],
            )
            _render_stat_card(
                ui,
                label="风险标签",
                value=str(len(scorecard["risk_labels"])),
                hint="命中高风险规则数",
            )
            _render_stat_card(
                ui,
                label="机会标签",
                value=str(len(scorecard["opportunity_labels"])),
                hint="命中机会规则数",
            )

        with ui.row().classes("w-full gap-4 wrap items-stretch"):
            with ui.card().classes("op-panel grow").style("min-width: 320px;"):
                ui.label("评分摘要").classes("op-section-title")
                ui.markdown(payload["answer_markdown"])
            with ui.card().classes("op-panel grow").style("min-width: 320px;"):
                ui.label("标签面板").classes("op-section-title")
                ui.label("风险标签").classes("op-note")
                with ui.row().classes("gap-2 wrap"):
                    risk_labels = scorecard["risk_labels"] or [{"name": "暂无高风险标签"}]
                    for item in risk_labels:
                        _render_pill(ui, item["name"], tone="risk" if item["name"] != "暂无高风险标签" else "neutral")
                ui.label("机会标签").classes("op-note mt-4")
                with ui.row().classes("gap-2 wrap"):
                    opportunity_labels = scorecard["opportunity_labels"] or [{"name": "暂无显著机会标签"}]
                    for item in opportunity_labels:
                        tone = "opportunity" if item["name"] != "暂无显著机会标签" else "neutral"
                        _render_pill(ui, item["name"], tone=tone)


def _render_charts(ui: Any, container: Any, payload: dict[str, Any]) -> None:
    container.clear()
    with container:
        for chart in payload["charts"]:
            with ui.card().classes("op-panel grow").style("min-width: 360px;"):
                ui.label(chart["title"]).classes("op-section-title")
                ui.echart(chart["options"]).classes("w-full").style("height: 340px;")


def _render_label_section(ui: Any, container: Any, payload: dict[str, Any]) -> None:
    container.clear()
    with container:
        with ui.card().classes("op-panel w-full"):
            ui.label("标签拆解").classes("op-section-title")
            ui.label("把风险/机会标签、触发信号、关联指标和证据链接放在同一层查看。").classes("op-subtitle")
            label_cards = payload.get("label_cards", [])
            if not label_cards:
                ui.label("当前公司暂无标签拆解数据。").classes("op-note")
                return
            with ui.row().classes("w-full gap-4 wrap items-stretch"):
                for card in label_cards:
                    _render_label_card(ui, card)


def _render_label_card(ui: Any, card: dict[str, Any]) -> None:
    tone = "risk" if card["kind"] == "risk" else "opportunity"
    with ui.card().classes("op-label-card"):
        with ui.row().classes("w-full items-start justify-between gap-3"):
            with ui.column().classes("gap-1"):
                ui.label(f"{card['code']} {card['name']}").classes("text-lg font-semibold")
                _render_pill(ui, "风险标签" if tone == "risk" else "机会标签", tone=tone)
            if card.get("signal_values"):
                ui.label(" / ".join(_format_signal_value(value) for value in card["signal_values"])).classes("op-stat-hint")
        if card["metrics"]:
            ui.label("关联指标").classes("op-note")
            with ui.column().classes("w-full gap-0"):
                for metric in card["metrics"]:
                    metric_value = _format_signal_value(metric["value"])
                    with ui.row().classes("op-detail-row w-full items-center justify-between gap-3"):
                        ui.label(f"{metric['metric_code']} {metric['metric_name']}").classes("text-sm")
                        ui.label(metric_value).classes("text-sm font-medium")
        if card.get("formula_metric_codes"):
            ui.label(
                "关联公式回放：" + " / ".join(card["formula_metric_codes"])
            ).classes("op-note")
        if card.get("evidence_refs"):
            ui.label("证据入口").classes("op-note")
            with ui.row().classes("gap-2 wrap"):
                for chunk_id in card["evidence_refs"]:
                    ui.link(
                        chunk_id,
                        _build_evidence_href(chunk_id, f"{card['code']} {card['name']}", card.get("anchor_terms", [])),
                    ).classes("op-evidence-link")


def _render_formula_section(ui: Any, container: Any, payload: dict[str, Any]) -> None:
    container.clear()
    with container:
        with ui.card().classes("op-panel w-full"):
            ui.label("公式回放").classes("op-section-title")
            ui.label("当前值、去年同期值、核心输入项与证据入口在同一屏展示。").classes("op-subtitle")
            cards = payload.get("formula_cards", [])
            if not cards:
                ui.label("当前公司暂无可回放公式指标。").classes("op-note")
                return
            with ui.row().classes("w-full gap-4 wrap items-stretch"):
                for card in cards:
                    _render_formula_card(ui, card)


def _render_formula_card(ui: Any, card: dict[str, Any]) -> None:
    with ui.card().classes("op-mini-card"):
        with ui.row().classes("w-full items-start justify-between gap-3"):
            with ui.column().classes("gap-1"):
                ui.label(f"{card['metric_code']} {card['title']}").classes("text-lg font-semibold")
                ui.label("公式指标").classes("op-note")
            ui.label(_format_formula_value(card)).classes("op-stat-value")
        ui.label(card["formula"]).classes("op-formula")
        with ui.column().classes("w-full gap-0"):
            for detail in card["lines"]:
                label, value = _split_formula_detail(detail)
                with ui.row().classes("op-detail-row w-full items-center justify-between gap-3"):
                    ui.label(label).classes("text-sm")
                    ui.label(value).classes("text-sm font-medium")
        if card.get("evidence_refs"):
            ui.label("证据入口").classes("op-note")
            with ui.row().classes("gap-2 wrap"):
                for chunk_id in card["evidence_refs"]:
                    ui.link(
                        chunk_id,
                        _build_evidence_href(chunk_id, f"{card['metric_code']} {card['title']}", card.get("anchor_terms", [])),
                    ).classes("op-evidence-link")


def _render_evidence_section(ui: Any, container: Any, payload: dict[str, Any]) -> None:
    container.clear()
    with container:
        with ui.card().classes("op-panel w-full"):
            ui.label("证据聚焦").classes("op-section-title")
            ui.label("优先查看当前标签和公式对应的关键证据，必要时再展开完整证据包。").classes("op-subtitle")
            for group in payload["evidence_groups"]:
                with ui.card().classes("op-mini-card"):
                    ui.label(group["title"]).classes("text-lg font-semibold")
                    ui.label(group["subtitle"]).classes("op-note")
                    for item in group["items"]:
                        with ui.column().classes("w-full gap-2"):
                            with ui.row().classes("w-full items-center justify-between gap-3 wrap"):
                                ui.link(
                                    item["chunk_id"],
                                    _build_evidence_href(
                                        item["chunk_id"],
                                        group["title"],
                                        group.get("anchor_terms", []),
                                    ),
                                ).classes("op-evidence-link")
                                ui.label(f"{item['source_title']} | p.{item['page']}").classes("op-note")
                            ui.label(item["excerpt"]).classes("op-evidence-excerpt")


def _render_stat_card(ui: Any, *, label: str, value: str, hint: str) -> None:
    with ui.card().classes("op-stat-card grow"):
        ui.label(label).classes("op-stat-label")
        ui.label(value).classes("op-stat-value")
        ui.label(hint).classes("op-stat-hint")


def _render_pill(ui: Any, label: str, *, tone: str) -> None:
    tone_class = {
        "risk": "op-pill-risk",
        "opportunity": "op-pill-opportunity",
        "neutral": "op-pill-neutral",
    }[tone]
    ui.label(label).classes(f"op-pill {tone_class}")


def _split_formula_detail(detail: str) -> tuple[str, str]:
    if "：" not in detail:
        return detail, ""
    label, value = detail.split("：", 1)
    return label, value


def _format_formula_value(card: dict[str, Any]) -> str:
    value = card.get("value")
    if value is None:
        return "N/A"
    if card["metric_code"] == "C3":
        return f"{value:.2f}%"
    return f"{value:.4f}"


def _format_signal_value(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1e8:
        return f"{value / 1e8:.2f} 亿元"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.4f}"


def _format_forecast_value(value: float | None, *, unit: str) -> str:
    if value is None:
        return "N/A"
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "x":
        return f"{value:.2f}x"
    return f"{value:.2f} {unit}"


def _build_report_options(reports: list[dict[str, Any]]) -> dict[str, str]:
    options: dict[str, str] = {}
    for report in reports:
        suffix_parts = [report.get("publish_date") or "日期未知"]
        if report.get("report_period"):
            suffix_parts.append(report["report_period"])
        if report.get("forecast_count"):
            suffix_parts.append(f"预测{report['forecast_count']}项")
        if report.get("rating_text") and report["rating_text"] != "未披露":
            suffix_parts.append(report["rating_text"])
        options[report["title"]] = f"{report['title']} | {' | '.join(suffix_parts)}"
    return options


def _format_rating_text(report_meta: dict[str, Any]) -> str:
    rating_parts = [
        part for part in (report_meta.get("rating_action"), report_meta.get("rating_label")) if part
    ]
    return "".join(rating_parts) or report_meta.get("rating_code") or "未披露"


def _build_evidence_href(chunk_id: str, context: str, anchor_terms: list[str]) -> str:
    params = []
    if context:
        params.append(f"context={quote_plus(context)}")
    if anchor_terms:
        params.append(f"anchors={quote_plus('|'.join(anchor_terms))}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return f"/evidence/{chunk_id}{suffix}"


def _highlight_excerpt(text: str, anchors: list[str]) -> str:
    highlighted = escape(text)
    for term in anchors:
        escaped_term = escape(term)
        highlighted = highlighted.replace(
            escaped_term,
            f"<mark class='op-highlight'>{escaped_term}</mark>",
        )
    return highlighted.replace("\n", "<br>")
