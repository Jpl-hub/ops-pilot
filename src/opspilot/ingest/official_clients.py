from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
import json
import re
import time

import requests


PERIODIC_REPORT_PATTERN = re.compile(
    r"(?:^|：)\s*\d{4}年(年度报告|半年度报告|一季度报告|第一季度报告|三季度报告|第三季度报告)(?:（[^）]*）)?(?:摘要)?$"
)
SSE_ARG1_PATTERN = re.compile(r"arg1='([0-9A-F]+)'")
SSE_UNSBOX = [
    0xF,
    0x23,
    0x1D,
    0x18,
    0x21,
    0x10,
    0x1,
    0x26,
    0xA,
    0x9,
    0x13,
    0x1F,
    0x28,
    0x1B,
    0x16,
    0x17,
    0x19,
    0xD,
    0x6,
    0xB,
    0x27,
    0x12,
    0x14,
    0x8,
    0xE,
    0x15,
    0x20,
    0x1A,
    0x2,
    0x1E,
    0x7,
    0x4,
    0x11,
    0x5,
    0x3,
    0x1C,
    0x22,
    0x25,
    0xC,
    0x24,
]
SSE_XOR_KEY = "3000176000856006061501533003690027800375"


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    company_name: str
    security_code: str
    ticker: str
    exchange: str
    subindustry: str


@dataclass(frozen=True, slots=True)
class ReportRecord:
    source: str
    company_name: str
    security_code: str
    exchange: str
    subindustry: str
    title: str
    publish_date: str
    report_type: str
    is_summary: bool
    source_url: str
    detail_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_company_pool(path: Path) -> list[CompanyProfile]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return [CompanyProfile(**item) for item in data]


def is_periodic_report_title(title: str) -> bool:
    if "英文" in title or "公告" in title:
        return False
    return bool(PERIODIC_REPORT_PATTERN.search(title))


def detect_periodic_report_type(title: str) -> str:
    match = PERIODIC_REPORT_PATTERN.search(title)
    return match.group(1) if match else "未知报告"


def extract_report_year(title: str, publish_date: str) -> int:
    match = re.search(r"(\d{4})年", title)
    if match:
        return int(match.group(1))
    return int(publish_date[:4])


def sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[\\\\/:*?\"<>|]+", "_", value)
    sanitized = re.sub(r"\s+", "_", sanitized).strip("_")
    return sanitized[:140] or "unnamed"


class SSEAnnouncementClient:
    endpoint = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.sse.com.cn/disclosure/listedinfo/regular/",
            }
        )

    def list_reports(
        self,
        company: CompanyProfile,
        *,
        since_date: str,
        max_items: int = 4,
        include_summaries: bool = False,
    ) -> list[ReportRecord]:
        reports: list[ReportRecord] = []
        page_no = 1
        while page_no <= 6:
            params = {
                "productId": company.security_code,
                "securityType": "0101,120100,020100,020200",
                "beginDate": since_date,
                "endDate": date.today().isoformat(),
                "isPagination": "true",
                "pageHelp.pageSize": "50",
                "pageHelp.pageNo": str(page_no),
                "pageHelp.beginPage": str(page_no),
                "pageHelp.endPage": str(page_no + 4),
            }
            response = self.session.get(self.endpoint, params=params, timeout=30)
            payload = _request_json_with_retry(
                self.session,
                "GET",
                self.endpoint,
                params=params,
            )
            rows = payload.get("pageHelp", {}).get("data", [])
            if not rows:
                break
            for row in rows:
                title = row["TITLE"]
                if row.get("BULLETIN_HEADING") != "定期报告" and not is_periodic_report_title(title):
                    continue
                is_summary = "摘要" in title
                if is_summary and not include_summaries:
                    continue
                reports.append(
                    ReportRecord(
                        source="SSE",
                        company_name=company.company_name,
                        security_code=company.security_code,
                        exchange=company.exchange,
                        subindustry=company.subindustry,
                        title=title,
                        publish_date=row["SSEDATE"],
                        report_type=detect_periodic_report_type(title),
                        is_summary=is_summary,
                        source_url=f"https://www.sse.com.cn{row['URL']}",
                    )
                )
            page_no += 1
        return select_periodic_reports(reports, max_items=max_items)


class SZSEAnnouncementClient:
    endpoint = "https://www.szse.cn/api/disc/announcement/annList"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.szse.cn/disclosure/listed/fixed/index.html",
                "Content-Type": "application/json",
            }
        )

    def list_reports(
        self,
        company: CompanyProfile,
        *,
        since_date: str,
        max_items: int = 4,
        include_summaries: bool = False,
    ) -> list[ReportRecord]:
        reports: list[ReportRecord] = []
        page_no = 1
        while page_no <= 6:
            payload = {
                "channelCode": ["fixed_disc"],
                "pageSize": 50,
                "pageNum": page_no,
                "stock": [company.security_code],
                "seDate": [since_date, date.today().isoformat()],
            }
            rows = _request_json_with_retry(
                self.session,
                "POST",
                self.endpoint,
                json=payload,
            ).get("data", [])
            if not rows:
                break
            for row in rows:
                title = row["title"]
                if not is_periodic_report_title(title):
                    continue
                is_summary = "摘要" in title
                if is_summary and not include_summaries:
                    continue
                attach_path = row["attachPath"]
                reports.append(
                    ReportRecord(
                        source="SZSE",
                        company_name=company.company_name,
                        security_code=company.security_code,
                        exchange=company.exchange,
                        subindustry=company.subindustry,
                        title=title,
                        publish_date=row["publishTime"].split(" ")[0],
                        report_type=detect_periodic_report_type(title),
                        is_summary=is_summary,
                        source_url=f"https://disc.static.szse.cn/download{attach_path}",
                    )
                )
            page_no += 1
        return select_periodic_reports(reports, max_items=max_items)


class EastmoneyResearchClient:
    endpoint = "https://reportapi.eastmoney.com/report/list"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://data.eastmoney.com/report/stock.jshtml",
            }
        )

    def list_reports(
        self,
        company: CompanyProfile,
        *,
        since_date: str,
        max_items: int = 5,
    ) -> list[ReportRecord]:
        reports: list[ReportRecord] = []
        page_no = 1
        while len(reports) < max_items and page_no <= 6:
            params = {
                "pageNo": page_no,
                "pageSize": 50,
                "code": company.security_code,
                "industryCode": "*",
                "industry": "*",
                "rating": "",
                "ratingChange": "",
                "beginTime": since_date,
                "endTime": date.today().isoformat(),
                "fields": "",
                "qType": 0,
            }
            rows = _request_json_with_retry(
                self.session,
                "GET",
                self.endpoint,
                params=params,
            ).get("data", [])
            if not rows:
                break
            for row in rows:
                reports.append(
                    ReportRecord(
                        source="EASTMONEY",
                        company_name=row["stockName"],
                        security_code=row["stockCode"],
                        exchange=company.exchange,
                        subindustry=company.subindustry,
                        title=row["title"],
                        publish_date=row["publishDate"].split(" ")[0],
                        report_type="个股研报",
                        is_summary=False,
                        source_url=f"https://data.eastmoney.com/report/info/{row['infoCode']}.html",
                        detail_url=f"https://data.eastmoney.com/report/info/{row['infoCode']}.html",
                    )
                )
                if len(reports) >= max_items:
                    break
            page_no += 1
        return reports


def download_binary(
    url: str,
    target_path: Path,
    session: requests.Session | None = None,
    *,
    force: bool = False,
) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not force:
        return target_path
    client = session or requests.Session()
    client.headers.setdefault("User-Agent", "Mozilla/5.0")
    if "sse.com.cn" in url:
        client.headers.setdefault("Referer", "https://www.sse.com.cn/disclosure/listedinfo/regular/")
    with client.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type and "sse.com.cn" in url:
            html = response.text
            _solve_sse_cookie(client, html)
            with client.get(url, stream=True, timeout=60) as retried:
                retried.raise_for_status()
                with target_path.open("wb") as file:
                    for chunk in retried.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            file.write(chunk)
            return target_path
        with target_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    file.write(chunk)
    return target_path


def download_text(
    url: str,
    target_path: Path,
    session: requests.Session | None = None,
    *,
    force: bool = False,
) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not force:
        return target_path
    client = session or requests.Session()
    response = client.get(url, timeout=60)
    response.raise_for_status()
    target_path.write_text(response.text, encoding="utf-8")
    return target_path


def build_periodic_filename(report: ReportRecord) -> str:
    return sanitize_filename(f"{report.publish_date}_{report.security_code}_{report.title}.pdf")


def build_research_filename(report: ReportRecord) -> str:
    return sanitize_filename(f"{report.publish_date}_{report.security_code}_{report.title}.html")


def write_manifest(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "record_count": len(records),
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def select_periodic_reports(reports: list[ReportRecord], *, max_items: int) -> list[ReportRecord]:
    best_by_period: dict[tuple[str, int, str], ReportRecord] = {}
    for report in reports:
        if not is_periodic_report_title(report.title):
            continue
        period_key = (
            report.security_code,
            extract_report_year(report.title, report.publish_date),
            report.report_type,
        )
        current = best_by_period.get(period_key)
        if current is None or report_rank_key(report) > report_rank_key(current):
            best_by_period[period_key] = report

    selected = sorted(best_by_period.values(), key=report_rank_key, reverse=True)
    return selected[:max_items]


def report_rank_key(report: ReportRecord) -> tuple[str, int]:
    return (report.publish_date, revision_priority(report.title))


def revision_priority(title: str) -> int:
    if "修订" in title or "更正" in title:
        return 2
    return 1


def _solve_sse_cookie(session: requests.Session, html: str) -> None:
    match = SSE_ARG1_PATTERN.search(html)
    if not match:
        raise RuntimeError("SSE anti-bot page detected, but arg1 token was not found.")
    arg1 = match.group(1)
    cookie_value = _hex_xor(_unsbox(arg1), SSE_XOR_KEY)
    session.cookies.set("acw_sc__v2", cookie_value)


def _unsbox(value: str) -> str:
    return "".join(value[index - 1] for index in SSE_UNSBOX)


def _hex_xor(left: str, right: str) -> str:
    return "".join(
        f"{int(left[index:index + 2], 16) ^ int(right[index:index + 2], 16):02x}"
        for index in range(0, min(len(left), len(right)), 2)
    )


def _request_json_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int = 3,
    **kwargs: Any,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(1.0 * attempt)
    assert last_error is not None
    raise last_error
