from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
import json
import re

import requests


PERIODIC_REPORT_PATTERN = re.compile(r"(年度报告|半年度报告|一季度报告|三季度报告)")


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
    return bool(PERIODIC_REPORT_PATTERN.search(title))


def detect_periodic_report_type(title: str) -> str:
    match = PERIODIC_REPORT_PATTERN.search(title)
    return match.group(1) if match else "未知报告"


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
        while len(reports) < max_items and page_no <= 6:
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
            response.raise_for_status()
            payload = response.json()
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
                if len(reports) >= max_items:
                    break
            page_no += 1
        return reports


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
        while len(reports) < max_items and page_no <= 6:
            payload = {
                "channelCode": ["fixed_disc"],
                "pageSize": 50,
                "pageNum": page_no,
                "stock": [company.security_code],
                "seDate": [since_date, date.today().isoformat()],
            }
            response = self.session.post(self.endpoint, json=payload, timeout=30)
            response.raise_for_status()
            rows = response.json().get("data", [])
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
                if len(reports) >= max_items:
                    break
            page_no += 1
        return reports


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
            response = self.session.get(self.endpoint, params=params, timeout=30)
            response.raise_for_status()
            rows = response.json().get("data", [])
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


def download_binary(url: str, target_path: Path, session: requests.Session | None = None) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        return target_path
    client = session or requests.Session()
    with client.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with target_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    file.write(chunk)
    return target_path


def download_text(url: str, target_path: Path, session: requests.Session | None = None) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
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
