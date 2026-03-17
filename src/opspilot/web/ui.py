from __future__ import annotations

from opspilot.api.routes import get_service


def run_ui_app() -> None:
    try:
        from nicegui import ui
    except ImportError as exc:
        raise RuntimeError("未安装 nicegui，请先执行 `pip install -e .`。") from exc

    service = get_service()
    default_company = service.list_company_names()[0]
    initial_score = service.score_company(default_company)
    initial_risk = service.risk_scan()

    @ui.page("/")
    def landing() -> None:
        ui.markdown("# OpsPilot-X")
        ui.markdown("P0 演示版聚焦样本集的评分、对标、风险扫描与证据回放。")
        with ui.row():
            ui.link("企业体检页", "/score")
            ui.link("行业风险页", "/risk")
            ui.link("证据查看器", f"/evidence/{initial_score['evidence'][0]['chunk_id']}")

    @ui.page("/score")
    def score_page() -> None:
        ui.markdown("## 企业运营体检页")
        company_select = ui.select(options=service.list_company_names(), value=default_company, label="选择公司")
        summary = ui.markdown(initial_score["answer_markdown"])
        radar = ui.echart(initial_score["charts"][0]["options"])
        trend = ui.echart(initial_score["charts"][1]["options"])
        formula = ui.markdown(_format_formula_cards(initial_score.get("formula_cards", [])))
        evidence = ui.markdown(_format_evidence(initial_score["evidence"]))

        def refresh() -> None:
            payload = service.score_company(company_select.value)
            summary.content = payload["answer_markdown"]
            radar.options = payload["charts"][0]["options"]
            trend.options = payload["charts"][1]["options"]
            radar.update()
            trend.update()
            formula.content = _format_formula_cards(payload.get("formula_cards", []))
            evidence.content = _format_evidence(payload["evidence"])

        ui.button("刷新评分", on_click=refresh)

    @ui.page("/risk")
    def risk_page() -> None:
        ui.markdown("## 行业风险与机会大屏")
        ui.echart(initial_risk["charts"][0]["options"])
        for item in initial_risk["risk_board"]:
            ui.markdown(f"- **{item['company_name']}** | 风险数：{item['risk_count']} | {'、'.join(item['risk_labels']) or '暂无高风险标签'}")

    @ui.page("/evidence/{chunk_id}")
    def evidence_page(chunk_id: str) -> None:
        evidence_item = service.get_evidence(chunk_id)
        ui.markdown(f"## 证据查看器：{chunk_id}")
        ui.json_editor({"content": {"json": evidence_item}})

    ui.run(title="OpsPilot-X", reload=False, host="0.0.0.0", port=8080)


def _format_evidence(evidence: list[dict]) -> str:
    lines = ["### 证据包"]
    for item in evidence:
        lines.append(
            f"- [`{item['chunk_id']}`](/evidence/{item['chunk_id']}) | {item['source_title']} | p.{item['page']} | {item['excerpt']}"
        )
    return "\n".join(lines)


def _format_formula_cards(formula_cards: list[dict]) -> str:
    lines = ["### 公式回放"]
    if not formula_cards:
        lines.append("- 当前公司暂无可回放公式指标。")
        return "\n".join(lines)
    for card in formula_cards:
        lines.append(f"#### {card['metric_code']} {card['title']}")
        lines.append(f"- 公式：`{card['formula']}`")
        for detail in card["lines"]:
            lines.append(f"- {detail}")
        if card.get("evidence_refs"):
            refs = " | ".join(
                f"[`{chunk_id}`](/evidence/{chunk_id})" for chunk_id in card["evidence_refs"]
            )
            lines.append(f"- 证据：{refs}")
    return "\n".join(lines)
