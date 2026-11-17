"""결과 행을 CSV 표로 만든다."""

from __future__ import annotations

import csv
import io

from site_audit.audit import AuditReport


def to_csv(report: AuditReport) -> str:
    buffer = io.StringIO()
    buffer.write("\ufeff")
    for note in report.notes:
        buffer.write(f"# {note}\n")
    buffer.write(f"# 수집 페이지 수: {report.checked}\n")
    if report.stopped:
        buffer.write("# 중단: 있음\n")
    else:
        buffer.write("# 중단: 없음\n")
    writer = csv.writer(buffer)
    writer.writerow(["주소", "유형", "결과", "이유"])
    for row in report.rows:
        reason = row.reason if row.verdict == "실패" or row.reason else "—"
        writer.writerow([row.url, row.kind, row.verdict, reason])
    return buffer.getvalue()
