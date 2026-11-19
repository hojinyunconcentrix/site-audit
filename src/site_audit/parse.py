"""HTML에서 링크·이미지를 뽑고, 대표 이미지의 가로·세로를 읽는다."""

from __future__ import annotations

import html as html_lib
import json
import re
import struct
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = {name.lower(): value for name, value in attrs if name}
        if tag == "a" and data.get("href"):
            self.links.append(data["href"])
        if tag == "img" and data.get("src"):
            self.images.append(data["src"])


def extract(html: str, base_url: str) -> tuple[list[str], list[str]]:
    parser = _Collector()
    parser.feed(html)
    parser.close()
    return _absolute(parser.links, base_url), _absolute(parser.images, base_url)


def _absolute(values: list[str], base_url: str) -> list[str]:
    found: list[str] = []
    seen = set()
    for raw in values:
        text = (raw or "").strip()
        if not text or text.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        absolute = urljoin(base_url, text)
        parts = urlsplit(absolute)
        if parts.scheme not in {"http", "https"}:
            continue
        cleaned = absolute.split("#", 1)[0]
        if cleaned not in seen:
            seen.add(cleaned)
            found.append(cleaned)
    return found


def image_size(blob: bytes) -> tuple[int, int] | None:
    if blob.startswith(b"\x89PNG\r\n\x1a\n") and len(blob) >= 24:
        width, height = struct.unpack(">II", blob[16:24])
        return width, height
    if blob.startswith((b"GIF87a", b"GIF89a")) and len(blob) >= 10:
        width, height = struct.unpack("<HH", blob[6:10])
        return width, height
    if blob.startswith(b"\xff\xd8"):
        return _jpeg_size(blob)
    if blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return _webp_size(blob)
    return None


def _webp_size(blob: bytes) -> tuple[int, int] | None:
    if len(blob) < 30:
        return None
    kind = blob[12:16]
    if kind == b"VP8X":
        width = 1 + int.from_bytes(blob[24:27], "little")
        height = 1 + int.from_bytes(blob[27:30], "little")
        return width, height
    if kind == b"VP8 ":
        start = blob.find(b"\x9d\x01\x2a", 20)
        if start < 0 or start + 7 > len(blob):
            return None
        width, height = struct.unpack("<HH", blob[start + 3 : start + 7])
        return width & 0x3FFF, height & 0x3FFF
    if kind == b"VP8L" and blob[20] == 0x2F:
        bits = struct.unpack("<I", blob[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def _jpeg_size(blob: bytes) -> tuple[int, int] | None:
    index = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while index + 8 < len(blob):
        if blob[index] != 0xFF:
            index += 1
            continue
        marker = blob[index + 1]
        index += 2
        if marker in sof:
            height, width = struct.unpack(">HH", blob[index + 3 : index + 7])
            return width, height
        if marker == 0xD8 or marker == 0xD9:
            continue
        if index + 2 > len(blob):
            return None
        size = struct.unpack(">H", blob[index : index + 2])[0]
        if size < 2:
            return None
        index += size
    return None


class _Signals(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_lang = ""
        self.og_locale = ""
        self.types: list[str] = []
        self.plp = False
        self._ld = False
        self._ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = {name.lower(): value for name, value in attrs if name}
        if tag == "html" and data.get("lang") and not self.html_lang:
            self.html_lang = data["lang"].strip()
        if tag == "meta":
            prop = (data.get("property") or data.get("name") or "").lower()
            if prop == "og:locale" and data.get("content") and not self.og_locale:
                self.og_locale = data["content"].strip()
        if tag == "script" and "ld+json" in (data.get("type") or "").lower():
            self._ld = True
            self._ld_parts = []
        if not self.plp and _class_is_plp(data.get("class", "")):
            self.plp = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._ld:
            self._ld = False
            self._read_types("".join(self._ld_parts))

    def handle_data(self, data: str) -> None:
        if self._ld:
            self._ld_parts.append(data)

    def _read_types(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        self._walk(payload)

    def _walk(self, node) -> None:
        if isinstance(node, list):
            for item in node:
                self._walk(item)
            return
        if not isinstance(node, dict):
            return
        kind = node.get("@type")
        if isinstance(kind, str):
            self.types.append(kind)
        elif isinstance(kind, list):
            self.types.extend(str(item) for item in kind)
        graph = node.get("@graph")
        if graph is not None:
            self._walk(graph)


def _class_is_plp(value: str) -> bool:
    return "c-result-area__product-list" in (value or "").lower()


_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


def _is_learn_more(text: str, aria: str) -> bool:
    label = " ".join((text or "").split()).lower()
    named = " ".join((aria or "").split()).lower()
    return label == "learn more" or named == "learn more"


class _PlpTargets(HTMLParser):
    """PLP 목록의 페이징 주소와 Learn more 주소를 가른다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paging: list[str] = []
        self.learn: list[str] = []
        self._stack: list[tuple[str, bool, bool]] = []
        self._control: dict | None = None
        self._control_left = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        self._open(tag, attrs, void=tag in _VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._open(tag, attrs, void=True)

    def _open(self, tag: str, attrs, *, void: bool) -> None:
        data = {name.lower(): value or "" for name, value in attrs if name}
        classes = data.get("class", "")
        opens_list = _class_is_plp(classes)
        opens_page = "c-page__list" in classes.lower()
        in_list = opens_list or any(item[1] for item in self._stack)
        in_page = opens_page or any(item[2] for item in self._stack)
        href = data.get("href") or data.get("data-href") or data.get("data-url") or data.get("data-link")
        if tag in {"a", "button"} and href:
            if self._control is None:
                self._control = {
                    "href": href,
                    "aria": data.get("aria-label", ""),
                    "parts": [],
                    "list": in_list,
                    "page": in_page,
                }
                self._control_left = 1
            else:
                self._control_left += 1
        if not void:
            self._stack.append((tag, opens_list, opens_page))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"a", "button"} and self._control is not None:
            self._control_left -= 1
            if self._control_left <= 0:
                self._close_control()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index]
                break

    def handle_data(self, data: str) -> None:
        if self._control is not None:
            self._control["parts"].append(data)

    def _close_control(self) -> None:
        item = self._control
        self._control = None
        if item is None:
            return
        text = " ".join(item["parts"])
        if item["page"]:
            self.paging.append(item["href"])
        if item["list"] and _is_learn_more(text, item["aria"]):
            self.learn.append(item["href"])


def plp_targets(html: str, base_url: str) -> tuple[list[str], list[str]]:
    parser = _PlpTargets()
    parser.feed(html or "")
    parser.close()
    return _absolute(parser.paging, base_url), _absolute(parser.learn, base_url)


def page_signals(html: str) -> dict:
    parser = _Signals()
    parser.feed(html or "")
    parser.close()
    return {
        "lang": parser.html_lang or parser.og_locale.replace("_", "-"),
        "types": parser.types,
        "plp": parser.plp,
    }


def _classes(value: str) -> str:
    return (value or "").lower()


def _new_nav_node() -> dict:
    return {"label": "", "url": "", "blank": False, "children": []}


def _mark_blank(node: dict, data: dict) -> None:
    if (data.get("target") or "").lower() == "_blank":
        node["blank"] = True


def _fold_gnb_column(items: list[dict]) -> list[dict]:
    """depth3 열의 첫 제목 아래로 같은 열의 나머지 항목을 붙인다."""
    head = None
    folded: list[dict] = []
    for node in items:
        labeled = bool(node.get("label") or node.get("url"))
        if head is None and labeled and not node.get("children"):
            head = node
            folded.append(node)
            continue
        if head is not None:
            if labeled:
                head["children"].append(node)
            else:
                head["children"].extend(node.get("children") or [])
            continue
        folded.append(node)
    return folded


class _NavMenus(HTMLParser):
    """첫 번째 GNB와 데스크톱 FNB의 계층만 뽑는다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.gnb: list[dict] = []
        self.fnb: list[dict] = []
        self._gnb_uls = 0
        self._gnb_done = False
        self._lists: list[list[dict]] = []
        self._items: list[dict] = []
        self._ul_mode: list[str] = []
        self._text_tag = ""
        self._footer = 0
        self._footer_done = False
        self._depth3 = 0
        self._footer_open: list[bool] = []
        self._level1: dict | None = None
        self._level2: dict | None = None
        self._text: list[str] | None = None
        self._text_left = 0
        self._text_node: dict | None = None
        self._skip_text = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        data = {name.lower(): value or "" for name, value in attrs if name}
        classes = _classes(data.get("class", ""))
        if not self._gnb_done and self._gnb_uls == 0 and "c-gnb__group--depth1" in classes and "primary" in classes:
            self._gnb_uls = 1
            self._lists = [self.gnb]
            self._items = []
            self._ul_mode = [""]
        elif self._gnb_uls:
            if tag == "ul":
                self._gnb_uls += 1
                mode = "depth3" if "c-gnb__group--depth3" in classes else ""
                if mode == "depth3":
                    self._lists.append([])
                elif self._items:
                    self._lists.append(self._items[-1]["children"])
                self._ul_mode.append(mode)
            if tag == "li" and self._lists:
                node = _new_nav_node()
                self._lists[-1].append(node)
                self._items.append(node)
            opens_label = tag in {"a", "button"} or (tag == "div" and "c-gnb__item-link" in classes)
            if opens_label and self._items:
                if self._text is None:
                    self._text = []
                    self._text_left = 1
                    self._text_tag = tag
                    self._text_node = self._items[-1]
                    href = (data.get("href") or "").strip()
                    if href:
                        self._text_node["url"] = href
                        _mark_blank(self._text_node, data)
                elif tag == self._text_tag:
                    self._text_left += 1
            return
        if tag in _VOID_TAGS or self._footer_done:
            return
        opens_footer = "c-footer__inner" in classes and "desktop-only" in classes and self._footer == 0
        if opens_footer:
            self._footer = 1
        elif self._footer:
            self._footer += 1
        if not self._footer:
            return
        opens_depth3 = "c-footer__depth3" in classes
        self._footer_open.append(opens_depth3)
        if opens_depth3:
            self._depth3 += 1
        if tag == "strong" and "c-footer__depth1" in classes:
            node = _new_nav_node()
            self.fnb.append(node)
            self._level1 = node
            self._level2 = None
            self._begin_text(node)
        elif tag == "a" and data.get("href"):
            parent = self._level2 if self._depth3 and self._level2 is not None else self._level1
            if parent is None:
                parent = _new_nav_node()
                self.fnb.append(parent)
                self._level1 = parent
            node = _new_nav_node()
            node["url"] = data["href"]
            _mark_blank(node, data)
            parent["children"].append(node)
            if not self._depth3:
                self._level2 = node
            self._begin_text(node)

    def _begin_text(self, node: dict) -> None:
        self._text = []
        self._text_left = 1
        self._text_node = node

    def handle_endtag(self, tag: str) -> None:
        if self._gnb_uls:
            if self._text is not None and tag == self._text_tag:
                self._text_left -= 1
                if self._text_left <= 0:
                    self._store_text()
            if tag == "li" and self._items:
                self._items.pop()
            if tag == "ul":
                mode = self._ul_mode.pop() if self._ul_mode else ""
                if mode == "depth3" and self._lists:
                    bucket = self._lists.pop()
                    folded = _fold_gnb_column(bucket)
                    if self._items:
                        self._items[-1]["children"].extend(folded)
                    elif self._lists:
                        self._lists[-1].extend(folded)
                elif len(self._lists) > 1:
                    self._lists.pop()
                self._gnb_uls -= 1
                if self._gnb_uls <= 0:
                    self._gnb_uls = 0
                    self._gnb_done = True
                    self._lists = []
                    self._items = []
                    self._ul_mode = []
            return
        if self._text is not None and tag in {"a", "strong", "button"}:
            self._text_left -= 1
            if self._text_left <= 0:
                self._store_text()
        if self._footer_open:
            if self._footer_open.pop() and self._depth3:
                self._depth3 -= 1
        if self._footer:
            self._footer -= 1
            if self._footer <= 0:
                self._footer = 0
                self._footer_done = True
                self._depth3 = 0
                self._footer_open = []

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)

    def _store_text(self) -> None:
        node = self._text_node
        label = " ".join("".join(self._text or []).split())
        self._text = None
        self._text_node = None
        self._text_tag = ""
        if node is not None and label and not node["label"]:
            node["label"] = label


class _OutsideNav(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self._nav = 0
        self._open: list[bool] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = {name.lower(): value or "" for name, value in attrs if name}
        classes = _classes(data.get("class", ""))
        if tag == "a" and data.get("href") and self._nav == 0:
            self.links.append(data["href"])
        if tag in _VOID_TAGS:
            return
        opens = "c-gnb" in classes or "c-footer" in classes
        self._open.append(opens)
        if opens:
            self._nav += 1

    def handle_endtag(self, tag: str) -> None:
        if self._open and self._open.pop() and self._nav:
            self._nav -= 1


def _trim_nav(nodes: list[dict]) -> list[dict]:
    kept = []
    for node in nodes:
        node["label"] = " ".join((node.get("label") or "").split())
        node["children"] = _trim_nav(node.get("children") or [])
        if not node["label"] and not node["url"]:
            kept.extend(node["children"])
            continue
        if node["label"] or node["url"] or node["children"]:
            kept.append(node)
    return kept


class _WaTypeMenus(HTMLParser):
    """data-wa-type 또는 tablist 안의 페이지 이동 링크와 이름을 모은다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._stack: list[tuple] = []
        self._text: list[str] | None = None
        self._link_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _VOID_TAGS:
            return
        data = {name.lower(): value or "" for name, value in attrs if name}
        classes = set(data.get("class", "").split())
        role = set(data.get("role", "").lower().split())
        parent_menu = self._stack[-1][1] if self._stack else False
        in_menu = parent_menu or bool(data.get("data-wa-type")) or "tablist" in role
        in_name = in_menu and "c-roll-selector__item-name" in classes
        link = {"href": data.get("href", ""), "label": ""} if in_menu and tag == "a" and data.get("href") else None
        self._stack.append((tag, in_menu, in_name, link))
        if in_name:
            self._text = []
        if link is not None:
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] != tag:
                continue
            frame = self._stack[index]
            if frame[2] and self._text is not None:
                label = " ".join("".join(self._text).split())
                for previous in reversed(self._stack[: index + 1]):
                    if previous[3] is not None:
                        previous[3]["label"] = label
                        break
                self._text = None
            if frame[3] is not None and tag == "a":
                if not frame[3]["label"] and self._link_text is not None:
                    frame[3]["label"] = " ".join("".join(self._link_text).split())
                self._link_text = None
                self.items.append(frame[3])
            del self._stack[index:]
            return

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)
        elif self._link_text is not None:
            self._link_text.append(data)


def wa_type_links(html: str, base_url: str) -> list[dict]:
    """탭 영역의 페이지 이동 링크. 영역 밖 링크와 내용만 바꾸는 탭은 넣지 않는다."""
    parser = _WaTypeMenus()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return []
    found: list[dict] = []
    seen: set[str] = set()
    for item in parser.items:
        absolute = _absolute([item.get("href") or ""], base_url)
        if not absolute:
            continue
        url = absolute[0]
        if url in seen:
            continue
        seen.add(url)
        found.append({"label": " ".join((item.get("label") or "").split()), "url": url})
    return found


class _Breadcrumb(HTMLParser):
    """첫 브래드크럼의 이름과 주소를 순서대로 모은다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._in = False
        self._done = False
        self._item: dict | None = None
        self._text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _VOID_TAGS or self._done:
            return
        data = {name.lower(): value or "" for name, value in attrs if name}
        classes = data.get("class", "")
        if not self._in and tag == "nav" and ("c-breadcrumb" in classes or data.get("aria-label", "").lower() == "breadcrumb"):
            self._in = True
        if not self._in:
            return
        if tag == "li":
            self._item = {"href": "", "label": ""}
            self._text = []
        if tag == "a" and self._item is not None and data.get("href"):
            self._item["href"] = data["href"]

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._item is not None:
            self._item["label"] = " ".join("".join(self._text or []).split())
            self.items.append(self._item)
            self._item = None
            self._text = None
        if tag == "nav" and self._in:
            self._in = False
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)


def breadcrumbs(html: str, base_url: str) -> list[dict]:
    """브래드크럼 항목. 현재 페이지처럼 주소가 없으면 url은 빈 문자열이다."""
    parser = _Breadcrumb()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return []
    found: list[dict] = []
    for item in parser.items:
        urls = _absolute([item.get("href") or ""], base_url) if item.get("href") else []
        found.append({"label": item.get("label") or "", "url": urls[0] if urls else ""})
    return found


def nav_trees(html: str, base_url: str) -> tuple[list[dict], list[dict]]:
    """첫 GNB와 데스크톱 FNB를 중복 제거 없이 돌려준다."""
    parser = _NavMenus()
    parser.feed(html or "")
    parser.close()

    def absolutize(nodes: list[dict]) -> None:
        for node in nodes:
            if node["url"]:
                absolute = _absolute([node["url"]], base_url)
                node["url"] = absolute[0] if absolute else ""
            absolutize(node["children"])

    gnb = _trim_nav(parser.gnb)
    fnb = _trim_nav(parser.fnb)
    absolutize(gnb)
    absolutize(fnb)
    return gnb, fnb


def site_nav(html: str, base_url: str) -> tuple[list[dict], list[dict]]:
    gnb, fnb = nav_trees(html, base_url)
    return gnb, _without_gnb(fnb, _nav_keys(gnb))


def _borrow_fnb_links(gnb: list[dict], fnb: list[dict]) -> None:
    """GNB에 주소가 없으면 같은 메뉴의 FNB 주소를 메뉴 링크에 쓴다."""
    nodes: dict[tuple, list[dict]] = {}

    def index(items: list[dict], parents: list[str]) -> None:
        for node in items:
            label = " ".join((node.get("label") or "").split())
            if not label:
                index(node.get("children") or [], parents)
                continue
            key = (_nav_key(label), tuple(_nav_key(part) for part in parents))
            nodes.setdefault(key, []).append(node)
            index(node.get("children") or [], [*parents, label])

    index(gnb, [])
    for g_item, f_item in _pair_spots(_menu_spots(gnb), _menu_spots(fnb)):
        urls = f_item.get("urls") or []
        if g_item.get("urls") or not urls:
            continue
        parents = g_item["path"][:-1]
        key = (_nav_key(g_item["label"]), tuple(_nav_key(part) for part in parents))
        for node in nodes.get(key, []):
            if node.get("url"):
                continue
            node["url"] = urls[0]
            break


def menu_listing(html: str, base_url: str) -> tuple[list[dict], list[dict], dict]:
    """GNB, 중복을 뺀 FNB, 링크 차이를 함께 돌려준다."""
    gnb, fnb = nav_trees(html, base_url)
    diff = diff_nav_links(gnb, fnb)
    _borrow_fnb_links(gnb, fnb)
    seen = set(_blank_urls(gnb))
    diff["blank"] = [*seen, *[url for url in _blank_urls(fnb) if url not in seen]]
    return gnb, _without_gnb(fnb, _nav_keys(gnb)), diff


def _blank_urls(nodes: list[dict]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def walk(items: list[dict]) -> None:
        for node in items:
            url = node.get("url") or ""
            if node.get("blank") and url and url not in seen:
                seen.add(url)
                found.append(url)
            walk(node.get("children") or [])

    walk(nodes)
    return found


def _nav_key(value: str) -> str:
    return " ".join((value or "").lower().split()).rstrip("/")


def _nav_keys(nodes: list[dict]) -> tuple[set[str], set[str]]:
    labels: set[str] = set()
    urls: set[str] = set()
    for node in nodes:
        label = _nav_key(node.get("label") or "")
        url = _nav_key(node.get("url") or "")
        if label:
            labels.add(label)
        if url:
            urls.add(url)
        child_labels, child_urls = _nav_keys(node.get("children") or [])
        labels.update(child_labels)
        urls.update(child_urls)
    return labels, urls


def _without_gnb(nodes: list[dict], seen: tuple[set[str], set[str]]) -> list[dict]:
    labels, urls = seen
    kept = []
    for node in nodes:
        children = _without_gnb(node.get("children") or [], seen)
        label = _nav_key(node.get("label") or "")
        url = _nav_key(node.get("url") or "")
        if (label and label in labels) or (url and url in urls):
            kept.extend(children)
            continue
        if not label and not url and not children:
            continue
        node["children"] = children
        kept.append(node)
    return kept


def _menu_spots(nodes: list[dict]) -> dict[tuple, dict]:
    """메뉴 이름과 상위 경로가 같은 항목의 주소를 모은다."""
    found: dict[tuple, dict] = {}

    def walk(items: list[dict], parents: list[str]) -> None:
        for node in items:
            label = " ".join((node.get("label") or "").split())
            url = node.get("url") or ""
            if label:
                path = [*parents, label]
                key = (_nav_key(label), tuple(_nav_key(part) for part in parents))
                item = found.setdefault(key, {"label": label, "path": path, "urls": []})
                if url and url not in item["urls"]:
                    item["urls"].append(url)
                walk(node.get("children") or [], path)
            else:
                walk(node.get("children") or [], parents)

    walk(nodes, [])
    return found


def _url_rows(nodes: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = {}

    def walk(items: list[dict]) -> None:
        for node in items:
            url = node.get("url") or ""
            key = _nav_key(url)
            if key and key not in found:
                label = " ".join((node.get("label") or "").split()) or url
                found[key] = {"label": label, "url": url}
            walk(node.get("children") or [])

    walk(nodes)
    return found


def _urls_only_on(left: list[str], right: list[str]) -> list[str]:
    """상대 주소와 겹치지 않는 주소만 남긴다."""
    other = {_nav_key(url) for url in right if url}
    seen: set[str] = set()
    kept = []
    for url in left:
        key = _nav_key(url)
        if not key or key in other or key in seen:
            continue
        seen.add(key)
        kept.append(url)
    return kept


def _pair_spots(gnb: dict[tuple, dict], fnb: dict[tuple, dict]) -> list[tuple[dict, dict]]:
    """같은 상위 메뉴를 먼저 맞추고, 없으면 같은 이름끼리 맞춘다."""
    leftover = dict(fnb)
    pairs = []
    pending = []
    for key, g_item in gnb.items():
        if key in leftover:
            pairs.append((g_item, leftover.pop(key)))
        else:
            pending.append(g_item)
    by_label: dict[str, list[tuple]] = {}
    for key, item in leftover.items():
        by_label.setdefault(key[0], []).append((key, item))
    for g_item in pending:
        bucket = by_label.get(_nav_key(g_item["label"])) or []
        if not bucket:
            continue
        _key, f_item = bucket.pop(0)
        leftover.pop(_key, None)
        pairs.append((g_item, f_item))
    return pairs


def diff_nav_links(gnb: list[dict], fnb: list[dict]) -> dict:
    """같은 주소는 빼고, 한쪽에만 있거나 이름은 같은데 주소가 다른 링크를 돌려준다."""
    g_spots = _menu_spots(gnb)
    f_spots = _menu_spots(fnb)
    g_urls = _url_rows(gnb)
    f_urls = _url_rows(fnb)
    renamed = []
    used: set[str] = set()
    for g_item, f_item in _pair_spots(g_spots, f_spots):
        g_list = _urls_only_on(g_item["urls"], f_item["urls"])
        f_list = _urls_only_on(f_item["urls"], g_item["urls"])
        if not g_list or not f_list:
            continue
        path = g_item["path"] if len(g_item["path"]) >= len(f_item["path"]) else f_item["path"]
        renamed.append({"label": g_item["label"], "path": path, "gnb": g_list, "fnb": f_list})
        used.update(_nav_key(url) for url in [*g_list, *f_list])
    renamed.sort(key=lambda row: " > ".join(row["path"]).lower())
    gnb_only = [g_urls[key] for key in g_urls if key not in f_urls and key not in used]
    fnb_only = [f_urls[key] for key in f_urls if key not in g_urls and key not in used]
    gnb_only.sort(key=lambda row: (_nav_key(row["label"]), row["url"]))
    fnb_only.sort(key=lambda row: (_nav_key(row["label"]), row["url"]))
    return {
        "shared": len(set(g_urls) & set(f_urls)),
        "gnb_only": gnb_only,
        "fnb_only": fnb_only,
        "same_label": renamed,
    }


def media_matches(query: str, width: int) -> bool:
    """가로 폭이 media 조건에 들어가는지. 비어 있으면 항상 맞다."""
    text = (query or "").strip().lower()
    if not text or text == "all":
        return True
    for part in re.split(r"\band\b", text):
        part = part.strip().strip("()")
        max_width = re.search(r"max-width:\s*(\d+)", part)
        min_width = re.search(r"min-width:\s*(\d+)", part)
        if max_width and width > int(max_width.group(1)):
            return False
        if min_width and width < int(min_width.group(1)):
            return False
    return True


def _class_visible(classes: str, width: int) -> bool:
    names = set((classes or "").split())
    if "mobile-only" in names and width > 767:
        return False
    if "desktop-only" in names and width < 768:
        return False
    return True


def _roll_image_hidden(classes: set[str], ancestors: list[set[str]]) -> bool:
    """스타일이 c-roll-selector__item-image를 display:none으로 숨기면 참."""
    if "c-roll-selector__item-image" not in classes:
        return False
    found: set[str] = set()
    for group in ancestors:
        found.update(group)
    if "is-sticky" in found or "st0025b" in found:
        return True
    if "bu0009" in found and "sticky-menu-wrap" in found and "__no-images" in found:
        return True
    if "bu0009" in found and "is-fixed" in found and "sticky-menu-wrap" in found and "__images" in found:
        return True
    return "pr0010" in found and "c-floating-wrap" in found and "is-fixed" in found and "is-sticky" in found and "c-roll-selector" in found


def _first_src(value: str) -> str:
    chunk = (value or "").split(",")[0].strip()
    return chunk.split()[0] if chunk else ""


def _image_src(data: dict) -> str:
    """data-src가 있으면 그 주소를, 없으면 src를 고른다."""
    for key in ("data-srcset", "data-src", "srcset", "src"):
        raw = data.get(key) or ""
        src = _first_src(raw) if key.endswith("srcset") else raw.strip()
        if src and not src.startswith(("data:", "javascript:")):
            return src
    return ""


def _start_tag(tag: str, attrs) -> str:
    parts = [f"<{tag}"]
    for name, value in attrs:
        if value is None:
            parts.append(f" {name}")
            continue
        escaped = str(value).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        parts.append(f' {name}="{escaped}"')
    parts.append(">")
    return "".join(parts)


class _ViewportAssets(HTMLParser):
    """한 화면 폭에서 보이는 링크와 이미지만 모은다."""

    def __init__(self, width: int) -> None:
        super().__init__(convert_charrefs=True)
        self.width = width
        self.links: list[str] = []
        self.images: list[str] = []
        self.image_tags: dict[str, str] = {}
        self.missing: list[str] = []
        self.missing_tags: dict[str, str] = {}
        self.link_titles: dict[str, str] = {}
        self._link_href = ""
        self._link_text: list[str] = []
        self._stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = {name.lower(): value or "" for name, value in attrs if name}
        parent = self._stack[-1] if self._stack else None
        hidden = bool(parent and parent["hidden"])
        classes = (data.get("class") or "").lower()
        names = set(classes.split())
        if "c-gnb" in classes or "c-footer" in classes:
            hidden = True
        if not _class_visible(classes, self.width):
            hidden = True
        style = data.get("style", "").replace(" ", "").lower()
        if "display:none" in style or _roll_image_hidden(names, [frame["classes"] for frame in self._stack]):
            hidden = True
        in_picture = tag == "picture" or bool(parent and parent["in_picture"])
        if tag == "source" and parent and parent["in_picture"] and not hidden:
            src = _image_src(data)
            if src and media_matches(data.get("media", ""), self.width):
                parent["sources"].append(src)
                parent["source_tags"].append(_start_tag("source", attrs))
            return
        if tag == "img" and not hidden:
            src = ""
            found = _start_tag("img", attrs)
            if parent and parent["in_picture"] and parent["sources"]:
                src = parent["sources"][-1]
                found = parent["source_tags"][-1]
            if not src:
                src = _image_src(data)
                found = _start_tag("img", attrs)
            if src:
                self.images.append(src)
                self.image_tags.setdefault(src, found)
            else:
                label = (data.get("alt") or "이미지").strip() or "이미지"
                self.missing.append(label)
                self.missing_tags.setdefault(label, _start_tag("img", attrs))
        if tag == "a" and not hidden and data.get("href"):
            self.links.append(data["href"])
            self._link_href = data["href"]
            self._link_text = []
        if tag in {"img", "source", "br", "meta", "link", "input", "hr", "area"}:
            return
        self._stack.append({
            "tag": tag,
            "hidden": hidden,
            "classes": names,
            "in_picture": in_picture,
            "sources": [] if tag == "picture" else (parent["sources"] if in_picture and parent else []),
            "source_tags": [] if tag == "picture" else (parent["source_tags"] if in_picture and parent else []),
        })

    def handle_data(self, data: str) -> None:
        if self._link_href:
            self._link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_href:
            title = " ".join("".join(self._link_text).split())
            if title:
                self.link_titles[self._link_href] = title
            self._link_href = ""
            self._link_text = []
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == tag:
                del self._stack[index:]
                return


def viewport_assets(html: str, base_url: str, width: int) -> dict:
    parser = _ViewportAssets(width)
    parser.feed(html or "")
    parser.close()
    titles = {}
    for raw, title in parser.link_titles.items():
        absolute = urljoin(base_url, raw.strip()).split("#", 1)[0]
        if title and absolute not in titles:
            titles[absolute] = title
    image_tags = {}
    for raw, tag in parser.image_tags.items():
        absolute = _absolute([raw], base_url)
        if absolute:
            image_tags.setdefault(absolute[0], tag)
    return {
        "links": _absolute(parser.links, base_url),
        "images": _absolute(parser.images, base_url),
        "imageTags": image_tags,
        "missing": parser.missing,
        "missingTags": parser.missing_tags,
        "linkTitles": titles,
    }


def content_links(html: str, base_url: str) -> list[str]:
    parser = _OutsideNav()
    parser.feed(html or "")
    parser.close()
    return _absolute(parser.links, base_url)


def has_discontinued_filter(html: str) -> bool:
    text = html or ""
    return "Discontinued Products" in text and "DISCONTINUED" in text


def insight_contents(html: str) -> list[str]:
    """Insights 필터의 Contents 체크 값. 화면에 나온 순서를 유지한다."""
    values: list[str] = []
    for tag in re.findall(r"<input\b[^>]*>", html or "", flags=re.I):
        if not re.search(r"""\bname=["']ec_contents_format["']""", tag, re.I):
            continue
        match = re.search(r"""\bvalue=["']([^"']*)["']""", tag)
        if not match:
            continue
        value = match.group(1).strip()
        if value and value not in values:
            values.append(value)
    return values


class _ArticleText(HTMLParser):
    """Insights 글 본문(`c-detail-content__txt`)만 모은다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._stack: list[tuple[bool, int]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = {name.lower(): value or "" for name, value in attrs if name}
        classes = data.get("class", "").lower()
        parent_detail, parent_skip = self._stack[-1] if self._stack else (False, 0)
        detail = parent_detail or "c-detail-content__txt" in classes
        skip = parent_skip
        if tag in {"script", "style", "noscript"} or "c-gnb" in classes or "c-footer" in classes:
            skip += 1
        if tag in _VOID_TAGS:
            return
        self._stack.append((detail, skip))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS or not self._stack:
            return
        self._stack.pop()

    def handle_data(self, data: str) -> None:
        if not self._stack:
            return
        detail, skip = self._stack[-1]
        if detail and skip == 0 and data.strip():
            self.parts.append(data)


def article_text(html: str) -> str:
    parser = _ArticleText()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return ""
    return " ".join(" ".join(parser.parts).split()).casefold()


def insight_endpoint(html: str) -> str:
    text = (html or "").replace("&quot;", '"').replace("\\u0026", "&")
    match = re.search(r'(/[A-Za-z0-9_./?&=%-]*searchInsightList[A-Za-z0-9_./?&=%-]*)', text)
    return match.group(1) if match else ""


PRODUCT_LIST_API = "/ncmsbtb/api/v1/proxy/retrieveProductList"
AUTHORING_API = "/ncmsbtb/api/v1/proxy/updateAuthoring"
_PLP_ENDPOINT = re.compile(
    r'data-endpoint="' + re.escape(PRODUCT_LIST_API)
)
_PLP_TYPE = re.compile(r"components/product/productlist")
_PDP_CALL = re.compile(
    r'data-count-url="' + re.escape(AUTHORING_API)
)


def _page_markup(html: str) -> str:
    text = html or ""
    return text.replace("\\/", "/").replace("&quot;", '"').replace('\\"', '"')


def api_page_kind(html: str) -> str:
    """제품 목록 컴포넌트가 있으면 PLP, 상품 페이지의 count URL만 PDP다."""
    text = _page_markup(html)
    if _PLP_ENDPOINT.search(text) or _PLP_TYPE.search(text):
        return "PLP"
    if _PDP_CALL.search(text):
        return "PDP"
    return ""


def _attr_json(html: str, name: str):
    match = re.search(rf'\b{re.escape(name)}="([^"]*)"', html or "")
    if not match:
        return None
    try:
        return json.loads(html_lib.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def _facet_tag(html: str) -> str:
    match = re.search(r'<[^>]*\bdata-facets="[^"]*"[^>]*>', html or "")
    return match.group(0) if match else ""


def plp_list_query(html: str, page_url: str) -> dict | None:
    """PLP 제품 수를 묻는 검색 조건. 토큰 값은 담지 않는다."""
    tag = _facet_tag(html)
    facets = _attr_json(tag, "data-facets")
    payload = _attr_json(tag, "data-payload")
    if not isinstance(facets, dict) or not isinstance(payload, dict):
        return None
    field = str(facets.get("categoryId") or "").strip()
    title = str(facets.get("categoryTitle") or facets.get("inputCategoryId") or "").strip()
    locale = str(facets.get("localeCode") or "").strip().upper()
    hub = str(payload.get("searchHub") or "").strip()
    text = _page_markup(html)
    token = re.search(r'coveoTokenUrl"\s*:\s*"([^"]+)"', text)
    if not token or not title or not locale:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]+", field) or not re.fullmatch(r"[A-Za-z0-9_-]+", hub):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", locale):
        return None
    if title != "allCategory" and not re.fullmatch(r"[A-Za-z0-9_-]+", title):
        return None
    path = token.group(1).strip()
    if not (path.startswith("/") or path.startswith("http://") or path.startswith("https://")):
        return None
    parts = [f'@ec_locale_code=="{locale}"']
    if title != "allCategory":
        parts.append(f'@{field}=="{title}"')
    return {
        "tokenUrl": urljoin(page_url, path),
        "searchHub": hub,
        "aq": " AND ".join(parts),
    }


def decode_html(body: bytes, content_type: str) -> str:
    lowered = content_type.lower()
    if "euc-kr" in lowered or "cp949" in lowered:
        return body.decode("cp949", errors="replace")
    return body.decode("utf-8", errors="replace")


class _PageTitle(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._parts: list[str] = []
        self.done = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title" and not self.done:
            self._in_title = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title" and self._in_title:
            self._in_title = False
            self.done = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)


def page_title(html: str) -> str:
    parser = _PageTitle()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return ""
    return " ".join("".join(parser._parts).split())


class _SpecEl:
    def __init__(self, tag: str, classes: set[str], attrs: dict | None = None) -> None:
        self.tag = tag
        self.classes = classes
        self.attrs = attrs or {}
        self.kids: list = []


class _SpecTree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _SpecEl("", set())
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self.skip:
            if tag not in _VOID_TAGS:
                self.skip += 1
            return
        if tag in {"script", "style"}:
            self.skip = 1
            return
        data = {name.lower(): value or "" for name, value in attrs if name}
        classes = set(data.get("class", "").lower().split())
        node = _SpecEl(tag, classes, data)
        self.stack[-1].kids.append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS and tag.lower() not in {"script", "style"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip:
            self.skip -= 1
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.skip or not data:
            return
        self.stack[-1].kids.append(data)


def _spec_tree(html: str) -> _SpecEl:
    parser = _SpecTree()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return parser.root
    return parser.root


def _node_has_content(node: _SpecEl) -> bool:
    for kid in node.kids:
        if isinstance(kid, str):
            if kid.strip():
                return True
            continue
        if isinstance(kid, _SpecEl):
            return True
    return False


def _dimension_image(box: _SpecEl) -> _SpecEl | None:
    found: list[_SpecEl] = []

    def visit(node: _SpecEl, in_frame: bool) -> None:
        if found:
            return
        frame = in_frame or (
            node.tag == "div" and "image" in node.classes and "c-image" in node.classes
        )
        if (
            frame
            and node is not box
            and node.tag == "div"
            and "cmp-image" in node.classes
        ):
            found.append(node)
            return
        for kid in node.kids:
            if isinstance(kid, _SpecEl):
                visit(kid, frame)

    visit(box, False)
    return found[0] if found else None


def dimension_state(html: str) -> str | None:
    """차원 영역. 없으면 None, 이미지나 글자가 있으면 ok, 비어 있으면 empty."""
    boxes: list[_SpecEl] = []

    def collect(node: _SpecEl) -> None:
        if node.tag == "div" and "c-specs-dimensions__container" in node.classes:
            boxes.append(node)
            return
        for kid in node.kids:
            if isinstance(kid, _SpecEl):
                collect(kid)

    collect(_spec_tree(html or ""))
    if not boxes:
        return None
    for box in boxes:
        image = _dimension_image(box)
        if image is None or not _node_has_content(image):
            return "empty"
    return "ok"


def headline_text(html: str) -> str:
    """상품 제목. c-text-contents__headline 안 첫 h1.cmp-text의 글자."""
    found: list[str] = []

    def visit(node: _SpecEl, in_headline: bool) -> None:
        if found:
            return
        here = in_headline or "c-text-contents__headline" in node.classes
        if here and node.tag == "h1" and "cmp-text" in node.classes:
            found.append(_spec_plain(node).strip())
            return
        for kid in node.kids:
            if isinstance(kid, _SpecEl):
                visit(kid, here)

    visit(_spec_tree(html or ""), False)
    return found[0] if found else ""


def _spec_plain(node) -> str:
    parts: list[str] = []

    def walk(item) -> None:
        if isinstance(item, str):
            parts.append(item)
            return
        for kid in item.kids:
            walk(kid)

    walk(node)
    return " ".join("".join(parts).split())


def _clean_spec_name(value: str) -> str:
    return " ".join((value or "").split()).rstrip(":").strip()


def _clean_spec_value(value: str) -> str:
    return " ".join((value or "").split())


def _norm_spec(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _grade_letter(value: str) -> str:
    """Energy Grade의 문자, 또는 ERP 값 YES (D) 안의 문자."""
    text = _clean_spec_value(value)
    alone = re.fullmatch(r"[A-G]\+{0,3}", text, re.I)
    if alone:
        return alone.group(0).upper()
    wrapped = re.fullmatch(r"yes\s*\(\s*([A-G]\+{0,3})\s*\)", text, re.I)
    if wrapped:
        return wrapped.group(1).upper()
    return ""


def _same_spec_value(left: str, right: str) -> bool:
    if _norm_spec(left) == _norm_spec(right):
        return True
    source = _grade_letter(left)
    compare = _grade_letter(right)
    return bool(source and compare and source == compare)


_ENERGY_LABEL = re.compile(r"^energy grade\s*:\s*([A-G]\+{0,3})$", re.I)


def _energy_grade_letter(root: _SpecEl) -> str:
    found: list[str] = []

    def visit(node: _SpecEl) -> None:
        if node.tag == "span" and "sr-only" in node.classes:
            match = _ENERGY_LABEL.match(_spec_plain(node))
            if match:
                found.append(match.group(1).upper())
        for kid in node.kids:
            if isinstance(kid, _SpecEl):
                visit(kid)

    visit(root)
    return found[0] if found else ""


def _standard_erp_grade(rows: list[dict] | None) -> str:
    """STANDARD 영역 ERP 값의 괄호 안 등급."""
    for row in rows or []:
        if _fold_label(row.get("group") or "") != "standard":
            continue
        if _fold_label(row.get("name") or "") != "erp":
            continue
        match = re.search(r"\(\s*([A-G]\+{0,3})\s*\)", row.get("value") or "", re.I)
        return match.group(1).upper() if match else ""
    return ""


def _image_alt(node: _SpecEl) -> str:
    if node.tag == "img":
        return (node.attrs.get("alt") or "").strip()
    for kid in node.kids:
        if isinstance(kid, _SpecEl):
            alt = _image_alt(kid)
            if alt:
                return alt
    return ""


def _file_list_energy_alt(root: _SpecEl) -> str | None:
    """file-list 이미지 alt가 등급 문자면 그 문자. 등급이 없으면 None."""
    found: list[str] = []

    def visit(node: _SpecEl) -> None:
        if found:
            return
        download = (node.attrs.get("data-file-download") or "").lower() == "true"
        if node.tag == "div" and "file-list" in node.classes and download:
            letter = _grade_letter(_image_alt(node))
            if letter:
                found.append(letter)
                return
        for kid in node.kids:
            if isinstance(kid, _SpecEl):
                visit(kid)

    visit(root)
    if not found:
        return None
    return found[0]


def energy_sheet_from_rows(source_html: str, rival_rows: list[dict] | None, compare_html: str = "") -> dict:
    """현 사이트 Energy Grade와 비교 사이트의 에너지 등급."""
    source = _energy_grade_letter(_spec_tree(source_html or ""))
    alt = _file_list_energy_alt(_spec_tree(compare_html)) if compare_html else None
    compare = alt or _standard_erp_grade(rival_rows)
    return {
        "source": source,
        "compare": compare,
        "same": bool(source and compare and source == compare),
    }


def _spec_title(value: str) -> str:
    """비교용 제목. 괄호와 그 안은 뺀다."""
    name = _clean_spec_name(value)
    title = re.sub(r"\s*[(（][^)）]*[)）]", "", name)
    title = " ".join(title.split()).strip()
    return title or name


def _fold_label(value: str) -> str:
    text = _norm_spec(value).replace("~", " ")
    text = re.sub(r"[()（）,./%]", " ", text)
    return " ".join(text.split())


def _paren_parts(name: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(.+?)\s*\(([^()]*)\)\s*", name.strip())
    if not match:
        return None
    head, inner = match.group(1).strip(), match.group(2).strip()
    if not head or not inner:
        return None
    return head, inner


def _slash_names(name: str) -> list[str]:
    """`SuperSign Control / Control+`처럼 마지막 단어의 다른 표기이면 두 이름을 돌려준다."""
    parts = [part.strip() for part in re.split(r"\s*/\s*", name) if part.strip()]
    if len(parts) != 2:
        return [name]
    left, right = parts
    words = left.split()
    if len(words) < 2:
        return [name]
    base = _norm_spec(words[-1]).rstrip("+")
    other = _norm_spec(right).rstrip("+")
    if not base or base != other:
        return [name]
    return [left, " ".join(words[:-1] + [right])]


def _match_keys(name: str, group: str) -> list[str]:
    """구체적인 키를 앞에 둔다. `제목 (세부)`는 그 제목 묶음의 세부 항목과 만난다."""
    keys: list[str] = []

    def add(key: str) -> None:
        key = " ".join(key.split())
        if key and key not in keys:
            keys.append(key)

    folded = _fold_label(name)
    outer = _paren_parts(name)
    if group:
        add(f"{_fold_label(group)}/{folded}")
    if outer:
        head, inner = outer
        add(f"{_fold_label(head)}/{_fold_label(inner)}")
        if group:
            add(f"{_fold_label(group)}/{_fold_label(inner)}")
            add(f"{_fold_label(group)}/{_fold_label(head)}")
        add(_fold_label(head))
    else:
        add(folded)
    return keys


_ALL_SPEC_LABELS = {
    "all spec",
    "all specs",
    "all specification",
    "all specifications",
    "전체 스펙",
    "전체 사양",
    "모든 스펙",
    "모든 사양",
}


def _is_all_spec_text(value: str) -> bool:
    compact = _norm_spec(value)
    if not compact or len(compact) > 32:
        return False
    if compact in _ALL_SPEC_LABELS:
        return True
    return compact.startswith("all spec")


def _class_has(classes: set[str], bits: tuple[str, ...], tails: tuple[str, ...]) -> bool:
    for token in classes:
        if any(bit in token for bit in bits):
            return True
        if token.endswith(tails):
            return True
    return False


def _is_spec_name(node: _SpecEl) -> bool:
    return _class_has(
        node.classes,
        ("spec-name", "spec-label", "spec-key"),
        ("__name", "__label", "-name", "-label"),
    )


def _is_spec_value(node: _SpecEl) -> bool:
    return _class_has(
        node.classes,
        ("spec-desc", "spec-value", "spec-text", "spec-data"),
        ("__desc", "__value", "__text", "__data", "-desc", "-value", "-text"),
    )


def _has_spec_structure(node: _SpecEl) -> bool:
    if node.tag in {"dl", "table", "tr"} or _is_spec_name(node):
        return True
    for kid in node.kids:
        if isinstance(kid, _SpecEl) and _has_spec_structure(kid):
            return True
    return False


def _heading_text(node: _SpecEl) -> str:
    if _has_spec_structure(node):
        return ""
    if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return _clean_spec_name(_spec_plain(node))
    named = node.classes & {"title", "category", "group"} or any(
        token.endswith("-title") or token.endswith("__category") or "spec-group" in token or "category" in token
        for token in node.classes
    )
    if not named:
        return ""
    return _clean_spec_name(_spec_plain(node))


def _elements(node: _SpecEl) -> list[_SpecEl]:
    return [kid for kid in node.kids if isinstance(kid, _SpecEl)]


def _from_dts(kids: list, group: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    name = ""
    values: list[str] = []

    def flush() -> None:
        nonlocal name, values
        if name:
            rows.append((group, name, " ".join(values)))
        name = ""
        values = []

    for kid in kids:
        if not isinstance(kid, _SpecEl):
            continue
        if kid.tag == "dt":
            flush()
            name = _spec_plain(kid)
            values = []
        elif kid.tag == "dd" and name:
            values.append(_spec_plain(kid))
        else:
            flush()
            rows.extend(_spec_pairs(kid, group))
    flush()
    return rows


def _from_rows(elements: list[_SpecEl], group: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    current = group
    for element in elements:
        if element.tag != "tr":
            heading = _heading_text(element)
            if heading:
                current = heading
            else:
                rows.extend(_spec_pairs(element, current))
            continue
        cells = [kid for kid in element.kids if isinstance(kid, _SpecEl) and kid.tag in {"td", "th"}]
        if len(cells) >= 2:
            rows.append((current, _spec_plain(cells[0]), " ".join(_spec_plain(cell) for cell in cells[1:])))
            continue
        if len(cells) == 1:
            nested = _spec_pairs(cells[0], current)
            if nested:
                rows.extend(nested)
            else:
                label = _clean_spec_name(_spec_plain(cells[0]))
                if label:
                    current = label
    return rows


def _from_mixed(elements: list[_SpecEl], group: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    current = group
    index = 0
    while index < len(elements):
        element = elements[index]
        if _is_spec_name(element) and index + 1 < len(elements) and _is_spec_value(elements[index + 1]):
            rows.append((current, _spec_plain(element), _spec_plain(elements[index + 1])))
            index += 2
            continue
        heading = _heading_text(element)
        if heading:
            current = heading
            index += 1
            continue
        rows.extend(_spec_pairs(element, current))
        index += 1
    return rows


def _section_heading(node: _SpecEl) -> str:
    """제목만 있는 칸. h4가 감싸져 있어도 다음 스펙 목록의 묶음 이름이 된다."""
    if _has_spec_structure(node):
        return ""
    direct = _heading_text(node)
    if direct:
        return direct
    found: list[str] = []

    def walk(el: _SpecEl) -> None:
        for kid in el.kids:
            if not isinstance(kid, _SpecEl) or _has_spec_structure(kid):
                continue
            text = _heading_text(kid)
            if text:
                found.append(text)
            else:
                walk(kid)

    walk(node)
    if len(found) != 1:
        return ""
    if _norm_spec(_spec_plain(node)) != _norm_spec(found[0]):
        return ""
    return found[0]


def _pair_container(node: _SpecEl) -> bool:
    if node.tag == "li":
        return True
    blob = " ".join(node.classes)
    return "spec" in blob or "__item" in blob


def _spec_pairs(node: _SpecEl, group: str = "") -> list[tuple[str, str, str]]:
    elements = _elements(node)
    if any(element.tag == "dt" for element in elements):
        return _from_dts(node.kids, group)
    if any(element.tag == "tr" for element in elements):
        return _from_rows(elements, group)
    if any(element.tag in {"table", "tbody", "thead", "dl"} or _is_spec_name(element) for element in elements):
        return _from_mixed(elements, group)
    if (
        _pair_container(node)
        and len(elements) == 2
        and not any(_has_spec_structure(element) for element in elements)
    ):
        return [(group, _spec_plain(elements[0]), _spec_plain(elements[1]))]
    rows: list[tuple[str, str, str]] = []
    current = group
    for element in elements:
        heading = _section_heading(element)
        if heading:
            current = heading
            continue
        rows.extend(_spec_pairs(element, current))
    return rows


def _label_before(chain: list[_SpecEl]) -> str:
    for depth in range(len(chain) - 2, -1, -1):
        parent = chain[depth]
        child = chain[depth + 1]
        prior: list = []
        for kid in parent.kids:
            if kid is child:
                break
            prior.append(kid)
        for kid in reversed(prior):
            if isinstance(kid, str):
                if kid.strip():
                    return kid
                continue
            if "c-compare-selling__spec" in kid.classes:
                continue
            text = _spec_plain(kid)
            if text:
                return text
    return ""


def _opens_with_all_spec(node: _SpecEl) -> bool:
    for kid in node.kids:
        if isinstance(kid, str):
            if _is_all_spec_text(kid):
                return True
            continue
        if kid.tag in {"button", "a", "h1", "h2", "h3", "h4", "summary"} and _is_all_spec_text(_spec_plain(kid)):
            return True
    return False


def _collect_regions(root: _SpecEl, pred) -> list[_SpecEl]:
    found: list[_SpecEl] = []

    def visit(node: _SpecEl, inside: bool) -> None:
        hit = pred(node) and not inside
        if hit:
            found.append(node)
        for kid in node.kids:
            if isinstance(kid, _SpecEl):
                visit(kid, inside or bool(pred(node)))

    visit(root, False)
    return found


def _selling_regions(root: _SpecEl) -> list[_SpecEl]:
    nodes: list[tuple[_SpecEl, list[_SpecEl]]] = []

    def visit(node: _SpecEl, ancestors: list[_SpecEl], inside: bool) -> None:
        hit = "c-compare-selling__spec" in node.classes and not inside
        if hit:
            nodes.append((node, ancestors + [node]))
        marked = inside or "c-compare-selling__spec" in node.classes
        for kid in node.kids:
            if isinstance(kid, _SpecEl):
                visit(kid, ancestors + [node], marked)

    visit(root, [], False)
    labeled = [
        node for node, chain in nodes
        if _is_all_spec_text(_label_before(chain)) or _opens_with_all_spec(node)
    ]
    if labeled:
        return labeled
    return [node for node, _chain in nodes]


_RIVAL_AREA = {"tech-spacs-area", "tech-specs-area", "tech-spec-area"}


def _rival_region(node: _SpecEl) -> bool:
    return bool(node.classes & _RIVAL_AREA) and {"collapse", "show"} <= node.classes


def _spec_dicts(regions: list[_SpecEl]) -> list[dict]:
    rows: list[dict] = []
    for region in regions:
        for group, name, value in _spec_pairs(region):
            label = _clean_spec_name(name)
            if not label or _is_all_spec_text(label):
                continue
            section = _clean_spec_name(group)
            if _norm_spec(section) == _norm_spec(label):
                section = ""
            rows.append({
                "group": section,
                "name": label,
                "value": _clean_spec_value(value),
            })
    return rows


def selling_spec_rows(html: str) -> list[dict] | None:
    """All Spec의 c-compare-selling__spec 항목. 영역이 없으면 None."""
    root = _spec_tree(html)
    regions = _selling_regions(root)
    if not regions:
        return None
    return _spec_dicts(regions)


def spec_sections(rows: list[dict] | None) -> list[dict]:
    """h4 제목별로 묶은 All Spec 항목."""
    sections: list[dict] = []
    found: dict[str, dict] = {}
    for row in rows or []:
        title = _clean_spec_name(row.get("group") or "")
        section = found.get(title)
        if section is None:
            section = {"title": title, "rows": []}
            found[title] = section
            sections.append(section)
        section["rows"].append({
            "name": row.get("name") or "",
            "value": row.get("value") or "",
        })
    return sections


def rival_spec_rows(html: str) -> list[dict] | None:
    """펼쳐진 tech-spacs-area 항목. 없으면 All Spec의 c-compare-selling__spec을 읽는다."""
    root = _spec_tree(html)
    regions = _collect_regions(root, _rival_region)
    if not regions:
        regions = _selling_regions(root)
    if not regions:
        return None
    return _spec_dicts(regions)


def _spec_items(rows: list[dict]) -> list[dict]:
    items: list[dict] = []
    family = 0
    for row in rows:
        name = _clean_spec_name(row.get("name") or "")
        if not name or _is_all_spec_text(name):
            family += 1
            continue
        group = _clean_spec_name(row.get("group") or "")
        value = _clean_spec_value(row.get("value") or "")
        aliases = _slash_names(name)
        optional = len(aliases) > 1
        for alias in aliases:
            items.append({
                "name": alias,
                "origin": name,
                "value": value,
                "group": group,
                "keys": _match_keys(alias, group),
                "optional": optional,
                "family": family,
            })
        family += 1
    return items


def _diff_label(one: dict | None, other: dict | None, general: bool) -> str:
    chosen = one or other
    if chosen is None:
        return ""
    if general:
        return _spec_title(chosen["name"])
    for item in (one, other):
        if item and "(" in item["origin"]:
            return item["origin"]
    return chosen["name"]


def spec_check_rows(source: list[dict], rival: list[dict]) -> list[dict]:
    """h4 묶음마다 맞춘 항목. 값이 같으면 same이다."""
    left = _spec_items(source)
    right = _spec_items(rival)
    index: dict[str, list[int]] = {}
    for position, item in enumerate(right):
        for key in item["keys"]:
            index.setdefault(key, []).append(position)
    used: set[int] = set()
    matched_left: set[int] = set()
    pairs: list[tuple[int, int, bool]] = []
    for position, item in enumerate(left):
        found = None
        general = False
        for key in item["keys"]:
            for candidate in index.get(key, []):
                if candidate in used:
                    continue
                other = right[candidate]
                left_group = _fold_label(item["group"])
                right_group = _fold_label(other["group"])
                if left_group and right_group and left_group != right_group:
                    continue
                found = candidate
                general = "/" not in key
                break
            if found is not None:
                break
        if found is None:
            continue
        used.add(found)
        matched_left.add(position)
        pairs.append((position, found, general))

    checks: list[dict] = []

    def covered(items: list[dict], position: int, matched: set[int]) -> bool:
        item = items[position]
        if not item["optional"]:
            return False
        return any(
            other in matched and items[other]["family"] == item["family"]
            for other in range(len(items))
        )

    def seen_family(items: list[dict], position: int, done: set[int]) -> bool:
        family = items[position]["family"]
        if family in done:
            return True
        done.add(family)
        return False

    def add(one: dict | None, other: dict | None, general: bool) -> None:
        source_value = one["value"] if one else ""
        compare_value = other["value"] if other else ""
        group = ""
        for item in (one, other):
            if item and item.get("group"):
                group = item["group"]
                break
        name = one["name"] if one and one.get("group") else other["name"] if other and other.get("group") else _diff_label(one, other, general)
        checks.append({
            "group": group,
            "name": name,
            "diffName": _diff_label(one, other, general),
            "source": source_value,
            "compare": compare_value,
            "same": _same_spec_value(source_value, compare_value),
        })

    for left_index, right_index, general in pairs:
        add(left[left_index], right[right_index], general)
    def alone(item: dict) -> dict:
        if not item["optional"]:
            return item
        return {**item, "name": item["origin"], "origin": item["origin"]}

    left_done: set[int] = set()
    for position, item in enumerate(left):
        if position in matched_left or covered(left, position, matched_left):
            continue
        if item["optional"] and seen_family(left, position, left_done):
            continue
        add(alone(item), None, False)
    right_done: set[int] = set()
    for position, item in enumerate(right):
        if position in used or covered(right, position, used):
            continue
        if item["optional"] and seen_family(right, position, right_done):
            continue
        add(None, alone(item), False)
    return checks


def diff_spec_rows(source: list[dict], rival: list[dict]) -> list[dict]:
    """값이 다르거나 한쪽에만 있는 항목."""
    return [
        {"name": row["diffName"], "source": row["source"], "compare": row["compare"]}
        for row in spec_check_rows(source, rival)
        if not row["same"]
    ]


def spec_check_sections(source: list[dict], rival: list[dict]) -> list[dict]:
    """c-compare-selling__spec의 h4를 제목으로 한 체크 목록."""
    sections: list[dict] = []
    found: dict[str, dict] = {}
    for row in spec_check_rows(source, rival):
        title = row["group"]
        section = found.get(title)
        if section is None:
            section = {"title": title, "rows": []}
            found[title] = section
            sections.append(section)
        section["rows"].append({
            "name": row["name"],
            "source": row["source"],
            "compare": row["compare"],
            "same": row["same"],
        })
    return sections
