"""Evidence — 规范化证据结构定义。

统一以下四类证据来源的数据结构：
  - 官方财报（OfficialRepository）：summary/statement/event 三种页类型
  - Bootstrap 样本（SampleRepository）：预置注释证据
  - Hybrid RAG 检索（VectorStore + ChunkRetriever）：BM25 ⊕ pgvector 融合结果
  - 研报摘录（Claim / Verify）：研报观点片段

设计原则
  - 使用 TypedDict（非 dataclass）确保与现有 dict[str, Any] 下游零摩擦
  - 所有必填字段都有明确含义和约束说明
  - 可选字段用 NotRequired 标注，仅在特定来源出现
  - 工厂函数（from_*）保证所有来源都能输出规范结构
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 来源类型
# ---------------------------------------------------------------------------

SourceType = Literal[
    "official_summary_page",    # 官方报告：摘要页
    "official_statement_page",  # 官方报告：财务报表页
    "official_event_page",      # 官方报告：重大事项页
    "official_snapshot_page",   # 官方报告：快照页（VisionAgent 多模态）
    "bootstrap_note",           # 预置样本注释
    "hybrid_rag_chunk",         # Hybrid RAG 检索块（BM25 + pgvector RRF）
    "research_report_excerpt",  # 研报观点摘录
    "research_forecast_excerpt",  # 研报盈利预测摘录
]

# ---------------------------------------------------------------------------
# 规范化证据结构
# ---------------------------------------------------------------------------


class EvidenceDict(TypedDict):
    """
    OpsPilot-X 统一证据结构。

    所有来源（官方财报 / Bootstrap 样本 / Hybrid RAG / 研报）最终都应转换为
    本结构，供 resolve_evidence / build_audit / _build_evidence_groups 等下游
    函数消费。

    必填字段（所有来源必须提供）
    ----------
    chunk_id
        稳定的全局唯一标识符。
        - 官方报告："{report_id}-{type}-{field|metric}-page-{page:03d}"
        - Bootstrap："ev-{company_slug}-{seq}"
        - Hybrid RAG：VectorStore 写入时由 build_embeddings.py 生成
        - 研报摘录："{report_id}-research-{claim_id}"

    company_name
        中文公司名称，与 repository 的 company_name 一致。

    report_period
        报告期，格式 "2024Q3" / "2024H1" / "2024FY"。
        研报摘录若无法对齐财报报期，填入 "N/A"。

    source_title
        来源文档标题（报告名称 / 研报名称）。

    source_type
        来源类型，见 SourceType Literal。

    page
        页码。向量检索来源使用 page_start；无页码时填 0。

    excerpt
        文本摘要，最多 400 字符（前端展示约束）。

    fingerprint
        去重标识符，用于跨来源合并时的幂等检测。
        格式建议："{report_id}-{field|type}-{page}"

    可选字段（仅部分来源出现）
    ----------
    source_url
        原文公开 URL（官方报告可通过 source_url 链接；Bootstrap / 研报为空）。

    local_path
        本地缓存文件路径（官方报告下载后写入；其他来源为空字符串）。

    similarity_score
        余弦相似度 [0, 1]，仅 VectorStore ANN 检索结果携带。

    retrieval_method
        检索方式，"bm25" / "vector" / "rrf_fused" / "official_index"。
        便于排查 RAG 质量问题。

    rank
        在融合排序结果中的位置（1 = 最相关）。
    """

    # ---- 必填 ----
    chunk_id: str
    company_name: str
    report_period: str
    source_title: str
    source_type: SourceType
    page: int
    excerpt: str
    fingerprint: str

    # ---- 可选 ----
    source_url: NotRequired[str]
    local_path: NotRequired[str]
    similarity_score: NotRequired[float]
    retrieval_method: NotRequired[str]
    rank: NotRequired[int]


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def from_official_index_entry(entry: dict[str, Any]) -> EvidenceDict:
    """将 OfficialRepository._build_evidence_index 的输出规范化。

    输入 entry 已经基本符合规范（有 chunk_id / company_name / report_period /
    source_title / source_type / page / excerpt / fingerprint / source_url /
    local_path），此函数主要负责类型校验和补全缺失字段。
    """
    return EvidenceDict(
        chunk_id=str(entry.get("chunk_id") or ""),
        company_name=str(entry.get("company_name") or ""),
        report_period=str(entry.get("report_period") or ""),
        source_title=str(entry.get("source_title") or ""),
        source_type=_coerce_source_type(entry.get("source_type"), "official_summary_page"),
        page=int(entry.get("page") or 0),
        excerpt=str(entry.get("excerpt") or "")[:400],
        fingerprint=str(entry.get("fingerprint") or entry.get("chunk_id") or ""),
        source_url=str(entry.get("source_url") or ""),
        local_path=str(entry.get("local_path") or ""),
        retrieval_method="official_index",
    )


def from_hybrid_chunk(
    chunk: dict[str, Any],
    company_name: str,
    report_period: str | None,
) -> EvidenceDict:
    """将 ChunkRetriever / VectorStore 的原始 chunk 转换为规范证据结构。

    原始 chunk 来自 PostgreSQL bronze 层，字段名可能为：
      - text / content  →  excerpt
      - page_start      →  page
      - title           →  source_title
      - source          →  source_url
      - score           →  similarity_score
    """
    raw_text = chunk.get("text") or chunk.get("content") or ""
    return EvidenceDict(
        chunk_id=str(chunk.get("chunk_id") or ""),
        company_name=str(chunk.get("company_name") or company_name),
        report_period=str(chunk.get("report_period") or report_period or ""),
        source_title=str(chunk.get("title") or ""),
        source_type="hybrid_rag_chunk",
        page=int(chunk.get("page_start") or chunk.get("page") or 0),
        excerpt=raw_text[:400],
        fingerprint=str(chunk.get("chunk_id") or ""),
        source_url=str(chunk.get("source") or chunk.get("source_url") or ""),
        local_path="",
        similarity_score=float(chunk["score"]) if "score" in chunk else None,  # type: ignore[misc]
        retrieval_method=str(chunk.get("retrieval_method") or "rrf_fused"),
        rank=int(chunk["rank"]) if "rank" in chunk else None,  # type: ignore[misc]
    )


def from_bootstrap_entry(entry: dict[str, Any]) -> EvidenceDict:
    """将 SampleRepository 的 bootstrap evidence.json 条目规范化。

    Bootstrap 条目通常缺少 source_url / local_path，使用 None。
    """
    return EvidenceDict(
        chunk_id=str(entry.get("chunk_id") or ""),
        company_name=str(entry.get("company_name") or ""),
        report_period=str(entry.get("report_period") or ""),
        source_title=str(entry.get("source_title") or ""),
        source_type=_coerce_source_type(entry.get("source_type"), "bootstrap_note"),
        page=int(entry.get("page") or 0),
        excerpt=str(entry.get("excerpt") or "")[:400],
        fingerprint=str(entry.get("fingerprint") or entry.get("chunk_id") or ""),
        source_url=str(entry.get("source_url") or ""),
        local_path=str(entry.get("local_path") or ""),
        retrieval_method="official_index",
    )


def from_research_excerpt(
    *,
    chunk_id: str,
    company_name: str,
    report_period: str,
    source_title: str,
    page: int,
    excerpt: str,
    source_type: SourceType = "research_report_excerpt",
    source_url: str = "",
) -> EvidenceDict:
    """从研报摘录字段直接构造规范证据。"""
    return EvidenceDict(
        chunk_id=chunk_id,
        company_name=company_name,
        report_period=report_period,
        source_title=source_title,
        source_type=source_type,
        page=page,
        excerpt=excerpt[:400],
        fingerprint=chunk_id,
        source_url=source_url,
        local_path="",
        retrieval_method="research_index",
    )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def normalize(raw: dict[str, Any], *, default_source_type: SourceType = "official_summary_page") -> EvidenceDict:
    """将任意来源的 dict 补全为规范证据结构（兜底函数）。

    适用于来源不确定或混合列表场景。优先尝试根据 source_type 判断，
    对于 hybrid_rag_chunk 走 from_hybrid_chunk 路径，其余走 from_official_index_entry。
    """
    source_type = raw.get("source_type", "")
    if source_type == "hybrid_rag_chunk" or "text" in raw or "page_start" in raw:
        return from_hybrid_chunk(raw, raw.get("company_name", ""), raw.get("report_period"))
    if source_type in ("research_report_excerpt", "research_forecast_excerpt"):
        return from_research_excerpt(
            chunk_id=str(raw.get("chunk_id") or ""),
            company_name=str(raw.get("company_name") or ""),
            report_period=str(raw.get("report_period") or "N/A"),
            source_title=str(raw.get("source_title") or ""),
            page=int(raw.get("page") or 0),
            excerpt=str(raw.get("excerpt") or "")[:400],
            source_type=_coerce_source_type(source_type, "research_report_excerpt"),
            source_url=str(raw.get("source_url") or ""),
        )
    return from_official_index_entry(raw)


def is_valid(ev: dict[str, Any]) -> bool:
    """快速校验一个 dict 是否满足 EvidenceDict 最低要求（必填字段非空）。"""
    required = ("chunk_id", "company_name", "report_period", "source_title",
                 "source_type", "excerpt", "fingerprint")
    return all(ev.get(k) for k in required)


def deduplicate(evidence_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 chunk_id 去重，保留首次出现的条目（通常是最高相关度的那条）。"""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for ev in evidence_list:
        cid = ev.get("chunk_id") or ev.get("fingerprint") or ""
        if cid and cid not in seen:
            seen.add(cid)
            result.append(ev)
    return result


# ---------------------------------------------------------------------------
# 私有辅助
# ---------------------------------------------------------------------------

_VALID_SOURCE_TYPES: frozenset[str] = frozenset(
    (
        "official_summary_page",
        "official_statement_page",
        "official_event_page",
        "official_snapshot_page",
        "bootstrap_note",
        "hybrid_rag_chunk",
        "research_report_excerpt",
        "research_forecast_excerpt",
    )
)


def _coerce_source_type(value: Any, default: SourceType) -> SourceType:
    if isinstance(value, str) and value in _VALID_SOURCE_TYPES:
        return value  # type: ignore[return-value]
    return default
