import threading
import time
import unittest
from unittest.mock import patch

from site_audit.audit import classify, run_audit
from site_audit.guard import UrlRejected, check_url
from site_audit.http_fetch import HttpResult
from site_audit.parse import extract, image_size
from site_audit.report import to_csv


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
)


def _public_resolve(host, port, type=None):
    return [(None, None, None, None, ("93.184.216.34", port))]


def _private_resolve(host, port, type=None):
    return [(None, None, None, None, ("127.0.0.1", port))]


class GuardTests(unittest.TestCase):
    def test_rejects_private_and_credentials(self):
        with self.assertRaises(UrlRejected):
            check_url("http://127.0.0.1/")
        with self.assertRaises(UrlRejected):
            check_url("http://10.1.1.1/")
        with self.assertRaises(UrlRejected):
            check_url("http://169.254.1.1/")
        with self.assertRaises(UrlRejected):
            check_url("https://user:secret@example.com/")
        with self.assertRaises(UrlRejected):
            check_url("file:///etc/passwd")
        with self.assertRaises(UrlRejected):
            check_url("https://example.com:22/")

    def test_accepts_public_example(self):
        target = check_url("https://example.com/shop", resolve=_public_resolve)
        self.assertEqual(target.hostname, "example.com")
        self.assertEqual(target.ip, "93.184.216.34")

    def test_rejects_name_that_resolves_private(self):
        with self.assertRaises(UrlRejected):
            check_url("https://example.com/", resolve=_private_resolve)


class ParseTests(unittest.TestCase):
    def test_extract_skips_non_http(self):
        html = '<a href="/a">a</a><a href="mailto:a@b.c">m</a><img src="/p.png"><img src="data:image/gif;base64,AA">'
        links, images = extract(html, "https://example.com/root")
        self.assertEqual(links, ["https://example.com/a"])
        self.assertEqual(images, ["https://example.com/p.png"])

    def test_png_size(self):
        self.assertEqual(image_size(PNG), (1, 1))

    def test_data_src_image_is_checked(self):
        from site_audit.parse import viewport_assets

        html = '<img alt="lazy" data-src="/lazy.jpg"><img alt="plain" src="/plain.jpg">'
        assets = viewport_assets(html, "https://example.com/uk/business/", 1440)
        self.assertIn("https://example.com/lazy.jpg", assets["images"])
        self.assertIn("https://example.com/plain.jpg", assets["images"])
        self.assertNotIn("lazy", assets["missing"])

    def test_hidden_roll_selector_images_are_skipped(self):
        from site_audit.parse import viewport_assets

        html = '''
            <div class="BU0009">
              <div class="sticky-menu-wrap __no-images">
                <div class="c-roll-selector__item-image"><img src="/hidden.jpg" alt="hidden"></div>
              </div>
            </div>
            <div class="c-roll-selector__item-image"><img src="/shown.jpg" alt="shown"></div>
        '''
        assets = viewport_assets(html, "https://example.com/uk/business/", 1440)
        self.assertIn("https://example.com/shown.jpg", assets["images"])
        self.assertNotIn("https://example.com/hidden.jpg", assets["images"])
        self.assertNotIn("hidden", assets["missing"])

    def test_wa_type_links_stay_inside_the_menu(self):
        from site_audit.parse import wa_type_links

        html = '''
            <a href="/uk/business/outside/">Outside</a>
            <div class="c-roll-selector" data-wa-type="tab">
              <a href="/uk/business/hvac/a/"><img alt="A"><div class="c-roll-selector__item-name">Known</div></a>
              <a href="/uk/business/hvac/b/"><div class="c-roll-selector__item-name">Added</div></a>
              <a href="javascript:void(0)">Skip</a>
            </div>
        '''
        links = wa_type_links(html, "https://example.com/uk/business/hvac/a/")
        self.assertEqual(links, [
            {"label": "Known", "url": "https://example.com/uk/business/hvac/a/"},
            {"label": "Added", "url": "https://example.com/uk/business/hvac/b/"},
        ])

    def test_tablist_link_is_kept_and_content_tab_is_not(self):
        from site_audit.parse import breadcrumbs, wa_type_links

        html = '''
            <a href="/uk/business/outside/">Outside</a>
            <ul role="tablist">
              <li role="tab"><a href="/uk/business/hvac/commercial-solutions/">Commercial Solutions</a></li>
              <li role="tab"><a href="#range">Range</a></li>
              <li role="tab"><button type="button">Overview</button></li>
              <li role="tab"><a href="/uk/business/hvac/residential-solutions/lg-allstars/">LG All Stars</a></li>
            </ul>
            <nav class="c-breadcrumb" aria-label="Breadcrumb">
              <ol>
                <li><a href="/uk/business/">Home</a></li>
                <li><a href="/uk/business/hvac/">HVAC</a></li>
                <li><a href="/uk/business/hvac/residential-solutions/">Residential Solutions</a></li>
                <li aria-current="page">LG All Stars</li>
              </ol>
            </nav>
        '''
        base = "https://example.com/uk/business/hvac/commercial-solutions/"
        links = wa_type_links(html, base)
        self.assertEqual([item["url"] for item in links], [
            "https://example.com/uk/business/hvac/commercial-solutions/",
            "https://example.com/uk/business/hvac/residential-solutions/lg-allstars/",
        ])
        self.assertEqual(links[1]["label"], "LG All Stars")
        self.assertEqual(breadcrumbs(html, base), [
            {"label": "Home", "url": "https://example.com/uk/business/"},
            {"label": "HVAC", "url": "https://example.com/uk/business/hvac/"},
            {"label": "Residential Solutions", "url": "https://example.com/uk/business/hvac/residential-solutions/"},
            {"label": "LG All Stars", "url": ""},
        ])

    def test_chunked_body(self):
        from site_audit.http_fetch import _unchunk

        raw = b"5\r\nhello\r\n0\r\n\r\n"
        self.assertEqual(_unchunk(raw), b"hello")


class AuditTests(unittest.TestCase):
    def test_child_pages_and_broken_image(self):
        pages = {
            "https://example.com/": (
                200,
                "text/html",
                '<a href="/item">item</a><img src="/ok.png">',
            ),
            "https://example.com/item": (
                200,
                "text/html",
                '<img src="https://cdn.example.net/missing.png">',
            ),
            "https://example.com/ok.png": (200, "image/png", ""),
            "https://cdn.example.net/missing.png": (404, "text/plain", ""),
        }

        def fake(url, read_body=True):
            status, content_type, body = pages.get(url, (0, "", ""))
            error = "" if status else "연결 실패"
            return HttpResult(url=url, status=status, content_type=content_type, body=body.encode(), error=error)

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": "https://example.com/",
            "hostname": "example.com",
        })()):
            report = run_audit("https://example.com/", rules={"path_contains": {}}, fetch_one=fake, resolve=_public_resolve)

        self.assertTrue(report.ok)
        self.assertEqual(report.child_count, 1)
        self.assertTrue(report.report_ready)
        by_url = {row.url: row for row in report.rows}
        self.assertEqual(by_url["https://example.com/"].verdict, "통과")
        self.assertEqual(by_url["https://example.com/item"].verdict, "실패")
        self.assertIn("깨진 이미지", by_url["https://example.com/item"].reason)
        self.assertIn("유형 표식 없음", " ".join(report.notes))
        csv_text = to_csv(report)
        self.assertIn("주소,유형,결과,이유", csv_text)

    def test_progress_names_the_current_step(self):
        pages = {
            "https://example.com/": (200, "text/html", '<a href="/item">item</a>'),
            "https://example.com/item": (200, "text/html", "<p>item</p>"),
        }

        def fake(url, read_body=True):
            status, content_type, body = pages[url]
            return HttpResult(url=url, status=status, content_type=content_type, body=body.encode())

        seen = []

        def on_progress(event):
            seen.append(event["step"])

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": "https://example.com/",
            "hostname": "example.com",
        })()):
            run_audit(
                "https://example.com/",
                rules={"path_contains": {}},
                fetch_one=fake,
                on_progress=on_progress,
            )

        self.assertIn("주소를 확인하는 중", seen)
        self.assertIn("페이지를 읽는 중", seen)
        self.assertTrue(any(step.startswith("링크를 확인하는 중") for step in seen))
        self.assertEqual(seen[-1], "결과를 정리하는 중")

    def test_discover_lists_child_pages_only(self):
        from site_audit.audit import discover_pages

        pages = {
            "https://example.com/": (200, "text/html", '<a href="/item">item</a><a href="https://cdn.example.net/x">out</a>'),
            "https://example.com/item": (200, "text/html", "<p>item</p>"),
        }
        fetched = []

        def fake(url, read_body=True):
            fetched.append(url)
            status, content_type, body = pages.get(url, (404, "text/plain", ""))
            return HttpResult(url=url, status=status, content_type=content_type, body=body.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": "https://example.com/",
            "hostname": "example.com",
        })()):
            listing = discover_pages("https://example.com/", rules={"path_contains": {}}, fetch_one=fake)

        self.assertTrue(listing.ok)
        self.assertEqual([page.url for page in listing.pages], ["https://example.com/item"])
        self.assertEqual(listing.pages[0].kind, "일반")
        self.assertNotIn("https://cdn.example.net/x", fetched)

    def test_discover_lists_every_child_without_a_count_cap(self):
        from site_audit.audit import discover_pages

        links = "".join(f'<a href="/p/{index}">p</a>' for index in range(5100))

        def fake(url, read_body=True):
            body = links if url == "https://example.com/" else "<p>x</p>"
            return HttpResult(url=url, status=200, content_type="text/html", body=body.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": "https://example.com/",
            "hostname": "example.com",
        })()):
            listing = discover_pages("https://example.com/", rules={"path_contains": {}}, fetch_one=fake)

        self.assertTrue(listing.ok)
        self.assertEqual(len(listing.pages), 5101)
        self.assertFalse(listing.stopped)
        self.assertFalse(any("상한" in note for note in listing.notes))

    def test_discover_stops_before_the_next_page(self):
        from site_audit.audit import discover_pages

        fetched = []

        def fake(url, read_body=True):
            fetched.append(url)
            body = '<a href="/item">item</a><a href="/other">other</a>' if url.endswith("/") else "<p>x</p>"
            return HttpResult(url=url, status=200, content_type="text/html", body=body.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": "https://example.com/",
            "hostname": "example.com",
        })()):
            listing = discover_pages(
                "https://example.com/",
                rules={"path_contains": {}},
                fetch_one=fake,
                should_stop=lambda: len(fetched) >= 2,
            )

        self.assertTrue(listing.stopped)
        self.assertEqual(fetched, ["https://example.com/", "https://example.com/item"])
        self.assertEqual([page.url for page in listing.pages], ["https://example.com/item"])
        self.assertIn("수집을 중지했습니다.", listing.notes)

    def test_stop_marks_the_running_job(self):
        from site_audit import server
        from site_audit.audit import PageList

        job_id = "stop-test"
        server._jobs.clear()
        server._running = True
        server._jobs[job_id] = {
            "id": job_id,
            "status": "running",
            "url": "https://example.com/",
            "message": "",
            "cancel": True,
        }

        def fake_discover(url, on_progress=None, should_stop=None):
            self.assertTrue(should_stop())
            return PageList(ok=True, root=url, pages=[], notes=["수집을 중지했습니다."], stopped=True)

        try:
            with patch.object(server, "discover_pages", fake_discover):
                server._run(job_id, "https://example.com/")
            self.assertEqual(server._jobs[job_id]["status"], "stopped")
            self.assertEqual(server._jobs[job_id]["message"], "수집을 중지했습니다.")
            self.assertFalse(server._running)
        finally:
            server._jobs.pop(job_id, None)
            server._running = False

    def test_no_children_is_not_a_pass_report(self):
        def fake(url, read_body=True):
            return HttpResult(url=url, status=200, content_type="text/html", body=b"<p>alone</p>")

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": "https://example.com/",
            "hostname": "example.com",
        })()):
            report = run_audit("https://example.com/", rules={"path_contains": {}}, fetch_one=fake)

        self.assertTrue(report.ok)
        self.assertEqual(report.child_count, 0)
        self.assertFalse(report.report_ready)

    def test_private_root_does_not_run(self):
        report = run_audit("http://127.0.0.1/")
        self.assertFalse(report.ok)
        self.assertEqual(report.rows, [])

    def test_classify_uses_path_rule(self):
        kind, has_rules = classify("https://example.com/product/1", {"path_contains": {"PDP": ["/product/"]}})
        self.assertEqual(kind, "PDP")
        self.assertTrue(has_rules)

    def test_missing_ufn_fails_pdp(self):
        def fake(url, read_body=True):
            if url.endswith("/product/1"):
                body = '<a href="/other">x</a><p>no marker</p>'
            else:
                body = "<p>other</p>"
            return HttpResult(url=url, status=200, content_type="text/html", body=body.encode())

        rules = {"path_contains": {"PDP": ["/product/"]}, "ufn_marker": "", "thumbnail_min_width": None, "thumbnail_min_height": None, "plp_count_pattern": ""}
        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": "https://example.com/product/1",
            "hostname": "example.com",
        })()):
            report = run_audit("https://example.com/product/1", rules=rules, fetch_one=fake)
        root = report.rows[0]
        self.assertEqual(root.kind, "PDP")
        self.assertEqual(root.verdict, "실패")
        self.assertIn("UFN 기준 없음", root.reason)

    def test_read_place_uses_html_lang_and_country_path(self):
        from site_audit.audit import read_place

        language, country = read_place("https://www.example.com/uk/tvs", '<html lang="en-GB"><p>uk</p></html>')
        self.assertEqual(language, "영어")
        self.assertEqual(country, "영국")

        language, country = read_place("https://www.example.com/ca_en/tvs", "<p>ca</p>")
        self.assertEqual(language, "영어")
        self.assertEqual(country, "캐나다")

    def test_infer_kind_marks_product_list_and_insights(self):
        from site_audit.audit import infer_kind

        rules = {"path_contains": {}}
        product = '<script type="application/ld+json">{"@type":"Product","name":"TV"}</script>'
        listing = '<script type="application/ld+json">{"@type":"ItemList","name":"TVs"}</script>'
        self.assertEqual(infer_kind("https://example.com/uk/tvs/lg-oled65c4", product, rules), "PDP")
        self.assertEqual(infer_kind("https://example.com/uk/tvs", listing, rules), "일반")
        self.assertEqual(infer_kind("https://example.com/uk/insights/story", "<p>x</p>", rules), "Insights")
        self.assertEqual(infer_kind("https://example.com/uk/about", "<p>x</p>", rules), "일반")
        listing_class = '<div class="c-result-area__product-list"></div>'
        other_class = '<section class="cmp-productList"></section>'
        product_api = '<div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK"></div>'
        escaped_api = '<div data-endpoint="\\/ncmsbtb\\/api\\/v1\\/proxy\\/retrieveProductList"></div>'
        component = '<script>{":type":"lgebtb/components/product/productlist"}</script>'
        short_component = '<script>{":type":"components/product/productlist"}</script>'
        compare_only = (
            '<script>{"compareBtnUrl":"/uk/business/compare-results/",'
            '"productListApi":"/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK"}</script>'
        )
        shared_api = (
            '<script>{"productListEndpoint":"/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK",'
            '"compareResultApiEndpoint":"/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK"}</script>'
        )
        self.assertEqual(infer_kind("https://example.com/uk/hvac/", listing_class, rules), "일반")
        self.assertEqual(infer_kind("https://example.com/uk/about", other_class, rules), "일반")
        self.assertEqual(infer_kind("https://example.com/uk/about", shared_api, rules), "일반")
        self.assertEqual(infer_kind("https://example.com/uk/about", compare_only, rules), "일반")
        self.assertEqual(infer_kind("https://example.com/uk/hvac/", product_api, rules), "PLP")
        self.assertEqual(infer_kind("https://example.com/uk/hvac/", escaped_api, rules), "PLP")
        self.assertEqual(infer_kind("https://example.com/uk/hvac/", component, rules), "PLP")
        self.assertEqual(infer_kind("https://example.com/uk/hvac/", short_component, rules), "PLP")
        authoring = '<div class="js-page-count" data-count-url="/ncmsbtb/api/v1/proxy/updateAuthoring?locale=UK"></div>'
        escaped_authoring = '<div class="js-page-count" data-count-url="\\/ncmsbtb\\/api\\/v1\\/proxy\\/updateAuthoring"></div>'
        shared_authoring = '<script>{"pdpPageVisitsEndpoint":"/ncmsbtb/api/v1/proxy/updateAuthoring?locale=UK"}</script>'
        both = product_api + authoring
        self.assertEqual(infer_kind("https://example.com/uk/tvs/lg-oled65c4", authoring, rules), "PDP")
        self.assertEqual(infer_kind("https://example.com/uk/tvs/lg-oled65c4", escaped_authoring, rules), "PDP")
        self.assertEqual(infer_kind("https://example.com/uk/about", shared_authoring, rules), "일반")
        self.assertEqual(infer_kind("https://example.com/uk/hvac/", both, rules), "PLP")

    def test_discover_keeps_depth_past_two_and_place(self):
        from site_audit.audit import discover_pages

        pages = {
            "https://example.com/uk": '<html lang="en-GB"><a href="/uk/a">a</a></html>',
            "https://example.com/uk/a": '<a href="/uk/a/b">b</a>',
            "https://example.com/uk/a/b": '<a href="/uk/a/b/c">c</a>',
            "https://example.com/uk/a/b/c": "<p>c</p>",
        }

        def fake(url, read_body=True):
            body = pages.get(url, "<p>x</p>")
            return HttpResult(url=url, status=200, content_type="text/html", body=body.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": "https://example.com/uk",
            "hostname": "example.com",
        })()):
            listing = discover_pages("https://example.com/uk", rules={"path_contains": {}}, fetch_one=fake)

        self.assertTrue(listing.ok)
        self.assertEqual(listing.language, "영어")
        self.assertEqual(listing.country, "영국")
        self.assertEqual(
            [(page.url, page.depth, page.parent) for page in listing.pages],
            [
                ("https://example.com/uk/a", 1, "https://example.com/uk"),
                ("https://example.com/uk/a/b", 2, "https://example.com/uk/a"),
                ("https://example.com/uk/a/b/c", 3, "https://example.com/uk/a/b"),
            ],
        )

    def test_discover_nests_deeper_path_under_its_section(self):
        from site_audit.audit import discover_pages

        root = "https://www.lg.com/uk/business/"
        pages = {
            root: (
                '<a href="/uk/business/hvac/commercial-solutions/">solutions</a>'
                '<a href="/uk/">outside</a>'
                '<a href="/uk/business/hvac/">hvac</a>'
            ),
            "https://www.lg.com/uk/business/hvac": "<p>hvac</p>",
            "https://www.lg.com/uk/business/hvac/commercial-solutions/": "<p>solutions</p>",
        }

        def fake(url, read_body=True):
            body = pages.get(url, "<p>x</p>")
            return HttpResult(url=url, status=200, content_type="text/html", body=body.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "www.lg.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages}
        self.assertNotIn("https://www.lg.com/uk/", by_url)
        hvac = by_url["https://www.lg.com/uk/business/hvac"]
        child = by_url["https://www.lg.com/uk/business/hvac/commercial-solutions/"]
        self.assertEqual((hvac.depth, hvac.parent), (1, root))
        self.assertEqual((child.depth, child.parent), (2, hvac.url))

    def test_plp_paging_and_learn_more_become_children(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        plp = "https://example.com/uk/business/hvac/"
        page2 = "https://example.com/uk/business/hvac/?page=2"
        pdp1 = "https://example.com/uk/business/hvac/lg-a1"
        pdp2 = "https://example.com/uk/business/products/lg-b2"
        other = "https://example.com/uk/business/hvac/other"
        pages = {
            root: '<a href="/uk/business/hvac/">hvac</a>',
            plp: '''
                <script>{"productListApi":"/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK"}</script><div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK"></div>
                <div class="c-result-area__product-list">
                  <a href="/uk/business/hvac/lg-a1"><span>Learn more</span></a>
                  <a href="/uk/business/hvac/other">Buy</a>
                </div>
                <ul class="c-page__list"><li><a href="?page=2">2</a></li></ul>
            ''',
            page2: '''
                <script>{"productListApi":"/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK"}</script><div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK"></div>
                <div class="c-result-area__product-list">
                  <a href="/uk/business/products/lg-b2">Learn More</a>
                </div>
            ''',
            pdp1: "<p>a</p>",
            pdp2: "<p>b</p>",
            other: "<p>other</p>",
        }

        def fake(url, read_body=True):
            body = pages.get(url, "<p>x</p>")
            return HttpResult(url=url, status=200, content_type="text/html", body=body.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages}
        self.assertEqual(by_url[plp].kind, "PLP")
        self.assertEqual((by_url[page2].kind, by_url[page2].parent, by_url[page2].depth), ("PLP", plp, 2))
        self.assertEqual((by_url[pdp1].kind, by_url[pdp1].parent, by_url[pdp1].depth), ("PDP", plp, 2))
        self.assertEqual((by_url[pdp2].kind, by_url[pdp2].parent, by_url[pdp2].depth), ("PDP", page2, 3))
        self.assertEqual((by_url[other].kind, by_url[other].parent), ("일반", plp))

    def test_product_list_api_marks_menu_item_as_plp(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        plp = "https://example.com/uk/business/hvac/"
        other = "https://example.com/uk/business/about/"
        hidden = "https://example.com/uk/business/hvac/lg-a1"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/">HVAC</a></li>
              <li><a href="/uk/business/about/">About</a></li>
            </ul>
        '''
        plp_html = '''
            <script>{"productListApi":"/ncmsbtb/api/v1/proxy/retrieveProductList"}</script><div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList"></div>
            <div class="c-result-area__product-list">
              <a href="/uk/business/hvac/lg-a1"><span>Learn more</span></a>
            </div>
        '''

        def fake(url, read_body=True, body=None):
            if url == plp:
                text = plp_html
            elif url == root:
                text = home
            else:
                text = (
                    '<script>{"productListEndpoint":"/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK",'
                    '"compareResultApiEndpoint":"/ncmsbtb/api/v1/proxy/retrieveProductList?locale=UK"}</script>'
                )
            return HttpResult(url=url, status=200, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages if page.url}
        self.assertEqual(by_url[plp].kind, "PLP")
        self.assertEqual(by_url[other].kind, "일반")
        self.assertNotIn(hidden, by_url)

    def test_product_list_api_marks_crawled_page_as_plp(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        plp = "https://example.com/uk/business/hvac/"
        pages = {
            root: '<a href="/uk/business/hvac/">hvac</a>',
            plp: '<script>{"productListApi":"\\/ncmsbtb\\/api\\/v1\\/proxy\\/retrieveProductList"}</script><div data-endpoint="\\/ncmsbtb\\/api\\/v1\\/proxy\\/retrieveProductList"></div>',
        }

        def fake(url, read_body=True):
            body = pages.get(url, "<p>x</p>")
            return HttpResult(url=url, status=200, content_type="text/html", body=body.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages}
        self.assertEqual(by_url[plp].kind, "PLP")

    def test_authoring_api_marks_menu_item_as_pdp(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        plp = "https://example.com/uk/business/hvac/"
        pdp = "https://example.com/uk/business/hvac/lg-a1/"
        other = "https://example.com/uk/business/about/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/">HVAC</a></li>
              <li><a href="/uk/business/hvac/lg-a1/">Model</a></li>
              <li><a href="/uk/business/about/">About</a></li>
            </ul>
        '''
        pages = {
            root: home,
            plp: '<script>{"productListApi":"/ncmsbtb/api/v1/proxy/retrieveProductList"}</script><div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList"></div>',
            pdp: '<div class="js-page-count" data-count-url="/ncmsbtb/api/v1/proxy/updateAuthoring?locale=UK"></div>',
            other: "<p>about</p>",
        }
        calls = []

        def fake(url, read_body=True, body=None):
            calls.append(url)
            text = pages.get(url, "<p>x</p>")
            return HttpResult(url=url, status=200, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages if page.url}
        self.assertEqual(by_url[plp].kind, "PLP")
        self.assertEqual(by_url[pdp].kind, "PDP")
        self.assertEqual(by_url[other].kind, "일반")
        self.assertEqual(calls.count(plp), 1)
        self.assertEqual(calls.count(pdp), 1)

    def test_page_kinds_are_read_together(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        first = "https://example.com/uk/business/hvac/"
        second = "https://example.com/uk/business/hvac/lg-a1/"
        third = "https://example.com/uk/business/about/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/">HVAC</a></li>
              <li><a href="/uk/business/hvac/lg-a1/">Model</a></li>
              <li><a href="/uk/business/about/">About</a></li>
            </ul>
        '''
        bodies = {
            first: '<script>{"productListApi":"/ncmsbtb/api/v1/proxy/retrieveProductList"}</script><div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList"></div>',
            second: '<div class="js-page-count" data-count-url="/ncmsbtb/api/v1/proxy/updateAuthoring"></div>',
            third: "<p>about</p>",
        }
        open_reads = 0
        peak = 0
        guard = threading.Lock()

        def fake(url, read_body=True, body=None):
            nonlocal open_reads, peak
            if url == root:
                return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())
            with guard:
                open_reads += 1
                peak = max(peak, open_reads)
            time.sleep(0.05)
            with guard:
                open_reads -= 1
            text = bodies.get(url, "<p>x</p>")
            return HttpResult(url=url, status=200, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages if page.url}
        self.assertGreaterEqual(peak, 2)
        self.assertEqual(by_url[first].kind, "PLP")
        self.assertEqual(by_url[second].kind, "PDP")
        self.assertEqual(by_url[third].kind, "일반")

    def test_missing_wa_type_menu_is_added_beside_the_page(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        known = "https://example.com/uk/business/hvac/a/"
        added = "https://example.com/uk/business/hvac/b/"
        outside = "https://example.com/uk/business/outside/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/a/">Known</a></li>
            </ul>
        '''
        page = '''
            <a href="/uk/business/outside/">Outside</a>
            <div class="c-roll-selector" data-wa-type="tab">
              <a href="/uk/business/hvac/a/?from=tab"><div class="c-roll-selector__item-name">Known</div></a>
              <a href="/uk/business/hvac/b/"><div class="c-roll-selector__item-name">Added</div></a>
            </div>
        '''
        plp = '<div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList"></div>'

        def fake(url, read_body=True, body=None):
            if url == root:
                text = home
            elif url == known:
                text = page
            elif url == added:
                text = plp
            else:
                text = "<p>x</p>"
            return HttpResult(url=url, status=200, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        urls = [page.url for page in listing.pages if page.url]
        self.assertEqual(urls.count(known), 1)
        self.assertNotIn(outside, urls)
        by_url = {page.url: page for page in listing.pages if page.url}
        source = by_url[known]
        extra = by_url[added]
        self.assertEqual(extra.title, "Added")
        self.assertTrue(extra.outside_gnb)
        self.assertFalse(source.outside_gnb)
        self.assertEqual(extra.parent, source.parent)
        self.assertEqual(extra.depth, source.depth)
        self.assertEqual(extra.group, "GNB")
        self.assertEqual(extra.kind, "PLP")
        self.assertLess(urls.index(known), urls.index(added))

    def test_tab_link_absent_from_gnb_follows_the_breadcrumb(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        commercial = "https://example.com/uk/business/hvac/commercial-solutions/"
        residential = "https://example.com/uk/business/hvac/residential-solutions/"
        allstars = "https://example.com/uk/business/hvac/residential-solutions/lg-allstars/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/">HVAC</a>
                <ul class="c-gnb__group c-gnb__group--depth2">
                  <li><a href="/uk/business/hvac/commercial-solutions/">Commercial Solutions</a></li>
                  <li><a href="/uk/business/hvac/residential-solutions/">Residential Solutions</a></li>
                </ul>
              </li>
            </ul>
        '''
        commercial_html = '''
            <ul role="tablist">
              <li role="tab"><a href="/uk/business/hvac/commercial-solutions/">Commercial Solutions</a></li>
              <li role="tab"><a href="#range">Range</a></li>
              <li role="tab"><button type="button">Overview</button></li>
              <li role="tab"><a href="/uk/business/hvac/residential-solutions/lg-allstars/">LG All Stars</a></li>
            </ul>
        '''
        allstars_html = '''
            <nav class="c-breadcrumb" aria-label="Breadcrumb">
              <ol>
                <li><a href="/uk/business/">Home</a></li>
                <li><a href="/uk/business/hvac/">HVAC</a></li>
                <li><a href="/uk/business/hvac/residential-solutions/">Residential Solutions</a></li>
                <li aria-current="page">LG All Stars</li>
              </ol>
            </nav>
        '''

        def fake(url, read_body=True, body=None):
            if url == root:
                text = home
            elif url == commercial:
                text = commercial_html
            elif url == allstars:
                text = allstars_html
            else:
                text = "<p>ok</p>"
            return HttpResult(url=url, status=200, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages if page.url}
        self.assertIn(allstars, by_url)
        extra = by_url[allstars]
        self.assertEqual(extra.title, "LG All Stars")
        self.assertTrue(extra.outside_gnb)
        self.assertFalse(by_url[commercial].outside_gnb)
        self.assertEqual(extra.parent, by_url[residential].id)
        self.assertEqual(extra.depth, by_url[residential].depth + 1)
        self.assertEqual(extra.group, "GNB")
        self.assertEqual([page.url for page in listing.pages].count(allstars), 1)

    def test_tab_name_is_added_when_gnb_uses_another_name(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        commercial = "https://example.com/uk/business/hvac/commercial-solutions/"
        residential = "https://example.com/uk/business/hvac/residential-solutions/"
        shared = "https://example.com/uk/business/hvac/residential-solutions/lg-allstars/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/">HVAC</a>
                <ul class="c-gnb__group c-gnb__group--depth2">
                  <li><a href="/uk/business/hvac/commercial-solutions/">Commercial Solutions</a></li>
                  <li><a href="/uk/business/hvac/residential-solutions/">Residential Solutions</a>
                    <ul class="c-gnb__group c-gnb__group--depth3">
                      <li><a href="/uk/business/hvac/residential-solutions/lg-allstars/">Air Solutions Online Academy</a></li>
                    </ul>
                  </li>
                </ul>
              </li>
            </ul>
        '''
        commercial_html = '''
            <ul role="tablist">
              <li role="tab"><a href="/uk/business/hvac/commercial-solutions/">Commercial Solutions</a></li>
              <li role="tab"><a href="#range">Range</a></li>
              <li role="tab"><a href="/uk/business/hvac/residential-solutions/lg-allstars/">LG All Stars</a></li>
            </ul>
        '''
        shared_html = '''
            <nav class="c-breadcrumb" aria-label="Breadcrumb">
              <ol>
                <li><a href="/uk/business/">Home</a></li>
                <li><a href="/uk/business/hvac/">HVAC</a></li>
                <li><a href="/uk/business/hvac/residential-solutions/">Residential Solutions</a></li>
                <li aria-current="page">LG AllStars</li>
              </ol>
            </nav>
            <ul role="tablist">
              <li role="tab"><a href="/uk/business/hvac/residential-solutions/lg-allstars/">LG All Stars</a></li>
            </ul>
        '''

        def fake(url, read_body=True, body=None):
            if url == root:
                text = home
            elif url == commercial:
                text = commercial_html
            elif url == shared:
                text = shared_html
            else:
                text = "<p>ok</p>"
            return HttpResult(url=url, status=200, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        matches = [page for page in listing.pages if page.url == shared]
        self.assertEqual(sorted(page.title for page in matches), ["Air Solutions Online Academy", "LG All Stars"])
        added = next(page for page in matches if page.title == "LG All Stars")
        kept = next(page for page in matches if page.title == "Air Solutions Online Academy")
        residential_page = next(page for page in listing.pages if page.url == residential)
        self.assertTrue(added.outside_gnb)
        self.assertFalse(kept.outside_gnb)
        self.assertEqual(added.parent, residential_page.id)
        self.assertEqual(added.depth, residential_page.depth + 1)

    def test_nav_lists_keep_hierarchy_and_drop_footer_duplicates(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        hvac = "https://example.com/uk/business/hvac/"
        commercial = "https://example.com/uk/business/hvac/commercial-solutions/"
        footer_only = "https://example.com/uk/business/only-footer/"
        story = "https://example.com/uk/business/hvac/story/"
        disc = "https://example.com/uk/business/hvac/lg-old/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><button><span>Solutions</span></button>
                <ul class="c-gnb__group c-gnb__group--depth2">
                  <li><a href="/uk/business/hvac/">HVAC</a>
                    <ul class="c-gnb__group c-gnb__group--depth3">
                      <li><a href="/uk/business/hvac/commercial-solutions/">Commercial</a></li>
                      <li><ul class="c-gnb__group c-gnb__group--detail">
                        <li><button><span>VRF System</span></button>
                          <ul><li><a href="/uk/business/hvac/commercial-solutions/vrf-system/multi-v-i/">MULTI V i</a></li></ul>
                        </li>
                      </ul></li>
                    </ul>
                  </li>
                </ul>
              </li>
              <li><button><span>Resources & Guides</span></button></li>
              <li><a href="/uk/business/monitors-pcs/pcs/">Thin Clients</a></li>
            </ul>
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/">HVAC again</a></li>
            </ul>
            <div class="c-footer__inner desktop-only">
              <strong class="c-footer__depth1">Solutions</strong>
              <a class="c-footer__depth2" href="/uk/business/hvac/">HVAC</a>
              <ul class="c-footer__depth3"><li><a href="/uk/business/only-footer/">Only</a></li></ul>
              <a href="/uk/business/hvac/resources-guides/">Resources & Guides</a>
              <a href="/uk/business/monitors-pcs/thin-clients/">Thin Clients</a>
            </div>
        '''
        calls = []

        def fake(url, read_body=True, body=None):
            calls.append(url)
            return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages if page.url}
        titles = [page.title for page in listing.pages]
        self.assertEqual(calls[0], root)
        self.assertTrue(set(calls[1:]).issubset(set(by_url)))
        self.assertNotIn(story, calls)
        self.assertNotIn(disc, calls)
        self.assertEqual(titles.count("GNB"), 1)
        self.assertEqual(titles.count("HVAC"), 1)
        self.assertIn("FNB", titles)
        self.assertEqual(by_url[hvac].group, "GNB")
        self.assertEqual(by_url[hvac].depth, 2)
        self.assertEqual(by_url[commercial].parent, by_url[hvac].id)
        self.assertEqual(by_url[commercial].depth, 3)
        vrf = next(page for page in listing.pages if page.title == "VRF System")
        product = "https://example.com/uk/business/hvac/commercial-solutions/vrf-system/multi-v-i/"
        self.assertEqual(by_url[product].parent, vrf.id)
        self.assertEqual(vrf.parent, by_url[commercial].id)
        self.assertNotIn(hvac, [page.url for page in listing.pages if page.group == "FNB"])
        self.assertEqual(by_url[footer_only].group, "FNB")
        guides = next(page for page in listing.pages if page.title == "Resources & Guides")
        self.assertEqual(guides.group, "GNB")
        self.assertEqual(guides.url, "https://example.com/uk/business/hvac/resources-guides/")
        self.assertNotIn("https://example.com/uk/business/monitors-pcs/thin-clients/", by_url)
        self.assertNotIn(story, by_url)
        self.assertNotIn(disc, by_url)
        paired = {row["label"]: row for row in listing.menu_diff["same_label"]}
        self.assertEqual(paired["Thin Clients"]["gnb"], ["https://example.com/uk/business/monitors-pcs/pcs/"])
        self.assertEqual(paired["Thin Clients"]["fnb"], ["https://example.com/uk/business/monitors-pcs/thin-clients/"])
        self.assertIn("https://example.com/uk/business/only-footer/", [row["url"] for row in listing.menu_diff["fnb_only"]])

    def test_compare_menus_reports_link_differences(self):
        from site_audit.audit import compare_menus

        root = "https://example.com/uk/business/"
        home = '''
            <html lang="en"><body>
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/">HVAC</a></li>
              <li><a href="/uk/business/monitors-pcs/pcs/">Thin Clients</a></li>
              <li><button><span>Resources & Guides</span></button></li>
              <li><a href="/uk/business/only-gnb/">Only GNB</a></li>
            </ul>
            <div class="c-footer__inner desktop-only">
              <a href="/uk/business/hvac/">HVAC</a>
              <a href="/uk/business/monitors-pcs/thin-clients/">Thin Clients</a>
              <a href="/uk/business/hvac/resources-guides/">Resources & Guides</a>
              <a href="/uk/business/only-footer/">Only FNB</a>
            </div>
            </body></html>
        '''

        def fake(url, read_body=True, body=None):
            return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            diff = compare_menus(root, fetch_one=fake)

        self.assertTrue(diff.ok)
        self.assertEqual(diff.shared, 1)
        self.assertEqual([row["url"] for row in diff.gnb_only], ["https://example.com/uk/business/only-gnb/"])
        self.assertEqual([row["url"] for row in diff.fnb_only], [
            "https://example.com/uk/business/only-footer/",
            "https://example.com/uk/business/hvac/resources-guides/",
        ])
        paired = {row["label"]: row for row in diff.same_label}
        self.assertEqual(paired["Thin Clients"]["gnb"], ["https://example.com/uk/business/monitors-pcs/pcs/"])
        self.assertEqual(paired["Thin Clients"]["fnb"], ["https://example.com/uk/business/monitors-pcs/thin-clients/"])
        self.assertNotIn("Resources & Guides", paired)

    def test_same_label_diff_keeps_parent_menu_path(self):
        from site_audit.parse import diff_nav_links

        gnb = [{
            "label": "Solutions",
            "url": "",
            "children": [{
                "label": "Monitors & PCs",
                "url": "",
                "children": [{
                    "label": "Thin Clients",
                    "url": "https://example.com/pcs/",
                    "children": [],
                }],
            }],
        }]
        fnb = [{
            "label": "Solutions",
            "url": "",
            "children": [{
                "label": "Monitors & PCs",
                "url": "",
                "children": [{
                    "label": "Thin Clients",
                    "url": "https://example.com/thin/",
                    "children": [],
                }],
            }],
        }]
        diff = diff_nav_links(gnb, fnb)
        self.assertEqual(diff["same_label"][0]["path"], ["Solutions", "Monitors & PCs", "Thin Clients"])

    def test_same_label_keeps_only_urls_that_differ_on_both_sides(self):
        from site_audit.parse import diff_nav_links

        gnb = [
            {"label": "Thin Clients", "url": "https://example.com/shared/", "children": []},
            {"label": "Thin Clients", "url": "https://example.com/pcs/", "children": []},
            {"label": "Guides", "url": "", "children": []},
            {"label": "Only Extra", "url": "https://example.com/same/", "children": []},
            {"label": "Only Extra", "url": "https://example.com/extra-gnb/", "children": []},
        ]
        fnb = [
            {"label": "Thin Clients", "url": "https://example.com/shared/", "children": []},
            {"label": "Thin Clients", "url": "https://example.com/thin/", "children": []},
            {"label": "Guides", "url": "https://example.com/guides/", "children": []},
            {"label": "Only Extra", "url": "https://example.com/same/", "children": []},
        ]
        diff = diff_nav_links(gnb, fnb)
        paired = {row["label"]: row for row in diff["same_label"]}
        self.assertEqual(list(paired), ["Thin Clients"])
        self.assertEqual(paired["Thin Clients"]["gnb"], ["https://example.com/pcs/"])
        self.assertEqual(paired["Thin Clients"]["fnb"], ["https://example.com/thin/"])
        self.assertEqual([row["url"] for row in diff["gnb_only"]], ["https://example.com/extra-gnb/"])
        self.assertEqual([row["url"] for row in diff["fnb_only"]], ["https://example.com/guides/"])

    def test_gnb_without_link_uses_the_matching_fnb_link(self):
        from site_audit.parse import _borrow_fnb_links

        def leaf(label, url=""):
            return {"label": label, "url": url, "children": []}

        gnb = [{
            "label": "Solutions",
            "url": "",
            "children": [
                {
                    "label": "Commercial Display",
                    "url": "",
                    "children": [leaf("Resources & Guides")],
                },
                {
                    "label": "HVAC",
                    "url": "",
                    "children": [leaf("Industrial Solutions"), leaf("Resources & Guides"), leaf("Thin Clients", "https://example.com/pcs/")],
                },
            ],
        }]
        fnb = [{
            "label": "Solutions",
            "url": "",
            "children": [{
                "label": "HVAC",
                "url": "",
                "children": [
                    leaf("Industrial Solutions", "https://www.lg.com/uk/business/hvac/industrial-solutions/chiller/"),
                    leaf("Resources & Guides", "https://www.lg.com/uk/business/hvac/resources-guides/"),
                ],
            }],
        }, {
            "label": "Commercial Display",
            "url": "",
            "children": [leaf("Resources & Guides", "https://www.lg.com/uk/business/hvac/resources-guides/")],
        }]
        _borrow_fnb_links(gnb, fnb)
        display = gnb[0]["children"][0]["children"][0]
        hvac = gnb[0]["children"][1]["children"]
        self.assertEqual(display["url"], "https://www.lg.com/uk/business/hvac/resources-guides/")
        self.assertEqual(hvac[0]["url"], "https://www.lg.com/uk/business/hvac/industrial-solutions/chiller/")
        self.assertEqual(hvac[1]["url"], "https://www.lg.com/uk/business/hvac/resources-guides/")
        self.assertEqual(hvac[2]["url"], "https://example.com/pcs/")

    def test_new_window_link_marks_404(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        gone = "https://example.com/uk/business/outside/"
        stay = "https://example.com/uk/business/hvac/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/outside/" target="_blank">Outside</a></li>
              <li><a href="/uk/business/hvac/">HVAC</a></li>
            </ul>
        '''

        def fake(url, read_body=True, body=None):
            status = 404 if url == gone else 200
            text = home if url == root else "<p>x</p>"
            return HttpResult(url=url, status=status, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages if page.url}
        self.assertTrue(by_url[gone].blank)
        self.assertEqual(by_url[gone].kind, "기타")
        self.assertTrue(by_url[gone].missing)
        self.assertFalse(by_url[stay].blank)
        self.assertEqual(by_url[stay].kind, "일반")
        self.assertFalse(by_url[stay].missing)
        self.assertTrue(listing.menu_diff["checks"][gone]["missing"])

    def test_menu_link_404_is_marked_missing(self):
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        gone = "https://example.com/uk/business/commercial-laundry/"
        stay = "https://example.com/uk/business/hvac/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/commercial-laundry/">Commercial Laundry</a></li>
              <li><a href="/uk/business/hvac/">HVAC</a></li>
            </ul>
        '''

        def fake(url, read_body=True, body=None):
            status = 404 if url == gone else 200
            text = home if url == root else "<p>ok</p>"
            return HttpResult(url=url, status=status, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_url = {page.url: page for page in listing.pages if page.url}
        self.assertTrue(by_url[gone].missing)
        self.assertFalse(by_url[stay].missing)
        self.assertEqual(by_url[gone].kind, "일반")

    def test_insights_contents_become_child_pages(self):
        import json
        from site_audit.audit import discover_pages

        root = "https://example.com/uk/business/"
        insights = "https://example.com/uk/business/insights/"
        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/insights/">Insights</a></li>
              <li><a href="/uk/business/insights/?contentsFormat=Blog">Blogs</a></li>
            </ul>
        '''
        insight_page = '''
            <input type="checkbox" name="ec_contents_format" value="News"/>
            <input type="checkbox" name="ec_contents_format" value="Blog"/>
            <script>{"searchInsightListEndPoint":"/ncmsbtb/api/v1/proxy/searchInsightList?locale=UK"}</script>
        '''

        def fake(url, read_body=True, body=None):
            if body:
                payload = json.loads(body.decode("utf-8"))
                name = payload["selectedFilterList"][0]["ec_contents_format"]
                page = int(payload["page"])
                batch = []
                if page == 1:
                    batch = [{
                        "title": f"{name} story",
                        "path": f"/uk/business/insights/{name.lower().replace(' ', '-')}/",
                        "contentsFormat": name,
                    }]
                data = {"insightLists": [{"totalCnt": 1 if page == 1 else 1, "insightList": batch}]}
                if page > 1:
                    data = {"insightLists": [{"totalCnt": 1, "insightList": []}]}
                return HttpResult(url=url, status=200, content_type="application/json", body=json.dumps(data).encode())
            text = insight_page if url == insights else home
            return HttpResult(url=url, status=200, content_type="text/html", body=text.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)

        by_title = {}
        for page in listing.pages:
            by_title.setdefault(page.title, []).append(page)
        news = by_title["News"][0]
        blog = by_title["Blog"][0]
        insights_menu = by_title["Insights"][0]
        self.assertEqual(news.parent, insights_menu.id)
        self.assertEqual(blog.parent, insights_menu.id)
        self.assertEqual(news.kind, "Insights")
        story = by_title["News story"][0]
        self.assertEqual(story.parent, news.id)
        self.assertEqual(story.url, "https://example.com/uk/business/insights/news/")
        self.assertEqual(by_title["Blog story"][0].url, "https://example.com/uk/business/insights/blog/")
        blogs = by_title["Blogs"][0]
        self.assertFalse(any(page.parent == blogs.id for page in listing.pages))

    def test_viewport_check_splits_broken_links_and_images(self):
        from site_audit.audit import check_page_assets

        root = "https://example.com/uk/business/"
        home = '''
            <html lang="en-GB">
            <nav class="c-gnb"><a href="/uk/business/gnb-missing/">GNB</a></nav>
            <div class="mobile-only"><a href="/uk/business/mobile-only/">Mobile</a></div>
            <div class="desktop-only">
              <a href="/uk/business/desktop-only/">Desktop</a>
              <img src="/gone.jpg" alt="gone">
            </div>
            <picture>
              <source media="(max-width: 768px)" srcset="/m.jpg">
              <source media="(min-width: 769px)" srcset="/d.jpg">
              <img src="/m.jpg" alt="hero">
            </picture>
            <img alt="empty">
            <a href="/uk/business/ok/">Ok</a>
            <a href="/uk/business/slow/">Slow</a>
            <a href="/uk/business/down/">Down</a>
            <footer class="c-footer"><a href="/uk/business/footer-missing/">FNB</a></footer>
            </html>
        '''

        def fake(url, read_body=True, body=None):
            if url == root:
                return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())
            if url.endswith("/gone.jpg"):
                return HttpResult(url=url, status=404, content_type="text/html", body=b"")
            if url.endswith("/desktop-only/"):
                return HttpResult(url=url, status=404, content_type="text/html", body=b"")
            if url.endswith("/slow/"):
                return HttpResult(url=url, status=0, content_type="", body=b"", error="시간 초과")
            if url.endswith("/down/"):
                return HttpResult(url=url, status=500, content_type="text/html", body=b"")
            if url.endswith("/gnb-missing/") or url.endswith("/footer-missing/"):
                return HttpResult(url=url, status=404, content_type="text/html", body=b"")
            return HttpResult(url=url, status=200, content_type="image/jpeg" if url.endswith(".jpg") else "text/html", body=b"")

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            checked = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake)

        from site_audit.parse import viewport_assets

        mobile_assets = viewport_assets(home, root, 390)
        pc_assets = viewport_assets(home, root, 1440)
        self.assertIn("https://example.com/m.jpg", mobile_assets["images"])
        self.assertNotIn("https://example.com/d.jpg", mobile_assets["images"])
        self.assertIn("https://example.com/d.jpg", pc_assets["images"])
        self.assertNotIn("https://example.com/uk/business/desktop-only/", mobile_assets["links"])
        self.assertIn("https://example.com/uk/business/desktop-only/", pc_assets["links"])

        by_name = {item["name"]: item for item in checked["viewports"]}
        mobile = by_name["Mobile"]
        pc = by_name["PC"]
        self.assertEqual(checked["kind"], "일반")
        self.assertNotIn("itemCount", checked)
        self.assertEqual(mobile["width"], 390)
        self.assertEqual(mobile["brokenLinks"], [])
        self.assertEqual(mobile["brokenImages"], [])
        self.assertEqual(mobile["missingImages"][0]["text"], "empty")
        self.assertIn('alt="empty"', mobile["missingImages"][0]["tag"])
        gone = next(row for row in pc["brokenImages"] if row["url"].endswith("/gone.jpg"))
        self.assertIn("/gone.jpg", gone["tag"])
        self.assertTrue(any(row["url"].endswith("/desktop-only/") for row in pc["brokenLinks"]))
        self.assertFalse(any(row["url"].endswith("/slow/") or row["url"].endswith("/down/") for row in pc["brokenLinks"]))
        self.assertFalse(any(row["url"].endswith("/gnb-missing/") or row["url"].endswith("/footer-missing/") for row in pc["brokenLinks"]))
        self.assertTrue(any(row["url"].endswith("/gone.jpg") for row in pc["brokenImages"]))
        self.assertFalse(any(row["url"].endswith("/d.jpg") for row in pc["brokenImages"]))
        self.assertEqual(by_name["Tablet"]["width"], 768)
        self.assertEqual([item["name"] for item in checked["viewports"]], ["Mobile", "Tablet", "PC"])
        desktop = next(row for row in pc["brokenLinks"] if row["url"].endswith("/desktop-only/"))
        self.assertEqual(desktop["title"], "Desktop")

    def test_chosen_kind_overrides_the_page_type(self):
        from site_audit.audit import check_page_assets

        root = "https://example.com/uk/business/"
        home = "<html lang=\"en-GB\"><a href=\"/uk/business/ok/\">Ok</a></html>"

        def fake(url, read_body=True, body=None, headers=None):
            return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            plp = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake, kind="PLP")
            plain = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake, kind="일반")

        self.assertEqual(plp["kind"], "PLP")
        self.assertIn("itemCount", plp)
        self.assertIsNone(plp["itemCount"])
        self.assertEqual(plp["siblingCount"], 0)
        self.assertEqual(plain["kind"], "일반")
        self.assertNotIn("itemCount", plain)
        self.assertNotIn("listing", plain)

    def test_plp_item_count_comes_from_the_list_search(self):
        import base64
        import json
        from site_audit.audit import check_page_assets, discover_pages

        root = "https://example.com/uk/business/"
        plp = "https://example.com/uk/business/hvac/"

        def token(org: str) -> str:
            def pack(value: dict) -> str:
                raw = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
                return raw

            return f"{pack({'alg': 'none'})}.{pack({'organization': org})}.sig"

        home = '''
            <ul class="c-gnb__group c-gnb__group--depth1 primary">
              <li><a href="/uk/business/hvac/">HVAC</a></li>
            </ul>
        '''
        plp_html = '''
            <script>{"productListApi":"/ncmsbtb/api/v1/proxy/retrieveProductList","coveoTokenUrl":"/ncmsbtb/api/v1/coveo/token"}</script>
            <div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList"></div>
            <div data-payload="{&quot;searchHub&quot;:&quot;UK-B2B-Search-V2&quot;}"></div>
            <div data-payload="{&quot;searchHub&quot;:&quot;UK-B2B-Listing-V2&quot;}" data-facets="{&quot;localeCode&quot;:&quot;UK&quot;,&quot;categoryTitle&quot;:&quot;CT1&quot;,&quot;categoryId&quot;:&quot;ec_sub_category_id&quot;}"></div>
        '''
        issued = token("exampleorg")

        def fake(url, read_body=True, body=None, headers=None):
            if url == root:
                return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())
            if url == plp:
                return HttpResult(url=url, status=200, content_type="text/html", body=plp_html.encode())
            if url.endswith("/coveo/token"):
                return HttpResult(url=url, status=200, content_type="application/json", body=json.dumps({"token": issued}).encode())
            self.assertEqual(headers["Authorization"], f"Bearer {issued}")
            self.assertIn(b'@ec_locale_code==\\"UK\\"', body)
            self.assertIn(b'@ec_sub_category_id==\\"CT1\\"', body)
            self.assertIn(b"UK-B2B-Listing-V2", body)
            self.assertNotIn(b"UK-B2B-Search-V2", body)
            self.assertIn(b"ec_sku", body)
            self.assertIn(b"ec_model_url_path", body)
            return HttpResult(
                url=url,
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "totalCountFiltered": 2,
                    "results": [
                        {
                            "raw": {
                                "ec_sku": "SKU-A",
                                "ec_model_status_code": "Active",
                                "ec_model_url_path": "/uk/business/hvac/sku-a/",
                                "ec_user_friendly_name": "Model A",
                            },
                            "childResults": [
                                {"raw": {"ec_sku": "SKU-A"}},
                                {"raw": {"ec_sku": "SKU-A2"}},
                            ],
                        },
                        {
                            "raw": {
                                "ec_sku": "SKU-B",
                                "ec_model_status_code": "DISCONTINUED",
                                "ec_model_url_path": "/uk/business/hvac/sku-b/",
                                "ec_user_friendly_name": "Model B",
                            },
                            "siblingModels": [
                                {"sku": "SKU-B"},
                                {"sku": "SKU-B2"},
                                {"sku": "SKU-B3"},
                            ],
                        },
                    ],
                }).encode(),
            )

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": plp,
            "hostname": "example.com",
        })()):
            checked = check_page_assets(plp, rules={"path_contains": {}}, fetch_one=fake)
        self.assertEqual(checked["itemCount"], 2)
        self.assertEqual(checked["siblingCount"], 3)
        self.assertEqual(checked["itemSkus"], [
            {"sku": "SKU-A", "discontinued": False, "url": "/uk/business/hvac/sku-a/", "title": "Model A", "siblings": 1},
            {"sku": "SKU-B", "discontinued": True, "url": "/uk/business/hvac/sku-b/", "title": "Model B", "siblings": 2},
        ])
        self.assertNotIn(issued, json.dumps(checked))

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            listing = discover_pages(root, rules={"path_contains": {}}, fetch_one=fake)
        found = next(page for page in listing.pages if page.url == plp)
        self.assertEqual(found.kind, "PLP")
        self.assertEqual(found.item_count, 2)
        self.assertEqual(found.sibling_count, 3)
        self.assertEqual(found.item_skus, [
            {"sku": "SKU-A", "discontinued": False, "url": "/uk/business/hvac/sku-a/", "title": "Model A", "siblings": 1},
            {"sku": "SKU-B", "discontinued": True, "url": "/uk/business/hvac/sku-b/", "title": "Model B", "siblings": 2},
        ])
        products = [page for page in listing.pages if page.parent == found.id]
        self.assertEqual([(page.title, page.url, page.discontinued, page.product, page.kind) for page in products], [
            ("Model A", "https://example.com/uk/business/hvac/sku-a/", False, True, "PDP"),
            ("Model B", "https://example.com/uk/business/hvac/sku-b/", True, True, "PDP"),
        ])
        self.assertEqual(products[0].depth, found.depth + 1)

    def test_plp_status_counts_match_the_screen_filter(self):
        import base64
        import json
        from site_audit.audit import check_page_assets

        plp = "https://example.com/uk/business/hvac/"

        def token(org: str) -> str:
            def pack(value: dict) -> str:
                raw = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
                return raw

            return f"{pack({'alg': 'none'})}.{pack({'organization': org})}.sig"

        plp_html = '''
            <div data-endpoint="/ncmsbtb/api/v1/proxy/retrieveProductList"></div>
            <div data-payload="{&quot;searchHub&quot;:&quot;UK-B2B-Listing-V2&quot;}" data-facets="{&quot;localeCode&quot;:&quot;UK&quot;,&quot;categoryTitle&quot;:&quot;CT1&quot;,&quot;categoryId&quot;:&quot;ec_sub_category_id&quot;}"></div>
            <script>{"coveoTokenUrl":"/ncmsbtb/api/v1/coveo/token"}</script>
        '''
        issued = token("exampleorg")

        def fake(url, read_body=True, body=None, headers=None):
            if url == plp:
                return HttpResult(url=url, status=200, content_type="text/html", body=plp_html.encode())
            if url.endswith("/coveo/token"):
                return HttpResult(url=url, status=200, content_type="application/json", body=json.dumps({"token": issued}).encode())
            query = json.loads(body.decode())
            if '@ec_model_status_code=="DISCONTINUED"' in query["aq"]:
                return HttpResult(
                    url=url,
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "totalCountFiltered": 101,
                        "results": [
                            {"raw": {"ec_sku": "SKU-B", "ec_model_status_code": "DISCONTINUED", "ec_model_url_path": "/uk/business/hvac/sku-b/", "ec_user_friendly_name": "Model B"}},
                            {
                                "raw": {"ec_sku": "SKU-C", "ec_model_status_code": "DISCONTINUED", "ec_model_url_path": "/uk/business/hvac/sku-c/", "ec_user_friendly_name": "Model C"},
                                "childResults": [
                                    {"raw": {"ec_sku": "SKU-C2", "ec_model_status_code": "DISCONTINUED"}},
                                    {"raw": {"ec_sku": "SKU-C3", "ec_model_status_code": "DISCONTINUED"}},
                                    {"raw": {"ec_sku": "SKU-C4", "ec_model_status_code": "DISCONTINUED"}},
                                    {"raw": {"ec_sku": "SKU-C5", "ec_model_status_code": "DISCONTINUED"}},
                                ],
                            },
                        ],
                    }).encode(),
                )
            self.assertIn("facets", query)
            return HttpResult(
                url=url,
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "totalCountFiltered": 113,
                    "facets": [{
                        "field": "ec_model_status_code",
                        "values": [
                            {"value": "ACTIVE", "numberOfResults": 20},
                            {"value": "DISCONTINUED", "numberOfResults": 101},
                        ],
                    }],
                    "results": [
                        {
                            "raw": {
                                "ec_sku": "SKU-A",
                                "ec_model_status_code": "ACTIVE",
                                "ec_model_url_path": "/uk/business/hvac/sku-a/",
                                "ec_user_friendly_name": "Model A",
                            },
                            "childResults": [
                                {"raw": {"ec_sku": "SKU-A2", "ec_model_status_code": "ACTIVE"}},
                            ],
                        },
                        {
                            "raw": {
                                "ec_sku": "SKU-B",
                                "ec_model_status_code": "DISCONTINUED",
                                "ec_model_url_path": "/uk/business/hvac/sku-b/",
                                "ec_user_friendly_name": "Model B",
                            },
                        },
                    ],
                }).encode(),
            )

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": plp,
            "hostname": "example.com",
        })()):
            checked = check_page_assets(plp, rules={"path_contains": {}}, fetch_one=fake)
        self.assertEqual(checked["itemCount"], 121)
        self.assertEqual(checked["activeCount"], 20)
        self.assertEqual(checked["discontinuedCount"], 101)
        self.assertEqual(checked["siblingCount"], 5)
        self.assertEqual([item["sku"] for item in checked["itemSkus"]], ["SKU-A", "SKU-B", "SKU-C"])
        siblings = {item["sku"]: item.get("siblings") for item in checked["itemSkus"]}
        self.assertEqual(siblings, {"SKU-A": 1, "SKU-B": 0, "SKU-C": 4})

    def test_sibling_count_skips_the_products_own_sku(self):
        from site_audit.audit import _sibling_model_count

        own_inside = {
            "sku": "SKU-A",
            "siblingModels": [
                {"sku": "SKU-A"},
                {"sku": "SKU-A2"},
                {"sku": ""},
            ],
        }
        children_only = {
            "raw": {"ec_sku": "SKU-B"},
            "childResults": [
                {"raw": {"ec_sku": "SKU-B2"}},
                {"raw": {"ec_sku": "SKU-B"}},
            ],
        }
        hidden = {
            "raw": {"ec_sku": "SKU-C", "ec_model_status_code": "ACTIVE"},
            "childResults": [
                {"raw": {"ec_sku": "SKU-C2", "ec_model_status_code": "ACTIVE"}},
                {"raw": {"ec_sku": "SKU-C3", "ec_model_status_code": "DISCONTINUED"}},
            ],
        }
        self.assertEqual(_sibling_model_count(own_inside), 1)
        self.assertEqual(_sibling_model_count(children_only), 1)
        self.assertEqual(_sibling_model_count(hidden), 1)
        self.assertEqual(_sibling_model_count(hidden, include_discontinued=True), 2)

    def test_link_title_uses_anchor_text_without_the_fragment(self):
        from site_audit.parse import viewport_assets

        html = '''
            <a href="https://www.energy.gov/energysaver/water%20heating#:~:text=Water%20heating">https://www.energy.gov/energysaver/water heating#:~:text=Water%20heating</a>
        '''
        assets = viewport_assets(html, "https://www.lg.com/uk/business/insights/", 1440)
        url = "https://www.energy.gov/energysaver/water%20heating"
        self.assertEqual(assets["links"], [url])
        self.assertEqual(
            assets["linkTitles"][url],
            "https://www.energy.gov/energysaver/water heating#:~:text=Water%20heating",
        )

    def test_page_check_keeps_document_title(self):
        from site_audit.audit import check_page_assets
        from site_audit.parse import page_title

        self.assertEqual(page_title("<title>LG &amp; OLED</title>"), "LG & OLED")
        root = "https://example.com/uk/oled/"
        home = "<html><head><title>OLED TV | LG UK</title></head><body></body></html>"

        def fake(url, read_body=True, body=None):
            return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            checked = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake, kind="일반")

        self.assertTrue(checked["ok"])
        self.assertEqual(checked["title"], "OLED TV | LG UK")

    def test_missing_page_is_404(self):
        from site_audit.audit import check_page_assets

        root = "https://example.com/uk/business/insights/missing/"

        def fake(url, read_body=True, body=None):
            return HttpResult(url=url, status=404, content_type="text/html", body=b"")

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            checked = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake)

        self.assertFalse(checked["ok"])
        self.assertEqual(checked["status"], 404)

    def test_insights_more_list_is_checked_without_nav(self):
        import json
        from site_audit.audit import check_page_assets

        root = "https://example.com/uk/business/insights/"
        home = '''
            <html lang="en-GB">
            <nav class="c-gnb"><a href="/uk/business/gnb-missing/">GNB</a></nav>
            <main><a href="/uk/business/contact-us/">Contact</a></main>
            <script>/ncmsbtb/api/v1/proxy/searchInsightList?locale=UK</script>
            <footer class="c-footer"><img src="/foot.jpg" alt="foot"></footer>
            </html>
        '''
        pages = {
            "1": [{"title": "One", "path": "/uk/business/insights/one/", "altText": "one",
                   "mobileImageAddr": "/m1.jpg", "tabletImageAddr": "/t1.jpg", "desktopImageAddr": "/d1.jpg"}],
            "2": [{"title": "Two", "path": "/uk/business/insights/two/", "altText": "two",
                   "mobileImageAddr": "", "tabletImageAddr": "", "desktopImageAddr": "/d2.jpg"}],
        }

        def fake(url, read_body=True, body=None):
            if url == root:
                return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())
            if "searchInsightList" in url:
                page = json.loads(body.decode())["page"] if body else "1"
                batch = pages.get(page, [])
                data = {"insightLists": [{"totalCnt": 2, "insightList": batch}]}
                return HttpResult(url=url, status=200, content_type="application/json", body=json.dumps(data).encode())
            status = 404 if url.endswith(("/one/", "/d2.jpg", "/gnb-missing/", "/foot.jpg")) else 200
            kind = "image/jpeg" if url.endswith(".jpg") else "text/html"
            return HttpResult(url=url, status=status, content_type=kind, body=b"")

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            checked = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake)

        by_name = {item["name"]: item for item in checked["viewports"]}
        mobile = by_name["Mobile"]
        pc = by_name["PC"]
        self.assertEqual(mobile["linkTotal"], 3)
        self.assertEqual(mobile["imageTotal"], 2)
        self.assertEqual(pc["imageTotal"], 2)
        one = next(row for row in mobile["brokenLinks"] if row["url"].endswith("/one/"))
        self.assertEqual(one["title"], "One")
        self.assertTrue(any(row["url"].endswith("/one/") for row in mobile["brokenLinks"]))
        self.assertFalse(any(row["url"].endswith("/gnb-missing/") for row in mobile["brokenLinks"]))
        self.assertFalse(any("/foot.jpg" in row["url"] for row in mobile["brokenImages"]))
        self.assertTrue(any(row["text"] == "two" for row in mobile["missingImages"]))
        self.assertTrue(any(row["url"].endswith("/d2.jpg") for row in pc["brokenImages"]))
        self.assertFalse(any(row["text"] == "two" for row in pc["missingImages"]))
        self.assertEqual(checked["listing"]["contentTotal"], 2)
        self.assertEqual(checked["listing"]["duplicates"], [])
        self.assertTrue(checked["listing"]["thumbnails"][0]["unread"])

    def test_insights_listing_flags_thumbnail_size_and_duplicates(self):
        import json
        import struct
        import zlib
        from site_audit.audit import check_page_assets

        def png(width, height):
            row = b"\x00" + (b"\x00\x00\x00" * width)
            raw = row * height
            def chunk(tag, data):
                return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
            return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

        root = "https://example.com/uk/business/insights/"
        home = '''
            <html lang="en-GB">
            <main></main>
            <script>/ncmsbtb/api/v1/proxy/searchInsightList?locale=UK</script>
            </html>
        '''
        small = {"mobileImageAddr": "/a.png", "tabletImageAddr": "/a.png", "desktopImageAddr": "/a.png"}
        pages = {
            "1": [
                {"title": "Same", "path": "/uk/business/insights/a/", **small},
                {"title": "Other", "path": "/uk/business/insights/b/", **small},
            ],
            "2": [
                {"title": "Same", "path": "/uk/business/insights/a/", **small},
                {"title": "Same", "path": "/uk/business/insights/d/", **small},
                {"title": "Same", "path": "/uk/business/insights/e/", **small},
                {"title": "Same", "path": "/uk/business/insights/g/", "mobileImageAddr": "/folder/a.png", "tabletImageAddr": "/folder/a.png", "desktopImageAddr": "/folder/a.png"},
                {"title": "Same", "path": "/uk/business/insights/c/", "mobileImageAddr": "/c.png", "tabletImageAddr": "/c.png", "desktopImageAddr": "/c.png"},
            ],
        }
        bodies = {"/a.png": png(10, 10), "/c.png": png(20, 12)}
        same_article = '<div class="GN0007-insight-detail"><div class="c-detail-content__txt"><p>Same body</p></div><p>01/01/2020</p></div>'
        other_article = '<div class="GN0007-insight-detail"><div class="c-detail-content__txt"><p>Other body</p></div></div>'

        def fake(url, read_body=True, body=None):
            if url == root:
                return HttpResult(url=url, status=200, content_type="text/html", body=home.encode())
            if "searchInsightList" in url:
                page = json.loads(body.decode())["page"] if body else "1"
                batch = pages.get(page, [])
                data = {"insightLists": [{"totalCnt": 3, "insightList": batch}]}
                return HttpResult(url=url, status=200, content_type="application/json", body=json.dumps(data).encode())
            name = "/" + url.rsplit("/", 1)[-1]
            if name in bodies:
                return HttpResult(url=url, status=200, content_type="image/png", body=bodies[name])
            article = same_article if url.rstrip("/").endswith(("/a", "/d", "/g")) else other_article
            return HttpResult(url=url, status=200, content_type="text/html", body=article.encode())

        with patch("site_audit.audit.check_url", return_value=type("T", (), {
            "url": root,
            "hostname": "example.com",
        })()):
            checked = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake)

        listing = checked["listing"]
        self.assertEqual(listing["contentTotal"], 7)
        self.assertEqual([row["url"].rstrip("/").rsplit("/", 1)[-1] for row in listing["duplicates"]], ["a", "d", "g"])
        self.assertTrue(all(row["detail"] == "같은 제목 · 같은 이미지 · 같은 내용" for row in listing["duplicates"]))
        copied = listing["duplicates"][1]
        self.assertTrue(copied["image"].endswith("/a.png"))
        self.assertTrue(copied["otherImage"].endswith("/a.png"))
        self.assertTrue(copied["otherUrl"].endswith("/a/"))
        mobile = listing["thumbnails"][0]
        self.assertEqual(mobile["name"], "Mobile")
        self.assertEqual(mobile["total"], 6)
        self.assertEqual(len(mobile["different"]), 1)
        self.assertEqual(mobile["different"][0]["detail"], "20x12 (기준 10x10)")
        self.assertFalse(mobile["unread"])
        self.assertEqual(listing["thumbnails"][2]["different"][0]["url"], "https://example.com/uk/business/insights/c/")


class SpecCompareTests(unittest.TestCase):
    def test_all_spec_diff_ignores_key_spec_and_collapsed_area(self):
        from site_audit.parse import diff_spec_rows, rival_spec_rows, selling_spec_rows

        source = """
        <div class="c-compare-selling">
          <button type="button">Key Spec</button>
          <div class="c-compare-selling__spec">
            <div class="c-compare-selling__spec-item">
              <span class="c-compare-selling__spec-name">Screen Size</span>
              <span class="c-compare-selling__spec-desc">65 inch</span>
            </div>
          </div>
          <button type="button">All Spec</button>
          <div class="c-compare-selling__spec">
            <div class="c-compare-selling__spec-item">
              <span class="c-compare-selling__spec-name">Screen Size</span>
              <span class="c-compare-selling__spec-desc">65"</span>
            </div>
            <div class="c-compare-selling__spec-item">
              <span class="c-compare-selling__spec-name">Resolution</span>
              <span class="c-compare-selling__spec-desc">4K</span>
            </div>
            <div class="c-compare-selling__spec-item">
              <span class="c-compare-selling__spec-name">HDMI</span>
              <span class="c-compare-selling__spec-desc">2.1</span>
            </div>
          </div>
        </div>
        """
        rival = """
        <div class="tech-spacs-area collapse">
          <table><tr><th>Screen Size</th><td>hidden</td></tr></table>
        </div>
        <div class="tech-specs-area collapse show">
          <table>
            <tr><th>DISPLAY</th></tr>
            <tr><th>Screen Size</th><td>65 inch</td></tr>
            <tr><th>Resolution</th><td>4k</td></tr>
            <tr><th>HDMI</th><td>2.1</td></tr>
            <tr><th>Speaker</th><td>40W</td></tr>
          </table>
        </div>
        """
        left = selling_spec_rows(source)
        right = rival_spec_rows(rival)
        self.assertEqual([row["value"] for row in left], ["65\"", "4K", "2.1"])
        self.assertEqual(right[0]["name"], "Screen Size")
        rows = {row["name"]: row for row in diff_spec_rows(left, right)}
        self.assertEqual(rows["Screen Size"]["source"], "65\"")
        self.assertEqual(rows["Screen Size"]["compare"], "65 inch")
        self.assertNotIn("Resolution", rows)
        self.assertNotIn("HDMI", rows)
        self.assertEqual(rows["Speaker"]["source"], "")
        self.assertEqual(rows["Speaker"]["compare"], "40W")

    def test_compare_page_uses_all_spec_when_tech_area_is_absent(self):
        from site_audit.parse import rival_spec_rows

        html = """
        <h3>All Spec</h3>
        <div class="c-compare-selling__spec">
          <div class="c-compare-selling__spec-item">
            <span class="c-compare-selling__spec-name">Typ.</span>
            <span class="c-compare-selling__spec-desc">130W</span>
          </div>
        </div>
        """
        rows = rival_spec_rows(html)
        self.assertEqual(rows, [{"group": "", "name": "Typ.", "value": "130W"}])

    def test_spec_compares_only_the_same_section(self):
        from site_audit.parse import diff_spec_rows

        different = diff_spec_rows(
            [{"name": "Screen Size", "value": "65\"", "group": "PANEL"}],
            [{"name": "Screen Size", "value": "55\"", "group": "INFO"}],
        )
        self.assertEqual(
            sorted((row["source"], row["compare"]) for row in different),
            [("", "55\""), ("65\"", "")],
        )
        same = diff_spec_rows(
            [{"name": "Screen Size", "value": "65\"", "group": "PANEL"}],
            [{"name": "Screen Size", "value": "55\"", "group": "PANEL"}],
        )
        self.assertEqual(same, [{
            "name": "Screen Size",
            "source": "65\"",
            "compare": "55\"",
        }])

    def test_energy_grade_matches_erp_letter(self):
        from site_audit.parse import diff_spec_rows, selling_spec_rows

        source = """
        <h3>All Spec</h3>
        <div class="c-compare-selling__spec">
          <h4>PANEL</h4>
          <div class="c-compare-selling__spec-item">
            <span class="c-compare-selling__spec-name">Screen Size</span>
            <span class="c-compare-selling__spec-desc">65"</span>
          </div>
        </div>
        <button>
          <span class="sr-only">Energy Grade<!-- --> : <!-- -->D</span>
        </button>
        """
        rival = """
        <h3>All Spec</h3>
        <div class="c-compare-selling__spec">
          <h4>STANDARD</h4>
          <div class="c-compare-selling__spec-item">
            <span class="c-compare-selling__spec-name">ERP</span>
            <span class="c-compare-selling__spec-desc">YES (D)</span>
          </div>
        </div>
        """
        rows = selling_spec_rows(source)
        self.assertEqual([row["name"] for row in rows], ["Screen Size"])
        from site_audit.parse import energy_sheet_from_rows, rival_spec_rows
        sheet = energy_sheet_from_rows(source, rival_spec_rows(rival), rival)
        self.assertEqual(sheet, {"source": "D", "compare": "D", "same": True})
        labeled = rival.replace(
            "</h3>",
            """</h3>
            <div class="file-list " data-file-download="true">
              <a href="#">
                <span class="label type-none">
                  <img src="/energy-label/bg/bg_481088.png" alt="A+++">
                </span>
              </a>
            </div>
            """,
        )
        preferred = energy_sheet_from_rows(source, rival_spec_rows(labeled), labeled)
        self.assertEqual(preferred["compare"], "A+++")
        self.assertFalse(preferred["same"])
        changed = source.replace("Energy Grade<!-- --> : <!-- -->D", "Energy Grade<!-- --> : <!-- -->G")
        changed_sheet = energy_sheet_from_rows(changed, rival_spec_rows(rival))
        self.assertEqual(changed_sheet, {"source": "G", "compare": "D", "same": False})

    def test_all_spec_sections_follow_headings(self):
        from site_audit.parse import selling_spec_rows, spec_sections

        html = """
        <h3>All Spec</h3>
        <div class="c-compare-selling__spec">
          <h4>PANEL</h4>
          <div class="c-compare-selling__spec-item">
            <span class="c-compare-selling__spec-name">Screen Size (Inch)</span>
            <span class="c-compare-selling__spec-desc">65"</span>
          </div>
          <h4>CONNECTIVITY</h4>
          <div class="c-compare-selling__spec-item">
            <span class="c-compare-selling__spec-name">HDMI In</span>
            <span class="c-compare-selling__spec-desc">Yes(3)</span>
          </div>
        </div>
        """
        sections = spec_sections(selling_spec_rows(html))
        self.assertEqual(sections, [
            {"title": "PANEL", "rows": [{"name": "Screen Size (Inch)", "value": "65\""}]},
            {"title": "CONNECTIVITY", "rows": [{"name": "HDMI In", "value": "Yes(3)"}]},
        ])

    def test_two_item_spec_list_stays_separate(self):
        from site_audit.parse import selling_spec_rows

        html = """
        <h3>All Spec</h3>
        <div class="c-compare-selling__spec">
          <div class="c-compare-selling__table">
            <h4>SPECIAL FEATURE</h4>
            <ul class="c-compare-selling__spec-list">
              <li class="c-compare-selling__item">
                <div class="c-compare-selling__spec-name"><p>Tilt (Face down)</p></div>
                <div class="c-compare-selling__spec-desc"><p>Yes(Max 30º degree, 40ºC temperature)</p></div>
              </li>
              <li class="c-compare-selling__item">
                <div class="c-compare-selling__spec-name"><p>Conformal Coating (Power Board)</p></div>
                <div class="c-compare-selling__spec-desc"><p>Yes(Partial space coating)</p></div>
              </li>
            </ul>
          </div>
        </div>
        """
        rows = {row["name"]: row["value"] for row in selling_spec_rows(html)}
        self.assertEqual(rows["Tilt (Face down)"], "Yes(Max 30º degree, 40ºC temperature)")
        self.assertEqual(rows["Conformal Coating (Power Board)"], "Yes(Partial space coating)")

    def test_spec_title_drops_parentheses_before_compare(self):
        from site_audit.parse import diff_spec_rows

        rows = diff_spec_rows(
            [{"name": "Brightness (Typ.)", "value": "500 nit", "group": ""}],
            [{"name": "Brightness", "value": "450 nit", "group": ""}],
        )
        self.assertEqual(rows, [{"name": "Brightness", "source": "500 nit", "compare": "450 nit"}])
        same = diff_spec_rows(
            [{"name": "Brightness (Typ.)", "value": "500 nit", "group": ""}],
            [{"name": "Brightness (Typ)", "value": "500 nit", "group": ""}],
        )
        self.assertEqual(same, [])

    def test_power_consumption_matches_heading_details(self):
        from site_audit.parse import diff_spec_rows

        source = [
            {"group": "POWER CONSUMPTION", "name": "Typ.", "value": "130W"},
            {"group": "POWER CONSUMPTION", "name": "Max.", "value": "205W"},
            {"group": "POWER CONSUMPTION", "name": "BTU (British Thermal Unit)", "value": "444 BTU/Hr(Typ.), 699 BTU/Hr(Max)"},
            {"group": "POWER CONSUMPTION", "name": "DPM", "value": "0.5W"},
            {"group": "POWER CONSUMPTION", "name": "Power off", "value": "0.5W"},
            {"group": "POWER CONSUMPTION", "name": "Smart Energy Saving (70%)", "value": "91W"},
        ]
        rival = [
            {"group": "", "name": "Power Consumption (Typ.)", "value": "130W"},
            {"group": "", "name": "Power Consumption (Max.)", "value": "200W"},
            {"group": "", "name": "Power Consumption (British Thermal Unit)", "value": "444 BTU/Hr(Typ.), 699 BTU/Hr(Max)"},
            {"group": "", "name": "Power Consumption (DPM)", "value": "0.5W"},
            {"group": "", "name": "Power Consumption (Power Off)", "value": "0.5W"},
            {"group": "", "name": "Power Consumption (Smart Energy Saving, ~70%)", "value": "91W"},
        ]
        rows = diff_spec_rows(source, rival)
        self.assertEqual(rows, [{
            "name": "Power Consumption (Max.)",
            "source": "205W",
            "compare": "200W",
        }])
        from site_audit.parse import spec_check_sections
        sections = spec_check_sections(source, rival)
        self.assertEqual([section["title"] for section in sections], ["POWER CONSUMPTION"])
        by_name = {row["name"]: row for row in sections[0]["rows"]}
        self.assertTrue(by_name["Typ."]["same"])
        self.assertFalse(by_name["Max."]["same"])
        self.assertEqual(by_name["Max."]["source"], "205W")
        self.assertEqual(by_name["Max."]["compare"], "200W")

    def test_slash_name_matches_either_variant(self):
        from site_audit.parse import diff_spec_rows

        same = diff_spec_rows(
            [{"name": "SuperSign Control+", "value": "Yes", "group": ""}],
            [{"name": "SuperSign Control / Control+", "value": "Yes", "group": ""}],
        )
        self.assertEqual(same, [])
        changed = diff_spec_rows(
            [{"name": "SuperSign Control+", "value": "No", "group": ""}],
            [{"name": "SuperSign Control / Control+", "value": "Yes", "group": ""}],
        )
        self.assertEqual(changed, [{
            "name": "SuperSign Control+",
            "source": "No",
            "compare": "Yes",
        }])

    def test_page_check_returns_spec_differences_for_pdp(self):
        from site_audit.audit import check_page_assets

        root = "https://example.com/uk/oled/"
        other = "https://example.com/compare/oled/"
        source = """
        <html lang="en-GB">
          <button>All Spec</button>
          <div class="c-compare-selling__spec">
            <dl><dt>Energy</dt><dd>A</dd></dl>
          </div>
        </html>
        """
        rival = """
        <html>
          <div class="tech-spacs-area collapse show">
            <dl><dt>Energy</dt><dd>B</dd></dl>
          </div>
        </html>
        """
        pages = {root: source, other: rival}

        def fake(url, read_body=True, body=None, headers=None):
            text = pages.get(url)
            if text is None:
                return HttpResult(url=url, status=404, content_type="text/html", body=b"")
            return HttpResult(url=url, status=200, content_type="text/html", body=text.encode())

        def allow(url, resolve=None):
            return type("T", (), {"url": url, "hostname": "example.com"})()

        with patch("site_audit.audit.check_url", side_effect=allow):
            checked = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake, kind="PDP", compare_url=other)
            plain = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake, kind="일반", compare_url=other)
            missing = check_page_assets(root, rules={"path_contains": {}}, fetch_one=fake, kind="PDP", compare_url="https://example.com/missing/")

        self.assertEqual(checked["specCompare"]["rows"], [{"name": "Energy", "source": "A", "compare": "B"}])
        self.assertEqual(checked["allSpec"]["sections"], [{
            "title": "",
            "rows": [{"name": "Energy", "value": "A"}],
        }])
        self.assertTrue(checked["specCompare"]["sourceFound"])
        self.assertTrue(checked["specCompare"]["compareFound"])
        self.assertNotIn("specCompare", plain)
        self.assertFalse(missing["specCompare"]["ok"])
        self.assertEqual(missing["specCompare"]["message"], "비교 주소를 읽지 못했습니다.")
        self.assertTrue(missing["ok"])


if __name__ == "__main__":
    unittest.main()
