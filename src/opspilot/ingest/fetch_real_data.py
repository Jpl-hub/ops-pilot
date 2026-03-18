from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any
import json

from opspilot.ingest.official_clients import (
    CNInfoSnapshotClient,
    EastmoneyResearchClient,
    SSEAnnouncementClient,
    SZSEAnnouncementClient,
    build_periodic_filename,
    build_research_filename,
    download_binary,
    download_text,
    load_company_pool,
    sanitize_filename,
    write_manifest,
)
from opspilot.ingest.manifest_utils import load_manifest_records, merge_manifest_records


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Fetch official-source reports for OpsPilot.")
    parser.add_argument(
        "--company-pool",
        default="data/universe/formal_company_pool.json",
        help="Path to the formal company pool JSON.",
    )
    parser.add_argument(
        "--output-root",
        default="data/raw/official",
        help="Directory to store official-source raw files and manifests.",
    )
    parser.add_argument(
        "--since-date",
        default="2024-01-01",
        help="Lower bound date for report discovery.",
    )
    parser.add_argument(
        "--max-periodic",
        type=int,
        default=7,
        help="Max periodic reports to download per company after de-duplication.",
    )
    parser.add_argument(
        "--max-research",
        type=int,
        default=2,
        help="Max Eastmoney research pages to download per company.",
    )
    parser.add_argument(
        "--max-industry-research",
        type=int,
        default=3,
        help="Max Eastmoney industry research pages to download per tracked industry.",
    )
    parser.add_argument(
        "--codes",
        default="",
        help="Comma-separated security codes to limit execution.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Only produce manifests and URLs without downloading raw files.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download files even if they already exist locally.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    company_pool = load_company_pool(Path(args.company_pool))
    selected_codes = {item.strip() for item in args.codes.split(",") if item.strip()}
    if selected_codes:
        company_pool = [item for item in company_pool if item.security_code in selected_codes]

    output_root = Path(args.output_root)
    periodic_root = output_root / "periodic_reports"
    research_root = output_root / "research_reports"
    industry_research_root = output_root / "industry_research_reports"
    snapshot_root = output_root / "company_snapshots"
    manifests_root = output_root / "manifests"

    sse_client = SSEAnnouncementClient()
    szse_client = SZSEAnnouncementClient()
    eastmoney_client = EastmoneyResearchClient()
    snapshot_client = CNInfoSnapshotClient()

    periodic_manifest: list[dict[str, Any]] = []
    research_manifest: list[dict[str, Any]] = []
    industry_research_manifest: list[dict[str, Any]] = []
    snapshot_manifest: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    try:
        industry_reports = eastmoney_client.list_industry_reports(
            since_date=args.since_date,
            max_items_per_industry=args.max_industry_research,
        )
    except Exception as exc:
        failures.append(
            {
                "security_code": "INDUSTRY",
                "company_name": "行业研报",
                "stage": "industry_research_reports",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        print(f"[warn] industry research fetch failed: {exc}")
        industry_reports = []
    for report in industry_reports:
        local_path = (
            industry_research_root
            / sanitize_filename(report.industry_name or report.company_name)
            / build_research_filename(report)
        )
        try:
            if not args.skip_download and report.detail_url:
                download_text(report.detail_url, local_path, force=args.refresh)
        except Exception as exc:
            failures.append(
                {
                    "security_code": "INDUSTRY",
                    "company_name": report.industry_name or report.company_name,
                    "stage": "industry_research_download",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"[warn] industry research download failed for {report.title}: {exc}")
            continue
        record = report.to_dict()
        record["local_path"] = str(local_path)
        industry_research_manifest.append(record)

    for company in company_pool:
        try:
            if company.exchange == "SSE":
                periodic_reports = sse_client.list_reports(
                    company,
                    since_date=args.since_date,
                    max_items=args.max_periodic,
                )
            elif company.exchange == "SZSE":
                periodic_reports = szse_client.list_reports(
                    company,
                    since_date=args.since_date,
                    max_items=args.max_periodic,
                )
            else:
                periodic_reports = []
        except Exception as exc:
            failures.append(
                {
                    "security_code": company.security_code,
                    "company_name": company.company_name,
                    "stage": "periodic_reports",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"[warn] periodic fetch failed for {company.security_code} {company.company_name}: {exc}")
            periodic_reports = []

        for report in periodic_reports:
            local_path = periodic_root / report.exchange / report.security_code / build_periodic_filename(report)
            try:
                if not args.skip_download:
                    download_binary(report.source_url, local_path, force=args.refresh)
            except Exception as exc:
                failures.append(
                    {
                        "security_code": report.security_code,
                        "company_name": report.company_name,
                        "stage": "periodic_download",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"[warn] periodic download failed for {report.security_code} {report.title}: {exc}")
                continue
            record = report.to_dict()
            record["local_path"] = str(local_path)
            periodic_manifest.append(record)

        try:
            research_reports = eastmoney_client.list_reports(
                company,
                since_date=args.since_date,
                max_items=args.max_research,
            )
        except Exception as exc:
            failures.append(
                {
                    "security_code": company.security_code,
                    "company_name": company.company_name,
                    "stage": "research_reports",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"[warn] research fetch failed for {company.security_code} {company.company_name}: {exc}")
            research_reports = []
        for report in research_reports:
            local_path = research_root / company.security_code / build_research_filename(report)
            try:
                if not args.skip_download and report.detail_url:
                    download_text(report.detail_url, local_path, force=args.refresh)
            except Exception as exc:
                failures.append(
                    {
                        "security_code": report.security_code,
                        "company_name": report.company_name,
                        "stage": "research_download",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"[warn] research download failed for {report.security_code} {report.title}: {exc}")
                continue
            record = report.to_dict()
            record["local_path"] = str(local_path)
            research_manifest.append(record)

        try:
            snapshot_payload = snapshot_client.fetch_snapshot(company)
        except Exception as exc:
            failures.append(
                {
                    "security_code": company.security_code,
                    "company_name": company.company_name,
                    "stage": "company_snapshot",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"[warn] snapshot fetch failed for {company.security_code} {company.company_name}: {exc}")
        else:
            local_path = snapshot_root / company.exchange / company.security_code / "company_snapshot.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(
                json.dumps(snapshot_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            snapshot_manifest.append(
                {
                    "source": "CNINFO_SNAPSHOT",
                    "company_name": company.company_name,
                    "security_code": company.security_code,
                    "exchange": company.exchange,
                    "subindustry": company.subindustry,
                    "title": "巨潮资讯公司快照",
                    "publish_date": snapshot_payload["snapshot_date"],
                    "report_type": "公司快照",
                    "is_summary": False,
                    "source_url": snapshot_payload["source_url"],
                    "detail_url": snapshot_payload["source_url"],
                    "local_path": str(local_path),
                }
            )

    selected_company_codes = [company.security_code for company in company_pool]
    periodic_manifest = merge_manifest_records(
        load_manifest_records(manifests_root / "periodic_reports_manifest.json"),
        periodic_manifest,
        company_codes=selected_company_codes,
        key_fields=("source", "security_code", "publish_date", "title"),
    )
    research_manifest = merge_manifest_records(
        load_manifest_records(manifests_root / "research_reports_manifest.json"),
        research_manifest,
        company_codes=selected_company_codes,
        key_fields=("source", "security_code", "publish_date", "title"),
    )
    industry_research_manifest = merge_manifest_records(
        load_manifest_records(manifests_root / "industry_research_reports_manifest.json"),
        industry_research_manifest,
        company_codes={"INDUSTRY"},
        key_fields=("source", "industry_name", "publish_date", "title"),
    )
    snapshot_manifest = merge_manifest_records(
        load_manifest_records(manifests_root / "company_snapshots_manifest.json"),
        snapshot_manifest,
        company_codes=selected_company_codes,
        key_fields=("source", "security_code"),
    )

    write_manifest(manifests_root / "periodic_reports_manifest.json", periodic_manifest)
    write_manifest(manifests_root / "research_reports_manifest.json", research_manifest)
    write_manifest(manifests_root / "industry_research_reports_manifest.json", industry_research_manifest)
    write_manifest(manifests_root / "company_snapshots_manifest.json", snapshot_manifest)

    print(f"companies={len(company_pool)}")
    print(f"periodic_reports={len(periodic_manifest)}")
    print(f"research_reports={len(research_manifest)}")
    print(f"industry_research_reports={len(industry_research_manifest)}")
    print(f"company_snapshots={len(snapshot_manifest)}")
    print(f"failures={len(failures)}")


if __name__ == "__main__":
    main()
