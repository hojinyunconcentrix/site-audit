"""루트 주소의 같은 호스트 페이지를 모아 유형과 통과·실패를 매긴다."""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from site_audit.guard import UrlRejected, check_url
from site_audit.http_fetch import (
    BLOCK_MESSAGE,
    HttpResult,
    fetch,
    hold_seconds,
    is_slow,
    limit_notice,
    reset_host_limits,
    set_slow_paths,
)
from site_audit.parse import (
    article_text,
    decode_html,
    extract,
    image_size,
    insight_contents,
    insight_endpoint,
    menu_listing,
    page_signals,
    page_title,
    viewport_assets,
    api_page_kind,
    plp_list_query,
    breadcrumbs,
    plp_targets,
    wa_type_links,
    selling_spec_rows,
    spec_sections,
    rival_spec_rows,
    diff_spec_rows,
    spec_check_sections,
    energy_sheet_from_rows,
    headline_text,
    dimension_state,
)

MAX_PAGES = 50
ASSET_KEEP = 3600.0

# 정상으로 확인한 링크·이미지는 잠시 기억해, 페이지마다 같은 메뉴 링크를 다시 부르지 않는다.
# 깨졌거나 확인하지 못한 주소는 기억하지 않아 다시 검수하면 새로 확인한다.
_asset_seen: dict[tuple[str, bool], float] = {}
_asset_lock = threading.Lock()


def _asset_known(url: str, image: bool) -> bool:
    with _asset_lock:
        at = _asset_seen.get((url, image))
        return at is not None and time.monotonic() - at < ASSET_KEEP


def _asset_remember(url: str, image: bool) -> None:
    with _asset_lock:
        _asset_seen[(url, image)] = time.monotonic()


def forget_assets() -> None:
    with _asset_lock:
        _asset_seen.clear()
MAX_DEPTH = 2
MAX_LINKS = 40
MAX_IMAGES = 20
MAX_SECONDS = 90
UNKNOWN_LANGUAGE = "언어를 확인하지 못함"
UNKNOWN_COUNTRY = "나라를 확인하지 못함"

LANG_KO = {
    "ko": "한국어",
    "en": "영어",
    "de": "독일어",
    "fr": "프랑스어",
    "es": "스페인어",
    "pt": "포르투갈어",
    "it": "이탈리아어",
    "nl": "네덜란드어",
    "ja": "일본어",
    "zh": "중국어",
    "pl": "폴란드어",
    "ru": "러시아어",
    "ar": "아랍어",
    "th": "태국어",
    "vi": "베트남어",
    "id": "인도네시아어",
    "tr": "터키어",
    "sv": "스웨덴어",
    "da": "덴마크어",
    "fi": "핀란드어",
    "cs": "체코어",
    "hu": "헝가리어",
    "el": "그리스어",
    "he": "히브리어",
    "uk": "우크라이나어",
    "ro": "루마니아어",
    "no": "노르웨이어",
    "nb": "노르웨이어",
    "ms": "말레이어",
    "hi": "힌디어",
}

COUNTRY_KO = {
    "kr": "한국",
    "us": "미국",
    "gb": "영국",
    "uk": "영국",
    "de": "독일",
    "fr": "프랑스",
    "jp": "일본",
    "cn": "중국",
    "tw": "대만",
    "hk": "홍콩",
    "sg": "싱가포르",
    "au": "호주",
    "ca": "캐나다",
    "br": "브라질",
    "mx": "멕시코",
    "in": "인도",
    "es": "스페인",
    "it": "이탈리아",
    "nl": "네덜란드",
    "pl": "폴란드",
    "se": "스웨덴",
    "at": "오스트리아",
    "ch": "스위스",
    "be": "벨기에",
    "ae": "아랍에미리트",
    "sa": "사우디아라비아",
    "th": "태국",
    "vn": "베트남",
    "id": "인도네시아",
    "my": "말레이시아",
    "ph": "필리핀",
    "nz": "뉴질랜드",
    "za": "남아프리카공화국",
    "tr": "튀르키예",
    "ru": "러시아",
    "cz": "체코",
    "hu": "헝가리",
    "pt": "포르투갈",
    "gr": "그리스",
    "dk": "덴마크",
    "fi": "핀란드",
    "no": "노르웨이",
    "ie": "아일랜드",
    "cl": "칠레",
    "co": "콜롬비아",
    "pe": "페루",
    "ar": "아르헨티나",
    "eg": "이집트",
    "il": "이스라엘",
    "ua": "우크라이나",
}

INSIGHT_MARKERS = ("/insights", "/lg-experience", "/blog/")

RULES_PATH = Path(__file__).with_name("rules.json")


@dataclass
class PageRow:
    url: str
    kind: str
    verdict: str
    reason: str


@dataclass
class ListedPage:
    url: str
    kind: str
    depth: int = 1
    parent: str = ""
    title: str = ""
    group: str = ""
    discontinued: bool = False
    product: bool = False
    outside_gnb: bool = False
    id: str = ""
    blank: bool = False
    missing: bool = False
    item_count: int | None = None
    item_skus: list[dict] = field(default_factory=list)
    sibling_count: int = 0
    active_count: int | None = None
    discontinued_count: int | None = None


@dataclass
class PageList:
    ok: bool
    message: str = ""
    root: str = ""
    pages: list[ListedPage] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stopped: bool = False
    language: str = ""
    country: str = ""
    menu_diff: dict | None = None


@dataclass
class MenuDiff:
    ok: bool
    message: str = ""
    root: str = ""
    language: str = ""
    country: str = ""
    shared: int = 0
    gnb_only: list[dict] = field(default_factory=list)
    fnb_only: list[dict] = field(default_factory=list)
    same_label: list[dict] = field(default_factory=list)
    checks: dict = field(default_factory=dict)


@dataclass
class AuditReport:
    ok: bool
    message: str = ""
    rows: list[PageRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stopped: bool = False
    child_count: int = 0
    checked: int = 0

    @property
    def report_ready(self) -> bool:
        return self.ok and self.child_count > 0 and len(self.rows) > 0

    @property
    def fail_count(self) -> int:
        return sum(1 for row in self.rows if row.verdict == "실패")

    @property
    def pass_count(self) -> int:
        return sum(1 for row in self.rows if row.verdict == "통과")


def load_rules(path: Path | None = None) -> dict:
    target = path or RULES_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("규칙 파일 형식")
    data.setdefault("path_contains", {})
    data.setdefault("ufn_marker", "")
    data.setdefault("thumbnail_min_width", None)
    data.setdefault("thumbnail_min_height", None)
    data.setdefault("plp_count_pattern", "")
    data.setdefault("slow_paths", [])
    data.setdefault("slow_gap", None)
    if path is None:
        set_slow_paths(data["slow_paths"], data["slow_gap"])
    return data


try:
    load_rules()
except (OSError, ValueError):
    pass


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def _path_parts(url: str) -> list[str]:
    return [part for part in (urlsplit(url).path or "").split("/") if part]


def _under_root(url: str, root_url: str) -> bool:
    if host_of(url) != host_of(root_url):
        return False
    root_parts = [part.lower() for part in _path_parts(root_url)]
    parts = [part.lower() for part in _path_parts(url)]
    if len(parts) <= len(root_parts):
        return False
    return parts[: len(root_parts)] == root_parts


def _url_for_parts(root_url: str, parts: list[str]) -> str:
    base = urlsplit(root_url)
    path = "/" + "/".join(parts)
    return f"{base.scheme}://{base.netloc}{path}"


def _ancestor_targets(url: str, root_url: str) -> list[str]:
    root_count = len(_path_parts(root_url))
    parts = _path_parts(url)
    return [_url_for_parts(root_url, parts[:index]) for index in range(root_count + 1, len(parts))]


def _path_key(url: str) -> tuple[str, ...]:
    return tuple(part.lower() for part in _path_parts(url))


def _page_identity(url: str) -> tuple:
    return (_path_key(url), urlsplit(url).query)


def _dedupe_pages(pages: list[ListedPage]) -> list[ListedPage]:
    kept: list[ListedPage] = []
    seen: set[tuple] = set()
    for page in pages:
        key = _page_identity(page.url)
        if key in seen:
            continue
        seen.add(key)
        kept.append(page)
    return kept


def _ensure_ancestors(pages: list[ListedPage], root_url: str, rules: dict) -> None:
    have = {_path_key(page.url) for page in pages}
    root_key = _path_key(root_url)
    for page in list(pages):
        parts = _path_parts(page.url)
        for index in range(len(root_key) + 1, len(parts)):
            key = tuple(part.lower() for part in parts[:index])
            if key in have or key == root_key:
                continue
            have.add(key)
            url = _url_for_parts(root_url, parts[:index])
            pages.append(ListedPage(url=url, kind=infer_kind(url, "", rules), depth=1, parent=root_url))


def _assign_places(pages: list[ListedPage], root_url: str) -> None:
    by_path: dict[tuple[str, ...], str] = {}
    for page in pages:
        key = _path_key(page.url)
        current = by_path.get(key)
        if current is None or (urlsplit(page.url).query == "" and urlsplit(current).query):
            by_path[key] = page.url
    root_count = len(_path_key(root_url))
    for page in pages:
        parts = _path_parts(page.url)
        extra = len(parts) - root_count
        page.depth = max(extra, 1)
        if extra <= 1:
            page.parent = root_url
            continue
        parent_key = tuple(part.lower() for part in parts[:-1])
        page.parent = by_path.get(parent_key) or _url_for_parts(root_url, parts[:-1])


def _attach_plp_children(pages: list[ListedPage], child_parent: dict[tuple, str], root_url: str) -> None:
    """PLP에서 찾은 페이징과 Learn more는 그 PLP 바로 아래에 둔다."""
    by_ident: dict[tuple, ListedPage] = {}
    for page in pages:
        by_ident.setdefault(_page_identity(page.url), page)
    root_ident = _page_identity(root_url)

    def _cycles(page: ListedPage, parent: ListedPage) -> bool:
        cursor: ListedPage | None = parent
        guard = 0
        while cursor is not None and guard <= len(pages):
            if cursor is page:
                return True
            parent_url = child_parent.get(_page_identity(cursor.url))
            cursor = by_ident.get(_page_identity(parent_url)) if parent_url else None
            guard += 1
        return False

    for _ in range(len(pages) + 1):
        changed = False
        for page in pages:
            parent_url = child_parent.get(_page_identity(page.url))
            if not parent_url or _page_identity(parent_url) == _page_identity(page.url):
                continue
            if _page_identity(parent_url) == root_ident:
                if page.parent != root_url or page.depth != 1:
                    page.parent = root_url
                    page.depth = 1
                    changed = True
                continue
            parent = by_ident.get(_page_identity(parent_url))
            if parent is None or parent is page or _cycles(page, parent):
                continue
            depth = parent.depth + 1
            if page.parent != parent.url or page.depth != depth:
                page.parent = parent.url
                page.depth = depth
                changed = True
        if not changed:
            break


def _split_locale(value: str) -> tuple[str, str]:
    text = (value or "").strip().replace("_", "-")
    if not text:
        return "", ""
    parts = [part for part in text.split("-") if part]
    lang = parts[0].lower() if parts else ""
    region = ""
    if len(parts) > 1 and 2 <= len(parts[1]) <= 3:
        region = parts[1].lower()
    return lang, region


def _locale_from_path(url: str) -> tuple[str, str]:
    parts = [part for part in (urlsplit(url).path or "").split("/") if part]
    if not parts:
        return "", ""
    segment = parts[0].lower()
    if "_" in segment:
        country, lang = segment.split("_", 1)
        country = country.lower()
        lang = lang.lower()
        if country in COUNTRY_KO and lang in LANG_KO:
            return lang, country
        return "", ""
    if segment in COUNTRY_KO:
        return "", segment
    return "", ""


def read_place(url: str, html: str) -> tuple[str, str]:
    signals = page_signals(html)
    lang, region = _split_locale(signals.get("lang", ""))
    path_lang, path_region = _locale_from_path(url)
    if not lang:
        lang = path_lang
    if not region:
        region = path_region
    language = LANG_KO.get(lang, "") if lang else ""
    country = COUNTRY_KO.get(region, "") if region else ""
    return language or UNKNOWN_LANGUAGE, country or UNKNOWN_COUNTRY


def _type_names(html: str) -> set[str]:
    names = set()
    for raw in page_signals(html).get("types") or []:
        names.add(str(raw).rstrip("/").split("/")[-1].lower())
    return names


def infer_kind(url: str, html: str, rules: dict) -> str:
    marked = api_page_kind(html)
    if marked:
        return marked
    kind, _has_rules = classify(url, rules)
    if kind != "일반":
        return kind
    path = (urlsplit(url).path or "/").lower()
    if any(marker in path for marker in INSIGHT_MARKERS):
        return "Insights"
    names = _type_names(html)
    if "product" in names:
        return "PDP"
    last = path.rstrip("/").split("/")[-1]
    if last.startswith("lg-") and any(char.isdigit() for char in last):
        return "PDP"
    return "일반"


def classify(url: str, rules: dict) -> tuple[str, bool]:
    mapping = rules.get("path_contains") or {}
    has_rules = any(needles for needles in mapping.values())
    path = (urlsplit(url).path or "/").lower()
    hits = []
    for kind, needles in mapping.items():
        for needle in needles or []:
            if needle and str(needle).lower() in path:
                hits.append(kind)
                break
    if not hits:
        return "일반", has_rules
    for kind in ("PDP", "PLP", "Insights", "일반"):
        if kind in hits:
            return kind, has_rules
    return hits[0], has_rules


def _join(reasons: list[str]) -> str:
    text = "; ".join(reasons)
    if len(text) > 500:
        return text[:497] + "..."
    return text


def _resource_reason(label: str, failures: list[str]) -> str:
    if not failures:
        return ""
    shown = failures[:3]
    extra = len(failures) - len(shown)
    body = ", ".join(shown)
    if extra > 0:
        body += f" 외 {extra}건"
    return f"{label}: {body}"


def _attach_limit(listing: PageList) -> PageList:
    notice = limit_notice()
    if notice and listing.ok and notice not in listing.notes:
        listing.notes.append(notice)
    return listing


def _emit(on_progress, step: str, url: str, done: int, waiting: int, limit: int = MAX_PAGES) -> None:
    if on_progress is None:
        return
    on_progress({
        "step": step,
        "url": url,
        "done": done,
        "waiting": waiting,
        "limit": limit,
    })


def _check_resources(
    urls: list[str],
    label: str,
    fetch_one,
    cap: int,
    tell,
    progress_label: str,
) -> tuple[list[str], bool]:
    reasons = []
    capped = len(urls) > cap
    checking = urls[:cap]
    total = len(checking)
    for index, target in enumerate(checking, start=1):
        tell(f"{progress_label} {index}/{total}", target)
        result: HttpResult = fetch_one(target, read_body=False)
        if result.error or not (200 <= result.status <= 299):
            detail = result.error or str(result.status or "응답 없음")
            reasons.append(f"{result.url or target} ({detail})")
    text = _resource_reason(label, reasons)
    if text:
        reasons_out = [text]
    else:
        reasons_out = []
    if capped:
        reasons_out.append(f"{label}는 {cap}개까지 확인했습니다")
    return reasons_out, capped


def _type_reasons(kind: str, html: str, page_url: str, images: list[str], rules: dict, fetch_one, tell) -> list[str]:
    if kind == "PLP":
        tell("PLP 수량을 확인하는 중", page_url)
        pattern = (rules.get("plp_count_pattern") or "").strip()
        if not pattern:
            return ["PLP 수량 위치 없음"]
        try:
            matched = re.search(pattern, html)
        except re.error:
            return ["PLP 수량 위치 없음"]
        if not matched or not matched.groups():
            return ["PLP 수량 위치 없음"]
        try:
            count = int(matched.group(1))
        except (TypeError, ValueError):
            return ["PLP 수량 위치 없음"]
        if count == 0:
            return ["PLP 수량 0"]
        return []
    if kind == "PDP":
        tell("UFN을 확인하는 중", page_url)
        marker = (rules.get("ufn_marker") or "").strip()
        if not marker:
            return ["UFN 기준 없음"]
        if marker not in html:
            return ["UFN 없음"]
        return []
    if kind == "Insights":
        tell("썸네일 크기를 확인하는 중", page_url)
        width = rules.get("thumbnail_min_width")
        height = rules.get("thumbnail_min_height")
        if not isinstance(width, int) or not isinstance(height, int):
            return ["썸네일 크기 기준 없음"]
        if not images:
            return ["썸네일 없음"]
        result = fetch_one(images[0], read_body=True)
        if result.error or not (200 <= result.status <= 299):
            return ["썸네일 크기를 확인하지 못함"]
        size = image_size(result.body)
        if size is None:
            return ["썸네일 크기를 확인하지 못함"]
        got_w, got_h = size
        if got_w < width or got_h < height:
            return [f"썸네일 크기 {got_w}x{got_h}"]
        return []
    return []


VIEWPORTS = (
    ("Mobile", 390),
    ("Tablet", 768),
    ("PC", 1440),
)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        kept.append(value)
    return kept


def _jwt_organization(token: str) -> str:
    parts = token.split(".")
    if len(parts) < 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[1]):
        return ""
    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return ""
    org = data.get("organization") if isinstance(data, dict) else ""
    if isinstance(org, str) and re.fullmatch(r"[A-Za-z0-9]+", org):
        return org
    return ""


def _raw_text(raw: dict, key: str) -> str:
    value = raw.get(key)
    if isinstance(value, list):
        value = next((part for part in value if isinstance(part, str) and part.strip()), "")
    if not isinstance(value, str):
        return ""
    return value.strip()


def _result_item(item: dict) -> dict | None:
    raw = item.get("raw") if isinstance(item, dict) else None
    if not isinstance(raw, dict):
        return None
    sku = _raw_text(raw, "ec_sku")
    if not sku:
        return None
    status = _raw_text(raw, "ec_model_status_code")
    product = {"sku": sku, "discontinued": status.upper() == "DISCONTINUED"}
    url = _raw_text(raw, "ec_model_url_path")
    title = _raw_text(raw, "ec_user_friendly_name")
    if url:
        product["url"] = url
    if title:
        product["title"] = title
    return product


def _model_sku(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    sku = item.get("sku")
    if isinstance(sku, str) and sku.strip():
        return sku.strip()
    raw = item.get("raw")
    if isinstance(raw, dict):
        return _raw_text(raw, "ec_sku")
    return ""


def _sibling_entries(item: dict) -> list:
    """Coveo childResults가 화면의 siblingModels다."""
    if not isinstance(item, dict):
        return []
    models = item.get("siblingModels")
    if isinstance(models, list):
        return models
    children = item.get("childResults")
    if isinstance(children, list):
        return children
    return []


def _model_status(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    if item.get("discontinued") is True:
        return "DISCONTINUED"
    for key in ("modelStatusCode", "ec_model_status_code"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    raw = item.get("raw")
    if isinstance(raw, dict):
        return _raw_text(raw, "ec_model_status_code").upper()
    return ""


def _sibling_model_count(item: dict, *, include_discontinued: bool = False) -> int:
    """화면에 나오는 sibling만 센다. 자기 sku는 뺀다.

    Active 카드의 Discontinued 모델은 버튼이 없어 뺀다.
    Discontinued 화면에서는 그 버튼이 보이므로 포함한다.
    """
    own = _model_sku(item)
    count = 0
    for model in _sibling_entries(item):
        sku = _model_sku(model)
        if not sku or sku == own:
            continue
        if not include_discontinued and _model_status(model) == "DISCONTINUED":
            continue
        count += 1
    return count


def _status_counts(data: dict) -> dict[str, int]:
    """화면 필터에 표시되는 Active·Discontinued 개수."""
    found: dict[str, int] = {}
    facets = data.get("facets") if isinstance(data, dict) else None
    if not isinstance(facets, list):
        return found
    for facet in facets:
        if not isinstance(facet, dict):
            continue
        field = str(facet.get("field") or facet.get("facetId") or "")
        if field != "ec_model_status_code":
            continue
        values = facet.get("values")
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            name = str(value.get("value") or "").strip().upper()
            count = value.get("numberOfResults")
            if name and isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                found[name] = count
    return found


def _search_page(request, search: str, token: str, payload: dict) -> dict | None:
    try:
        result = request(
            search,
            body=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}"},
        )
    except TypeError:
        return None
    if result.error or not (200 <= result.status <= 299):
        return None
    try:
        data = json.loads(result.body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _result_batch(data: dict) -> list:
    listed = data.get("productList")
    batch = listed if isinstance(listed, list) else data.get("results")
    return batch if isinstance(batch, list) else []


def _append_discontinued_skus(skus: list[dict], request, search: str, token: str, spec: dict) -> int:
    """Discontinued 필터 화면의 카드와 그 카드에 보이는 sibling 버튼 수를 맞춘다."""
    by_sku = {item.get("sku"): item for item in skus if item.get("sku")}
    added = 0
    aq = f'{spec["aq"]} AND @ec_model_status_code=="DISCONTINUED"'
    first = 0
    total: int | None = None
    page_size = 100
    while first < 500:
        data = _search_page(request, search, token, {
            "q": "",
            "aq": aq,
            "searchHub": spec["searchHub"],
            "firstResult": first,
            "numberOfResults": page_size,
            "fieldsToInclude": ["ec_sku", "ec_model_status_code", "ec_model_url_path", "ec_user_friendly_name"],
        })
        if data is None:
            return added
        count = data.get("totalCountFiltered")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            total = count
        batch = _result_batch(data)
        if not batch:
            return added
        for item in batch:
            if not isinstance(item, dict):
                continue
            product = _result_item(item)
            if not product:
                continue
            visible = _sibling_model_count(item, include_discontinued=True)
            current = by_sku.get(product["sku"])
            if current is not None:
                if not current.get("discontinued"):
                    continue
                previous = current.get("siblings") if isinstance(current.get("siblings"), int) else 0
                current["siblings"] = visible
                added += visible - previous
                continue
            product["discontinued"] = True
            product["siblings"] = visible
            skus.append(product)
            by_sku[product["sku"]] = product
            added += visible
        first += len(batch)
        if total is not None and first >= total:
            return added
        if len(batch) < page_size:
            return added
    return added


def _plp_item_count(html: str, page_url: str, request) -> tuple[int | None, list[dict], int, int | None, int | None]:
    """PLP 제품 수, SKU, sibling 수, 화면 Active·Discontinued 수. 검색 토큰은 결과로 남기지 않는다."""
    spec = plp_list_query(html, page_url)
    if spec is None:
        return None, [], 0, None, None
    token_page = request(spec["tokenUrl"])
    if token_page.error or not (200 <= token_page.status <= 299):
        return None, [], 0, None, None
    try:
        token = json.loads(token_page.body.decode("utf-8", errors="replace")).get("token")
    except json.JSONDecodeError:
        return None, [], 0, None, None
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        return None, [], 0, None, None
    org = _jwt_organization(token)
    if not org:
        return None, [], 0, None, None
    search = f"https://{org}.org.coveo.com/rest/search/v2?organizationId={org}"
    skus: list[dict] = []
    siblings = 0
    first = 0
    total: int | None = None
    status_counts: dict[str, int] = {}
    page_size = 100
    while first < 500:
        payload = {
            "q": "",
            "aq": spec["aq"],
            "searchHub": spec["searchHub"],
            "firstResult": first,
            "numberOfResults": page_size,
            "fieldsToInclude": ["ec_sku", "ec_model_status_code", "ec_model_url_path", "ec_user_friendly_name"],
        }
        if first == 0:
            payload["facets"] = [{
                "facetId": "ec_model_status_code",
                "field": "ec_model_status_code",
                "type": "specific",
                "numberOfValues": 8,
            }]
        data = _search_page(request, search, token, payload)
        if data is None:
            return None, [], 0, None, None
        if first == 0:
            status_counts = _status_counts(data)
        count = data.get("totalCountFiltered")
        if not isinstance(count, bool) and isinstance(count, int) and count >= 0:
            total = count
        batch = _result_batch(data)
        if not batch:
            break
        for item in batch:
            product = _result_item(item if isinstance(item, dict) else {})
            visible = 0
            if isinstance(item, dict):
                visible = _sibling_model_count(
                    item,
                    include_discontinued=bool(product and product.get("discontinued")),
                )
            siblings += visible
            if product:
                product["siblings"] = visible
                skus.append(product)
        first += len(batch)
        if total is not None and first >= total:
            break
        if len(batch) < page_size:
            break
    if total is None:
        return None, [], 0, None, None
    active_count = status_counts.get("ACTIVE")
    discontinued_count = status_counts.get("DISCONTINUED")
    if isinstance(discontinued_count, int) and discontinued_count > 0:
        siblings += _append_discontinued_skus(skus, request, search, token, spec)
    if isinstance(active_count, int) and isinstance(discontinued_count, int):
        total = active_count + discontinued_count
    return total, skus, siblings, active_count, discontinued_count


def _asset_state(result: HttpResult, *, image: bool) -> str:
    if result.status == 404:
        return "404"
    if image and not result.error and 200 <= result.status <= 299 and "text/html" in (result.content_type or "").lower():
        return "이미지가 아님"
    return ""


def _thumb_urls(item: dict, page_url: str) -> list[str]:
    urls: list[str] = []
    for key in ("mobileImageAddr", "tabletImageAddr", "desktopImageAddr"):
        raw = str(item.get(key) or "").strip()
        if not raw:
            continue
        absolute = urljoin(page_url, raw)
        if absolute not in urls:
            urls.append(absolute)
    return urls


def _insight_image(item: dict, width: int) -> str:
    if width <= 767:
        key = "mobileImageAddr"
    elif width <= 1023:
        key = "tabletImageAddr"
    else:
        key = "desktopImageAddr"
    return str(item.get(key) or "").strip()


def _insight_more_items(page_url: str, html: str, request) -> tuple[list[dict], list[dict], int]:
    """더보기 전체 글, 중복 글, 주소가 있는 글 수."""
    endpoint = insight_endpoint(html)
    if not endpoint:
        return [], [], 0
    target = urljoin(page_url, endpoint)
    found: list[dict] = []
    candidates: list[tuple[dict, dict]] = []
    seen: dict[str, dict] = {}
    titles: dict[str, list[dict]] = {}
    content_total = 0
    total = 0
    for number in range(1, 81):
        payload = json.dumps({
            "searchKeyword": "",
            "sortBy": "",
            "page": str(number),
            "hashTag": "",
            "selectedFilterList": [],
        }).encode("utf-8")
        result = request(target, payload)
        if result.error or not (200 <= result.status <= 299):
            break
        try:
            data = json.loads(result.body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            break
        block = (data.get("insightLists") or [{}])[0] or {}
        total = int(block.get("totalCnt") or total or 0)
        batch = block.get("insightList") or []
        if not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            content_total += 1
            title = " ".join(str(item.get("title") or "").split())
            key = title.casefold()
            url = urljoin(page_url, path)
            thumbs = _thumb_urls(item, page_url)
            story = {
                "title": title,
                "key": key,
                "url": url,
                "path": path,
                "thumbs": thumbs,
                "image": thumbs[0] if thumbs else "",
            }
            earlier = _same_title_image(story, seen.get(path), titles.get(key, []))
            if earlier:
                candidates.append((story, earlier))
            if path in seen:
                continue
            seen[path] = story
            if key:
                titles.setdefault(key, []).append(story)
            found.append(item)
        if total and len(seen) >= total:
            break
    return found, _same_content(candidates, request), content_total


def _image_stem(url: str) -> str:
    name = urlsplit(url).path.rsplit("/", 1)[-1].lower()
    stem, dot, _ext = name.rpartition(".")
    return stem if dot else name


def _thumb_relation(left: list[str], right: list[str]) -> str:
    if set(left) & set(right):
        return "exact"
    stems = {_image_stem(url) for url in right if _image_stem(url)}
    if any(_image_stem(url) in stems for url in left):
        return "stem"
    return ""


def _same_title_image(story: dict, same_path: dict | None, titled: list[dict]) -> dict | None:
    """제목이 같고 썸네일 주소 또는 파일 이름이 같은 앞선 글."""
    if not story["key"] or not story["thumbs"]:
        return None
    pool = [same_path] if same_path else titled
    for earlier in pool:
        if not earlier or earlier["key"] != story["key"]:
            continue
        if _thumb_relation(story["thumbs"], earlier["thumbs"]):
            return earlier
    return None


def _same_content(candidates: list[tuple[dict, dict]], request) -> list[dict]:
    """제목·이미지가 같은 글의 본문이 같을 때만 중복으로 남긴다."""
    texts: dict[str, str] = {}
    sizes: dict[str, tuple[int, int] | None] = {}

    def body(url: str) -> str:
        if url not in texts:
            result = request(url)
            if result.error or not (200 <= result.status <= 299):
                texts[url] = ""
            else:
                html = decode_html(result.body, result.content_type)
                texts[url] = article_text(html)
        return texts[url]

    def pixels(url: str) -> tuple[int, int] | None:
        if url not in sizes:
            result = request(url)
            if result.error or not (200 <= result.status <= 299):
                sizes[url] = None
            else:
                sizes[url] = image_size(result.body or b"")
        return sizes[url]

    def pictures_match(story: dict, earlier: dict) -> bool:
        relation = _thumb_relation(story["thumbs"], earlier["thumbs"])
        if relation == "exact":
            return True
        if relation != "stem":
            return False
        stems = {_image_stem(url): url for url in earlier["thumbs"]}
        for left in story["thumbs"]:
            right = stems.get(_image_stem(left))
            if not right:
                continue
            size = pixels(left)
            if size and size == pixels(right):
                return True
        return False

    duplicates: list[dict] = []
    for story, earlier in candidates:
        if not pictures_match(story, earlier):
            continue
        left = body(story["url"])
        right = body(earlier["url"])
        if not left or left != right:
            continue
        duplicates.append({
            "title": story["title"],
            "url": story["url"],
            "image": story["image"],
            "otherTitle": earlier["title"],
            "otherUrl": earlier["url"],
            "otherImage": earlier["image"],
            "detail": "같은 제목 · 같은 이미지 · 같은 내용",
        })
    return duplicates


def _add_insight_items(assets: dict, items: list[dict], page_url: str, width: int) -> None:
    for item in items:
        path = str(item.get("path") or "").strip()
        if path:
            url = urljoin(page_url, path)
            assets["links"].append(url)
            title = str(item.get("title") or "").strip()
            if title:
                assets.setdefault("linkTitles", {})[url] = title
        image = _insight_image(item, width)
        if image:
            assets["images"].append(urljoin(page_url, image))
            continue
        label = str(item.get("altText") or item.get("title") or "이미지").strip() or "이미지"
        assets["missing"].append(label)


def _thumbnail_views(items: list[dict], page_url: str, request) -> list[dict]:
    """화면 폭마다 더보기 썸네일 중 가장 많은 크기와 다른 글을 고른다."""
    grouped: list[tuple[str, int, list[tuple[str, str, str]]]] = []
    urls: list[str] = []
    for name, width in VIEWPORTS:
        rows: list[tuple[str, str, str]] = []
        for item in items:
            image = _insight_image(item, width)
            if not image:
                continue
            path = str(item.get("path") or "").strip()
            title = " ".join(str(item.get("title") or "").split())
            image_url = urljoin(page_url, image)
            rows.append((title, urljoin(page_url, path) if path else image_url, image_url))
            urls.append(image_url)
        grouped.append((name, width, rows))

    sizes: dict[str, tuple[int, int] | None] = {}

    def measure(url: str) -> tuple[str, tuple[int, int] | None]:
        result = request(url)
        if result.error or not (200 <= result.status <= 299):
            return url, None
        if "text/html" in (result.content_type or "").lower():
            return url, None
        return url, image_size(result.body or b"")

    unique = _unique(urls)
    if unique:
        with ThreadPoolExecutor(max_workers=min(6, len(unique))) as pool:
            for url, size in pool.map(measure, unique):
                sizes[url] = size

    views = []
    for name, width, rows in grouped:
        measured = [(title, page, sizes[image]) for title, page, image in rows if sizes.get(image)]
        counts: dict[tuple[int, int], int] = {}
        first: dict[tuple[int, int], int] = {}
        for index, (*_item, size) in enumerate(measured):
            counts[size] = counts.get(size, 0) + 1
            first.setdefault(size, index)
        common = max(counts, key=lambda size: (counts[size], -first[size])) if counts else None
        different = []
        if common is not None:
            for title, page, size in measured:
                if size == common:
                    continue
                different.append({
                    "title": title,
                    "url": page,
                    "detail": f"{size[0]}x{size[1]} (기준 {common[0]}x{common[1]})",
                })
        views.append({
            "name": name,
            "width": width,
            "total": len(rows),
            "different": different,
            "unread": bool(rows) and not measured,
        })
    return views


def _with_scheme(url: str) -> str:
    text = (url or "").strip()
    if not text or re.match(r"^[a-z][a-z0-9+.-]*:", text, re.I):
        return text
    return "https://" + text.lstrip("/")


def _spec_compare_page(compare_url: str, source_html: str, request, resolve) -> dict:
    """비교 주소의 펼친 스펙과 All Spec이 다른 항목만 돌려준다."""
    raw = _with_scheme(compare_url)
    empty = {"ok": False, "url": raw, "sourceFound": False, "compareFound": False, "rows": []}
    try:
        kwargs = {"resolve": resolve} if resolve is not None else {}
        target = check_url(raw, **kwargs)
    except UrlRejected as exc:
        return {**empty, "message": exc.message}
    page = request(target.url)
    if getattr(page, "error", "") == BLOCK_MESSAGE:
        return {**empty, "url": target.url, "message": BLOCK_MESSAGE}
    if page.status == 404 or page.error or not (200 <= page.status <= 299):
        return {**empty, "url": page.url or target.url, "message": "비교 주소를 읽지 못했습니다."}
    compare_html = decode_html(page.body, page.content_type)
    source_rows = selling_spec_rows(source_html)
    rival_rows = rival_spec_rows(compare_html)
    source_found = source_rows is not None
    compare_found = rival_rows is not None
    rows = diff_spec_rows(source_rows or [], rival_rows or []) if source_found and compare_found else []
    sections = spec_check_sections(source_rows or [], rival_rows or []) if source_found and compare_found else []
    return {
        "ok": True,
        "url": page.url or target.url,
        "sourceFound": source_found,
        "compareFound": compare_found,
        "rows": rows,
        "sections": sections,
        "energySheet": energy_sheet_from_rows(source_html, rival_rows or [], compare_html),
    }


def check_page_assets(root: str, *, rules: dict | None = None, fetch_one=None, resolve=None, kind: str | None = None, compare_url: str | None = None) -> dict:
    """한 페이지를 화면 폭마다 읽어 깨진 링크, 없는 이미지, 깨진 이미지를 나눈다."""
    try:
        kwargs = {"resolve": resolve} if resolve is not None else {}
        target = check_url(root, **kwargs)
    except UrlRejected as exc:
        return {"ok": False, "message": exc.message}

    limited_hits: list[str] = []

    def limited(status: int = 429) -> dict:
        # 호스트가 닫혀 있으면 화면이 그 시간만큼 기다렸다가 같은 주소부터 이어 간다.
        wait = hold_seconds(target.hostname) if fetch_one is None else 0.0
        return {"ok": False, "status": status, "message": BLOCK_MESSAGE, "retryIn": int(wait + 0.999)}

    def request(url: str, body: bytes | None = None, headers: dict | None = None) -> HttpResult:
        if fetch_one is not None:
            if headers:
                try:
                    result = fetch_one(url, read_body=True, body=body, headers=headers)
                except TypeError:
                    result = HttpResult(url=url, status=0, content_type="", body=b"", error="연결 실패")
            else:
                try:
                    result = fetch_one(url, read_body=True, body=body)
                except TypeError:
                    result = fetch_one(url)
        else:
            result = fetch(url, read_body=True, body=body, resolve=resolve, headers=headers)
        if getattr(result, "error", "") == BLOCK_MESSAGE:
            limited_hits.append(url)
        return result

    def probe(url: str) -> HttpResult:
        if fetch_one is not None:
            try:
                result = fetch_one(url, read_body=False)
            except TypeError:
                result = fetch_one(url)
        else:
            result = fetch(url, read_body=False, resolve=resolve)
        return result

    page = request(target.url)
    if page.error == BLOCK_MESSAGE:
        return limited(page.status or 429)
    if page.status == 404:
        return {"ok": False, "status": 404, "message": "404"}
    if page.error or not (200 <= page.status <= 299):
        return {"ok": False, "message": "페이지를 읽지 못했습니다."}
    html = decode_html(page.body, page.content_type)
    page_url = page.url or target.url
    active_rules = rules if rules is not None else load_rules()
    inferred = infer_kind(page_url, html, active_rules)
    chosen = kind if kind in ("일반", "PLP", "PDP", "Insights") else inferred
    language, country = read_place(page_url, html)
    more_items: list[dict] = []
    duplicates: list[dict] = []
    content_total = 0
    if chosen == "Insights" and _insight_listing(page_url):
        more_items, duplicates, content_total = _insight_more_items(page_url, html, request)
        if limited_hits:
            return limited()
    gathered = []
    pending: dict[str, bool] = {}
    for name, width in VIEWPORTS:
        assets = viewport_assets(html, page_url, width)
        _add_insight_items(assets, more_items, page_url, width)
        gathered.append((name, width, assets))
        for url in assets["links"]:
            pending.setdefault(url, False)
        for url in assets["images"]:
            pending[url] = True

    keep = fetch_one is None

    def one(item: tuple[str, bool]) -> tuple[str, str]:
        url, image = item
        if keep and _asset_known(url, image):
            return url, ""
        try:
            result = probe(url)
        except Exception:
            # 주소 하나에서 난 오류로 페이지 검수 전체가 멈추지 않게 한다.
            return url, ""
        # 링크나 이미지 하나가 막힌 것은 그 주소만 확인하지 못한 것으로 두고, 페이지 검수는 이어 간다.
        if result.error:
            return url, ""
        state = _asset_state(result, image=image)
        if keep and not state and 200 <= result.status <= 299:
            _asset_remember(url, image)
        return url, state

    states: dict[str, str] = {}
    if pending:
        # 느린 경로는 뒤로 보내, 기다리는 동안 다른 주소 확인이 밀리지 않게 한다.
        ordered = sorted(pending.items(), key=lambda item: is_slow(item[0]))
        with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
            for url, detail in pool.map(one, ordered):
                states[url] = detail

    viewports = []
    for name, width, assets in gathered:
        links = _unique(assets["links"])
        images = _unique(assets["images"])
        missing = _unique(assets["missing"])
        missing_tags = assets.get("missingTags") or {}
        image_tags = assets.get("imageTags") or {}
        titles = assets.get("linkTitles") or {}
        viewports.append({
            "name": name,
            "width": width,
            "linkTotal": len(links),
            "imageTotal": len(images) + len(missing),
            "brokenLinks": [
                {"url": url, "detail": states[url], "title": titles.get(url, "")}
                for url in links if states.get(url)
            ],
            "missingImages": [{"text": label, "tag": missing_tags.get(label, "")} for label in missing],
            "brokenImages": [
                {"url": url, "detail": states[url], "tag": image_tags.get(url, "")}
                for url in images if states.get(url)
            ],
        })
    result = {
        "ok": True,
        "url": page_url,
        "title": page_title(html),
        "kind": chosen,
        "language": language,
        "country": country,
        "viewports": viewports,
    }
    if chosen == "Insights" and _insight_listing(page_url):
        result["listing"] = {
            "contentTotal": content_total,
            "duplicates": duplicates,
            "thumbnails": _thumbnail_views(more_items, page_url, request),
        }
    if chosen == "PLP":
        count, skus, siblings, active_count, discontinued_count = _plp_item_count(html, page_url, request)
        if limited_hits:
            return limited()
        result["itemCount"] = count
        result["itemSkus"] = skus
        result["siblingCount"] = siblings
        if isinstance(active_count, int):
            result["activeCount"] = active_count
        if isinstance(discontinued_count, int):
            result["discontinuedCount"] = discontinued_count
    if limited_hits:
        return limited()
    if chosen == "PDP":
        source_rows = selling_spec_rows(html)
        result["allSpec"] = {
            "found": source_rows is not None,
            "sections": spec_sections(source_rows),
        }
        result["energySheet"] = energy_sheet_from_rows(html, [])
        result["ufn"] = headline_text(html)
        result["dimension"] = dimension_state(html)
    if chosen == "PDP" and (compare_url or "").strip():
        compared = _spec_compare_page(compare_url or "", html, request, resolve)
        sheet = compared.pop("energySheet", None)
        result["specCompare"] = compared
        if sheet:
            result["energySheet"] = sheet
    return result


def judge_page(url: str, html: str, rules: dict, fetch_one, tell=None) -> PageRow:
    if tell is None:
        tell = lambda *_args: None
    kind, _has_rules = classify(url, rules)
    links, images = extract(html, url)
    reasons: list[str] = []
    link_reasons, _capped = _check_resources(links, "깨진 링크", fetch_one, MAX_LINKS, tell, "링크를 확인하는 중")
    image_reasons, _image_cap = _check_resources(images, "깨진 이미지", fetch_one, MAX_IMAGES, tell, "이미지를 확인하는 중")
    reasons.extend(link_reasons)
    reasons.extend(image_reasons)
    reasons.extend(_type_reasons(kind, html, url, images, rules, fetch_one, tell))
    # 상한 안내만 있고 실제 실패가 없으면 통과로 둔다.
    hard = [item for item in reasons if "까지 확인했습니다" not in item]
    if hard:
        return PageRow(url=url, kind=kind, verdict="실패", reason=_join(reasons))
    note = _join(reasons)
    return PageRow(url=url, kind=kind, verdict="통과", reason=note)


def run_audit(root: str, *, rules: dict | None = None, fetch_one=None, resolve=None, on_progress=None) -> AuditReport:
    if fetch_one is None:
        reset_host_limits()
    getter = fetch_one or (lambda url, read_body=True: fetch(url, read_body=read_body, resolve=resolve))
    _emit(on_progress, "주소를 확인하는 중", root, 0, 0)
    try:
        kwargs = {"resolve": resolve} if resolve is not None else {}
        root_target = check_url(root, **kwargs)
    except UrlRejected as exc:
        return AuditReport(ok=False, message=exc.message)
    active_rules = rules if rules is not None else load_rules()
    has_type_rules = any((active_rules.get("path_contains") or {}).values())
    started = time.monotonic()
    queue: deque[tuple[str, int]] = deque([(root_target.url, 0)])
    seen = set()
    rows: list[PageRow] = []
    stopped = False
    root_host = root_target.hostname
    notes = []
    if not has_type_rules:
        notes.append("유형 표식 없음. PLP·PDP·Insights 전용 검사는 하지 않음. 통과는 깨진 링크·깨진 이미지에 한정.")

    while queue:
        if len(rows) >= MAX_PAGES:
            stopped = True
            break
        if time.monotonic() - started > MAX_SECONDS:
            stopped = True
            break
        url, depth = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if host_of(url) != root_host:
            continue
        _emit(on_progress, "페이지를 읽는 중", url, len(rows), len(queue))
        result = getter(url, read_body=True)
        if result.error or not (200 <= result.status <= 299):
            detail = result.error or str(result.status or "응답 없음")
            if result.error == BLOCK_MESSAGE and BLOCK_MESSAGE not in notes:
                notes.append(BLOCK_MESSAGE)
            if url == root_target.url and not rows:
                message = BLOCK_MESSAGE if result.error == BLOCK_MESSAGE else "루트 페이지를 읽지 못했습니다."
                return AuditReport(ok=False, message=message)
            rows.append(PageRow(url=url, kind="일반", verdict="실패", reason=f"페이지를 읽지 못함 ({detail})"))
            continue
        content_type = result.content_type.lower()
        html = decode_html(result.body, result.content_type)
        if "html" not in content_type and not html.lstrip().startswith("<"):
            rows.append(PageRow(url=result.url or url, kind="일반", verdict="실패", reason="HTML이 아님"))
            continue
        page_url = result.url or url
        if host_of(page_url) != root_host:
            if not rows:
                return AuditReport(ok=False, message="루트가 다른 주소로 이동했습니다.")
            rows.append(PageRow(url=url, kind="일반", verdict="실패", reason="다른 호스트로 이동"))
            continue
        def tell(step: str, target: str) -> None:
            _emit(on_progress, step, target, len(rows), len(queue))

        row = judge_page(page_url, html, active_rules, getter, tell)
        rows.append(row)
        if depth < MAX_DEPTH and len(rows) < MAX_PAGES:
            links, _images = extract(html, page_url)
            for link in links:
                if host_of(link) == root_host and link not in seen:
                    queue.append((link, depth + 1))

    if stopped:
        notes.append("수집 상한에서 중단. 못 본 주소는 통과로 넣지 않음.")
    child_count = max(0, len(rows) - 1)
    if child_count == 0:
        notes.append("같은 주소의 하위 페이지가 없습니다.")
    _emit(on_progress, "결과를 정리하는 중", root_target.url, len(rows), 0)
    return AuditReport(
        ok=True,
        rows=rows,
        notes=notes,
        stopped=stopped,
        child_count=child_count,
        checked=len(rows),
    )


def _status_url(url: str, status: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["ec_model_status_code"] = [status]
    flat = urlencode([(key, value) for key, values in query.items() for value in values])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, flat, ""))


def _insight_listing(url: str) -> bool:
    parts = urlsplit(url)
    path = (parts.path or "").rstrip("/").lower()
    if not path.endswith("/insights"):
        return False
    query = {key.lower(): values for key, values in parse_qs(parts.query).items()}
    return not query.get("contentsformat")


def _insight_stories(page_url: str, html: str, request, contents: str, should_stop=None) -> list[tuple[str, str]]:
    """Contents 하나를 선택한 뒤 More로 이어지는 글의 제목과 주소."""
    endpoint = insight_endpoint(html)
    if not endpoint or not contents:
        return []
    category = ""
    for value in parse_qs(urlsplit(page_url).query).get("category") or []:
        category = value
        break
    target = urljoin(page_url, endpoint)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    total = 0
    filters = []
    if category:
        filters.append({"ec_solution_category": category})
    filters.append({"ec_contents_format": contents})
    for number in range(1, 81):
        if should_stop and should_stop():
            break
        payload = {
            "searchKeyword": "",
            "sortBy": "",
            "page": str(number),
            "hashTag": "",
            "selectedFilterList": filters,
        }
        result = request(target, body=json.dumps(payload).encode("utf-8"))
        if result.error or not (200 <= result.status <= 299):
            break
        try:
            data = json.loads(result.body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            break
        block = (data.get("insightLists") or [{}])[0] or {}
        total = int(block.get("totalCnt") or total or 0)
        batch = block.get("insightList") or []
        if not batch:
            break
        for item in batch:
            path = str(item.get("path") or "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            title = str(item.get("title") or "").strip() or path
            found.append((title, urljoin(page_url, path)))
        if total and len(seen) >= total:
            break
    return found


def _read_page_kind(request, url: str) -> tuple[str, str, int | None, list[dict], list[dict], bool, list[dict], int, int | None, int | None]:
    try:
        result = request(url)
    except Exception:
        return url, "", None, [], [], False, [], 0, None, None
    if result.error or not (200 <= result.status <= 299):
        return url, "", None, [], [], result.status == 404, [], 0, None, None
    html = decode_html(result.body, result.content_type)
    page_url = result.url or url
    links = wa_type_links(html, page_url)
    crumbs = breadcrumbs(html, page_url)
    kind = api_page_kind(html)
    if kind != "PLP":
        return url, kind, None, [], links, False, crumbs, 0, None, None
    count, skus, siblings, active_count, discontinued_count = _plp_item_count(html, page_url, request)
    return url, kind, count, skus, links, False, crumbs, siblings, active_count, discontinued_count


def _mark_page_kinds(listing: PageList, request, on_progress, should_stop, only: set[str] | None = None) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """주소가 있는 메뉴 페이지를 최대 6개씩 읽어 PLP·PDP API가 있으면 그 유형으로 둔다."""
    root_host = host_of(listing.root)
    targets = [
        page for page in listing.pages
        if page.url and not page.blank and page.kind != "Insights" and host_of(page.url) == root_host
        and (only is None or page.url in only)
    ]
    urls: list[str] = []
    for page in targets:
        if page.url not in urls:
            urls.append(page.url)
    found: dict[str, tuple[str, int | None, list[dict], bool, int, int | None, int | None]] = {}
    menus: dict[str, list[dict]] = {}
    crumbs: dict[str, list[dict]] = {}
    total = len(urls)
    done = 0
    for start in range(0, total, 6):
        if should_stop and should_stop():
            listing.stopped = True
            if "수집을 중지했습니다." not in listing.notes:
                listing.notes.append("수집을 중지했습니다.")
            break
        batch = urls[start:start + 6]
        _emit(on_progress, "유형을 확인하는 중", batch[0], done, total - done, limit=total)
        with ThreadPoolExecutor(max_workers=min(6, len(batch))) as pool:
            for url, kind, count, skus, links, missing, trail, siblings, active_count, discontinued_count in pool.map(lambda url: _read_page_kind(request, url), batch):
                found[url] = (kind, count, skus, missing, siblings, active_count, discontinued_count)
                menus[url] = links
                crumbs[url] = trail
        done += len(batch)
    for page in targets:
        if page.url not in found:
            continue
        kind, count, skus, missing, siblings, active_count, discontinued_count = found[page.url]
        page.kind = kind or "일반"
        page.missing = missing
        if kind == "PLP":
            page.sibling_count = siblings
            page.active_count = active_count
            page.discontinued_count = discontinued_count
        if isinstance(count, int):
            page.item_count = count
            page.item_skus = skus
    return menus, crumbs


def _menu_label_key(value: str) -> str:
    return " ".join((value or "").lower().split())


def _add_wa_pages(listing: PageList, links_by_url: dict[str, list[dict]]) -> list[str]:
    """탭의 페이지 이동 링크 중 같은 이름의 메뉴가 없으면 그 페이지와 같은 단계에 넣는다."""
    seen = {
        (_path_key(page.url), _menu_label_key(page.title))
        for page in listing.pages if page.url
    }
    grouped: dict[int, list[ListedPage]] = {}
    new_urls: list[str] = []
    serial = 0
    root_host = host_of(listing.root)
    for index, page in enumerate(listing.pages):
        for link in links_by_url.get(page.url) or []:
            url = link.get("url") or ""
            key = _path_key(url)
            label = " ".join((link.get("label") or "").split())
            if not label:
                parts = _path_parts(url)
                label = (parts[-1] if parts else url).replace("-", " ")
            pair = (key, _menu_label_key(label))
            if not key or pair in seen or host_of(url) != root_host or not _under_root(url, listing.root):
                continue
            seen.add(pair)
            grouped.setdefault(index, []).append(ListedPage(
                url=url,
                kind="일반",
                depth=page.depth,
                parent=page.parent,
                title=label,
                group=page.group,
                outside_gnb=True,
                id=f"{page.parent}/wa/{serial}",
            ))
            serial += 1
            new_urls.append(url)
    for index in sorted(grouped, reverse=True):
        listing.pages[index + 1:index + 1] = grouped[index]
    return new_urls


def _place_outside_pages(listing: PageList, crumbs_by_url: dict[str, list[dict]]) -> None:
    """GNB에 없어 추가한 메뉴를 브래드크럼의 가장 깊은 메뉴 아래에 둔다."""
    by_path: dict[tuple, ListedPage] = {}
    for page in listing.pages:
        if not page.url:
            continue
        key = _path_key(page.url)
        current = by_path.get(key)
        if current is None or (current.outside_gnb and not page.outside_gnb):
            by_path[key] = page
    for page in listing.pages:
        if not page.outside_gnb:
            continue
        parent = None
        for crumb in crumbs_by_url.get(page.url) or []:
            url = crumb.get("url") or ""
            if not url or _path_key(url) == _path_key(page.url):
                continue
            match = by_path.get(_path_key(url))
            if match is not None and match is not page:
                parent = match
        if parent is None:
            continue
        page.parent = parent.id or parent.url
        page.depth = parent.depth + 1
        page.group = parent.group


def _read_tab_page(request, url: str) -> tuple[str, list[dict], list[dict]]:
    try:
        result = request(url)
    except Exception:
        return url, [], []
    if result.error or not (200 <= result.status <= 299):
        return url, [], []
    html = decode_html(result.body, result.content_type)
    page_url = result.url or url
    return url, wa_type_links(html, page_url), breadcrumbs(html, page_url)


def _fill_tab_menus(listing: PageList, request, on_progress, should_stop) -> None:
    """유형을 확인하기 전에 탭의 페이지 이동 링크로 메뉴 구성을 맞춘다."""
    pending: list[str] = []
    root_host = host_of(listing.root)
    for page in listing.pages:
        if page.url and not page.blank and host_of(page.url) == root_host and page.url not in pending:
            pending.append(page.url)
    fetched: set[str] = set()
    crumbs_by_url: dict[str, list[dict]] = {}
    for _round in range(8):
        if should_stop and should_stop():
            listing.stopped = True
            if "수집을 중지했습니다." not in listing.notes:
                listing.notes.append("수집을 중지했습니다.")
            return
        todo = [url for url in pending if url not in fetched]
        links: dict[str, list[dict]] = {}
        if todo:
            total = len(todo)
            done = 0
            for start in range(0, total, 6):
                if should_stop and should_stop():
                    listing.stopped = True
                    if "수집을 중지했습니다." not in listing.notes:
                        listing.notes.append("수집을 중지했습니다.")
                    return
                batch = todo[start:start + 6]
                _emit(on_progress, "메뉴를 구성하는 중", batch[0], done, total - done, limit=total)
                with ThreadPoolExecutor(max_workers=min(6, len(batch))) as pool:
                    for url, found, trail in pool.map(lambda url: _read_tab_page(request, url), batch):
                        links[url] = found
                        crumbs_by_url[url] = trail
                done += len(batch)
            fetched.update(todo)
        new_urls = _add_wa_pages(listing, links) if links else []
        _place_outside_pages(listing, crumbs_by_url)
        if not new_urls:
            return
        pending = new_urls


def _product_page_url(raw: str, page_url: str) -> str:
    text = (raw or "").strip()
    if not text or text.startswith(("#", "javascript:", "mailto:", "tel:")):
        return ""
    absolute = urljoin(page_url, text).split("#", 1)[0]
    if urlsplit(absolute).scheme not in {"http", "https"}:
        return ""
    if host_of(absolute) != host_of(page_url):
        return ""
    return absolute


def _attach_plp_products(listing: PageList) -> None:
    """PLP 제품의 Learn more 주소를 그 메뉴 바로 아래에 둔다."""
    grouped: dict[int, list[ListedPage]] = {}
    for index, page in enumerate(listing.pages):
        if page.kind != "PLP" or not page.url:
            continue
        seen = {_path_key(page.url)}
        children: list[ListedPage] = []
        for item in page.item_skus:
            if not isinstance(item, dict):
                continue
            url = _product_page_url(str(item.get("url") or ""), page.url)
            key = _path_key(url)
            if not key or key in seen:
                continue
            seen.add(key)
            title = " ".join(str(item.get("title") or item.get("sku") or "").split()) or url
            children.append(ListedPage(
                url=url,
                kind="PDP",
                depth=page.depth + 1,
                parent=page.id or page.url,
                title=title,
                group=page.group,
                discontinued=bool(item.get("discontinued")),
                product=True,
                id=f"{page.id or 'plp'}/product/{len(children)}",
            ))
        if children:
            grouped[index] = children
    for index in sorted(grouped, reverse=True):
        listing.pages[index + 1:index + 1] = grouped[index]


def _attach_insights(listing: PageList, request, on_progress, should_stop) -> None:
    """Insights 메뉴 아래에 Contents별 글 제목과 링크를 붙인다."""
    added: list[ListedPage] = []
    for page in list(listing.pages):
        if should_stop and should_stop():
            listing.stopped = True
            listing.notes.append("수집을 중지했습니다.")
            break
        if not page.url or not _insight_listing(page.url):
            continue
        _emit(on_progress, "Insights 목록을 모으는 중", page.url, len(listing.pages), 0, limit=0)
        result = request(page.url)
        if result.error or not (200 <= result.status <= 299):
            continue
        html = decode_html(result.body, result.content_type)
        for index, name in enumerate(insight_contents(html)):
            if should_stop and should_stop():
                listing.stopped = True
                listing.notes.append("수집을 중지했습니다.")
                break
            group = ListedPage(
                url="",
                kind="Insights",
                depth=page.depth + 1,
                parent=page.id,
                title=name,
                group=page.group,
                id=f"{page.id}/insights/{index}",
            )
            stories = _insight_stories(page.url, html, request, name, should_stop)
            if not stories:
                continue
            added.append(group)
            for story_index, (title, url) in enumerate(stories):
                added.append(ListedPage(
                    url=url,
                    kind="Insights",
                    depth=group.depth + 1,
                    parent=group.id,
                    title=title,
                    group=page.group,
                    id=f"{group.id}/{story_index}",
                ))
    listing.pages.extend(added)


def _pages_from_nav(root_url: str, root_html: str, gnb: list, fnb: list, *, rules: dict, request, on_progress, should_stop, language: str, country: str, menu_diff: dict | None = None) -> PageList:
    """입력 페이지의 GNB·FNB를 한 번만 읽어 메뉴 단계로 만든다."""
    del root_html, rules, request, should_stop
    pages: list[ListedPage] = []

    def header(name: str) -> ListedPage:
        page = ListedPage(url="", kind="메뉴", depth=0, parent=root_url, title=name, group=name, id=f"group:{name}")
        pages.append(page)
        return page

    def add_nodes(nodes: list, parent: ListedPage) -> None:
        for index, node in enumerate(nodes):
            label = node.get("label") or node.get("url") or "항목"
            url = node.get("url") or ""
            if _insight_listing(url):
                kind = "Insights"
            elif url and not node.get("blank"):
                kind = "일반"
            elif url:
                kind = "기타"
            else:
                kind = "메뉴"
            item = ListedPage(
                url=url,
                kind=kind,
                depth=parent.depth + 1,
                parent=parent.id,
                title=label,
                group=parent.group,
                id=f"{parent.id}/{index}",
                blank=bool(node.get("blank")),
            )
            pages.append(item)
            add_nodes(node.get("children") or [], item)

    add_nodes(gnb, header("GNB"))
    if fnb:
        add_nodes(fnb, header("FNB"))
    _emit(on_progress, "메뉴를 정리하는 중", root_url, len(pages), 0, limit=0)
    return PageList(
        ok=True,
        root=root_url,
        pages=pages,
        notes=[],
        stopped=False,
        language=language,
        country=country,
        menu_diff=menu_diff,
    )


def compare_menus(root: str, *, fetch_one=None, resolve=None) -> MenuDiff:
    """입력한 페이지 하나의 GNB 링크와 FNB 링크를 비교한다."""
    if fetch_one is None:
        reset_host_limits()
    try:
        kwargs = {"resolve": resolve} if resolve is not None else {}
        target = check_url(root, **kwargs)
    except UrlRejected as exc:
        return MenuDiff(ok=False, message=exc.message)
    if fetch_one is not None:
        result = fetch_one(target.url, read_body=True)
    else:
        result = fetch(target.url, read_body=True, resolve=resolve)
    if result.error == BLOCK_MESSAGE:
        return MenuDiff(ok=False, message=BLOCK_MESSAGE)
    if result.error or not (200 <= result.status <= 299):
        return MenuDiff(ok=False, message="페이지를 읽지 못했습니다.")
    html = decode_html(result.body, result.content_type)
    page_url = result.url or target.url
    language, country = read_place(page_url, html)
    gnb, fnb, diff = menu_listing(html, page_url)
    if not gnb and not fnb:
        return MenuDiff(ok=True, root=page_url, language=language, country=country, message="GNB와 FNB를 찾지 못했습니다.")
    probe = fetch_one or (lambda url, read_body=True: fetch(url, read_body=read_body, resolve=resolve))
    found = MenuDiff(
        ok=True,
        root=page_url,
        language=language,
        country=country,
        shared=diff["shared"],
        gnb_only=diff["gnb_only"],
        fnb_only=diff["fnb_only"],
        same_label=diff["same_label"],
        checks=_blank_checks(diff.get("blank") or [], probe),
    )
    if limit_notice():
        found.message = BLOCK_MESSAGE
    return found


def _is_404(url: str, fetch_one) -> bool:
    try:
        result = fetch_one(url, read_body=False)
    except TypeError:
        result = fetch_one(url)
    except Exception:
        return False
    if getattr(result, "error", ""):
        return False
    return getattr(result, "status", 0) == 404


def _blank_checks(urls: list[str], fetch_one) -> dict:
    if not urls:
        return {}

    def one(url: str) -> tuple[str, bool]:
        return url, _is_404(url, fetch_one)

    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as pool:
        found = dict(pool.map(one, urls))
    return {url: {"blank": True, "missing": missing} for url, missing in found.items()}


def _apply_blank(listing: PageList, fetch_one) -> None:
    diff = listing.menu_diff or {}
    checks = _blank_checks(list(diff.get("blank") or []), fetch_one)
    if listing.menu_diff is not None:
        listing.menu_diff.pop("blank", None)
        listing.menu_diff["checks"] = checks
    for page in listing.pages:
        info = checks.get(page.url)
        if page.blank and info:
            page.missing = bool(info["missing"])


def discover_pages(root: str, *, rules: dict | None = None, fetch_one=None, resolve=None, on_progress=None, should_stop=None) -> PageList:
    """입력한 주소 경로 아래만 모은다. 단계는 경로 깊이다."""
    if fetch_one is None:
        reset_host_limits()
        forget_assets()

    page_cache: dict[str, HttpResult] = {}

    def request(url: str, *, body: bytes | None = None, headers: dict | None = None):
        use_cache = body is None and not headers
        if use_cache and url in page_cache:
            return page_cache[url]
        if fetch_one is not None:
            if headers:
                try:
                    result = fetch_one(url, read_body=True, body=body, headers=headers)
                except TypeError:
                    result = HttpResult(url=url, status=0, content_type="", body=b"", error="연결 실패")
            else:
                try:
                    result = fetch_one(url, read_body=True, body=body)
                except TypeError:
                    result = fetch_one(url, read_body=True)
        else:
            result = fetch(url, read_body=True, resolve=resolve, body=body, headers=headers)
        if use_cache and not getattr(result, "error", ""):
            page_cache[url] = result
            # 목록을 모으며 정상으로 읽은 페이지는 페이지 검수에서 링크로 다시 부르지 않는다.
            if fetch_one is None and 200 <= result.status <= 299:
                _asset_remember(url, False)
        return result

    getter = fetch_one or (lambda url, read_body=True: fetch(url, read_body=read_body, resolve=resolve))

    def halted() -> bool:
        return bool(should_stop and should_stop())

    language = UNKNOWN_LANGUAGE
    country = UNKNOWN_COUNTRY

    def stopped_at(root_url: str, pages: list[ListedPage], notes: list[str]) -> PageList:
        notes.append("수집을 중지했습니다.")
        return _attach_limit(PageList(
            ok=True,
            root=root_url,
            pages=pages,
            notes=notes,
            stopped=True,
            language=language,
            country=country,
        ))

    _emit(on_progress, "주소를 확인하는 중", root, 0, 0, limit=0)
    if halted():
        return stopped_at(root, [], [])
    try:
        kwargs = {"resolve": resolve} if resolve is not None else {}
        root_target = check_url(root, **kwargs)
    except UrlRejected as exc:
        return PageList(ok=False, message=exc.message)
    active_rules = rules if rules is not None else load_rules()
    queue: deque[tuple[str, int, str]] = deque([(root_target.url, 0, "")])
    seen = {root_target.url}
    queued = {root_target.url}
    pages: list[ListedPage] = []
    root_host = root_target.hostname
    notes: list[str] = []
    root_url = root_target.url
    child_parent: dict[tuple, str] = {}
    learn_ids: set[tuple] = set()

    def remember(link: str, parent_url: str, *, pdp: bool) -> None:
        if host_of(link) != root_host or not _under_root(link, root_url):
            return
        if _page_identity(link) == _page_identity(parent_url):
            return
        child_parent.setdefault(_page_identity(link), parent_url)
        if not pdp:
            return
        learn_ids.add(_page_identity(link))
        for page in pages:
            if _page_identity(page.url) == _page_identity(link):
                page.kind = "PDP"

    def listed_kind(target: str, html: str) -> str:
        if _page_identity(target) in learn_ids:
            return "PDP"
        return infer_kind(target, html, active_rules)

    def carry(requested: str, landed: str) -> None:
        source = _page_identity(requested)
        target = _page_identity(landed)
        if source in child_parent and target not in child_parent:
            child_parent[target] = child_parent[source]
        if source in learn_ids:
            learn_ids.add(target)

    def queue_under(link: str) -> None:
        if host_of(link) != root_host:
            return
        for target in [*_ancestor_targets(link, root_url), link]:
            if target in seen or target in queued or not _under_root(target, root_url):
                continue
            queued.add(target)
            queue.append((target, 1, ""))

    def place() -> list[ListedPage]:
        placed = _dedupe_pages(pages)
        _ensure_ancestors(placed, root_url, active_rules)
        _assign_places(placed, root_url)
        _attach_plp_children(placed, child_parent, root_url)
        return placed

    def halted_list() -> PageList:
        notes.append("수집을 중지했습니다.")
        placed = place()
        return _attach_limit(PageList(
            ok=True,
            root=root_url,
            pages=placed,
            notes=notes,
            stopped=True,
            language=language,
            country=country,
        ))

    while queue:
        if halted():
            return halted_list()
        url, depth, parent = queue.popleft()
        if url in seen and depth > 0:
            continue
        seen.add(url)
        if host_of(url) != root_host:
            continue
        if depth > 0 and not _under_root(url, root_url):
            continue
        _emit(on_progress, "하위 페이지를 모으는 중", url, len(pages), len(queue), limit=0)
        result = getter(url, read_body=True)
        if depth > 0 and (result.error or not (200 <= result.status <= 299)):
            if _under_root(url, root_url):
                pages.append(ListedPage(url=url, kind=listed_kind(url, ""), depth=1, parent=root_url))
            continue
        if result.error or not (200 <= result.status <= 299):
            message = BLOCK_MESSAGE if result.error == BLOCK_MESSAGE else "루트 페이지를 읽지 못했습니다."
            return PageList(ok=False, message=message)
        html = decode_html(result.body, result.content_type)
        content_type = result.content_type.lower()
        if "html" not in content_type and not html.lstrip().startswith("<"):
            continue
        page_url = result.url or url
        seen.add(page_url)
        queued.add(page_url)
        if host_of(page_url) != root_host:
            if depth == 0:
                return PageList(ok=False, message="루트가 다른 주소로 이동했습니다.")
            continue
        carry(url, page_url)
        if depth == 0:
            root_url = page_url
            language, country = read_place(page_url, html)
            gnb, fnb, menu_diff = menu_listing(html, page_url)
            if gnb or fnb:
                listing = _pages_from_nav(
                    page_url,
                    html,
                    gnb,
                    fnb,
                    rules=active_rules,
                    request=request,
                    on_progress=on_progress,
                    should_stop=should_stop,
                    language=language,
                    country=country,
                    menu_diff=menu_diff,
                )
                _fill_tab_menus(listing, request, on_progress, should_stop)
                if listing.stopped:
                    return _attach_limit(listing)
                _mark_page_kinds(listing, request, on_progress, should_stop)
                if listing.stopped:
                    return _attach_limit(listing)
                _attach_plp_products(listing)
                _attach_insights(listing, request, on_progress, should_stop)
                _emit(on_progress, "새창 링크를 확인하는 중", page_url, len(listing.pages), len(menu_diff.get("blank") or []), limit=0)
                _apply_blank(listing, lambda url, read_body=False: getter(url, read_body=read_body))
                return _attach_limit(listing)
        elif _under_root(page_url, root_url):
            pages.append(ListedPage(
                url=page_url,
                kind=listed_kind(page_url, html),
                depth=1,
                parent=root_url,
            ))
        else:
            continue
        if infer_kind(page_url, html, active_rules) == "PLP":
            paging, learn = plp_targets(html, page_url)
            for link in paging:
                remember(link, page_url, pdp=False)
                queue_under(link)
            for link in learn:
                remember(link, page_url, pdp=True)
                queue_under(link)
        links, _images = extract(html, page_url)
        for link in links:
            queue_under(link)

    if halted():
        return halted_list()
    pages = place()
    if not pages:
        notes.append("같은 주소의 하위 페이지가 없습니다.")
    _emit(on_progress, "목록을 정리하는 중", root_url, len(pages), 0, limit=0)
    return _attach_limit(PageList(
        ok=True,
        root=root_url,
        pages=pages,
        notes=notes,
        stopped=False,
        language=language,
        country=country,
    ))
