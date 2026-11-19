const home = document.querySelector("#home");
const listPage = document.querySelector("#list-page");
const listRoot = document.querySelector("#list-root");
const form = document.querySelector("#form");
const urlInput = document.querySelector("#url");
const start = document.querySelector("#start");
const formStatus = document.querySelector("#form-status");
const panel = document.querySelector("#panel");
const summary = document.querySelector("#summary");
const status = document.querySelector("#status");
const tree = document.querySelector("#tree");
const listPlace = document.querySelector("#list-place");
const deleteAnalysis = document.querySelector("#delete-analysis");
const excelDownload = document.querySelector("#excel-download");
const recent = document.querySelector("#recent");
const STORE = "site-audit-analyses";
const ONE_STORE = "site-audit-one";
let onePayload = null;

const viewOne = document.querySelector("#view-one");
const viewCompare = document.querySelector("#view-compare");
const topbar = document.querySelector(".topbar");
const kindPick = document.querySelector("#kind-pick");

function setMenu(name) {
  document.querySelectorAll(".side-link").forEach((link) => {
    link.classList.toggle("is-current", link.dataset.view === name);
  });
}

function hideModes() {
  viewOne.hidden = true;
  viewCompare.hidden = true;
}

function showKindPick(show) {
  if (kindPick) kindPick.hidden = !show;
  if (!show) {
    const field = document.querySelector("#compare-url-field");
    if (field) field.hidden = true;
    return;
  }
  syncCompareField();
}

function showHome() {
  home.hidden = false;
  listPage.hidden = true;
  topbar.hidden = false;
  showKindPick(false);
  hideModes();
  document.title = "하위전체 검수 · 사이트 분석";
  document.body.classList.remove("nav-open");
  setMenu("search");
}

function showListPage(url) {
  home.hidden = true;
  listPage.hidden = false;
  topbar.hidden = false;
  showKindPick(false);
  hideModes();
  document.title = "하위 페이지 · 사이트 분석";
  document.body.classList.remove("nav-open");
  setMenu("search");
  if (url) listRoot.textContent = url;
}

function showOne() {
  home.hidden = true;
  listPage.hidden = true;
  topbar.hidden = false;
  showKindPick(true);
  viewOne.hidden = false;
  viewCompare.hidden = true;
  document.title = "url 하나 검수 · 사이트 분석";
  document.body.classList.remove("nav-open");
  setMenu("one");
  form.noValidate = true;
}

function showCompare() {
  home.hidden = true;
  listPage.hidden = true;
  topbar.hidden = false;
  showKindPick(false);
  viewOne.hidden = true;
  viewCompare.hidden = false;
  document.title = "gnb/fnb 비교 · 사이트 분석";
  document.body.classList.remove("nav-open");
  setMenu("compare");
}

function openPage() {
  const path = window.location.pathname;
  if (path === "/all") showHome();
  else if (path === "/compare") showCompare();
  else showOne();
  setBusy(false);
}

function kpiCard(label, value, tone, options) {
  const pressed = Boolean(options && options.pressed);
  const article = document.createElement(
    options && options.onClick ? "button" : "article",
  );
  if (article.tagName === "BUTTON") article.type = "button";
  article.className = pressed ? "kpi is-on" : "kpi";
  if (article.tagName === "BUTTON")
    article.setAttribute("aria-pressed", pressed ? "true" : "false");
  const copy = document.createElement("div");
  const lab = document.createElement("p");
  lab.className = "kpi-label";
  lab.textContent = label;
  const num = document.createElement("p");
  num.className = "kpi-value";
  num.textContent = String(value);
  const sub = document.createElement("p");
  sub.className = "kpi-sub";
  sub.textContent = options && options.hint ? options.hint : "이 목록";
  copy.append(lab, num, sub);
  const icon = document.createElement("span");
  icon.className = `kpi-icon ${tone}`;
  icon.setAttribute("aria-hidden", "true");
  article.append(copy, icon);
  if (options && options.onClick)
    article.addEventListener("click", options.onClick);
  if (!options || !options.onRecheck) return article;
  const wrap = document.createElement("div");
  wrap.className = "kpi-wrap";
  const again = document.createElement("button");
  again.type = "button";
  again.className = "text-btn kpi-recheck";
  again.textContent = "다시 분석";
  again.addEventListener("click", options.onRecheck);
  wrap.append(article, again);
  return wrap;
}

function onComparePage() {
  return window.location.pathname === "/compare";
}

function onOnePage() {
  return window.location.pathname === "/";
}

function setBusy(busy) {
  urlInput.disabled = busy;
  start.disabled = busy || urlInput.value.trim() === "";
  if (onComparePage()) start.textContent = busy ? "비교 중" : "비교하기";
  else if (onOnePage()) start.textContent = busy ? "검수 중" : "검수하기";
  else start.textContent = busy ? "검수 중" : "검수하기";
}

function showFormError(message) {
  formStatus.hidden = false;
  formStatus.replaceChildren();
  const first = document.createElement("span");
  first.textContent = "이 주소는 검사할 수 없습니다.";
  const second = document.createElement("span");
  second.textContent = message || "주소를 다시 입력해 주세요.";
  formStatus.append(first, document.createElement("br"), second);
  urlInput.classList.add("bad");
  urlInput.focus();
}

function showListError(message) {
  showListPage("");
  if (excelDownload) excelDownload.hidden = true;
  panel.hidden = false;
  summary.replaceChildren();
  tree.replaceChildren();
  if (listPlace) listPlace.textContent = "";
  status.replaceChildren();
  const first = document.createElement("span");
  first.textContent = "이 주소는 검사할 수 없습니다.";
  const second = document.createElement("span");
  second.textContent = message || "주소를 다시 입력해 주세요.";
  status.append(first, document.createElement("br"), second);
}

function showRunning(progress) {
  if (excelDownload) excelDownload.hidden = true;
  showListPage(
    progress && progress.root ? progress.root : listRoot.textContent,
  );
  panel.hidden = false;
  summary.replaceChildren();
  tree.replaceChildren();
  if (listPlace) listPlace.textContent = "언어와 나라를 확인하는 중";
  const step = progress && progress.step ? progress.step : "주소를 확인하는 중";
  const done = progress && Number.isFinite(progress.done) ? progress.done : 0;
  const waiting =
    progress && Number.isFinite(progress.waiting) ? progress.waiting : 0;
  const known = Math.max(done + waiting, 1);
  const ratio = Math.min(100, Math.round((done / known) * 100));

  status.replaceChildren();
  const title = document.createElement("span");
  title.textContent = "하위 페이지를 모으는 중입니다.";
  const detail = document.createElement("span");
  detail.textContent = `${step} · 확인 ${done} · 대기 ${waiting}`;
  status.append(title, document.createElement("br"), detail);
  if (progress && progress.url) {
    const current = document.createElement("span");
    current.className = "progress-url";
    current.textContent = progress.url;
    status.append(current);
  }
  const meter = document.createElement("span");
  meter.className = "meter";
  meter.setAttribute("role", "progressbar");
  meter.setAttribute("aria-valuemin", "0");
  meter.setAttribute("aria-valuemax", String(known));
  meter.setAttribute("aria-valuenow", String(done));
  const fill = document.createElement("span");
  fill.style.width = `${ratio}%`;
  meter.append(fill);
  status.append(meter);
}

function kindClass(kind) {
  if (kind === "PLP") return "kind-plp";
  if (kind === "PDP") return "kind-pdp";
  if (kind === "Insights") return "kind-insights";
  if (kind === "기타") return "kind-etc";
  return "kind-page";
}

function displayKind(page) {
  if (!page) return "";
  if (page.url && isInsightListing(page.url)) return "Insights";
  if (
    page.kind === "PLP" ||
    page.kind === "PDP" ||
    page.kind === "Insights" ||
    page.kind === "일반" ||
    page.kind === "기타"
  ) {
    return page.kind;
  }
  if (page.url) return "기타";
  return "";
}

function normalizeUrl(value) {
  const text = (value || "").trim();
  try {
    const url = new URL(text);
    url.hash = "";
    const path = url.pathname.replace(/\/+$/, "") || "/";
    return `${url.protocol}//${url.host}${path}${url.search}`;
  } catch (_err) {
    return text;
  }
}

function loadAnalyses() {
  try {
    const items = JSON.parse(localStorage.getItem(STORE) || "[]");
    return Array.isArray(items) ? items : [];
  } catch (_err) {
    return [];
  }
}

function writeAnalyses(items) {
  let batch = items.slice(0, 20);
  const currentId = listedJobId;
  while (batch.length) {
    try {
      localStorage.setItem(STORE, JSON.stringify(batch));
      return;
    } catch (_err) {
      if (batch.length === 1) return;
      const current = batch.find((item) => currentId && item.id === currentId);
      const rest = batch.filter((item) => item !== current);
      rest.pop();
      batch = current ? [current, ...rest] : rest;
    }
  }
}

function loadOneChecks() {
  try {
    const items = JSON.parse(localStorage.getItem(ONE_STORE) || "[]");
    return Array.isArray(items) ? items : [];
  } catch (_err) {
    return [];
  }
}

function writeOneChecks(items) {
  let batch = items.slice(0, 20);
  if (!batch.length) {
    localStorage.removeItem(ONE_STORE);
    return;
  }
  while (batch.length) {
    try {
      localStorage.setItem(ONE_STORE, JSON.stringify(batch));
      return;
    } catch (_err) {
      if (batch.length === 1) return;
      batch.pop();
    }
  }
}

function compareUrlOf(payload) {
  if (!payload) return "";
  if (payload.compareUrl) return String(payload.compareUrl);
  const spec = payload.specCompare;
  return spec && spec.url ? String(spec.url) : "";
}

function oneCheckKey(url, kind, compareUrl) {
  return `${normalizeUrl(url)}|${kind || "일반"}|${normalizeUrl(compareUrl || "")}`;
}

function paintOneSaved() {
  const list = document.querySelector("#one-saved");
  const save = document.querySelector("#one-save");
  const clear = document.querySelector("#one-clear");
  if (save) save.disabled = !onePayload;
  if (!list) return;
  list.replaceChildren();
  const items = loadOneChecks();
  if (clear) clear.disabled = !items.length;
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "아직 저장한 검수가 없습니다.";
    list.append(li);
    return;
  }
  for (const item of items) {
    const payload = item.payload || {};
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "link";
    const host = document.createElement("span");
    host.textContent = payload.url || "주소 없음";
    const meta = document.createElement("span");
    const compareUrl = compareUrlOf(payload);
    meta.textContent = [
      payload.kind || "일반",
      compareUrl ? `비교 ${compareUrl}` : "",
      item.when,
    ]
      .filter(Boolean)
      .join(" · ");
    button.append(host, meta);
    button.addEventListener("click", () => openSavedOne(item));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-btn";
    remove.textContent = "삭제";
    remove.addEventListener("click", () => {
      writeOneChecks(loadOneChecks().filter((entry) => entry.id !== item.id));
      paintOneSaved();
    });
    li.append(button, remove);
    list.append(li);
  }
}

function saveOneCheck(payload) {
  if (!payload || !payload.url) return;
  const stored = JSON.parse(JSON.stringify(payload));
  const compareUrl = compareUrlOf(stored);
  if (stored.kind === "PDP" && compareUrl) stored.compareUrl = compareUrl;
  const key = oneCheckKey(stored.url, stored.kind, compareUrlOf(stored));
  const previous = loadOneChecks().find(
    (item) =>
      oneCheckKey(
        item.payload && item.payload.url,
        item.payload && item.payload.kind,
        compareUrlOf(item.payload),
      ) === key,
  );
  const record = {
    id:
      (previous && previous.id) ||
      `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`,
    when: new Date().toLocaleString("ko-KR", { hour12: false }),
    payload: stored,
  };
  writeOneChecks([
    record,
    ...loadOneChecks().filter(
      (item) =>
        item.id !== record.id &&
        oneCheckKey(
          item.payload && item.payload.url,
          item.payload && item.payload.kind,
          compareUrlOf(item.payload),
        ) !== key,
    ),
  ]);
  paintOneSaved();
}

function openSavedOne(item) {
  const payload = item && item.payload;
  if (!payload) return;
  urlInput.value = payload.url || "";
  const radio = document.querySelector(
    `input[name='page-kind'][value='${payload.kind || "일반"}']`,
  );
  if (radio) radio.checked = true;
  syncCompareField();
  const compareInput = document.querySelector("#compare-url");
  if (compareInput) compareInput.value = compareUrlOf(payload);
  renderPageCheck(payload);
}

function findAnalysis(url) {
  const key = normalizeUrl(url);
  return loadAnalyses().find((item) => normalizeUrl(item.url) === key) || null;
}

let listFilter = "전체";
let listedJobId = "";
let listedJob = null;
let listedPages = [];

function renderList(job) {
  showListPage(job.url || "");
  panel.hidden = false;
  status.replaceChildren();
  const language = job.language || "언어를 확인하지 못함";
  const country = job.country || "나라를 확인하지 못함";
  if (listPlace) listPlace.textContent = `${language} · ${country}`;
  if (deleteAnalysis) {
    deleteAnalysis.hidden = !job.id;
    deleteAnalysis.dataset.id = job.id || "";
  }
  if (excelDownload) excelDownload.hidden = !(job && job.url);
  listedJob = job;
  const jobKey = job.id || job.url || "";
  if (jobKey !== listedJobId) {
    listedJobId = jobKey;
    listFilter = "전체";
  }
  listedPages = job.pages || [];
  for (const page of listedPages) {
    if (page.url && isInsightListing(page.url)) page.kind = "Insights";
  }
  hydrateChecks(job);

  if (!(job.pages || []).length && !(job.notes || []).length) {
    const line = document.createElement("span");
    line.textContent = "같은 주소의 하위 페이지가 없습니다.";
    status.append(line);
  }
  if (job.notes && job.notes.length) {
    if (status.childNodes.length) status.append(document.createElement("br"));
    const note = document.createElement("span");
    note.textContent = job.notes.join(" ");
    status.append(note);
  }

  paintFilters(job);
  const menuBox = document.querySelector("#list-compare");
  if (job.menuDiff) {
    menuBox.hidden = false;
    paintMenuDiff(menuBox, job.menuDiff);
  } else {
    menuBox.hidden = true;
    menuBox.replaceChildren();
  }
  paintTree(job);
}

function paintFilters(job) {
  const kinds = { 일반: 0, PLP: 0, PDP: 0, Insights: 0, 기타: 0 };
  const real = (job.pages || []).filter((page) => displayKind(page));
  for (const page of real) {
    const kind = displayKind(page);
    if (Object.prototype.hasOwnProperty.call(kinds, kind)) kinds[kind] += 1;
  }
  const choices = [
    ["전체", real.length, "purple"],
    ["일반", kinds["일반"], "purple"],
    ["PLP", kinds.PLP, "coral"],
    ["PDP", kinds.PDP, "amber"],
    ["Insights", kinds.Insights, "green"],
    ["기타", kinds["기타"], "purple"],
    ["오류", (job.pages || []).filter(pageHasRed).length, "coral"],
    ["미검수", uncheckedCount(job), "amber"],
  ];
  summary.classList.add("filters");
  summary.replaceChildren();
  for (const [label, value, tone] of choices) {
    const options = {
      pressed: listFilter === label,
      hint:
        label === "전체"
          ? "모두 보기"
          :         label === "오류"
            ? "검수 열만"
            : label === "미검수"
              ? "결과 없는 페이지만"
              : "이 유형만",
      onClick: () => {
        listFilter = label;
        paintFilters(job);
        paintTree(job);
      },
    };
    if (label !== "기타" && label !== "오류" && label !== "미검수")
      options.onRecheck = () => recheckFilter(label, job);
    summary.append(kpiCard(label, value, tone, options));
  }
}

function checkHasRed(payload) {
  if (!payload || typeof payload !== "object") return false;
  if (payload.status === 404) return true;
  for (const view of shownViews(payload.viewports)) {
    if ((view.brokenLinks || []).length) return true;
    if ((view.missingImages || []).length) return true;
  }
  const listing = payload.listing;
  if (listing) {
    for (const view of shownViews(listing.thumbnails)) {
      if ((view.different || []).length) return true;
    }
    if ((listing.duplicates || []).length) return true;
  }
  return languageDiffers(payload);
}

function languageDiffers(payload) {
  const pageLanguage = payload && String(payload.language || "").trim();
  const rootLanguage = listedJob && String(listedJob.language || "").trim();
  if (!pageLanguage || !rootLanguage) return false;
  return pageLanguage !== rootLanguage;
}

function paintLanguage(slot, payload) {
  const cell = slot && slot.langCell;
  if (!cell) return;
  const pageLanguage = payload && String(payload.language || "").trim();
  const rootLanguage = listedJob && String(listedJob.language || "").trim();
  cell.classList.remove("is-na");
  if (!pageLanguage || !rootLanguage) {
    cell.textContent = "";
    return;
  }
  const differs = pageLanguage !== rootLanguage;
  const mark = document.createElement("span");
  mark.className = differs ? "mark-o is-bad" : "mark-o";
  mark.textContent = "O";
  mark.setAttribute(
    "aria-label",
    differs ? `언어 다름 ${pageLanguage}` : `언어 같음 ${pageLanguage}`,
  );
  cell.replaceChildren(mark);
}

function pageHasRed(page) {
  if (!page || !page.url) return false;
  return checkHasRed(storedChecks.get(page.url));
}

function reviewNode(page) {
  if (isGnbHeader(page) && listedJob && listedJob.url) return mainCheckNode(listedJob);
  return page;
}

function pageUnchecked(page) {
  const node = reviewNode(page);
  if (!node || !node.url || !assetPage(node)) return false;
  return !storedChecks.has(node.url);
}

function uncheckedCount(job) {
  const seen = new Set();
  let count = 0;
  for (const page of pagesWithMain(job || {})) {
    if (!assetPage(page) || !page.url || seen.has(page.url)) continue;
    seen.add(page.url);
    if (!storedChecks.has(page.url)) count += 1;
  }
  return count;
}

function clearUncheckedMark(url) {
  for (const mark of tree.querySelectorAll(".badge.unchecked")) {
    if (mark.dataset.url !== url) continue;
    const row = mark.closest("tr");
    if (row) row.classList.remove("is-unchecked");
    mark.remove();
  }
}

function pageMatches(page) {
  if (listFilter === "전체") return true;
  if (listFilter === "오류") return pageHasRed(page);
  if (listFilter === "미검수") return pageUnchecked(page);
  return displayKind(page) === listFilter;
}

function nodeKey(page) {
  return page.id || normalizeUrl(page.url);
}

function isGnbHeader(node) {
  if (!node) return false;
  if (node.id === "group:GNB") return true;
  return node.title === "GNB" && !node.url && node.group === "GNB";
}

function mainCheckNode(job) {
  const root = normalizeUrl((job && job.url) || "");
  const found = (job.pages || []).find(
    (page) => page.url && normalizeUrl(page.url) === root,
  );
  const kind = found ? displayKind(found) : "";
  return {
    url: (job && job.url) || "",
    kind: kind && kind !== "기타" ? kind : "일반",
    title: "메인",
    itemCount:
      found && Number.isFinite(found.itemCount) ? found.itemCount : null,
    itemSkus: found && Array.isArray(found.itemSkus) ? found.itemSkus : null,
    siblingCount:
      found && Number.isFinite(found.siblingCount) ? found.siblingCount : null,
    activeCount:
      found && Number.isFinite(found.activeCount) ? found.activeCount : null,
    discontinuedCount:
      found && Number.isFinite(found.discontinuedCount)
        ? found.discontinuedCount
        : null,
  };
}

function pagesWithMain(job) {
  const pages = job.pages || [];
  if (!pages.some(isGnbHeader)) return pages;
  const root = normalizeUrl(job.url || "");
  if (!root) return pages;
  if (
    pages.some(
      (page) => page.url && normalizeUrl(page.url) === root && assetPage(page),
    )
  )
    return pages;
  return [mainCheckNode(job), ...pages];
}

function paintTree(job) {
  assetTargets.clear();
  rowActions.clear();
  tree.replaceChildren();
  const pages = job.pages || [];
  const byParent = new Map();
  for (const page of pages) {
    const key =
      page.parent && !page.parent.startsWith("http")
        ? page.parent
        : normalizeUrl(page.parent || job.url || "");
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(page);
  }
  const known = new Set(pages.map((page) => nodeKey(page)));

  function childNodes(node) {
    return (byParent.get(nodeKey(node)) || []).filter(
      (child) => nodeKey(child) !== nodeKey(node),
    );
  }

  function keep(node) {
    if (pageMatches(node)) return true;
    return childNodes(node).some(keep);
  }

  const top = [];
  const seenTop = new Set();
  for (const page of pages) {
    const parent =
      page.parent && !String(page.parent).startsWith("http")
        ? page.parent
        : normalizeUrl(page.parent || "");
    const own = nodeKey(page);
    const atRoot =
      !parent || parent === normalizeUrl(job.url || "") || !known.has(parent);
    if (atRoot && keep(page) && !seenTop.has(own)) {
      seenTop.add(own);
      top.push(page);
    }
  }
  if (!top.length) {
    if (pages.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent =
        listFilter === "오류"
          ? "빨간색으로 표시된 페이지가 없습니다."
          : listFilter === "미검수"
            ? "검수 결과가 없는 페이지가 없습니다."
            : "이 유형의 페이지가 없습니다.";
      tree.append(empty);
    }
    return;
  }
  function itemsFrom(nodes) {
    const items = [];
    for (const node of nodes) {
      if (!keep(node)) continue;
      const children = itemsFrom(childNodes(node));
      const descendants = children.reduce((sum, child) => {
        const linked = child.node.url ? 1 : 0;
        return sum + linked + child.descendants;
      }, 0);
      items.push({ node, children, descendants, open: true });
    }
    return items;
  }

  tree.append(pageTable(itemsFrom(top), job));
}

function menuOpenLink(url, label, missing) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch (_err) {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  const link = document.createElement("a");
  link.className = missing
    ? "text-btn menu-link is-missing"
    : "text-btn menu-link";
  link.href = parsed.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "링크";
  link.setAttribute(
    "aria-label",
    missing ? `${label} 404, 새 창에서 열기` : `${label} 새 창에서 열기`,
  );
  return link;
}

function windowBadge(missing) {
  const badge = document.createElement("span");
  badge.className = missing ? "badge window-missing" : "badge window-ok";
  badge.textContent = "새창";
  badge.setAttribute("aria-label", missing ? "새창 404" : "새창");
  return badge;
}

function blankMarks(url, checks) {
  const info = checks && checks[url];
  if (!info || !info.blank) return null;
  return windowBadge(Boolean(info.missing));
}

function hideDescendants(item) {
  for (const child of item.children) {
    child.row.hidden = true;
    hideDescendants(child);
  }
}

function syncChildren(item) {
  for (const child of item.children) {
    child.row.hidden = !item.open;
    if (item.open) syncChildren(child);
    else hideDescendants(child);
  }
}

function isInsightListing(url) {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.replace(/\/+$/, "").toLowerCase();
    if (!path.endsWith("/insights")) return false;
    for (const key of parsed.searchParams.keys()) {
      if (key.toLowerCase() === "contentsformat") return false;
    }
    return true;
  } catch {
    return false;
  }
}

const pageChecks = new Map();
const storedChecks = new Map();

function loadPageCheck(url) {
  const existing = pageChecks.get(url);
  if (existing) return existing.promise;
  const controller = new AbortController();
  const promise = fetch("/api/page-check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
    signal: controller.signal,
  }).then(async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (payload.status === 404) return { ok: false, status: 404, url };
      throw new Error(payload.message || "이 페이지를 확인하지 못했습니다.");
    }
    return payload;
  });
  pageChecks.set(url, { promise, controller });
  return promise;
}

function uniqueProblems(views, key) {
  const seen = new Set();
  const rows = [];
  for (const view of views) {
    for (const row of view[key] || []) {
      const id = typeof row === "string" ? row : row.url;
      if (seen.has(id)) continue;
      seen.add(id);
      rows.push(row);
    }
  }
  return rows;
}

function modalLink(url) {
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = url;
  return link;
}

function modalChips(detail) {
  const chips = document.createElement("p");
  chips.className = "modal-chips";
  for (const part of String(detail || "")
    .split(" · ")
    .map((text) => text.trim())
    .filter(Boolean)) {
    const chip = document.createElement("span");
    chip.className = "modal-chip";
    chip.textContent = part;
    chips.append(chip);
  }
  return chips;
}

function modalSide(label, title, url, image) {
  const side = document.createElement("div");
  side.className = "modal-side";
  const cap = document.createElement("p");
  cap.className = "modal-side-label";
  cap.textContent = label;
  side.append(cap);
  if (image) {
    const img = document.createElement("img");
    img.src = image;
    img.alt = "";
    side.append(img);
  }
  if (title) {
    const name = document.createElement("strong");
    name.className = "modal-item-title";
    name.textContent = title;
    side.append(name);
  }
  if (url) side.append(modalLink(url));
  return side;
}

function otherPageUrl(row) {
  if (row.otherUrl) return row.otherUrl;
  const title = String(row.otherTitle || row.title || "")
    .trim()
    .toLowerCase();
  if (!title) return "";
  const match = listedPages.find((page) => {
    const pageTitle = String(page.title || "")
      .trim()
      .toLowerCase();
    return page.url && page.url !== row.url && pageTitle === title;
  });
  return match ? match.url : "";
}

function compareCard(row) {
  const card = document.createElement("article");
  card.className = "modal-compare";
  const pair = document.createElement("div");
  pair.className = "modal-pair";
  pair.append(
    modalSide("이 글", row.title, row.url, row.image),
    modalSide(
      "비교 글",
      row.otherTitle || row.title,
      otherPageUrl(row),
      row.otherImage,
    ),
  );
  if (row.detail) card.append(modalChips(row.detail));
  card.append(pair);
  return card;
}

function issueCard(row) {
  const card = document.createElement("article");
  card.className = "modal-issue";
  if (typeof row === "string") {
    card.textContent = row;
    return card;
  }
  if (row.detail) card.append(modalChips(row.detail));
  if (row.title) {
    const name = document.createElement("strong");
    name.className = "modal-item-title";
    name.textContent = row.title;
    card.append(name);
  }
  if (row.url) card.append(modalLink(row.url));
  return card;
}

function modalProblemList(rows, compare) {
  const list = document.createElement("div");
  list.className = "modal-list";
  if (!rows.length) {
    const item = document.createElement("p");
    item.className = "empty";
    item.textContent = "없습니다.";
    list.append(item);
    return list;
  }
  for (const row of rows) {
    const paired = compare || (row && (row.otherImage || row.otherUrl));
    list.append(paired ? compareCard(row) : issueCard(row));
  }
  return list;
}

function openDetailModal(heading, sections) {
  const modal = document.querySelector("#link-modal");
  const body = document.querySelector("#link-modal-body");
  const card = modal.querySelector(".modal-card");
  document.querySelector("#link-modal-title").textContent = heading;
  card.classList.remove("is-table");
  card.classList.toggle(
    "is-wide",
    sections.some((section) => section.compare),
  );
  body.replaceChildren();
  for (const section of sections) {
    const block = document.createElement("section");
    if (section.heading) {
      const title = document.createElement("h3");
      title.textContent = section.heading;
      block.append(title);
    }
    block.append(
      modalProblemList(section.rows || [], Boolean(section.compare)),
    );
    body.append(block);
  }
  modal.hidden = false;
  document.body.classList.add("modal-open");
  modal.querySelector(".modal-head [data-close]").focus();
}

function shownViews(views) {
  return (views || []).filter((view) => view.name !== "Wide PC");
}

function textPlace(pageUrl, text) {
  const value = String(text || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!pageUrl || !value) return "";
  const encoded = encodeURIComponent(value.slice(0, 120)).replace(/-/g, "%2D");
  return `${String(pageUrl).split("#")[0]}#:~:text=${encoded}`;
}

function linkField(label, value, href) {
  const field = document.createElement("div");
  field.className = "link-field";
  const name = document.createElement("span");
  name.className = "link-field-label";
  name.textContent = label;
  const text = document.createElement(href ? "a" : "p");
  text.className = "link-field-value";
  text.textContent = value;
  if (href) {
    text.href = href;
    text.target = "_blank";
    text.rel = "noreferrer";
  }
  field.append(name, text);
  return field;
}

function linkStatusField(detail) {
  const field = document.createElement("div");
  field.className = "link-field";
  const name = document.createElement("span");
  name.className = "link-field-label";
  name.textContent = "상태";
  const badge = document.createElement("span");
  badge.className = detail === "404" ? "badge window-missing" : "badge fail";
  badge.textContent = detail || "404";
  field.append(name, badge);
  return field;
}

function linkCheckCell(row, pageUrl) {
  const cell = document.createElement("td");
  if (!row) {
    cell.className = "is-empty";
    cell.textContent = "없음";
    return cell;
  }
  const text = row.title || row.url;
  cell.append(
    linkField("내용 텍스트", text, textPlace(pageUrl, text)),
    linkStatusField(row.detail),
  );
  return cell;
}

function viewportTable(names, order, cellAt) {
  const table = document.createElement("table");
  table.className = "link-check";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const name of names) {
    const cell = document.createElement("th");
    cell.textContent = name;
    headRow.append(cell);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  if (!order.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = names.length;
    cell.className = "is-empty";
    cell.textContent = "없습니다.";
    row.append(cell);
    body.append(row);
  } else {
    for (const key of order) {
      const row = document.createElement("tr");
      for (const name of names) row.append(cellAt(key, name));
      body.append(row);
    }
  }
  table.append(head, body);
  return table;
}

function linkCheckTable(payload) {
  const names = ["Mobile", "Tablet", "PC"];
  const byName = new Map(
    shownViews(payload.viewports).map((view) => [view.name, view]),
  );
  const order = [];
  const byUrl = new Map();
  for (const name of names) {
    const view = byName.get(name);
    for (const row of (view && view.brokenLinks) || []) {
      if (!row || !row.url) continue;
      if (!byUrl.has(row.url)) {
        byUrl.set(row.url, {});
        order.push(row.url);
      }
      byUrl.get(row.url)[name] = row;
    }
  }
  return viewportTable(names, order, (url, name) =>
    linkCheckCell(byUrl.get(url)[name], payload.url),
  );
}

function imageProblemRows(view) {
  const rows = [];
  for (const item of (view && view.missingImages) || []) {
    const title =
      typeof item === "string"
        ? String(item).trim()
        : String((item && (item.text || item.title)) || "").trim();
    const label = title || "이미지";
    const tag = item && typeof item === "object" ? String(item.tag || "") : "";
    rows.push({ key: `missing:${label}`, title: label, detail: "없음", tag });
  }
  for (const item of (view && view.brokenImages) || []) {
    if (!item || !item.url) continue;
    rows.push({
      key: `broken:${item.url}`,
      url: item.url,
      detail: item.detail || "404",
      tag: String(item.tag || ""),
    });
  }
  return rows;
}

function imageStatusField(row) {
  if (row.tag) {
    const field = linkField("상태", row.tag);
    field.querySelector(".link-field-value").classList.add("is-tag");
    return field;
  }
  return linkStatusField(row.detail || "없음");
}

function imageCheckCell(row, pageUrl) {
  const cell = document.createElement("td");
  if (!row) {
    cell.className = "is-empty";
    cell.textContent = "없음";
    return cell;
  }
  if (row.url) {
    cell.append(
      linkField("이미지 주소", row.url, row.url),
      imageStatusField(row),
    );
    return cell;
  }
  const text = row.title || "이미지";
  cell.append(
    linkField("대체 텍스트", text, textPlace(pageUrl, text)),
    imageStatusField(row),
  );
  return cell;
}

function imageCheckTable(payload) {
  const names = ["Mobile", "Tablet", "PC"];
  const byName = new Map(
    shownViews(payload.viewports).map((view) => [view.name, view]),
  );
  const order = [];
  const byKey = new Map();
  for (const name of names) {
    for (const row of imageProblemRows(byName.get(name))) {
      if (!byKey.has(row.key)) {
        byKey.set(row.key, {});
        order.push(row.key);
      }
      byKey.get(row.key)[name] = row;
    }
  }
  return viewportTable(names, order, (key, name) =>
    imageCheckCell(byKey.get(key)[name], payload.url),
  );
}

function openAssetModal(title, node) {
  const modal = document.querySelector("#link-modal");
  const body = document.querySelector("#link-modal-body");
  const card = modal.querySelector(".modal-card");
  document.querySelector("#link-modal-title").textContent = title;
  card.classList.remove("is-wide");
  card.classList.add("is-table");
  body.replaceChildren(node);
  modal.hidden = false;
  document.body.classList.add("modal-open");
  modal.querySelector(".modal-head [data-close]").focus();
}

function skuProduct(item) {
  if (typeof item === "string" && item)
    return { sku: item, discontinued: false };
  if (!item || typeof item !== "object") return null;
  const sku = typeof item.sku === "string" ? item.sku : "";
  if (!sku) return null;
  const product = { sku, discontinued: Boolean(item.discontinued) };
  if (Number.isFinite(item.siblings)) product.siblings = item.siblings;
  return product;
}

function skuCount(label, count, tone) {
  const item = document.createElement("p");
  item.className = "sku-count";
  const name = document.createElement("span");
  name.textContent = label;
  const value = document.createElement("strong");
  if (tone) value.className = tone;
  value.textContent = String(count);
  item.append(name, " ", value);
  return item;
}

function skuColumn(label, products, tone) {
  const column = document.createElement("section");
  const title = document.createElement("h3");
  title.textContent = label;
  const list = document.createElement("div");
  list.className = "sku-badges";
  if (!products.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "없습니다.";
    list.append(empty);
  } else {
    for (const product of products) {
      const badge = document.createElement("span");
      badge.className = `badge sku-badge ${tone}`;
      badge.textContent = product.sku;
      list.append(badge);
    }
  }
  column.append(title, list);
  return column;
}

function siblingTotal(payload, slot) {
  if (payload && Number.isFinite(payload.siblingCount))
    return payload.siblingCount;
  if (slot && Number.isFinite(slot.siblingCount)) return slot.siblingCount;
  return 0;
}

function siblingParts(products, totalSiblings) {
  const total = Number.isFinite(totalSiblings) ? totalSiblings : 0;
  const known = products.some((item) => Number.isFinite(item.siblings));
  if (!known) return { active: total, discontinued: 0, all: total };
  const sum = (discontinued) =>
    products
      .filter((item) => Boolean(item.discontinued) === discontinued)
      .reduce(
        (count, item) =>
          count + (Number.isFinite(item.siblings) ? item.siblings : 0),
        0,
      );
  const active = sum(false);
  const discontinued = sum(true);
  return { active, discontinued, all: active + discontinued };
}

function screenCount(payload, slot, key) {
  if (payload && Number.isFinite(payload[key])) return payload[key];
  if (slot && Number.isFinite(slot[key])) return slot[key];
  return null;
}

function openSkuModal(skus, total, siblings, activeTotal, stoppedTotal) {
  const products = (skus || []).map(skuProduct).filter(Boolean);
  const stopped = products.filter((item) => item.discontinued);
  const active = products.filter((item) => !item.discontinued);
  const summed = Number.isFinite(activeTotal) && Number.isFinite(stoppedTotal)
    ? activeTotal + stoppedTotal
    : null;
  const all = summed != null ? summed : (Number.isFinite(total) ? total : products.length);
  const activeCount = Number.isFinite(activeTotal)
    ? activeTotal
    : Math.max(0, all - stopped.length);
  const discontinuedCount = Number.isFinite(stoppedTotal)
    ? stoppedTotal
    : stopped.length;
  const parts = siblingParts(products, siblings);
  const panel = document.createElement("div");
  panel.className = "sku-modal";
  const summary = document.createElement("div");
  summary.className = "sku-summary";
  summary.append(
    skuCount(
      "Active -",
      `${activeCount + parts.active}(${activeCount}/${parts.active})`,
      "is-clear",
    ),
    skuCount(
      "Discontinued -",
      `${discontinuedCount + parts.discontinued}(${discontinuedCount}/${parts.discontinued})`,
      "is-bad",
    ),
    skuCount(
      "All -",
      `${all + parts.all}(${all}/${parts.all})`,
      "",
    ),
  );
  const columns = document.createElement("div");
  columns.className = "sku-columns";
  columns.append(
    skuColumn("Active", active, "pass"),
    skuColumn("Discontinued", stopped, "fail"),
  );
  panel.append(summary, columns);
  openAssetModal("아이템 수량", panel);
  const card = document.querySelector("#link-modal .modal-card");
  card.classList.remove("is-table");
  card.classList.add("is-wide");
}

function openLinkModal(payload) {
  openAssetModal("broken link", linkCheckTable(payload));
}

function openImageModal(payload) {
  openAssetModal("broken image", imageCheckTable(payload));
}

function closeLinkModal() {
  const modal = document.querySelector("#link-modal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
}

function ratioLine(title, total, bad, onClick) {
  const line = document.createElement("div");
  line.className = "asset-line";
  const name = document.createElement("span");
  name.className = "asset-title";
  name.textContent = title;
  const count = document.createElement(onClick ? "button" : "span");
  if (onClick) count.type = "button";
  count.className = `count-num ${bad ? "is-bad" : "is-clear"}`;
  count.textContent = `${total}/${bad}`;
  count.setAttribute("aria-label", `${title} 전체 ${total}, 문제 ${bad}`);
  if (onClick) count.addEventListener("click", onClick);
  line.append(name, count);
  return line;
}

const assetTargets = new Map();
const rowActions = new Map();
let assetQueue = [];
let assetCurrent = "";
let assetDone = 0;
let assetTotal = 0;
let assetToken = 0;
let assetActive = false;
let assetHalted = false;
let assetLabel = "Insights";
let assetAnnounceEmpty = false;
let lastFinishedJob = null;

function assetPage(node) {
  const kind = displayKind(node);
  return (
    Boolean(node.url) &&
    (kind === "일반" || kind === "PLP" || kind === "PDP" || kind === "Insights")
  );
}

function checksForJob(job) {
  const onJob = job.checks || {};
  if (Object.keys(onJob).length) return onJob;
  const saved = loadAnalyses().find((item) => item.id && item.id === job.id);
  return (saved && saved.checks) || {};
}

function hydrateChecks(job) {
  storedChecks.clear();
  const checks = checksForJob(job);
  job.checks = checks;
  for (const [url, payload] of Object.entries(checks)) {
    if (payload) storedChecks.set(url, payload);
  }
}

function mergedChecks(previous) {
  const checks = Object.assign({}, previous || {});
  for (const [url, payload] of storedChecks) {
    if (url && payload) checks[url] = payload;
  }
  return checks;
}

function persistListedChecks() {
  if (!listedJobId) return;
  const items = loadAnalyses();
  const item = items.find((entry) => entry.id === listedJobId);
  if (!item) return;
  item.checks = mergedChecks(item.checks);
  writeAnalyses(items);
}

function rememberCheck(url, payload) {
  storedChecks.set(url, payload);
  persistListedChecks();
  if (!listedJob) return;
  clearUncheckedMark(url);
  paintFilters(listedJob);
  if (listFilter === "오류" || listFilter === "미검수") paintTree(listedJob);
}

function applyAsset(slot, payload) {
  if (payload && payload.status === 404) paintAsset404(slot);
  else paintAssetResult(slot, payload);
}

function skuValues(payload, slot) {
  if (payload && Array.isArray(payload.itemSkus)) return payload.itemSkus;
  return Array.isArray(slot.itemSkus) ? slot.itemSkus : null;
}

function paintItemCount(slot, payload) {
  if (!slot.plp || !slot.countCell) return;
  const hasPayload =
    payload && Object.prototype.hasOwnProperty.call(payload, "itemCount");
  const value = hasPayload ? payload.itemCount : slot.itemCount;
  const skus = skuValues(payload, slot);
  if (Array.isArray(skus)) slot.itemSkus = skus;
  if (payload && Number.isFinite(payload.siblingCount))
    slot.siblingCount = payload.siblingCount;
  if (payload && Number.isFinite(payload.activeCount))
    slot.activeCount = payload.activeCount;
  if (payload && Number.isFinite(payload.discontinuedCount))
    slot.discontinuedCount = payload.discontinuedCount;
  const siblings = siblingTotal(payload, slot);
  if (Number.isFinite(value)) {
    slot.itemCount = value;
    slot.countCell.classList.remove("is-na");
    slot.countCell.replaceChildren();
    if (Array.isArray(slot.itemSkus)) {
      const products = slot.itemSkus.map(skuProduct).filter(Boolean);
      const listedStopped = products.filter((item) => item.discontinued).length;
      const stoppedFromScreen = screenCount(payload, slot, "discontinuedCount");
      const activeFromScreen = screenCount(payload, slot, "activeCount");
      const stopped = stoppedFromScreen ?? listedStopped;
      const active = activeFromScreen ?? Math.max(0, value - listedStopped);
      const all = activeFromScreen != null && stoppedFromScreen != null
        ? activeFromScreen + stoppedFromScreen
        : value;
      const parts = siblingParts(products, siblings);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "count-num";
      const activeLine = document.createElement("span");
      activeLine.className = "count-pair is-clear";
      activeLine.textContent = `Active - ${active + parts.active}(${active}/${parts.active})`;
      const stoppedLine = document.createElement("span");
      stoppedLine.className = "count-pair is-bad";
      stoppedLine.textContent = `Discontinued - ${stopped + parts.discontinued}(${stopped}/${parts.discontinued})`;
      const totalLine = document.createElement("span");
      totalLine.className = "count-pair";
      totalLine.textContent = `All - ${all + parts.all}(${all}/${parts.all})`;
      button.append(activeLine, stoppedLine, totalLine);
      button.setAttribute(
        "aria-label",
        `Active - ${active + parts.active}(${active}/${parts.active}), Discontinued - ${stopped + parts.discontinued}(${stopped}/${parts.discontinued}), All - ${all + parts.all}(${all}/${parts.all})`,
      );
      button.addEventListener("click", () =>
        openSkuModal(slot.itemSkus, all, siblings, active, stopped),
      );
      slot.countCell.append(button);
      return;
    }
    slot.countCell.textContent = String(value);
    return;
  }
  if (hasPayload) {
    slot.countCell.classList.remove("is-na");
    slot.countCell.textContent = "확인 실패";
    return;
  }
  if (Number.isFinite(slot.itemCount)) {
    slot.countCell.textContent = String(slot.itemCount);
    return;
  }
  slot.countCell.textContent = "";
}

function paintListingGap(slot) {
  if (slot.listing) return;
  for (const cell of [slot.thumbCell, slot.dupCell]) {
    cell.classList.add("is-na");
    cell.textContent = "해당 없음";
  }
}

function paintListing(slot, payload) {
  if (!slot.listing) return;
  const listing = payload && payload.listing;
  if (!listing) {
    slot.thumbCell.textContent = "";
    slot.dupCell.textContent = "";
    return;
  }
  const thumbs = document.createElement("div");
  thumbs.className = "asset-lines";
  for (const view of shownViews(listing.thumbnails)) {
    if (view.unread) {
      const failed = document.createElement("span");
      failed.className = "asset-title";
      failed.textContent = `${view.name} 확인 실패`;
      thumbs.append(failed);
      continue;
    }
    const rows = view.different || [];
    const total = Number.isFinite(view.total) ? view.total : rows.length;
    thumbs.append(
      ratioLine(view.name, total, rows.length, () =>
        openDetailModal("Thumbnail", [
          {
            heading: `${view.name} · ${view.width}px (${total}/${rows.length})`,
            rows,
          },
        ]),
      ),
    );
  }
  const copies = listing.duplicates || [];
  const total = Number.isFinite(listing.contentTotal)
    ? listing.contentTotal
    : copies.length;
  const dup = document.createElement("div");
  dup.className = "asset-lines";
  dup.append(
    ratioLine("전체", total, copies.length, () =>
      openDetailModal("중복", [
        {
          heading: `전체 ${total} / 중복 ${copies.length}`,
          rows: copies,
          compare: true,
        },
      ]),
    ),
  );
  slot.thumbCell.replaceChildren(thumbs);
  slot.dupCell.replaceChildren(dup);
  slot.thumbCell.classList.remove("is-na");
  slot.dupCell.classList.remove("is-na");
}

function clearAssetSlot(slot) {
  slot.linkCell.textContent = "";
  slot.imageCell.textContent = "";
  paintItemCount(slot);
  if (slot.listing) {
    slot.thumbCell.textContent = "";
    slot.dupCell.textContent = "";
    slot.thumbCell.classList.remove("is-na");
    slot.dupCell.classList.remove("is-na");
  }
  slot.linkCell.title = "";
  if (slot.langCell) slot.langCell.textContent = "";
  paintListingGap(slot);
}

function paintAssetWait(slot, label) {
  slot.linkCell.textContent = label;
  slot.imageCell.textContent = label;
  if (slot.langCell) slot.langCell.textContent = label;
  if (slot.plp && slot.countCell) slot.countCell.textContent = label;
  if (slot.listing) {
    slot.thumbCell.textContent = label;
    slot.dupCell.textContent = label;
    slot.thumbCell.classList.remove("is-na");
    slot.dupCell.classList.remove("is-na");
  }
  paintListingGap(slot);
}

function paintAssetResult(slot, payload) {
  const views = shownViews(payload.viewports);
  const linkLines = document.createElement("div");
  linkLines.className = "asset-lines";
  const imageLines = document.createElement("div");
  imageLines.className = "asset-lines";
  for (const view of views) {
    const broken = (view.brokenLinks || []).length;
    const missing = (view.missingImages || []).length;
    const linkTotal = Number.isFinite(view.linkTotal) ? view.linkTotal : broken;
    const imageTotal = Number.isFinite(view.imageTotal)
      ? view.imageTotal
      : missing;
    linkLines.append(
      ratioLine(view.name, linkTotal, broken, () => openLinkModal(payload)),
    );
    imageLines.append(
      ratioLine(view.name, imageTotal, missing, () => openImageModal(payload)),
    );
  }
  slot.linkCell.replaceChildren(linkLines);
  slot.imageCell.replaceChildren(imageLines);
  slot.linkCell.title = "";
  paintItemCount(slot, payload);
  paintListing(slot, payload);
  paintLanguage(slot, payload);
  paintListingGap(slot);
}

function paintAsset404(slot) {
  const cells = [slot.linkCell, slot.imageCell];
  if (slot.plp && slot.countCell) cells.push(slot.countCell);
  if (slot.listing) cells.push(slot.thumbCell, slot.dupCell);
  for (const cell of cells) {
    const mark = document.createElement("span");
    mark.className = "count-num is-bad";
    mark.textContent = "404";
    cell.replaceChildren(mark);
    cell.classList.remove("is-na");
  }
  slot.linkCell.title = "";
  if (slot.langCell) slot.langCell.textContent = "";
  paintListingGap(slot);
}

function paintAssetFailed(slot, message) {
  slot.linkCell.textContent = "확인 실패";
  slot.imageCell.textContent = "";
  paintItemCount(slot);
  if (slot.listing) {
    slot.thumbCell.textContent = "확인 실패";
    slot.dupCell.textContent = "";
    slot.thumbCell.classList.remove("is-na");
    slot.dupCell.classList.remove("is-na");
  }
  slot.linkCell.title = message || "이 페이지를 확인하지 못했습니다.";
  if (slot.langCell) slot.langCell.textContent = "";
  paintListingGap(slot);
}

function slotsFor(url) {
  return assetTargets.get(url) || [];
}

function assetRowState(url) {
  if (url && url === assetCurrent) return "live";
  if (url && assetQueue.includes(url)) return "wait";
  return "idle";
}

function syncRowAction(url) {
  const state = assetRowState(url);
  for (const controls of rowActions.get(url) || []) {
    controls.analyze.disabled = state === "wait" || state === "live";
    controls.stop.hidden = state !== "live";
  }
}

function syncRowActions() {
  for (const url of rowActions.keys()) syncRowAction(url);
}

function analyzePage(node) {
  const url = node && node.url;
  if (!url || displayKind(node) === "기타" || assetRowState(url) !== "idle")
    return;
  clearReviewHalt(listedJobId);
  if (assetActive) {
    assetQueue.push(url);
    assetTotal += 1;
    for (const slot of slotsFor(url)) paintAssetWait(slot, "대기");
    showAssetStatus();
    syncRowActions();
    return;
  }
  assetLabel = node.title || "선택 페이지";
  assetAnnounceEmpty = false;
  assetHalted = false;
  assetToken += 1;
  assetQueue = [url];
  assetCurrent = "";
  assetDone = 0;
  assetTotal = 1;
  assetActive = true;
  showAssetStatus();
  pumpAssetQueue(assetToken);
}

function stopAssetChecks() {
  const urls = [];
  if (assetCurrent) urls.push(assetCurrent);
  urls.push(...assetQueue);
  assetHalted = true;
  assetToken += 1;
  assetQueue = [];
  assetCurrent = "";
  assetActive = false;
  assetDone = 0;
  assetTotal = 0;
  assetAnnounceEmpty = false;
  for (const url of urls) {
    const job = pageChecks.get(url);
    pageChecks.delete(url);
    if (job) job.controller.abort();
    const saved = storedChecks.get(url);
    for (const slot of slotsFor(url)) {
      if (saved) applyAsset(slot, saved);
      else clearAssetSlot(slot);
    }
  }
  const line = document.querySelector("#asset-status");
  if (line) {
    line.classList.remove("is-live");
    line.textContent = "검수를 중단했습니다.";
  }
  if (lastFinishedJob) paintFinished(lastFinishedJob);
  else paintAssetHalt();
  syncRowActions();
}

function showAssetStatus() {
  let line = document.querySelector("#asset-status");
  if (!line) {
    line = document.createElement("span");
    line.id = "asset-status";
    if (status.childNodes.length) status.append(document.createElement("br"));
    status.append(line);
  }
  if (!assetTotal) {
    assetActive = false;
    line.classList.remove("is-live");
    line.textContent = assetAnnounceEmpty
      ? `${assetLabel}에서 검사할 주소가 없습니다.`
      : "";
    if (assetAnnounceEmpty) {
      const title = document.querySelector("#running-title");
      const detail = document.querySelector("#running-detail");
      const meter = document.querySelector("#running-meter");
      if (title) title.textContent = "검수할 주소 없음";
      if (detail) detail.textContent = line.textContent;
      if (meter) meter.hidden = true;
    }
    return;
  }
  const live = assetDone < assetTotal;
  line.classList.toggle("is-live", live);
  line.textContent = live
    ? `${assetLabel} 검수 중 ${assetDone}/${assetTotal}`
    : `${assetLabel} 검수가 끝났습니다. ${assetTotal}페이지`;
  if (assetActive) {
    if (lastFinishedJob) paintFinished(lastFinishedJob);
    else {
      const title = document.querySelector("#running-title");
      const detail = document.querySelector("#running-detail");
      const meter = document.querySelector("#running-meter");
      const fill = document.querySelector("#running-fill");
      if (title) title.textContent = "검수 중";
      if (detail)
        detail.textContent = `${assetLabel} ${assetDone}/${assetTotal}`;
      if (meter) meter.hidden = false;
      if (fill)
        fill.style.width = `${Math.min(100, Math.round((assetDone / Math.max(assetTotal, 1)) * 100))}%`;
      const stop = document.querySelector("#running-stop");
      if (stop) {
        stop.hidden = false;
        stop.disabled = false;
        stop.textContent = "중지";
      }
    }
    return;
  }
  if (lastFinishedJob) paintFinished(lastFinishedJob);
}

function watchAssetCells(
  linkCell,
  imageCell,
  thumbCell,
  dupCell,
  countCell,
  langCell,
  node,
) {
  if (!node.url || displayKind(node) === "기타") return;
  const slot = {
    linkCell,
    imageCell,
    thumbCell,
    dupCell,
    countCell,
    langCell,
    itemCount: Number.isFinite(node.itemCount) ? node.itemCount : null,
    itemSkus: Array.isArray(node.itemSkus) ? node.itemSkus : null,
    siblingCount: Number.isFinite(node.siblingCount) ? node.siblingCount : null,
    activeCount: Number.isFinite(node.activeCount) ? node.activeCount : null,
    discontinuedCount: Number.isFinite(node.discontinuedCount)
      ? node.discontinuedCount
      : null,
    listing: isInsightListing(node.url),
    insight: node.kind === "Insights" || isInsightListing(node.url),
    plp: displayKind(node) === "PLP",
  };
  if (!assetTargets.has(node.url)) assetTargets.set(node.url, []);
  assetTargets.get(node.url).push(slot);
  const saved = storedChecks.get(node.url);
  if (saved) {
    applyAsset(slot, saved);
    return;
  }
  const state = assetRowState(node.url);
  if (state === "idle") {
    paintListingGap(slot);
    paintItemCount(slot);
    return;
  }
  paintAssetWait(slot, state === "live" ? "검수 중" : "대기");
  const pending = pageChecks.get(node.url);
  if (!pending) return;
  pending.promise.then(
    (payload) => {
      if (pageChecks.get(node.url) !== pending) return;
      paintAssetResult(slot, payload);
    },
    (error) => {
      if (error && error.name === "AbortError") return;
      if (pageChecks.get(node.url) !== pending) return;
      paintAssetFailed(slot, error.message);
    },
  );
}

function pumpAssetQueue(token) {
  if (token !== assetToken) return;
  if (!assetQueue.length) {
    assetCurrent = "";
    assetActive = assetDone < assetTotal;
    persistListedChecks();
    showAssetStatus();
    syncRowActions();
    return;
  }
  const url = assetQueue.shift();
  assetCurrent = url;
  assetActive = true;
  for (const slot of slotsFor(url)) paintAssetWait(slot, "검수 중");
  syncRowActions();
  showAssetStatus();
  loadPageCheck(url).then(
    (payload) => {
      if (token !== assetToken) return;
      pageChecks.delete(url);
      assetDone += 1;
      rememberCheck(url, payload);
      if (assetCurrent === url) assetCurrent = "";
      for (const slot of slotsFor(url)) applyAsset(slot, payload);
      syncRowActions();
      pumpAssetQueue(token);
    },
    (error) => {
      if (token !== assetToken) return;
      pageChecks.delete(url);
      assetDone += 1;
      if (assetCurrent === url) assetCurrent = "";
      if (!(error && error.name === "AbortError")) {
        for (const slot of slotsFor(url)) paintAssetFailed(slot, error.message);
      }
      syncRowActions();
      pumpAssetQueue(token);
    },
  );
}

function pagesForFilter(pages, label) {
  if (label === "기타") return [];
  return pages.filter((page) => {
    const kind = displayKind(page);
    if (!page.url || !kind || kind === "기타") return false;
    if (label === "전체") return true;
    return kind === label;
  });
}

function forgetChecks(urls) {
  const drop = new Set(urls);
  for (const url of drop) {
    storedChecks.delete(url);
    pageChecks.delete(url);
  }
  const items = loadAnalyses();
  const item = items.find((entry) => entry.id === listedJobId);
  if (!item || !item.checks) return;
  for (const url of drop) delete item.checks[url];
  writeAnalyses(items);
}

function recheckFilter(label, job) {
  clearReviewHalt(job && job.id);
  const pages = pagesForFilter(pagesWithMain(job), label);
  forgetChecks(pages.map((page) => page.url));
  listFilter = label;
  paintFilters(job);
  paintTree(job);
  startAssetChecks(pages, { force: true, label, announceEmpty: true });
}

function startAssetChecks(pages, options) {
  const force = Boolean(options && options.force);
  assetLabel = (options && options.label) || "페이지";
  assetAnnounceEmpty = Boolean(options && options.announceEmpty);
  assetHalted = false;
  const urls = [];
  const seen = new Set();
  for (const page of pages) {
    const kind = displayKind(page);
    const allowed = force ? Boolean(kind) && kind !== "기타" : assetPage(page);
    if (!allowed || seen.has(page.url)) continue;
    seen.add(page.url);
    urls.push(page.url);
  }
  assetToken += 1;
  assetCurrent = "";
  assetQueue = urls.filter(
    (url) => force || (!storedChecks.has(url) && !pageChecks.has(url)),
  );
  assetDone = urls.length - assetQueue.length;
  assetTotal = urls.length;
  assetActive = assetDone < assetTotal;
  for (const url of assetQueue) {
    for (const slot of slotsFor(url)) paintAssetWait(slot, "대기");
  }
  syncRowActions();
  showAssetStatus();
  pumpAssetQueue(assetToken);
}

function markCheckArea(cell, applies) {
  if (applies) {
    cell.classList.remove("is-na");
    cell.textContent = "";
    return;
  }
  cell.classList.add("is-na");
  cell.textContent = "해당 없음";
}

function pageTable(items, job) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "page-table";
  const head = document.createElement("thead");
  const titles = document.createElement("tr");
  for (const text of [
    "메뉴",
    "아이템",
    "아이템 수량 (item/sibling)",
    "언어",
    "UFN",
    "Dimension",
    "broken link",
    "broken image",
    "Thumbnail",
    "중복",
    "분석",
  ]) {
    const cell = document.createElement("th");
    cell.textContent = text;
    titles.append(cell);
  }
  head.append(titles);
  const body = document.createElement("tbody");
  function addRows(list) {
    for (const item of list) {
      const node = item.node;
      const mainHeader = isGnbHeader(node);
      const checking = mainHeader && job && job.url ? mainCheckNode(job) : node;
      const depth = Number.isFinite(node.depth) ? node.depth : 1;
      const line = document.createElement("tr");
      item.row = line;
      const label = mainHeader ? "메인" : node.title || node.url || "항목";
      const name = document.createElement("td");
      name.className = "menu-name";
      name.style.paddingLeft = `${12 + Math.max(depth, 0) * 16}px`;
      if (item.children.length) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "tree-step";
        toggle.textContent = label;
        toggle.setAttribute("aria-expanded", "true");
        toggle.setAttribute("aria-label", `${label} 접기`);
        toggle.addEventListener("click", () => {
          item.open = !item.open;
          toggle.setAttribute("aria-expanded", item.open ? "true" : "false");
          toggle.setAttribute(
            "aria-label",
            item.open ? `${label} 접기` : `${label} 펼치기`,
          );
          syncChildren(item);
        });
        name.append(toggle);
      } else {
        const title = document.createElement("span");
        title.className = "menu-label";
        title.textContent = label;
        name.append(title);
      }
      const openLink = menuOpenLink(
        checking.url,
        label,
        Boolean(checking.missing),
      );
      if (openLink) name.append(openLink);
      if (node.outsideGnb) {
        const added = document.createElement("span");
        added.className = "badge outside-gnb";
        added.textContent = "GNB 없음";
        name.append(added);
      }
      if (item.descendants) {
        const count = document.createElement("span");
        count.className = "tree-count";
        count.textContent = `(하위 ${item.descendants})`;
        name.append(count);
      }
      if (node.blank) name.append(windowBadge(Boolean(node.missing)));
      if (node.product || node.discontinued) {
        const stopped = document.createElement("span");
        const inactive = Boolean(node.discontinued);
        stopped.className = inactive ? "badge discontinued" : "badge active";
        stopped.textContent = inactive ? "Discontinued" : "Active";
        name.append(stopped);
      }
      if (checking.url && assetPage(checking) && !storedChecks.has(checking.url)) {
        line.classList.add("is-unchecked");
        const pending = document.createElement("span");
        pending.className = "badge unchecked";
        pending.dataset.url = checking.url;
        pending.textContent = "미검수";
        name.append(pending);
      }
      const itemCell = document.createElement("td");
      const itemKind = displayKind(checking);
      if (itemKind) {
        const kind = document.createElement("span");
        kind.className = `badge ${kindClass(itemKind)}`;
        kind.textContent = itemKind;
        itemCell.append(kind);
      }
      const countCell = document.createElement("td");
      countCell.className = "item-count";
      const langCell = document.createElement("td");
      langCell.className = "check-area";
      const ufnCell = document.createElement("td");
      ufnCell.className = "check-area";
      const dimensionCell = document.createElement("td");
      dimensionCell.className = "check-area";
      const linkCell = document.createElement("td");
      linkCell.className = "asset-count";
      const imageCell = document.createElement("td");
      imageCell.className = "asset-count";
      const thumbCell = document.createElement("td");
      thumbCell.className = "asset-count";
      const dupCell = document.createElement("td");
      dupCell.className = "asset-count";
      if (itemKind) {
        if (itemKind !== "PLP") markCheckArea(countCell, false);
        markCheckArea(langCell, true);
        markCheckArea(ufnCell, itemKind === "PDP");
        markCheckArea(dimensionCell, itemKind === "PDP");
      }
      watchAssetCells(
        linkCell,
        imageCell,
        thumbCell,
        dupCell,
        countCell,
        langCell,
        checking,
      );
      const actionCell = document.createElement("td");
      actionCell.className = "row-action";
      if (checking.url && itemKind !== "기타") {
        const actions = document.createElement("div");
        actions.className = "row-actions";
        const analyze = document.createElement("button");
        analyze.type = "button";
        analyze.className = "text-btn row-analyze";
        analyze.textContent = "분석하기";
        analyze.addEventListener("click", () => analyzePage(checking));
        const stop = document.createElement("button");
        stop.type = "button";
        stop.className = "text-btn row-stop";
        stop.textContent = "검수 중단";
        stop.hidden = true;
        stop.addEventListener("click", () => stopAssetChecks());
        actions.append(analyze, stop);
        if (!rowActions.has(checking.url)) rowActions.set(checking.url, []);
        rowActions.get(checking.url).push({ analyze, stop });
        syncRowAction(checking.url);
        actionCell.append(actions);
      }
      line.append(
        name,
        itemCell,
        countCell,
        langCell,
        ufnCell,
        dimensionCell,
        linkCell,
        imageCell,
        thumbCell,
        dupCell,
        actionCell,
      );
      body.append(line);
      addRows(item.children);
    }
  }
  addRows(items);
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

const EXCEL_LIMIT = 20 * 1024 * 1024;

function showExcelNote(message) {
  const line = document.querySelector("#excel-status");
  if (line && home && !home.hidden) {
    line.hidden = !message;
    line.textContent = message || "";
  }
  if (!message || !listPage || listPage.hidden) return;
  const note = document.createElement("span");
  note.textContent = message;
  if (status.childNodes.length) status.append(document.createElement("br"));
  status.append(note);
}

function newAnalysisId() {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function analysisFromJob(job) {
  const saved =
    loadAnalyses().find((item) => item.id && job.id && item.id === job.id) ||
    null;
  const base = Object.assign(
    {},
    (saved && saved.checks) || {},
    job.checks || {},
  );
  const checks =
    listedJobId && job.id === listedJobId ? mergedChecks(base) : base;
  const record = {
    id: (saved && saved.id) || job.id || "",
    url: job.url || (saved && saved.url) || "",
    when: (saved && saved.when) || job.when || "",
    language: job.language || (saved && saved.language) || "",
    country: job.country || (saved && saved.country) || "",
    childCount: job.childCount || (job.pages || []).length,
    notes: job.notes || (saved && saved.notes) || [],
    pages: job.pages || (saved && saved.pages) || [],
    menuDiff: job.menuDiff || (saved && saved.menuDiff) || null,
    checks,
  };
  if ((saved && saved.reviewHalted) || job.reviewHalted) record.reviewHalted = true;
  return record;
}

function ratioLines(views, totalKey, rowKey) {
  return shownViews(views)
    .map((view) => {
      if (view.unread) return `${view.name} 확인 실패`;
      const rows = (view[rowKey] || []).length;
      const total = Number.isFinite(view[totalKey]) ? view[totalKey] : rows;
      return `${view.name} ${total}/${rows}`;
    })
    .join("\n");
}

function itemQuantityText(page, payload) {
  const kind = displayKind(page);
  if (payload && payload.status === 404) return "404";
  if (kind && kind !== "PLP") return "해당 없음";
  const hasPayload =
    payload && Object.prototype.hasOwnProperty.call(payload, "itemCount");
  const value = hasPayload ? payload.itemCount : page.itemCount;
  if (!Number.isFinite(value)) {
    if (hasPayload) return "확인 실패";
    return Number.isFinite(page.itemCount) ? String(page.itemCount) : "";
  }
  const skus =
    payload && Array.isArray(payload.itemSkus) ? payload.itemSkus : page.itemSkus;
  if (!Array.isArray(skus)) return String(value);
  const products = skus.map(skuProduct).filter(Boolean);
  const listedStopped = products.filter((item) => item.discontinued).length;
  const stopped = screenCount(payload, page, "discontinuedCount") ?? listedStopped;
  const active =
    screenCount(payload, page, "activeCount") ?? Math.max(0, value - listedStopped);
  const all =
    screenCount(payload, page, "activeCount") != null &&
    screenCount(payload, page, "discontinuedCount") != null
      ? screenCount(payload, page, "activeCount") +
        screenCount(payload, page, "discontinuedCount")
      : value;
  const parts = siblingParts(products, siblingTotal(payload, page));
  return [
    `Active - ${active + parts.active}(${active}/${parts.active})`,
    `Discontinued - ${stopped + parts.discontinued}(${stopped}/${parts.discontinued})`,
    `All - ${all + parts.all}(${all}/${parts.all})`,
  ].join("\n");
}

function languageText(record, payload) {
  if (payload && payload.status === 404) return "";
  const pageLanguage = payload && String(payload.language || "").trim();
  const rootLanguage = String((record && record.language) || "").trim();
  if (!pageLanguage || !rootLanguage) return "";
  return pageLanguage === rootLanguage
    ? `같음 ${pageLanguage}`
    : `다름 ${pageLanguage}`;
}

function areaText(kind, applies, payload) {
  if (payload && payload.status === 404) return "404";
  if (!kind) return "";
  return applies ? "" : "해당 없음";
}

function resultRows(record) {
  const rows = [[
    "단계",
    "메뉴",
    "주소",
    "상위",
    "유형",
    "아이템 수량 (item/sibling)",
    "언어",
    "UFN",
    "Dimension",
    "broken link",
    "broken image",
    "Thumbnail",
    "중복",
    "새창",
    "페이지 상태",
    "GNB 없음",
    "표시",
  ]];
  const checks = record.checks || {};
  for (const page of record.pages || []) {
    const main = isGnbHeader(page);
    const checking = main ? mainCheckNode(record) : page;
    const payload = checking.url ? checks[checking.url] : null;
    const kind = displayKind(checking);
    const listing = payload && payload.listing;
    const insightList = kind === "Insights" && checking.url && isInsightListing(checking.url);
    let thumb = "";
    let dup = "";
    if (payload && payload.status === 404 && insightList) {
      thumb = "404";
      dup = "404";
    } else if (insightList) {
      thumb = listing
        ? shownViews(listing.thumbnails)
            .map((view) => {
              if (view.unread) return `${view.name} 확인 실패`;
              const different = (view.different || []).length;
              const total = Number.isFinite(view.total) ? view.total : different;
              return `${view.name} ${total}/${different}`;
            })
            .join("\n")
        : "";
      const copies = listing ? listing.duplicates || [] : [];
      const total =
        listing && Number.isFinite(listing.contentTotal)
          ? listing.contentTotal
          : copies.length;
      dup = listing ? `전체 ${total}/${copies.length}` : "";
    } else if (kind === "PLP" || kind === "Insights") {
      thumb = "해당 없음";
      dup = "해당 없음";
    }
    rows.push([
      Number.isFinite(page.depth) ? page.depth : "",
      main ? "메인" : page.title || page.url || "항목",
      checking.url || "",
      page.parent || "",
      kind,
      itemQuantityText(checking, payload),
      languageText(record, payload),
      areaText(kind, kind === "PDP", payload),
      areaText(kind, kind === "PDP", payload),
      payload && payload.viewports
        ? ratioLines(payload.viewports, "linkTotal", "brokenLinks")
        : payload && payload.status === 404
          ? "404"
          : "",
      payload && payload.viewports
        ? ratioLines(payload.viewports, "imageTotal", "missingImages")
        : payload && payload.status === 404
          ? "404"
          : "",
      thumb,
      dup,
      page.blank ? (page.missing ? "404" : "새창") : "",
      payload && payload.status === 404 ? "404" : "",
      page.outsideGnb ? "예" : "",
      page.discontinued ? "Discontinued" : page.product ? "Active" : "",
    ]);
  }
  return rows;
}

function summaryRows(record) {
  return [
    ["항목", "값"],
    ["주소", record.url || ""],
    ["언어", record.language || ""],
    ["나라", record.country || ""],
    ["검사 시각", record.when || ""],
    ["하위 페이지 수", (record.pages || []).length],
    ["메모", (record.notes || []).join("\n")],
    ["검수 중단", record.reviewHalted ? "예" : "아니오"],
  ];
}

function menuRows(diff) {
  const rows = [["구분", "메뉴", "경로", "GNB", "FNB", "주소"]];
  if (!diff) return rows;
  for (const row of differentMenuRows(diff.sameLabel)) {
    rows.push([
      "같은 메뉴, 다른 주소",
      row.label || "",
      Array.isArray(row.path) ? row.path.join(" > ") : "",
      (row.gnb || []).join("\n"),
      (row.fnb || []).join("\n"),
      "",
    ]);
  }
  for (const row of diff.gnbOnly || []) {
    rows.push(["GNB에만", row.label || "", "", "", "", row.url || ""]);
  }
  for (const row of diff.fnbOnly || []) {
    rows.push(["FNB에만", row.label || "", "", "", "", row.url || ""]);
  }
  return rows;
}

function chunkText(text) {
  const size = 20000;
  const rows = [["부분"]];
  for (let index = 0; index < text.length; index += size) {
    rows.push([text.slice(index, index + size)]);
  }
  return rows;
}

function workbookFor(record) {
  return [
    { name: "요약", rows: summaryRows(record) },
    { name: "결과", rows: resultRows(record) },
    { name: "메뉴차이", rows: menuRows(record.menuDiff) },
    { name: "원본", rows: chunkText(JSON.stringify(record)) },
  ];
}

function excelFileName(record) {
  return SiteXlsx.fileName(record);
}

async function downloadAnalysis(record) {
  if (!globalThis.SiteXlsx) throw new Error("엑셀을 만들지 못했습니다.");
  const bytes = await SiteXlsx.writeWorkbook(workbookFor(record));
  const blob = new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = excelFileName(record);
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function plainValue(value, depth) {
  if (depth > 14) return null;
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") return value.slice(0, 200000);
  if (Array.isArray(value)) {
    return value.slice(0, 20000).map((item) => plainValue(item, depth + 1));
  }
  if (typeof value === "object") {
    const copy = Object.create(null);
    for (const key of Object.keys(value).slice(0, 400)) {
      if (key === "__proto__" || key === "constructor" || key === "prototype")
        continue;
      copy[key] = plainValue(value[key], depth + 1);
    }
    return copy;
  }
  return null;
}

function cleanPage(page) {
  const source = plainValue(page, 0) || {};
  const next = {
    url: String(source.url || ""),
    kind: String(source.kind || ""),
    depth: Number.isFinite(source.depth) ? source.depth : 1,
    parent: String(source.parent || ""),
    title: String(source.title || ""),
    group: String(source.group || ""),
    discontinued: Boolean(source.discontinued),
    product: Boolean(source.product),
    outsideGnb: Boolean(source.outsideGnb),
    id: String(source.id || ""),
    blank: Boolean(source.blank),
    missing: Boolean(source.missing),
  };
  if (Number.isFinite(source.itemCount)) next.itemCount = source.itemCount;
  if (Array.isArray(source.itemSkus)) next.itemSkus = source.itemSkus;
  if (Number.isFinite(source.siblingCount)) next.siblingCount = source.siblingCount;
  if (Number.isFinite(source.activeCount)) next.activeCount = source.activeCount;
  if (Number.isFinite(source.discontinuedCount)) {
    next.discontinuedCount = source.discontinuedCount;
  }
  return next;
}

function httpUrl(value) {
  try {
    const url = new URL(String(value || "").trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    return String(value || "").trim();
  } catch (_err) {
    return "";
  }
}

function acceptAnalysis(raw) {
  const source = plainValue(raw, 0);
  const url = httpUrl(source && source.url);
  if (!url) throw new Error("엑셀에서 검사 주소를 찾지 못했습니다.");
  const pages = Array.isArray(source.pages)
    ? source.pages.slice(0, 20000).map(cleanPage)
    : [];
  const checks =
    source.checks && typeof source.checks === "object" ? source.checks : {};
  const id = /^[a-z0-9]+$/.test(source.id || "") ? source.id : newAnalysisId();
  const record = {
    id,
    url,
    when:
      String(source.when || "").slice(0, 80) ||
      new Date().toLocaleString("ko-KR", { hour12: false }),
    language: String(source.language || "").slice(0, 80),
    country: String(source.country || "").slice(0, 80),
    childCount: pages.length,
    notes: Array.isArray(source.notes)
      ? source.notes.map((note) => String(note)).slice(0, 20)
      : [],
    pages,
    menuDiff:
      source.menuDiff && typeof source.menuDiff === "object"
        ? source.menuDiff
        : null,
    checks,
  };
  if (source.reviewHalted) record.reviewHalted = true;
  return record;
}

function sheetText(rows) {
  if (!rows || !rows.length) return "";
  const start = String(rows[0][0] || "") === "부분" ? 1 : 0;
  return rows
    .slice(start)
    .map((row) => String((row && row[0]) || ""))
    .join("");
}

function analysisFromBook(book) {
  const text = sheetText(book && book.sheets && book.sheets["원본"]);
  if (text.trim()) {
    try {
      return acceptAnalysis(JSON.parse(text));
    } catch (error) {
      if (error && error.message && error.message.startsWith("엑셀에서")) throw error;
      throw new Error("엑셀의 검수 원본을 읽지 못했습니다.");
    }
  }
  const table = book && book.sheets && book.sheets["결과"];
  if (!table || !table.length) {
    throw new Error("하위전체 검수 결과가 없는 파일입니다.");
  }
  const header = table[0] || [];
  const map = new Map();
  header.forEach((name, index) => map.set(String(name || "").trim(), index));
  const summary = (book.sheets && book.sheets["요약"]) || [];
  const values = {};
  for (const row of summary.slice(1)) {
    if (row && row[0]) values[String(row[0])] = row[1] || "";
  }
  const pick = (row, name) => {
    const index = map.get(name);
    if (index === undefined || row[index] === undefined || row[index] === null) {
      return "";
    }
    return String(row[index]);
  };
  const pages = [];
  for (const row of table.slice(1)) {
    const title = pick(row, "메뉴");
    const url = httpUrl(pick(row, "주소"));
    if (!title && !url) continue;
    const depth = Number(pick(row, "단계"));
    const windowMark = pick(row, "새창");
    const state = pick(row, "표시");
    pages.push({
      url,
      title: title === "메인" ? "GNB" : title,
      kind: pick(row, "유형"),
      parent: pick(row, "상위"),
      depth: Number.isFinite(depth) && depth > 0 ? depth : 1,
      group: title === "메인" ? "GNB" : "",
      id: title === "메인" ? "group:GNB" : "",
      outsideGnb: pick(row, "GNB 없음") === "예",
      blank: windowMark === "새창" || windowMark === "404",
      missing: windowMark === "404" || pick(row, "페이지 상태") === "404",
      discontinued: state === "Discontinued",
      product: state === "Active" || state === "Discontinued",
    });
  }
  return acceptAnalysis({
    url: values["주소"] || (pages.find((page) => page.url) || {}).url || "",
    language: values["언어"] || "",
    country: values["나라"] || "",
    when: values["검사 시각"] || "",
    notes: values["메모"] ? String(values["메모"]).split("\n") : [],
    reviewHalted: values["검수 중단"] === "예",
    pages,
    checks: {},
    menuDiff: null,
  });
}

function storeImported(record) {
  const key = normalizeUrl(record.url);
  const items = [
    record,
    ...loadAnalyses().filter((item) => normalizeUrl(item.url) !== key),
  ];
  writeAnalyses(items);
  if (!loadAnalyses().some((item) => item.id === record.id)) {
    throw new Error(
      "이 브라우저에 결과를 저장하지 못했습니다. 최근 검사를 지운 뒤 다시 올려 주세요.",
    );
  }
  loadRecent();
}

async function importExcelFile(file) {
  if (!file) return;
  if (!globalThis.SiteXlsx) throw new Error("엑셀을 열 수 없습니다.");
  if (file.size > EXCEL_LIMIT) throw new Error("엑셀은 20MB 이하만 올릴 수 있습니다.");
  const name = String(file.name || "").toLowerCase();
  if (name && !name.endsWith(".xlsx")) throw new Error("xlsx 파일만 올릴 수 있습니다.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const record = analysisFromBook(await SiteXlsx.readWorkbook(bytes));
  storeImported(record);
  window.location.assign(`/lists/saved/${record.id}`);
}

function removeAnalysis(id) {
  writeAnalyses(loadAnalyses().filter((item) => item.id !== id));
  loadRecent();
}

function loadRecent() {
  recent.replaceChildren();
  const items = loadAnalyses();
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "아직 분석이 없습니다.";
    recent.append(li);
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "link";
    const host = document.createElement("span");
    host.textContent = item.url;
    const meta = document.createElement("span");
    const outcome = item.childCount ? `하위 ${item.childCount}` : "하위 없음";
    const place = [item.language, item.country].filter(Boolean).join(" · ");
    const review = reviewSnapshot(item);
    const left = Math.max(review.total - review.done, 0);
    const reviewLabel = !review.total
      ? ""
      : item.reviewHalted
        ? `검수 중단 · 남은 검수 ${left}`
        : left
          ? `남은 검수 ${left}`
          : "검수 완료";
    meta.textContent = [item.when, place, outcome, reviewLabel]
      .filter(Boolean)
      .join(" · ");
    button.append(host, meta);
    button.addEventListener("click", () => {
      window.location.assign(`/lists/saved/${item.id}`);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-btn";
    remove.textContent = "삭제";
    remove.addEventListener("click", () => {
      removeAnalysis(item.id);
      if (window.location.pathname === `/lists/saved/${item.id}`)
        window.location.assign("/all");
    });
    const excel = document.createElement("button");
    excel.type = "button";
    excel.className = "text-btn";
    excel.textContent = "엑셀";
    excel.addEventListener("click", () => {
      downloadAnalysis(item).catch((error) => {
        showExcelNote((error && error.message) || "엑셀을 만들지 못했습니다.");
      });
    });
    li.append(button, excel, remove);
    recent.append(li);
  }
}

function saveRecent(job) {
  const when = new Date().toLocaleString("ko-KR", { hour12: false });
  const record = {
    id: job.id,
    url: job.url,
    when,
    language: job.language || "",
    country: job.country || "",
    childCount: job.childCount || (job.pages || []).length,
    notes: job.notes || [],
    pages: job.pages || [],
    menuDiff: job.menuDiff || null,
    checks: mergedChecks(
      Object.assign(
        {},
        (
          loadAnalyses().find(
            (item) => normalizeUrl(item.url) === normalizeUrl(job.url || ""),
          ) || {}
        ).checks || {},
        job.checks || {},
      ),
    ),
  };
  const key = normalizeUrl(record.url);
  const items = [
    record,
    ...loadAnalyses().filter((item) => normalizeUrl(item.url) !== key),
  ];
  writeAnalyses(items);
  loadRecent();
}

let reviewAfterCollect = false;

async function poll(id) {
  const response = await fetch(`/api/audits/${id}`);
  if (!response.ok) {
    showListError("검사를 찾지 못했습니다.");
    setBusy(false);
    return;
  }
  const job = await response.json();
  if (job.url) showListPage(job.url);
  if (job.status === "running") {
    reviewAfterCollect = true;
    showRunning(job.progress);
    window.setTimeout(() => poll(id), 400);
    return;
  }
  setBusy(false);
  const beginReview = reviewAfterCollect;
  reviewAfterCollect = false;
  if (job.status === "error") {
    showListError(job.message);
    return;
  }
  renderList(job);
  saveRecent(job);
  if (beginReview && !reviewWasHalted(job)) startAssetChecks(pagesWithMain(job));
}

function compareSide(title, urls, checks) {
  const line = document.createElement("span");
  line.className = "compare-side";
  if (!urls || !urls.length) {
    line.textContent = `${title} · 링크 없음`;
    return line;
  }
  line.append(`${title} · `);
  urls.forEach((url, index) => {
    if (index) line.append(document.createTextNode(", "));
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = url;
    line.append(link);
    const marks = blankMarks(url, checks);
    if (marks) line.append(marks);
  });
  return line;
}

function collapsibleCard(title, count, body, open) {
  const section = document.createElement("section");
  section.className = "card";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "card-toggle";
  button.setAttribute("aria-expanded", open ? "true" : "false");
  button.setAttribute("aria-label", open ? `${title} 접기` : `${title} 펼치기`);
  const heading = document.createElement("span");
  heading.className = "card-toggle-title";
  heading.textContent = title;
  const meta = document.createElement("span");
  meta.className = "caption";
  const state = document.createElement("span");
  state.textContent = open ? "접기" : "펼치기";
  meta.append(`${count}개 · `, state);
  button.append(heading, meta);
  body.hidden = !open;
  button.addEventListener("click", () => {
    const expanded = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", expanded ? "false" : "true");
    button.setAttribute(
      "aria-label",
      expanded ? `${title} 펼치기` : `${title} 접기`,
    );
    body.hidden = expanded;
    state.textContent = expanded ? "펼치기" : "접기";
  });
  section.append(button, body);
  return section;
}

function urlsOnlyOn(left, right) {
  const other = new Set(
    (right || []).map((url) => normalizeUrl(url).toLowerCase()),
  );
  const seen = new Set();
  const kept = [];
  for (const url of left || []) {
    const key = normalizeUrl(url).toLowerCase();
    if (!key || other.has(key) || seen.has(key)) continue;
    seen.add(key);
    kept.push(url);
  }
  return kept;
}

function differentMenuRows(rows) {
  const kept = [];
  for (const row of rows || []) {
    const gnb = urlsOnlyOn(row.gnb, row.fnb);
    const fnb = urlsOnlyOn(row.fnb, row.gnb);
    if (!gnb.length || !fnb.length) continue;
    kept.push({ ...row, gnb, fnb });
  }
  return kept;
}

function fillSameLinks(list, rows, checks) {
  list.replaceChildren();
  if (!rows.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "이름은 같고 주소만 다른 메뉴가 없습니다.";
    list.append(item);
    return;
  }
  for (const row of rows) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.className = "compare-name";
    name.textContent =
      Array.isArray(row.path) && row.path.length
        ? row.path.join(" > ")
        : row.label;
    item.append(
      name,
      compareSide("GNB", row.gnb, checks),
      compareSide("FNB", row.fnb, checks),
    );
    list.append(item);
  }
}

function paintMenuDiff(container, payload) {
  const sameRows = differentMenuRows(payload.sameLabel);
  const gnbRows = payload.gnbOnly || [];
  const fnbRows = payload.fnbOnly || [];
  const sameList = document.createElement("ul");
  sameList.className = "compare-list";
  const checks = payload.checks || {};
  fillSameLinks(sameList, sameRows, checks);
  const gnbList = document.createElement("ul");
  gnbList.className = "compare-list";
  fillCompareLinks(gnbList, gnbRows, "GNB에만 있는 링크가 없습니다.", checks);
  const fnbList = document.createElement("ul");
  fnbList.className = "compare-list";
  fillCompareLinks(fnbList, fnbRows, "FNB에만 있는 링크가 없습니다.", checks);
  const grid = document.createElement("div");
  grid.className = "compare-grid";
  grid.append(
    collapsibleCard("GNB에만 있는 링크", gnbRows.length, gnbList, false),
    collapsibleCard("FNB에만 있는 링크", fnbRows.length, fnbList, false),
  );
  container.replaceChildren(
    collapsibleCard("같은 메뉴, 다른 주소", sameRows.length, sameList, true),
    grid,
  );
}

function fillCompareLinks(list, rows, emptyText, checks) {
  list.replaceChildren();
  if (!rows.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = emptyText;
    list.append(item);
    return;
  }
  for (const row of rows) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.className = "compare-name";
    name.textContent = row.label || row.url;
    const link = document.createElement("a");
    link.className = "compare-side";
    link.href = row.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = row.url;
    item.append(name, link);
    const marks = blankMarks(row.url, checks);
    if (marks) item.append(marks);
    list.append(item);
  }
}

function renderCompare(payload) {
  const place = document.querySelector("#compare-place");
  const note = document.querySelector("#compare-status");
  const result = document.querySelector("#compare-result");
  const sameRows = differentMenuRows(payload.sameLabel);
  const gnbRows = payload.gnbOnly || [];
  const fnbRows = payload.fnbOnly || [];
  const where = [payload.language, payload.country].filter(Boolean).join(" · ");
  place.textContent = where ? `${payload.url} · ${where}` : payload.url;
  note.textContent = payload.message || "같은 주소는 빼 두었습니다.";
  if (
    payload.message &&
    !sameRows.length &&
    !gnbRows.length &&
    !fnbRows.length &&
    !(payload.shared || 0)
  ) {
    result.hidden = true;
    return;
  }
  result.hidden = false;
  const board = document.querySelector("#compare-summary");
  board.replaceChildren();
  board.append(
    kpiCard("같은 링크", payload.shared || 0, "purple", {
      hint: "양쪽 주소가 같음",
    }),
    kpiCard("이름만 같음", sameRows.length, "amber", { hint: "주소가 다름" }),
    kpiCard("GNB만", gnbRows.length, "coral", { hint: "FNB에 없음" }),
    kpiCard("FNB만", fnbRows.length, "green", { hint: "GNB에 없음" }),
  );
  paintMenuDiff(document.querySelector("#compare-blocks"), payload);
}

function problemList(title, rows, empty) {
  const block = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = `${title} ${rows.length}`;
  const list = document.createElement("ul");
  list.className = "compare-list";
  if (!rows.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = empty;
    list.append(item);
  } else {
    for (const row of rows) {
      const item = document.createElement("li");
      if (typeof row === "string") {
        item.textContent = row;
      } else if (!row.url) {
        item.textContent = row.text || row.title || "이미지";
      } else {
        const link = document.createElement("a");
        link.href = row.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = row.url;
        item.append(link, document.createTextNode(` (${row.detail})`));
      }
      list.append(item);
    }
  }
  block.append(heading, list);
  return block;
}

function pageCheckUrl(value) {
  const text = (value || "").trim();
  if (!text || /^[a-z][a-z0-9+.-]*:/i.test(text)) return text;
  return `https://${text.replace(/^\/+/, "")}`;
}

function selectedKind() {
  const picked = document.querySelector("input[name='page-kind']:checked");
  return picked ? picked.value : "일반";
}

function comparePageUrl() {
  const input = document.querySelector("#compare-url");
  if (!input || selectedKind() !== "PDP") return "";
  return pageCheckUrl(input.value);
}

function syncCompareField() {
  const field = document.querySelector("#compare-url-field");
  if (field) field.hidden = selectedKind() !== "PDP";
}

function paintOneLanguage(cell, language) {
  cell.classList.remove("is-na");
  const name = String(language || "").trim();
  if (!name) {
    cell.textContent = "";
    return;
  }
  const mark = document.createElement("span");
  mark.className = "mark-o";
  mark.textContent = "O";
  mark.setAttribute("aria-label", `언어 같음 ${name}`);
  cell.replaceChildren(mark);
}

function renderPageCheck(payload) {
  const place = document.querySelector("#one-result-place");
  const result = document.querySelector("#one-result-body");
  const kind = payload.kind || "일반";
  if (place) {
    place.textContent = [payload.language, payload.country]
      .filter(Boolean)
      .join(" · ");
  }
  onePayload = payload;
  paintOneSaved();
  result.replaceChildren();

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "page-table";
  const head = document.createElement("thead");
  const titles = document.createElement("tr");
  const body = document.createElement("tbody");
  const line = document.createElement("tr");
  const name = document.createElement("td");
  name.className = "menu-name";
  const label = document.createElement("span");
  label.className = "menu-label";
  label.textContent = payload.url || "";
  name.append(label);
  const openLink = menuOpenLink(payload.url, payload.url || "페이지", false);
  if (openLink) name.append(openLink);

  const itemCell = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = `badge ${kindClass(kind)}`;
  badge.textContent = kind;
  itemCell.append(badge);

  const countCell = document.createElement("td");
  countCell.className = "item-count";
  const langCell = document.createElement("td");
  langCell.className = "check-area";
  const ufnCell = document.createElement("td");
  ufnCell.className = "check-area";
  const dimensionCell = document.createElement("td");
  dimensionCell.className = "check-area";
  const linkCell = document.createElement("td");
  linkCell.className = "asset-count";
  const imageCell = document.createElement("td");
  imageCell.className = "asset-count";
  const thumbCell = document.createElement("td");
  thumbCell.className = "asset-count";
  const dupCell = document.createElement("td");
  dupCell.className = "asset-count";
  const listing = kind === "Insights" && isInsightListing(payload.url || "");
  const slot = {
    linkCell,
    imageCell,
    thumbCell,
    dupCell,
    countCell,
    langCell,
    itemCount: null,
    itemSkus: null,
    siblingCount: null,
    activeCount: null,
    discontinuedCount: null,
    listing,
    insight: kind === "Insights",
    plp: kind === "PLP",
  };
  markCheckArea(langCell, true);
  if (kind === "PDP") {
    markCheckArea(ufnCell, true);
    markCheckArea(dimensionCell, true);
  }
  paintAssetResult(slot, payload);
  paintOneLanguage(langCell, payload.language);

  const actionCell = document.createElement("td");
  actionCell.className = "row-action";
  const again = document.createElement("button");
  again.type = "button";
  again.className = "text-btn row-analyze";
  again.textContent = "분석하기";
  again.addEventListener("click", () =>
    runPageCheck(payload.url || urlInput.value.trim()),
  );
  actionCell.append(again);
  const columns = [
    ["메뉴", name],
    ["아이템", itemCell],
  ];
  if (kind === "PLP")
    columns.push([
      "아이템 수량 (item/sibling)",
      countCell,
    ]);
  columns.push(["언어", langCell]);
  if (kind === "PDP") {
    columns.push(["UFN", ufnCell], ["Dimension", dimensionCell]);
  }
  columns.push(["broken link", linkCell], ["broken image", imageCell]);
  if (listing) columns.push(["Thumbnail", thumbCell], ["중복", dupCell]);
  columns.push(["분석", actionCell]);
  for (const [text, cell] of columns) {
    const title = document.createElement("th");
    title.textContent = text;
    titles.append(title);
    line.append(cell);
  }
  head.append(titles);
  body.append(line);
  table.append(head, body);
  wrap.append(table);
  result.append(wrap);
  paintEnergySheet(result, payload);
  paintAllSpec(result, payload);
}

function paintEnergySheet(result, payload) {
  const sheet = payload && payload.energySheet;
  if (!sheet || (!sheet.source && !sheet.compare)) return;
  const block = document.createElement("section");
  block.className = "all-spec energy-sheet";
  const heading = document.createElement("h3");
  heading.textContent = "Energy Sheet";
  block.append(heading);
  const table = document.createElement("table");
  table.className = "all-spec-table is-compare";
  const head = document.createElement("thead");
  const titles = document.createElement("tr");
  for (const text of ["항목", "검수 페이지", "비교 페이지"]) {
    const title = document.createElement("th");
    title.scope = "col";
    title.textContent = text;
    titles.append(title);
  }
  head.append(titles);
  const body = document.createElement("tbody");
  const line = document.createElement("tr");
  const name = document.createElement("th");
  name.scope = "row";
  name.textContent = "Energy Grade";
  const source = document.createElement("td");
  source.dataset.label = "검수 페이지";
  source.textContent = sheet.source || "없음";
  const other = document.createElement("td");
  other.dataset.label = "비교 페이지";
  other.textContent = sheet.compare || "없음";
  if (!sheet.same) {
    if (!sheet.source) source.className = "is-empty";
    other.className = sheet.compare ? "is-diff" : "is-empty";
  }
  line.append(name, source, other);
  body.append(line);
  table.append(head, body);
  block.append(table);
  result.append(block);
}

function paintAllSpec(result, payload) {
  const spec = payload && payload.allSpec;
  const compare = payload && payload.specCompare;
  if (!spec && !compare) return;
  const block = document.createElement("section");
  block.className = "all-spec";
  const heading = document.createElement("h3");
  heading.textContent = "All Spec";
  block.append(heading);
  if (compare && compare.url) {
    const note = document.createElement("p");
    note.className = "spec-note";
    note.append(document.createTextNode("비교 주소 "));
    const link = document.createElement("a");
    link.href = compare.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = compare.url;
    note.append(link);
    block.append(note);
  }
  const compared = Boolean(
    compare && compare.ok && compare.sourceFound && compare.compareFound,
  );
  let message = "";
  if (compare && !compare.ok) message = compare.message || "비교 주소를 읽지 못했습니다.";
  else if (compare && !compare.sourceFound && !compare.compareFound)
    message = "All Spec 영역과 비교 사이트의 스펙 영역을 찾지 못했습니다.";
  else if (compare && !compare.sourceFound) message = "All Spec 영역을 찾지 못했습니다.";
  else if (compare && !compare.compareFound)
    message = "비교 사이트의 스펙 영역을 찾지 못했습니다.";
  if (message) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = message;
    block.append(empty);
  }
  const sections = compared
    ? compare.sections || []
    : (spec && spec.sections) || [];
  if (!sections.length && !(spec && spec.found) && !message) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "All Spec 영역을 찾지 못했습니다.";
    block.append(empty);
  }
  for (const section of sections) {
    const group = document.createElement("section");
    group.className = "all-spec-group";
    if (section.title) {
      const title = document.createElement("h4");
      title.textContent = section.title;
      group.append(title);
    }
    if (compared) paintComparedSpec(group, section.rows || []);
    else paintSpecSheet(group, section.rows || []);
    block.append(group);
  }
  result.append(block);
}

function paintSpecSheet(group, rows) {
  const table = document.createElement("table");
  table.className = "all-spec-table";
  const body = document.createElement("tbody");
  for (let index = 0; index < rows.length; index += 2) {
    const line = document.createElement("tr");
    appendSpecPair(line, rows[index]);
    appendSpecPair(line, rows[index + 1]);
    body.append(line);
  }
  table.append(body);
  group.append(table);
}

function appendSpecPair(line, row) {
  const name = document.createElement("th");
  name.scope = "row";
  name.textContent = row ? row.name || "" : "";
  const value = document.createElement("td");
  value.textContent = row ? row.value || "" : "";
  line.append(name, value);
}

function paintComparedSpec(group, rows) {
  const table = document.createElement("table");
  table.className = "all-spec-table is-compare";
  const head = document.createElement("thead");
  const titles = document.createElement("tr");
  for (const text of ["항목", "검수 페이지", "비교 페이지"]) {
    const title = document.createElement("th");
    title.scope = "col";
    title.textContent = text;
    titles.append(title);
  }
  head.append(titles);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const line = document.createElement("tr");
    const name = document.createElement("th");
    name.scope = "row";
    name.textContent = row.name || "";
    const source = document.createElement("td");
    source.dataset.label = "검수 페이지";
    source.textContent = row.source ? String(row.source) : "없음";
    const other = document.createElement("td");
    other.dataset.label = "비교 페이지";
    other.textContent = row.compare ? String(row.compare) : "없음";
    if (!row.same) {
      source.className = row.source ? "" : "is-empty";
      other.className = "is-diff";
    }
    line.append(name, source, other);
    body.append(line);
  }
  table.append(head, body);
  group.append(table);
}

async function runPageCheck(url) {
  if (oneCheck) oneCheck.controller.abort();
  const controller = new AbortController();
  const kind = selectedKind();
  oneCheck = { url, kind, controller };
  formStatus.hidden = true;
  const result = document.querySelector("#one-result-body");
  const place = document.querySelector("#one-result-place");
  if (place) place.textContent = "";
  result.replaceChildren();
  const waiting = document.createElement("p");
  waiting.className = "empty";
  waiting.textContent = "검수 결과가 여기에 표시됩니다.";
  result.append(waiting);
  onePayload = null;
  paintOneSaved();
  setBusy(true);
  paintOneCheck();
  try {
    const body = { url, kind };
    const compareUrl = comparePageUrl();
    if (compareUrl) body.compareUrl = compareUrl;
    const response = await fetch("/api/page-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (oneCheck && oneCheck.controller === controller) oneCheck = null;
    syncPageLoading();
    if (!response.ok) {
      setBusy(false);
      showFormError(payload.message || "이 주소는 검사할 수 없습니다.");
      return;
    }
    urlInput.value = "";
    urlInput.classList.remove("bad");
    setBusy(false);
    renderPageCheck(payload);
  } catch (error) {
    if (oneCheck && oneCheck.controller === controller) oneCheck = null;
    setBusy(false);
    syncPageLoading();
    if (error && error.name === "AbortError") {
      paintAssetHalt();
      return;
    }
    showFormError("검사를 끝내지 못했습니다.");
  }
}

async function runCompare(url) {
  formStatus.hidden = true;
  const note = document.querySelector("#compare-status");
  document.querySelector("#compare-result").hidden = true;
  note.textContent = "GNB와 FNB를 읽는 중입니다.";
  setBusy(true);
  const response = await fetch("/api/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const payload = await response.json().catch(() => ({}));
  setBusy(false);
  if (!response.ok) {
    note.textContent = "";
    showFormError(payload.message || "이 주소는 검사할 수 없습니다.");
    return;
  }
  renderCompare(payload);
}

urlInput.addEventListener("input", () => {
  urlInput.classList.remove("bad");
  if (
    start.textContent !== "목록 만드는 중" &&
    start.textContent !== "비교 중" &&
    start.textContent !== "검수 중"
  )
    setBusy(false);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;
  if (onComparePage()) {
    await runCompare(url);
    return;
  }
  if (onOnePage()) {
    const pageUrl = pageCheckUrl(url);
    urlInput.value = pageUrl;
    await runPageCheck(pageUrl);
    return;
  }
  const existing = findAnalysis(url);
  if (existing) {
    const again = window.confirm(
      "이 주소는 이미 분석되어 있습니다. 다시 분석할까요?",
    );
    if (!again) {
      window.location.assign(`/lists/saved/${existing.id}`);
      return;
    }
  }
  formStatus.hidden = true;
  setBusy(true);
  const response = await fetch("/api/audits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    showFormError(payload.message || "이 주소는 검사할 수 없습니다.");
    setBusy(false);
    return;
  }
  sessionStorage.setItem(ACTIVE, payload.id);
  window.location.assign(`/lists/${payload.id}`);
});

const savedList = window.location.pathname.match(
  /^\/lists\/saved\/([a-z0-9]+)$/,
);
const currentList = window.location.pathname.match(/^\/lists\/([a-f0-9]+)$/);
if (savedList) {
  const saved = loadAnalyses().find((item) => item.id === savedList[1]);
  if (!saved) showListError("저장된 분석을 찾지 못했습니다.");
  else renderList(saved);
  setBusy(false);
} else if (currentList) {
  showListPage("");
  setBusy(true);
  showRunning({
    step: "주소를 확인하는 중",
    url: "",
    done: 0,
    waiting: 0,
  });
  poll(currentList[1]);
} else {
  openPage();
  setBusy(false);
}
loadRecent();
paintOneSaved();
document.querySelector("#one-save").addEventListener("click", () => {
  if (!onePayload) return;
  saveOneCheck(onePayload);
});

const oneClear = document.querySelector("#one-clear");
if (oneClear) {
  oneClear.addEventListener("click", () => {
    if (!loadOneChecks().length) return;
    const ok = window.confirm(
      "이 브라우저에 저장한 검수 내역을 모두 삭제할까요?",
    );
    if (!ok) return;
    writeOneChecks([]);
    paintOneSaved();
  });
}

if (deleteAnalysis) {
  deleteAnalysis.addEventListener("click", () => {
    const id = deleteAnalysis.dataset.id;
    if (!id) return;
    removeAnalysis(id);
    window.location.assign("/all");
  });
}

if (excelDownload) {
  excelDownload.addEventListener("click", () => {
    if (!listedJob) return;
    downloadAnalysis(analysisFromJob(listedJob)).catch((error) => {
      showExcelNote((error && error.message) || "엑셀을 만들지 못했습니다.");
    });
  });
}

const excelUpload = document.querySelector("#excel-upload");
const excelFile = document.querySelector("#excel-file");
if (excelUpload && excelFile) {
  excelUpload.addEventListener("click", () => excelFile.click());
  excelFile.addEventListener("change", () => {
    const file = excelFile.files && excelFile.files[0];
    excelFile.value = "";
    if (!file) return;
    showExcelNote("");
    importExcelFile(file).catch((error) => {
      showExcelNote((error && error.message) || "엑셀을 올리지 못했습니다.");
    });
  });
}

document.querySelectorAll("input[name='page-kind']").forEach((input) => {
  input.addEventListener("change", syncCompareField);
});
syncCompareField();

document.querySelector("#nav-toggle").addEventListener("click", () => {
  document.body.classList.toggle("nav-open");
});

document.querySelector("#backdrop").addEventListener("click", () => {
  document.body.classList.remove("nav-open");
});

document.querySelector("#link-modal").addEventListener("click", (event) => {
  if (event.target.closest("[data-close]")) closeLinkModal();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeLinkModal();
});

const ACTIVE = "site-audit-active";
const runningBar = document.querySelector("#running");
const runningTitle = document.querySelector("#running-title");
const runningDetail = document.querySelector("#running-detail");
const runningOpen = document.querySelector("#running-open");
const runningStop = document.querySelector("#running-stop");
const runningMeter = document.querySelector("#running-meter");
const runningFill = document.querySelector("#running-fill");
let followId = sessionStorage.getItem(ACTIVE) || "";
let finished = false;
let barReviewId = "";
let oneCheck = null;

function syncPageLoading() {
  const layer = document.querySelector("#page-loading");
  if (!layer) return;
  const wasHidden = layer.hidden;
  layer.hidden = !oneCheck;
  document.body.classList.toggle("page-loading-open", Boolean(oneCheck));
  const app = document.querySelector(".app");
  if (app) app.inert = Boolean(oneCheck);
  const detail = document.querySelector("#page-loading-detail");
  if (!oneCheck || !detail) return;
  detail.textContent = `${oneCheck.url} · ${oneCheck.kind}`;
  if (wasHidden) document.querySelector("#page-loading-stop")?.focus();
}

function paintOneCheck() {
  if (!oneCheck) return;
  runningBar.hidden = false;
  runningTitle.textContent = "검수 중";
  runningDetail.textContent = `${oneCheck.url} · ${oneCheck.kind}`;
  runningOpen.hidden = true;
  runningStop.hidden = false;
  runningStop.disabled = false;
  runningStop.textContent = "중지";
  runningMeter.hidden = true;
  start.disabled = true;
  syncPageLoading();
}

function reviewWasHalted(job) {
  if (!job || !job.id) return false;
  const saved = loadAnalyses().find((item) => item.id === job.id);
  return Boolean(saved && saved.reviewHalted);
}

function markReviewHalted(id) {
  if (!id) return;
  const items = loadAnalyses();
  const item = items.find((entry) => entry.id === id);
  if (!item) return;
  item.reviewHalted = true;
  writeAnalyses(items);
}

function clearReviewHalt(id) {
  if (!id) return;
  const items = loadAnalyses();
  const item = items.find((entry) => entry.id === id);
  if (!item || !item.reviewHalted) return;
  delete item.reviewHalted;
  writeAnalyses(items);
}

function remember(id) {
  followId = id || "";
  if (followId) sessionStorage.setItem(ACTIVE, followId);
}

function paintAssetHalt() {
  runningBar.hidden = false;
  runningTitle.textContent = "검수를 중단했습니다";
  runningDetail.textContent = "남은 페이지는 검사하지 않습니다.";
  runningOpen.hidden = true;
  runningStop.hidden = false;
  runningStop.disabled = true;
  runningStop.textContent = "중지";
  runningMeter.hidden = true;
}

function paintLiveReview() {
  const job = listedJob || lastFinishedJob || {};
  runningBar.hidden = false;
  runningTitle.textContent = "검수 중";
  runningDetail.textContent = `${job.url || ""} · ${assetLabel} ${assetDone}/${assetTotal}`;
  runningMeter.hidden = false;
  runningFill.style.width = `${Math.min(100, Math.round((assetDone / Math.max(assetTotal, 1)) * 100))}%`;
  if (job.id) {
    runningOpen.hidden = false;
    runningOpen.href = job.when ? `/lists/saved/${job.id}` : `/lists/${job.id}`;
    runningOpen.textContent = "결과 보기";
  }
  runningStop.hidden = false;
  runningStop.disabled = false;
  runningStop.textContent = "중지";
  barReviewId = (job && job.id) || barReviewId;
}

function paintIdle() {
  if (assetHalted) {
    paintAssetHalt();
    return;
  }
  if (assetActive && assetTotal) {
    paintLiveReview();
    return;
  }
  runningBar.hidden = false;
  runningTitle.textContent = "진행 중인 수집 없음";
  runningDetail.textContent =
    "수집이 시작되면 주소와 진행이 여기에 표시됩니다.";
  runningOpen.hidden = true;
  runningStop.hidden = false;
  runningStop.disabled = true;
  runningStop.textContent = "중지";
  runningMeter.hidden = true;
  if (start.textContent !== "목록 만드는 중")
    start.disabled = urlInput.value.trim() === "";
}

function paintRunning(job) {
  const progress = job.progress || {};
  const stopping = Boolean(job.stopping);
  const done = Number.isFinite(progress.done) ? progress.done : 0;
  const waiting = Number.isFinite(progress.waiting) ? progress.waiting : 0;
  const known = Math.max(done + waiting, 1);
  runningBar.hidden = false;
  runningTitle.textContent = stopping ? "중지하는 중" : "수집 중";
  runningDetail.textContent = `${job.url || progress.url || ""} · ${progress.step || "주소를 확인하는 중"} · 확인 ${done} · 대기 ${waiting}`;
  runningOpen.hidden = window.location.pathname === `/lists/${job.id}`;
  runningOpen.href = `/lists/${job.id}`;
  runningOpen.textContent = "목록 화면";
  runningStop.hidden = false;
  runningStop.disabled = stopping;
  runningStop.textContent = stopping ? "중지하는 중" : "중지";
  runningMeter.hidden = false;
  runningFill.style.width = `${Math.min(100, Math.round((done / known) * 100))}%`;
  start.disabled = true;
  barReviewId = "";
}

function reviewSnapshot(job) {
  const urls = [];
  const seen = new Set();
  for (const page of pagesWithMain(job || {})) {
    if (!assetPage(page) || !page.url || seen.has(page.url)) continue;
    seen.add(page.url);
    urls.push(page.url);
  }
  const savedItem = loadAnalyses().find(
    (item) => item.id && job && item.id === job.id,
  );
  const saved = (savedItem && savedItem.checks) || {};
  let done = 0;
  for (const url of urls) {
    if (storedChecks.has(url) || saved[url]) done += 1;
  }
  return { done, total: urls.length };
}

function paintFinished(job) {
  lastFinishedJob = job;
  runningBar.hidden = false;
  const review = reviewSnapshot(job);
  const reviewOpen =
    job.status === "done" &&
    !assetHalted &&
    !reviewWasHalted(job) &&
    assetActive &&
    review.done < review.total;
  if (reviewOpen) {
    const done = assetActive ? assetDone : review.done;
    const total = assetActive ? assetTotal : review.total;
    const label = assetActive ? assetLabel : "페이지";
    runningTitle.textContent = "검수 중";
    runningDetail.textContent = `${job.url || ""} · ${label} ${done}/${total}`;
    runningMeter.hidden = false;
    runningFill.style.width = `${Math.min(100, Math.round((done / Math.max(total, 1)) * 100))}%`;
  } else if (assetHalted) {
    runningTitle.textContent = "검수를 중단했습니다";
    runningDetail.textContent = `${job.url || ""} · 남은 페이지는 검사하지 않습니다.`;
    runningMeter.hidden = true;
  } else if (job.status === "stopped") {
    runningTitle.textContent = "수집을 중지했습니다";
  } else if (job.status === "error") {
    runningTitle.textContent = "수집을 끝내지 못했습니다";
  } else {
    runningTitle.textContent = "수집이 끝났습니다";
  }
  if (!reviewOpen && !assetHalted) {
    runningDetail.textContent =
      job.status === "error"
        ? `${job.url || ""} · ${job.message || ""}`
        : `${job.url || ""} · 하위 ${job.childCount || 0}`;
    runningMeter.hidden = true;
  }
  runningOpen.hidden = false;
  runningOpen.href = `/lists/${job.id}`;
  runningOpen.textContent = "결과 보기";
  runningStop.hidden = false;
  runningStop.disabled = !reviewOpen;
  runningStop.textContent = "중지";
  barReviewId = reviewOpen ? job.id || "" : "";
  if (!reviewOpen) runningMeter.hidden = true;
  if (start.textContent !== "목록 만드는 중")
    start.disabled = urlInput.value.trim() === "";
}

async function refreshRunning() {
  if (oneCheck) {
    paintOneCheck();
    return;
  }
  try {
    const response = await fetch("/api/audits/current");
    if (!response.ok) return;
    const job = await response.json();
    if (job.status === "running") {
      finished = false;
      remember(job.id);
      paintRunning(job);
      return;
    }
    const id =
      followId ||
      (window.location.pathname.match(/^\/lists\/([a-f0-9]+)$/) || [])[1] ||
      "";
    if (!id) {
      finished = false;
      paintIdle();
      return;
    }
    if (finished && id === followId) {
      if (assetActive && assetTotal) paintLiveReview();
      return;
    }
    const doneResponse = await fetch(`/api/audits/${id}`);
    if (!doneResponse.ok) {
      sessionStorage.removeItem(ACTIVE);
      followId = "";
      finished = false;
      paintIdle();
      return;
    }
    const doneJob = await doneResponse.json();
    if (doneJob.status === "running") {
      remember(doneJob.id);
      finished = false;
      paintRunning(doneJob);
      return;
    }
    remember(doneJob.id);
    finished = true;
    paintFinished(doneJob);
  } catch (_err) {
    return;
  }
}

document.addEventListener("click", (event) => {
  if (!oneCheck) return;
  if (event.target.closest("#page-loading-stop, #running-stop")) return;
  if (event.target.closest("a")) event.preventDefault();
});

document.querySelector("#page-loading-stop").addEventListener("click", () => {
  if (oneCheck) oneCheck.controller.abort();
});

runningStop.addEventListener("click", async () => {
  if (oneCheck) {
    oneCheck.controller.abort();
    return;
  }
  if (assetActive || barReviewId) {
    const id = barReviewId || listedJobId;
    markReviewHalted(id);
    barReviewId = "";
    if (assetActive) stopAssetChecks();
    else {
      assetHalted = true;
      paintAssetHalt();
    }
    return;
  }
  if (!followId) return;
  runningStop.disabled = true;
  runningStop.textContent = "중지하는 중";
  runningTitle.textContent = "중지하는 중";
  await fetch(`/api/audits/${followId}/stop`, { method: "POST" });
});

refreshRunning();
window.setInterval(refreshRunning, 400);
