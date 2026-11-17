"""로컬에서만 열고, 검사 기록은 서버에 남기지 않는다."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from site_audit.audit import check_page_assets, compare_menus, discover_pages
from site_audit.report import to_csv

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
HOST = "127.0.0.1"
PORT = 8765

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_running = False


def _public_job(job: dict) -> dict:
    report = job.get("report")
    progress = job.get("progress")
    listing = job.get("listing")
    if report is None and listing is not None:
        return {
            "id": job["id"],
            "status": job["status"],
            "message": job.get("message", ""),
            "mode": "list",
            "url": listing.root,
            "notes": listing.notes,
            "stopped": listing.stopped,
            "childCount": len(listing.pages),
            "language": listing.language,
            "country": listing.country,
            "menuDiff": None if listing.menu_diff is None else {
                "shared": listing.menu_diff.get("shared", 0),
                "gnbOnly": listing.menu_diff.get("gnb_only", []),
                "fnbOnly": listing.menu_diff.get("fnb_only", []),
                "sameLabel": listing.menu_diff.get("same_label", []),
                "checks": listing.menu_diff.get("checks", {}),
            },
            "pages": [
                {
                    "url": page.url,
                    "kind": page.kind,
                    "depth": page.depth,
                    "parent": page.parent,
                    "title": page.title,
                    "group": page.group,
                    "discontinued": page.discontinued,
                    "product": page.product,
                    "outsideGnb": page.outside_gnb,
                    "id": page.id,
                    "blank": page.blank,
                    "missing": page.missing,
                    **(
                        {"itemCount": page.item_count, "itemSkus": page.item_skus}
                        if isinstance(page.item_count, int)
                        else {}
                    ),
                    **(
                        {
                            "siblingCount": page.sibling_count,
                            **(
                                {"activeCount": page.active_count}
                                if isinstance(page.active_count, int)
                                else {}
                            ),
                            **(
                                {"discontinuedCount": page.discontinued_count}
                                if isinstance(page.discontinued_count, int)
                                else {}
                            ),
                        }
                        if page.kind == "PLP"
                        else {}
                    ),
                }
                for page in listing.pages
            ],
        }
    if report is None:
        payload = {
            "id": job["id"],
            "status": job["status"],
            "message": job.get("message", ""),
            "url": job.get("url", ""),
            "mode": "list",
        }
        if job.get("status") == "running":
            payload["stopping"] = bool(job.get("cancel"))
            payload["progress"] = progress or {
                "step": "주소를 확인하는 중",
                "url": job.get("url", ""),
                "done": 0,
                "waiting": 0,
                "limit": 0,
            }
        return payload
    return {
        "id": job["id"],
        "status": job["status"],
        "message": job.get("message", ""),
        "url": job.get("url", ""),
        "notes": report.notes,
        "stopped": report.stopped,
        "childCount": report.child_count,
        "checked": report.checked,
        "failCount": report.fail_count,
        "passCount": report.pass_count,
        "reportReady": report.report_ready,
        "allPass": report.report_ready and report.fail_count == 0,
        "rows": [
            {"url": row.url, "kind": row.kind, "verdict": row.verdict, "reason": row.reason or "—"}
            for row in report.rows
        ],
    }


def _run(job_id: str, url: str) -> None:
    global _running

    def on_progress(event: dict) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is not None and job.get("status") == "running":
                job["progress"] = event

    try:
        def should_stop() -> bool:
            with _lock:
                current = _jobs.get(job_id)
                return bool(current and current.get("cancel"))

        listing = discover_pages(url, on_progress=on_progress, should_stop=should_stop)
        with _lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            if not listing.ok:
                job["status"] = "error"
                job["message"] = listing.message
            elif listing.stopped:
                job["status"] = "stopped"
                job["listing"] = listing
                job["message"] = "수집을 중지했습니다."
            else:
                job["status"] = "done"
                job["listing"] = listing
                job["message"] = ""
    except Exception:
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "error"
                job["message"] = "검사를 끝내지 못했습니다."
    finally:
        with _lock:
            _running = False


class Handler(BaseHTTPRequestHandler):
    server_version = "site-audit"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/all", "/compare") or path.startswith("/lists/"):
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/static/app.css":
            self._send(200, (STATIC / "app.css").read_bytes(), "text/css; charset=utf-8")
            return
        if path == "/static/app.js":
            self._send(200, (STATIC / "app.js").read_bytes(), "text/javascript; charset=utf-8")
            return
        if path == "/api/audits/current":
            with _lock:
                running = next((job for job in _jobs.values() if job.get("status") == "running"), None)
                payload = {"status": "idle"} if running is None else _public_job(running)
            self._json(200, payload)
            return
        if path.startswith("/api/audits/") and path.endswith("/report.csv"):
            job_id = path.removeprefix("/api/audits/").removesuffix("/report.csv")
            with _lock:
                job = _jobs.get(job_id)
                report = None if job is None else job.get("report")
            if job is None or report is None or not report.report_ready:
                self._json(404, {"message": "받을 보고서가 없습니다."})
                return
            body = to_csv(report).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=site-audit.csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/api/audits/"):
            job_id = path.removeprefix("/api/audits/")
            with _lock:
                job = _jobs.get(job_id)
                payload = None if job is None else _public_job(job)
            if payload is None:
                self._json(404, {"message": "검사를 찾지 못했습니다."})
                return
            self._json(200, payload)
            return
        self._json(404, {"message": "없는 주소입니다."})

    def do_POST(self) -> None:
        global _running
        path = urlparse(self.path).path
        if path.startswith("/api/audits/") and path.endswith("/stop"):
            job_id = path.removeprefix("/api/audits/").removesuffix("/stop").strip("/")
            with _lock:
                job = _jobs.get(job_id)
                if job is None:
                    self._json(404, {"message": "검사를 찾지 못했습니다."})
                    return
                if job.get("status") == "running":
                    job["cancel"] = True
                status = "stopping" if job.get("cancel") and job.get("status") == "running" else job.get("status")
            self._json(202, {"id": job_id, "status": status})
            return
        if path == "/api/page-check":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > 8000:
                self._json(400, {"message": "요청이 너무 깁니다."})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"message": "요청 형식이 올바르지 않습니다."})
                return
            url = payload.get("url") if isinstance(payload, dict) else None
            if not isinstance(url, str) or not url.strip():
                self._json(400, {"message": "주소가 비어 있습니다."})
                return
            kind = payload.get("kind") if isinstance(payload, dict) else None
            if kind is not None and kind not in ("일반", "PLP", "PDP", "Insights"):
                self._json(400, {"message": "유형을 다시 선택해 주세요."})
                return
            checked = check_page_assets(url.strip(), kind=kind if isinstance(kind, str) else None)
            if not checked.get("ok"):
                self._json(400, {
                    "message": checked.get("message") or "이 주소는 검사할 수 없습니다.",
                    "status": checked.get("status") or 0,
                })
                return
            self._json(200, checked)
            return
        if path == "/api/compare":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > 8000:
                self._json(400, {"message": "요청이 너무 깁니다."})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"message": "요청 형식이 올바르지 않습니다."})
                return
            url = payload.get("url") if isinstance(payload, dict) else None
            if not isinstance(url, str) or not url.strip():
                self._json(400, {"message": "주소가 비어 있습니다."})
                return
            diff = compare_menus(url.strip())
            if not diff.ok:
                self._json(400, {"message": diff.message})
                return
            self._json(200, {
                "url": diff.root,
                "language": diff.language,
                "country": diff.country,
                "message": diff.message,
                "shared": diff.shared,
                "gnbOnly": diff.gnb_only,
                "fnbOnly": diff.fnb_only,
                "sameLabel": diff.same_label,
                "checks": diff.checks,
            })
            return
        if path != "/api/audits":
            self._json(404, {"message": "없는 주소입니다."})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 8000:
            self._json(400, {"message": "요청이 너무 깁니다."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"message": "요청 형식이 올바르지 않습니다."})
            return
        url = payload.get("url") if isinstance(payload, dict) else None
        if not isinstance(url, str) or not url.strip():
            self._json(400, {"message": "주소가 비어 있습니다."})
            return
        with _lock:
            if _running:
                self._json(409, {"message": "이미 검사가 진행 중입니다."})
                return
            job_id = uuid.uuid4().hex
            _jobs[job_id] = {
                "id": job_id,
                "status": "running",
                "url": url.strip(),
                "message": "",
                "cancel": False,
            }
            if len(_jobs) > 20:
                for old in list(_jobs)[:-20]:
                    _jobs.pop(old, None)
            globals()["_running"] = True
        thread = threading.Thread(target=_run, args=(job_id, url.strip()), daemon=True)
        thread.start()
        self._json(202, {"id": job_id, "status": "running"})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"사이트 검수: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
