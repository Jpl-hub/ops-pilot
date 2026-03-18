from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote_plus

from fastapi import Request
from opspilot.api.routes import get_service


HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@500;700;800&family=Noto+Sans+SC:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --op-bg: #07111f;
    --op-bg-soft: #0e1d31;
    --op-surface: rgba(9, 22, 39, 0.86);
    --op-surface-strong: rgba(12, 28, 49, 0.96);
    --op-surface-soft: rgba(16, 38, 63, 0.72);
    --op-ink: #edf3ff;
    --op-muted: #93a6c2;
    --op-border: rgba(161, 182, 215, 0.12);
    --op-grid: rgba(122, 145, 177, 0.08);
    --op-accent: #ffb84d;
    --op-accent-strong: #ffc870;
    --op-accent-soft: rgba(255, 184, 77, 0.14);
    --op-risk: #ff7b72;
    --op-risk-soft: rgba(255, 123, 114, 0.14);
    --op-opportunity: #57e389;
    --op-opportunity-soft: rgba(87, 227, 137, 0.14);
    --op-shadow: 0 20px 60px rgba(2, 7, 16, 0.42);
  }

  body {
    font-family: "Noto Sans SC", sans-serif;
    color: var(--op-ink);
    background:
      radial-gradient(circle at 12% 18%, rgba(255, 184, 77, 0.18), transparent 22%),
      radial-gradient(circle at 88% 16%, rgba(95, 167, 255, 0.16), transparent 24%),
      radial-gradient(circle at 50% 100%, rgba(87, 227, 137, 0.08), transparent 30%),
      linear-gradient(180deg, #06101c 0%, #091627 48%, #07111f 100%);
    min-height: 100vh;
  }

  .nicegui-content {
    background: transparent;
  }

  .op-shell {
    position: relative;
    width: min(1280px, calc(100vw - 32px));
    margin: 0 auto;
    padding: 28px 0 48px;
  }

  .op-hero,
  .op-panel,
  .op-stat-card,
  .op-mini-card,
  .op-command-card {
    border: 1px solid var(--op-border);
    border-radius: 28px;
    box-shadow: var(--op-shadow);
  }

  .op-hero {
    background:
      linear-gradient(135deg, rgba(17, 37, 63, 0.98), rgba(11, 28, 50, 0.92)),
      linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0));
    color: #f7fbff;
    padding: 30px;
    overflow: hidden;
    position: relative;
  }

  .op-panel,
  .op-stat-card,
  .op-mini-card,
  .op-command-card {
    background: var(--op-surface);
    backdrop-filter: blur(14px);
  }

  .op-panel {
    padding: 22px;
  }

  .op-stat-card {
    min-width: 180px;
    padding: 20px;
    background:
      linear-gradient(180deg, rgba(14, 31, 54, 0.98), rgba(10, 24, 42, 0.92));
    position: relative;
    overflow: hidden;
  }

  .op-mini-card {
    min-width: 280px;
    flex: 1 1 340px;
    padding: 20px;
    background:
      linear-gradient(180deg, rgba(14, 31, 54, 0.92), rgba(9, 22, 39, 0.86));
  }

  .op-label-card {
    min-width: 280px;
    flex: 1 1 320px;
    padding: 20px;
    border: 1px solid var(--op-border);
    border-radius: 24px;
    background: linear-gradient(180deg, rgba(14, 31, 54, 0.96), rgba(9, 22, 39, 0.92));
    box-shadow: var(--op-shadow);
  }

  .op-command-card {
    min-width: 280px;
    flex: 1 1 320px;
    padding: 20px;
    background:
      linear-gradient(180deg, rgba(19, 42, 70, 0.92), rgba(10, 24, 42, 0.9));
  }

  .op-page-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
  }

  .op-page-title {
    font-family: "Syne", "Noto Sans SC", sans-serif;
    font-size: 34px;
    line-height: 1;
    font-weight: 700;
    letter-spacing: -0.03em;
  }

  .op-page-subtitle {
    max-width: 720px;
    font-size: 15px;
    line-height: 1.65;
    color: var(--op-muted);
  }

  .op-kicker {
    letter-spacing: 0.14em;
    text-transform: uppercase;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.66);
  }

  .op-title {
    font-family: "Syne", "Noto Sans SC", sans-serif;
    font-size: clamp(42px, 7vw, 76px);
    line-height: 0.96;
    font-weight: 800;
    max-width: 720px;
    letter-spacing: -0.05em;
    margin-top: 6px;
  }

  .op-subtitle {
    font-size: 15px;
    line-height: 1.7;
    color: var(--op-muted);
  }

  .op-hero .op-subtitle {
    color: rgba(237, 243, 255, 0.76);
    max-width: 560px;
  }

  .op-stat-label {
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(147, 166, 194, 0.72);
  }

  .op-stat-value {
    font-family: "Syne", "Noto Sans SC", sans-serif;
    font-size: clamp(28px, 4vw, 42px);
    line-height: 1;
    font-weight: 700;
    letter-spacing: -0.04em;
    margin-top: 16px;
  }

  .op-stat-hint {
    font-size: 13px;
    color: var(--op-muted);
    line-height: 1.6;
    margin-top: 18px;
  }

  .op-section-title {
    font-family: "Syne", "Noto Sans SC", sans-serif;
    font-size: 22px;
    font-weight: 700;
    line-height: 1.1;
  }

  .op-formula {
    font-family: "IBM Plex Mono", monospace;
    background: rgba(255, 184, 77, 0.1);
    color: #ffe3b5;
    border-radius: 14px;
    padding: 10px 12px;
    font-size: 13px;
    line-height: 1.6;
    border: 1px solid rgba(255, 184, 77, 0.12);
  }

  .op-detail-row {
    padding: 9px 0;
    border-bottom: 1px solid rgba(161, 182, 215, 0.08);
  }

  .op-detail-row:last-child {
    border-bottom: none;
  }

  .op-pill {
    display: inline-flex;
    align-items: center;
    padding: 5px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 500;
    border: 1px solid transparent;
  }

  .op-pill-risk {
    background: var(--op-risk-soft);
    color: var(--op-risk);
    border-color: rgba(255, 123, 114, 0.18);
  }

  .op-pill-opportunity {
    background: var(--op-opportunity-soft);
    color: var(--op-opportunity);
    border-color: rgba(87, 227, 137, 0.18);
  }

  .op-pill-neutral {
    background: rgba(122, 145, 177, 0.12);
    color: var(--op-accent);
    border-color: rgba(255, 184, 77, 0.18);
  }

  .op-evidence-link {
    color: #f7fbff;
    text-decoration: none;
    font-size: 12px;
    font-weight: 600;
    padding: 6px 10px;
    border-radius: 999px;
    background: rgba(255, 184, 77, 0.12);
    border: 1px solid rgba(255, 184, 77, 0.18);
  }

  .op-evidence-link:hover {
    background: rgba(255, 184, 77, 0.2);
  }

  .op-evidence-excerpt {
    font-size: 13px;
    line-height: 1.72;
    color: var(--op-muted);
  }

  .op-select {
    min-width: 240px;
  }

  .op-note {
    font-size: 13px;
    color: var(--op-muted);
    line-height: 1.55;
  }

  .op-highlight {
    background: rgba(255, 184, 77, 0.24);
    color: #fff1d8;
    padding: 0 3px;
    border-radius: 4px;
  }

  .op-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 28px;
  }

  .op-nav-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 42px;
    padding: 0 16px;
    border-radius: 999px;
    border: 1px solid rgba(255, 184, 77, 0.16);
    background: rgba(255, 184, 77, 0.08);
    color: #f8fbff;
    font-weight: 600;
    text-decoration: none;
  }

  .op-nav-link:hover {
    background: rgba(255, 184, 77, 0.16);
  }

  .op-hero-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.85fr);
    gap: 26px;
    align-items: stretch;
  }

  .op-hero-matrix {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
    position: relative;
    z-index: 1;
  }

  .op-hero-panel {
    padding: 18px;
    border-radius: 22px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    min-height: 100%;
  }

  .op-hero-panel-title {
    font-family: "Syne", "Noto Sans SC", sans-serif;
    font-size: 20px;
    line-height: 1.1;
    margin-bottom: 8px;
  }

  .op-hero-panel::before {
    content: "";
    position: absolute;
    inset: auto -80px -100px auto;
    width: 220px;
    height: 220px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(255, 184, 77, 0.22), transparent 62%);
    pointer-events: none;
  }

  .op-stat-card::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, rgba(255, 184, 77, 0.86), rgba(87, 227, 137, 0.38));
  }

  .op-stat-card::after {
    content: "";
    position: absolute;
    right: -28px;
    bottom: -40px;
    width: 120px;
    height: 120px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.08), transparent 70%);
    pointer-events: none;
  }

  .op-split {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.85fr);
    gap: 18px;
  }

  .op-summary-hero {
    min-height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    background:
      linear-gradient(135deg, rgba(18, 42, 70, 0.98), rgba(10, 24, 42, 0.92));
  }

  .op-summary-company {
    font-family: "Syne", "Noto Sans SC", sans-serif;
    font-size: clamp(34px, 5vw, 54px);
    line-height: 0.98;
    letter-spacing: -0.05em;
    margin-top: 12px;
  }

  .op-metric-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 12px;
    margin-top: 18px;
  }

  .op-metric-chip {
    padding: 12px 14px;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .op-metric-chip-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: rgba(147, 166, 194, 0.78);
  }

  .op-metric-chip-value {
    font-family: "Syne", "Noto Sans SC", sans-serif;
    font-size: 22px;
    line-height: 1;
    margin-top: 10px;
  }

  .op-summary-list {
    margin: 0;
    padding-left: 18px;
    line-height: 1.8;
  }

  .op-clamp-3 {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    overflow: hidden;
  }

  .op-clamp-5 {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 5;
    overflow: hidden;
  }

  .op-card-title-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .op-value-inline {
    font-family: "IBM Plex Mono", monospace;
    color: var(--op-accent-strong);
    font-size: 13px;
  }

  .op-card-divider {
    margin: 14px 0;
    border-top: 1px solid rgba(161, 182, 215, 0.08);
  }

  @media (max-width: 900px) {
    .op-hero-grid,
    .op-split {
      grid-template-columns: 1fr;
    }

    .op-page-header {
      align-items: flex-start;
      flex-direction: column;
    }
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
    initial_admin = service.admin_overview()
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
                with ui.element("div").classes("op-hero-grid w-full"):
                    with ui.column().classes("gap-3 justify-between"):
                        ui.label("OpsPilot-X").classes("op-kicker")
                        ui.label("让新能源公司的经营质量，像驾驶舱一样被看清。").classes("op-title")
                        ui.label(
                            "统一整合真实财报、研究观点、公式回放和证据定位，把企业体检、行业风险、研报核验和系统管理收束为一套面向用户的决策产品。"
                        ).classes("op-subtitle")
                        with ui.element("div").classes("op-nav"):
                            ui.link("企业体检", "/score").classes("op-nav-link")
                            ui.link("行业风险", "/risk").classes("op-nav-link")
                            ui.link("研报核验", "/verify").classes("op-nav-link")
                            ui.link("系统管理", "/admin").classes("op-nav-link")
                            ui.link(
                                "证据查看",
                                f"/evidence/{initial_score['evidence'][0]['chunk_id']}",
                            ).classes("op-nav-link")
                    with ui.card().classes("op-hero-panel"):
                        ui.label("当前系统快照").classes("op-hero-panel-title")
                        ui.label(
                            "主链已经切到真实数据，当前更适合直接从入口进入任务，而不是先读说明。"
                        ).classes("op-subtitle")
                        with ui.element("div").classes("op-hero-matrix mt-4"):
                            _render_stat_card(
                                ui,
                                label="主周期",
                                value=initial_score["report_period"],
                                hint=f"公司池 {len(service.list_company_names())} 家",
                            )
                            _render_stat_card(
                                ui,
                                label="风险巡检",
                                value=str(len(initial_risk["risk_board"])),
                                hint="支持横向扫描",
                            )
                            _render_stat_card(
                                ui,
                                label="公式回放",
                                value=str(len(initial_score.get("formula_cards", []))),
                                hint="字段级公式链",
                            )
                            _render_stat_card(
                                ui,
                                label="研报核验",
                                value=str(len(initial_claim.get("claim_cards", []))),
                                hint="真实观点核验",
                            )

            with ui.row().classes("w-full gap-4 wrap"):
                _render_command_card(
                    ui,
                    title="企业体检",
                    detail="围绕单家公司看总分、标签、公式和证据。",
                    stats=[
                        ("总分", f"{initial_score['scorecard']['total_score']}"),
                        ("风险", str(len(initial_score["scorecard"]["risk_labels"]))),
                    ],
                )
                _render_command_card(
                    ui,
                    title="行业风险",
                    detail="把 50 家正式公司放进同一主周期扫描风险密度。",
                    stats=[
                        ("高风险公司", str(sum(1 for item in initial_risk["risk_board"] if item["risk_count"] > 0))),
                        ("行业研报", str(initial_risk["industry_research"]["key_numbers"][1]["value"])),
                    ],
                )
                _render_command_card(
                    ui,
                    title="研报核验",
                    detail="把券商观点、目标价和真实财报指标直接放在一屏对照。",
                    stats=[
                        ("匹配观点", str(next(item["value"] for item in initial_claim.get("key_numbers", []) if item["label"] == "匹配观点")) if initial_claim.get("key_numbers") else "0"),
                        ("可用研报", str(len(initial_claim_reports))),
                    ],
                )
                _render_command_card(
                    ui,
                    title="系统管理",
                    detail="检查覆盖缺口、数据链路状态和标准作业命令。",
                    stats=[
                        ("标准作业", str(len(initial_admin["job_catalog"]))),
                        ("主周期就绪", str(initial_admin["quality_overview"]["coverage"]["preferred_period_ready"])),
                    ],
                )

    @ui.page("/score")
    def score_page() -> None:
        with ui.column().classes("op-shell gap-6"):
            with ui.element("div").classes("op-page-header w-full"):
                with ui.column().classes("gap-1"):
                    ui.label("企业运营体检").classes("op-page-title")
                    ui.label("把真实财报评分、风险标签、公式解释和证据链压到同一层里看，不让用户自己在页面之间来回找。").classes("op-page-subtitle")
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
            with ui.element("div").classes("op-page-header w-full"):
                with ui.column().classes("gap-1"):
                    ui.label("行业风险与机会").classes("op-page-title")
                    ui.label("先看行业整体风险密度，再叠加行业研报背景，避免只盯单家公司。").classes("op-page-subtitle")
                _render_stat_card(
                    ui,
                    label="高风险公司数",
                    value=str(sum(1 for item in initial_risk["risk_board"] if item["risk_count"] > 0)),
                    hint="主周期下风险标签命中数大于 0",
                )

            with ui.card().classes("op-panel w-full"):
                ui.echart(initial_risk["charts"][0]["options"]).classes("w-full").style("height: 380px;")

            with ui.card().classes("op-panel w-full"):
                ui.label("行业研报观察").classes("op-section-title")
                ui.label("接入赛题给定的东方财富行业研报，补足行业景气与机构观点背景。").classes("op-subtitle")
                with ui.row().classes("w-full gap-4 wrap"):
                    for number in initial_risk["industry_research"]["key_numbers"]:
                        _render_stat_card(
                            ui,
                            label=number["label"],
                            value=str(number["value"]),
                            hint=number["unit"],
                        )
                with ui.row().classes("w-full gap-4 wrap items-stretch mt-2"):
                    for group in initial_risk["industry_research"]["groups"]:
                        latest = group["latest_report"]
                        with ui.card().classes("op-mini-card"):
                            ui.label(group["industry_name"]).classes("text-lg font-semibold")
                            ui.label(f"{group['report_count']} 篇真实行业研报").classes("op-stat-hint")
                            ui.label(latest["title"]).classes("text-sm font-medium op-clamp-3")
                            ui.label(latest["excerpt"]).classes("op-evidence-excerpt op-clamp-5")
                            with ui.row().classes("gap-2 wrap"):
                                _render_pill(
                                    ui,
                                    latest["source_name"] or "机构未披露",
                                    tone="neutral",
                                )
                                _render_pill(
                                    ui,
                                    latest["rating_text"],
                                    tone="neutral",
                                )
                            with ui.row().classes("gap-2 wrap"):
                                ui.link("打开详情", latest["source_url"], new_tab=True).classes("op-evidence-link")
                                if latest.get("attachment_url"):
                                    ui.link("打开附件", latest["attachment_url"], new_tab=True).classes("op-evidence-link")

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
            with ui.element("div").classes("op-page-header w-full"):
                with ui.column().classes("gap-1"):
                    ui.label("研报观点核验").classes("op-page-title")
                    ui.label("用户看到的不是研报原文堆砌，而是观点、报期、评级和真实财报证据之间的明确对应关系。").classes("op-page-subtitle")
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
                    compare_sort_select = ui.select(
                        options={
                            "priority": "优先看分歧",
                            "latest": "按时间最新",
                            "target_price_desc": "目标价从高到低",
                            "forecast_desc": "首年利润预测从高到低",
                        },
                        value="priority",
                        label="对比排序",
                    ).classes("op-select")
                    compare_filter_select = ui.select(
                        options={
                            "all": "全部研报",
                            "supported": "仅报期已对齐",
                            "target_price": "仅看含目标价",
                            "forecast": "仅看含盈利预测",
                            "divergence": "仅看分歧信号",
                        },
                        value="all",
                        label="对比筛选",
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
                    payload["research_compare"] = service.compare_research_reports(
                        company_select.value,
                        sort_by=compare_sort_select.value,
                        filter_mode=compare_filter_select.value,
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
                        _render_stat_card(
                            ui,
                            label="目标价",
                            value=_format_target_price(payload["report_meta"].get("target_price")),
                            hint=payload["report_meta"].get("rating_change") or "评级动作未披露",
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
                            _render_stat_card(
                                ui,
                                label="评级动作",
                                value=payload["report_meta"].get("rating_change") or "未披露",
                                hint=_format_target_price(payload["report_meta"].get("target_price")),
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
                    compare_payload = payload.get("research_compare", {})
                    if compare_payload.get("rows"):
                        with ui.card().classes("op-panel w-full"):
                            ui.label("同公司研报横向对比").classes("op-section-title")
                            ui.label(
                                f"当前展示 {compare_payload.get('filtered_reports', len(compare_payload.get('rows', [])))} / "
                                f"{compare_payload.get('total_reports', len(compare_payload.get('rows', [])))} 篇研报，"
                                "横向比较不同机构的评级、目标价和首年利润预测。"
                            ).classes("op-note")
                            if compare_payload.get("insights"):
                                with ui.row().classes("w-full gap-4 wrap items-stretch"):
                                    for insight in compare_payload["insights"]:
                                        with ui.card().classes("op-mini-card"):
                                            _render_pill(
                                                ui,
                                                "一致信号" if insight["kind"] == "consensus" else "分歧信号",
                                                tone="opportunity" if insight["kind"] == "consensus" else "risk",
                                            )
                                            ui.label(insight["title"]).classes("text-lg font-semibold")
                                            ui.label(insight["detail"]).classes("op-evidence-excerpt")
                            with ui.row().classes("w-full gap-4 wrap"):
                                for item in compare_payload.get("key_numbers", []):
                                    _render_stat_card(
                                        ui,
                                        label=item["label"],
                                        value=_format_compare_value(item.get("value"), item.get("unit")),
                                        hint=payload["company_name"],
                                    )
                            ui.echart(compare_payload["charts"][0]["options"]).classes("w-full").style("height: 320px;")
                            with ui.row().classes("w-full gap-4 wrap items-stretch"):
                                for row in compare_payload["rows"]:
                                    with ui.card().classes("op-mini-card"):
                                        ui.label(row["title"]).classes("text-lg font-semibold")
                                        ui.label(
                                            f"{row.get('source_name') or '机构未披露'} | {row.get('publish_date') or '日期未知'}"
                                        ).classes("op-note")
                                        if row.get("signal_tags"):
                                            with ui.row().classes("gap-2 wrap"):
                                                for tag in row["signal_tags"]:
                                                    tone = "neutral"
                                                    if tag in {"目标价最高", "预测最乐观"} or tag.startswith("评级:"):
                                                        tone = "opportunity"
                                                    elif tag in {"目标价最低", "预测最谨慎", "报期待核实"}:
                                                        tone = "risk"
                                                    _render_pill(ui, tag, tone=tone)
                                        with ui.column().classes("w-full gap-0"):
                                            for label, value in (
                                                ("评级", row.get("rating_text") or "未披露"),
                                                ("目标价", _format_target_price(row.get("target_price"))),
                                                (
                                                    "首年利润预测",
                                                    _format_forecast_value(
                                                        row.get("headline_forecast_value"),
                                                        unit="亿元",
                                                    ),
                                                ),
                                                (
                                                    "首年PE",
                                                    _format_forecast_value(
                                                        row.get("headline_forecast_pe"),
                                                        unit="x",
                                                    ),
                                                ),
                                            ):
                                                with ui.row().classes("op-detail-row w-full items-center justify-between gap-3"):
                                                    ui.label(label).classes("text-sm")
                                                    ui.label(value).classes("text-sm font-medium")
                    elif compare_payload:
                        with ui.card().classes("op-panel w-full"):
                            ui.label("同公司研报横向对比").classes("op-section-title")
                            ui.label("当前筛选条件下没有命中的研报，建议切回“全部研报”或放宽筛选。").classes("op-note")
                    timeline_payload = payload.get("research_timeline", {})
                    if timeline_payload.get("institutions"):
                        with ui.card().classes("op-panel w-full"):
                            ui.label("机构观点变化轨迹").classes("op-section-title")
                            ui.label("按机构追踪评级、目标价和首年利润预测的时间序列变化。").classes("op-note")
                            with ui.row().classes("w-full gap-4 wrap"):
                                for item in timeline_payload.get("key_numbers", []):
                                    _render_stat_card(
                                        ui,
                                        label=item["label"],
                                        value=_format_compare_value(item.get("value"), item.get("unit")),
                                        hint=payload["company_name"],
                                    )
                            with ui.row().classes("w-full gap-4 wrap items-stretch"):
                                for institution in timeline_payload["institutions"]:
                                    with ui.card().classes("op-mini-card"):
                                        ui.label(institution["institution"]).classes("text-lg font-semibold")
                                        ui.label(
                                            f"共 {institution['report_count']} 篇 | 最新评级 {institution['latest_rating']}"
                                        ).classes("op-note")
                                        if institution.get("rating_stability") is not None:
                                            _render_pill(
                                                ui,
                                                f"评级稳定度 {institution['rating_stability']:.2f}%",
                                                tone="neutral",
                                            )
                                        with ui.column().classes("w-full gap-0"):
                                            for label, value in (
                                                ("最新目标价", _format_target_price(institution.get("latest_target_price"))),
                                                (
                                                    "最新首年利润预测",
                                                    _format_forecast_value(
                                                        institution.get("latest_forecast_value"),
                                                        unit="亿元",
                                                    ),
                                                ),
                                            ):
                                                with ui.row().classes("op-detail-row w-full items-center justify-between gap-3"):
                                                    ui.label(label).classes("text-sm")
                                                    ui.label(value).classes("text-sm font-medium")
                                        if institution.get("latest_transition"):
                                            tone = (
                                                "risk"
                                                if institution["latest_transition"]["transition_kind"] in {"rating_changed", "target_changed"}
                                                else "neutral"
                                            )
                                            _render_pill(ui, institution["latest_transition"]["summary"], tone=tone)
                                        if institution.get("transitions"):
                                            ui.label("时间序列").classes("op-note mt-3")
                                            with ui.column().classes("w-full gap-2"):
                                                for transition in reversed(institution["transitions"]):
                                                    with ui.card().classes("op-panel"):
                                                        ui.label(
                                                            f"{transition.get('publish_date') or '日期未知'} | {transition.get('title') or '研报'}"
                                                        ).classes("text-sm font-semibold")
                                                        ui.label(transition["summary"]).classes("op-evidence-excerpt")
                                                        with ui.row().classes("gap-2 wrap"):
                                                            if transition.get("source_url"):
                                                                ui.link(
                                                                    "打开研报详情",
                                                                    transition["source_url"],
                                                                    new_tab=True,
                                                                ).classes("op-evidence-link")
                                                            if transition.get("attachment_url"):
                                                                ui.link(
                                                                    "打开研报附件",
                                                                    transition["attachment_url"],
                                                                    new_tab=True,
                                                                ).classes("op-evidence-link")
                                                        with ui.row().classes("gap-2 wrap"):
                                                            _render_pill(
                                                                ui,
                                                                "同报期可比" if transition["is_rating_comparable"] else "跨报期不可比",
                                                                tone="neutral" if transition["is_rating_comparable"] else "risk",
                                                            )
                                                            _render_pill(
                                                                ui,
                                                                transition["rating_to"],
                                                                tone="neutral",
                                                            )
                                                            if transition.get("target_delta") not in (None, 0):
                                                                _render_pill(
                                                                    ui,
                                                                    f"目标价变动 {transition['target_delta']:.2f} 元",
                                                                    tone="risk" if transition["target_delta"] < 0 else "opportunity",
                                                                )
                                                            if transition.get("forecast_delta") not in (None, 0):
                                                                _render_pill(
                                                                    ui,
                                                                    f"首年利润变动 {transition['forecast_delta']:.2f} 亿元",
                                                                    tone="risk" if transition["forecast_delta"] < 0 else "opportunity",
                                                                )
                                                            elif not transition["is_forecast_comparable"]:
                                                                _render_pill(
                                                                    ui,
                                                                    "首年预测口径不同",
                                                                    tone="risk",
                                                                )
                _render_evidence_section(ui, evidence_section, payload)

            company_select.on_value_change(lambda _: sync_report_options())
            refresh()

    @ui.page("/admin")
    def admin_page() -> None:
        with ui.column().classes("op-shell gap-6"):
            payload = service.admin_overview()
            health = payload["health"]
            data_status = payload["data_status"]
            quality_overview = payload["quality_overview"]
            coverage = quality_overview["coverage"]
            with ui.element("div").classes("op-page-header w-full"):
                with ui.column().classes("gap-1"):
                    ui.label("系统管理台").classes("op-page-title")
                    ui.label("统一查看系统健康、真实数据状态、覆盖缺口和标准作业，不把运维信息散落在仓库和终端里。").classes("op-page-subtitle")
                ui.link("返回首页", "/").classes("op-evidence-link")

            with ui.row().classes("w-full gap-4 wrap"):
                _render_stat_card(
                    ui,
                    label="系统状态",
                    value=health["status"],
                    hint=health["env"],
                )
                _render_stat_card(
                    ui,
                    label="默认主周期",
                    value=health["preferred_period"] or health["default_period"],
                    hint=f"公司 {health['companies']} 家",
                )
                _render_stat_card(
                    ui,
                    label="原始报告",
                    value=str(data_status["periodic_reports"]["record_count"]),
                    hint=f"公司 {data_status['periodic_reports']['company_count']} 家",
                )
                _render_stat_card(
                    ui,
                    label="结构化指标",
                    value=str(data_status["silver_financial_metrics"]["record_count"]),
                    hint=f"公司 {data_status['silver_financial_metrics']['company_count']} 家",
                )

            with ui.card().classes("op-panel w-full"):
                ui.label("系统能力").classes("op-section-title")
                with ui.row().classes("gap-2 wrap"):
                    for capability in payload["capabilities"]:
                        _render_pill(ui, capability, tone="neutral")

            with ui.card().classes("op-panel w-full"):
                ui.label("覆盖诊断").classes("op-section-title")
                with ui.row().classes("w-full gap-4 wrap"):
                    _render_stat_card(
                        ui,
                        label="正式公司池",
                        value=str(coverage["pool_companies"]),
                        hint="当前冻结正式公司范围",
                    )
                    _render_stat_card(
                        ui,
                        label="主周期可评估",
                        value=str(coverage["preferred_period_ready"]),
                        hint=quality_overview["preferred_period"] or "未识别主周期",
                    )
                    _render_stat_card(
                        ui,
                        label="研报已覆盖",
                        value=str(coverage["research_ready"]),
                        hint="有真实研报详情页",
                    )
                    _render_stat_card(
                        ui,
                        label="页级解析完成",
                        value=str(coverage["bronze_ready"]),
                        hint="raw -> bronze 已打通",
                    )
                    _render_stat_card(
                        ui,
                        label="结构化完成",
                        value=str(coverage["silver_ready"]),
                        hint="bronze -> silver 已打通",
                    )

            with ui.card().classes("op-panel w-full"):
                ui.label("问题分桶").classes("op-section-title")
                ui.label("直接暴露真实数据链路的缺口，优先处理主周期、研报和解析断点。").classes("op-note")
                issue_buckets = quality_overview["issue_buckets"]
                if not issue_buckets:
                    ui.label("当前正式公司池未发现覆盖缺口。").classes("op-note")
                else:
                    with ui.row().classes("w-full gap-4 wrap items-stretch"):
                        for bucket in issue_buckets:
                            with ui.card().classes("op-mini-card"):
                                ui.label(bucket["label"]).classes("text-lg font-semibold")
                                ui.label(f"{bucket['count']} 家").classes("op-stat-hint")
                                ui.label("、".join(bucket["companies"])).classes("op-evidence-excerpt")

            with ui.card().classes("op-panel w-full"):
                ui.label("数据状态").classes("op-section-title")
                with ui.row().classes("w-full gap-4 wrap items-stretch"):
                    for label, item in (
                        ("定期报告", data_status["periodic_reports"]),
                        ("研报详情页", data_status["research_reports"]),
                        ("行业研报", data_status["industry_research_reports"]),
                        ("官方快照", data_status["company_snapshots"]),
                        ("页级解析", data_status["bronze_periodic_reports"]),
                        ("结构化指标", data_status["silver_financial_metrics"]),
                    ):
                        with ui.card().classes("op-mini-card"):
                            ui.label(label).classes("text-lg font-semibold")
                            with ui.column().classes("w-full gap-0"):
                                for detail_label, detail_value in (
                                    ("记录数", str(item["record_count"])),
                                    ("公司数", str(item["company_count"])),
                                    ("Manifest", item["manifest_path"]),
                                ):
                                    with ui.row().classes("op-detail-row w-full items-center justify-between gap-3"):
                                        ui.label(detail_label).classes("text-sm")
                                        ui.label(detail_value).classes("text-sm font-medium")

            with ui.card().classes("op-panel w-full"):
                ui.label("公司覆盖明细").classes("op-section-title")
                ui.label("优先显示存在缺口的公司，便于直接定位下一步数据作业目标。").classes("op-note")
                with ui.row().classes("w-full gap-4 wrap items-stretch"):
                    for item in quality_overview["companies"][:18]:
                        with ui.card().classes("op-mini-card"):
                            ui.label(item["company_name"]).classes("text-lg font-semibold")
                            ui.label(item["subindustry"]).classes("op-stat-hint")
                            with ui.column().classes("w-full gap-0"):
                                for detail_label, detail_value in (
                                    ("最新结构化报期", item["latest_silver_period"] or "未构建"),
                                    ("定期报告", str(item["raw_report_count"])),
                                    ("页级解析", str(item["bronze_report_count"])),
                                    ("结构化记录", str(item["silver_record_count"])),
                                    ("研报", str(item["research_report_count"])),
                                ):
                                    with ui.row().classes("op-detail-row w-full items-center justify-between gap-3"):
                                        ui.label(detail_label).classes("text-sm")
                                        ui.label(detail_value).classes("text-sm font-medium")
                            with ui.row().classes("gap-2 wrap"):
                                if item["preferred_period_ready"]:
                                    _render_pill(ui, "主周期已就绪", tone="opportunity")
                                else:
                                    _render_pill(ui, "缺主周期", tone="risk")
                                if item["issues"]:
                                    for issue in item["issues"]:
                                        if issue == "缺主周期":
                                            continue
                                        _render_pill(ui, issue, tone="risk")
                                else:
                                    _render_pill(ui, "链路完整", tone="neutral")

            with ui.card().classes("op-panel w-full"):
                ui.label("标准作业").classes("op-section-title")
                ui.label("当前管理台先冻结标准命令目录，保持数据构建链路清晰可复现。").classes("op-note")
                with ui.row().classes("w-full gap-4 wrap items-stretch"):
                    for job in payload["job_catalog"]:
                        with ui.card().classes("op-mini-card"):
                            ui.label(job["title"]).classes("text-lg font-semibold")
                            ui.label(job["description"]).classes("op-evidence-excerpt")
                            _render_pill(ui, job["output_stage"], tone="neutral")
                            ui.label(job["command"]).classes("op-formula")

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
                ui.label("证据查看器").classes("op-page-title")
                ui.label(context or chunk_id).classes("op-page-subtitle")
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

        with ui.element("div").classes("op-split w-full"):
            with ui.card().classes("op-panel op-summary-hero"):
                ui.label("评分摘要").classes("op-kicker")
                ui.label(payload["company_name"]).classes("op-summary-company")
                ui.label(
                    f"{payload['report_period']} · 等级 {scorecard['grade']} · 对标子行业 {payload['subindustry']}"
                ).classes("op-subtitle")
                with ui.element("div").classes("op-metric-strip"):
                    _render_metric_chip(ui, "总分", f"{scorecard['total_score']}")
                    _render_metric_chip(ui, "分位", f"{scorecard['subindustry_percentile']}pct")
                    _render_metric_chip(ui, "强项", str(len(scorecard["strengths"])))
                    _render_metric_chip(ui, "弱项", str(len(scorecard["weaknesses"])))
                ui.label("当前公司在主周期下的经营结论，不再用大段 markdown 平铺。").classes("op-note")

            with ui.card().classes("op-panel"):
                ui.label("核心判断").classes("op-section-title")
                ui.label("把用户最关心的四件事先讲清楚。").classes("op-subtitle")
                with ui.element("ul").classes("op-summary-list"):
                    with ui.element("li"):
                        ui.label(
                            f"总分 {scorecard['total_score']}，等级 {scorecard['grade']}，子行业分位 {scorecard['subindustry_percentile']}pct。"
                        )
                    with ui.element("li"):
                        ui.label("强项: " + _join_metric_names(scorecard["strengths"], fallback="暂无显著强项"))
                    with ui.element("li"):
                        ui.label("弱项: " + _join_metric_names(scorecard["weaknesses"], fallback="暂无显著弱项"))
                    with ui.element("li"):
                        ui.label(
                            "风险标签: "
                            + _join_label_names(scorecard["risk_labels"], fallback="暂无高风险标签")
                        )
                    with ui.element("li"):
                        ui.label(
                            "机会标签: "
                            + _join_label_names(scorecard["opportunity_labels"], fallback="暂无显著机会标签")
                        )
                ui.separator().classes("op-card-divider")
                ui.label("标签面板").classes("op-note")
                with ui.row().classes("gap-2 wrap"):
                    risk_labels = scorecard["risk_labels"] or [{"name": "暂无高风险标签"}]
                    for item in risk_labels:
                        _render_pill(ui, item["name"], tone="risk" if item["name"] != "暂无高风险标签" else "neutral")
                with ui.row().classes("gap-2 wrap mt-2"):
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
        with ui.element("div").classes("op-card-title-row w-full"):
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
                            ui.label(item["excerpt"]).classes("op-evidence-excerpt op-clamp-5")


def _render_stat_card(ui: Any, *, label: str, value: str, hint: str) -> None:
    with ui.card().classes("op-stat-card grow"):
        ui.label(label).classes("op-stat-label")
        ui.label(value).classes("op-stat-value")
        ui.label(hint).classes("op-stat-hint")


def _render_command_card(
    ui: Any,
    *,
    title: str,
    detail: str,
    stats: list[tuple[str, str]],
) -> None:
    with ui.card().classes("op-command-card"):
        ui.label(title).classes("op-section-title")
        ui.label(detail).classes("op-evidence-excerpt op-clamp-3")
        with ui.element("div").classes("op-metric-strip"):
            for label, value in stats:
                _render_metric_chip(ui, label, value)


def _render_metric_chip(ui: Any, label: str, value: str) -> None:
    with ui.element("div").classes("op-metric-chip"):
        ui.label(label).classes("op-metric-chip-label")
        ui.label(value).classes("op-metric-chip-value")


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


def _format_target_price(value: float | None) -> str:
    if value is None:
        return "未披露"
    return f"{value:.2f} 元"


def _format_compare_value(value: float | int | None, unit: str) -> str:
    if value is None:
        return "N/A"
    if unit == "元":
        return f"{value:.2f} 元"
    if unit == "亿元":
        return f"{value:.2f} 亿元"
    return f"{value} {unit}".strip()


def _join_metric_names(items: list[dict[str, Any]], *, fallback: str) -> str:
    if not items:
        return fallback
    return "、".join(item["name"] for item in items)


def _join_label_names(items: list[dict[str, Any]], *, fallback: str) -> str:
    if not items:
        return fallback
    return "、".join(item["name"] for item in items)


def _build_report_options(reports: list[dict[str, Any]]) -> dict[str, str]:
    options: dict[str, str] = {}
    for report in reports:
        suffix_parts = [report.get("publish_date") or "日期未知"]
        if report.get("report_period"):
            suffix_parts.append(report["report_period"])
        if report.get("forecast_count"):
            suffix_parts.append(f"预测{report['forecast_count']}项")
        if report.get("target_price") is not None:
            suffix_parts.append(_format_target_price(report["target_price"]))
        if report.get("rating_text") and report["rating_text"] != "未披露":
            suffix_parts.append(report["rating_text"])
        options[report["title"]] = f"{report['title']} | {' | '.join(suffix_parts)}"
    return options


def _format_rating_text(report_meta: dict[str, Any]) -> str:
    rating_parts = [
        part for part in (report_meta.get("rating_action"), report_meta.get("rating_label")) if part
    ]
    if rating_parts:
        return "".join(rating_parts)
    rating_code = report_meta.get("rating_code")
    if isinstance(rating_code, str) and len(rating_code) == 1 and rating_code.isupper():
        return "未披露"
    return rating_code or "未披露"


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
