import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(r"D:\deepsearch")
OUT = ROOT / "frontend" / "test-results" / "v3-3"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE_URL = "http://127.0.0.1:5173"
SIZES = [
    (1440, 900),
    (1366, 768),
    (1024, 768),
    (768, 1024),
    (390, 844),
    (360, 640),
    (844, 390),
]
TABS = ["overview", "agents", "sources", "evidence", "claims", "conflicts", "timeline", "report", "review"]

sys.stdout.reconfigure(encoding="utf-8")
OUT.mkdir(parents=True, exist_ok=True)
results = {"checks": [], "screenshots": [], "console_errors": [], "page_errors": [], "notes": []}


def check(name, passed, details=None):
    results["checks"].append({"name": name, "passed": bool(passed), "details": details})


def attach_error_capture(page, label):
    page.on("console", lambda message: results["console_errors"].append({"page": label, "text": message.text}) if message.type == "error" else None)
    page.on("pageerror", lambda error: results["page_errors"].append({"page": label, "text": str(error)}))


def set_theme(page, theme):
    page.add_init_script(f"localStorage.setItem('search-report-theme', {json.dumps(theme)})")


def open_case(page):
    page.goto(BASE_URL, wait_until="networkidle")
    if page.locator(".section-nav").count():
        return
    if page.locator(".mobile-menu-trigger").is_visible():
        page.locator(".mobile-menu-trigger").click()
        page.locator(".case-card").first.click()
    else:
        page.locator(".case-card").first.click()
    page.wait_for_selector(".section-nav")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)


def reveal_page(page):
    height = page.evaluate("document.documentElement.scrollHeight")
    viewport = page.viewport_size["height"]
    for position in (viewport, height // 2, max(0, height - viewport)):
        page.evaluate("value => window.scrollTo(0, value)", position)
        page.wait_for_timeout(180)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(180)


def screenshot(page, name, full_page=False):
    path = OUT / name
    page.screenshot(path=str(path), full_page=full_page)
    results["screenshots"].append(str(path.relative_to(ROOT)))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path=EDGE)

    for width, height in SIZES:
        for theme in ("dark", "light"):
            label = f"{width}x{height}-{theme}"
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            attach_error_capture(page, label)
            set_theme(page, theme)
            open_case(page)
            reveal_page(page)

            metrics = page.evaluate("""
                () => ({
                  clientWidth: document.documentElement.clientWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                  theme: document.documentElement.dataset.theme,
                  navOverflow: document.querySelector('.section-nav')?.scrollWidth > document.querySelector('.section-nav')?.clientWidth,
                  drawerVisible: getComputedStyle(document.querySelector('.mobile-sidebar-bar')).display !== 'none'
                })
            """)
            check(f"{label}: no horizontal document overflow", metrics["scrollWidth"] <= metrics["clientWidth"], metrics)
            check(f"{label}: theme applied", metrics["theme"] == theme, metrics["theme"])
            check(f"{label}: responsive drawer boundary", metrics["drawerVisible"] == (width < 768), metrics)

            if width < 768:
                page.locator(".mobile-menu-trigger").click()
                page.wait_for_timeout(320)
                panel_box = page.locator(".sidebar-panel").bounding_box()
                check(f"{label}: drawer remains in viewport", panel_box and panel_box["x"] >= 0 and panel_box["x"] + panel_box["width"] <= width and panel_box["height"] <= height, panel_box)
                page.locator(".mobile-drawer-close").click()
                page.wait_for_timeout(320)
                touch = page.locator(".mobile-menu-trigger").bounding_box()
                check(f"{label}: primary touch target >=44", touch and touch["width"] >= 44 and touch["height"] >= 44, touch)

            screenshot(page, f"viewport-{label}.png")
            if theme == "dark" and (width, height) in ((1440, 900), (390, 844), (844, 390)):
                screenshot(page, f"full-{label}.png", full_page=True)
            context.close()

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    attach_error_capture(page, "desktop-interactions")
    set_theme(page, "dark")
    open_case(page)

    rendered_tabs = page.locator("[data-tab-key]").evaluate_all("nodes => nodes.map(node => node.dataset.tabKey)")
    check("all nine tabs preserved", rendered_tabs == TABS, rendered_tabs)
    for tab in TABS:
        page.locator(f"[data-tab-key='{tab}']").click()
        page.wait_for_timeout(500)
        active = page.locator(f"[data-tab-key='{tab}']").get_attribute("aria-current")
        check(f"tab activates: {tab}", active == "page", active)
        screenshot(page, f"tab-{tab}.png")

    page.locator("[data-tab-key='sources']").click()
    page.wait_for_timeout(450)
    source_card = page.locator(".source-record").first
    source_card.scroll_into_view_if_needed()
    source_card.hover()
    page.wait_for_timeout(260)
    source_style = source_card.evaluate("node => ({ transform: getComputedStyle(node).transform, border: getComputedStyle(node).borderColor, cursor: getComputedStyle(node).cursor })")
    check("desktop card hover feedback", source_style["transform"] != "none" and source_style["cursor"] == "pointer", source_style)

    page.locator("[data-tab-key='overview']").click()
    page.wait_for_timeout(450)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(180)
    hero_action = page.locator(".hero-primary-action")
    hero_box = hero_action.bounding_box()
    page.mouse.move(hero_box["x"] + hero_box["width"] - 2, hero_box["y"] + hero_box["height"] / 2)
    page.wait_for_timeout(220)
    magnetic_transform = hero_action.evaluate("node => getComputedStyle(node).transform")
    check("desktop primary CTA magnetic response", magnetic_transform != "none", magnetic_transform)
    page.mouse.move(0, 0)

    page.locator("[data-tab-key='report']").click()
    page.wait_for_selector(".report-detail")
    page.wait_for_selector(".report-version-content")
    page.wait_for_timeout(700)
    report_style = page.locator(".report-version-content").evaluate("node => ({ opacity: getComputedStyle(node).opacity, transform: getComputedStyle(node).transform })")
    check("report opening settles visibly", report_style["opacity"] == "1" and report_style["transform"] == "none", report_style)
    select_trigger = page.locator(".report-toolbar .select-trigger")
    select_trigger.click()
    page.wait_for_selector(".report-toolbar [role='option']")
    option_count = page.locator(".report-toolbar [role='option']").count()
    check("report version selector opens", option_count >= 1, option_count)
    if option_count > 1:
        before = select_trigger.inner_text()
        page.locator(".report-toolbar [role='option']").nth(1).click()
        page.wait_for_timeout(700)
        after = select_trigger.inner_text()
        check("report version switches", before != after, {"before": before, "after": after})
    else:
        page.keyboard.press("Escape")
        results["notes"].append("The replay fixture exposes one report version; selector open/keyboard behavior was verified, but cross-version switching is data-limited.")

    sections = page.locator("[data-report-section]")
    check("report has scrollspy sections", sections.count() > 1, sections.count())
    if sections.count() > 1:
        second_id = sections.nth(1).get_attribute("id")
        sections.nth(1).evaluate("node => { document.documentElement.style.scrollBehavior = 'auto'; window.scrollTo(0, node.getBoundingClientRect().top + window.scrollY - 80) }")
        page.wait_for_timeout(300)
        active_href = page.locator(".report-outline-desktop a.active").get_attribute("href")
        check("report scrollspy follows section", active_href == f"#{second_id}", {"expected": second_id, "active": active_href})

    citation_link = page.locator(".citation-link").first
    citation_link.scroll_into_view_if_needed()
    citation_link.hover()
    page.wait_for_selector(".citation-preview")
    page.wait_for_timeout(250)
    preview_box = page.locator(".citation-preview").bounding_box()
    check("citation preview stays in viewport", preview_box and preview_box["x"] >= 0 and preview_box["y"] >= 0 and preview_box["x"] + preview_box["width"] <= 1440 and preview_box["y"] + preview_box["height"] <= 900, preview_box)
    screenshot(page, "report-citation-preview.png")
    citation_link.click()
    page.wait_for_selector(".citation-dialog[open]")
    page.wait_for_timeout(300)
    check("evidence stamp rendered", page.locator(".citation-dialog .evidence-stamp").count() > 0, page.locator(".citation-dialog .evidence-stamp").count())
    dialog_box = page.locator(".citation-dialog").bounding_box()
    check("citation provenance dialog opens in viewport", dialog_box and dialog_box["x"] >= 0 and dialog_box["y"] >= 0 and dialog_box["x"] + dialog_box["width"] <= 1440 and dialog_box["y"] + dialog_box["height"] <= 900, dialog_box)
    screenshot(page, "report-citation-dialog.png")
    page.locator(".citation-dialog .quiet-button").click()
    page.wait_for_timeout(250)
    check("citation provenance dialog closes", not page.locator(".citation-dialog").get_attribute("open"), None)

    page.locator("[data-report-section]").last.scroll_into_view_if_needed()
    page.wait_for_timeout(350)
    progress_value = int(page.locator(".reading-progress").get_attribute("aria-valuenow"))
    check("reading progress updates", progress_value > 0, progress_value)
    screenshot(page, "report-reader-full.png", full_page=True)
    context.close()

    context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = context.new_page()
    attach_error_capture(page, "reduced-motion")
    set_theme(page, "dark")
    open_case(page)
    page.locator("[data-tab-key='sources']").click()
    page.wait_for_timeout(250)
    page.locator("[data-tab-key='report']").click()
    page.wait_for_selector(".report-version-content")
    reduced = page.evaluate("""
      () => ({
        scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
        heroOpacity: getComputedStyle(document.querySelector('.hero-title')).opacity,
        reportOpacity: getComputedStyle(document.querySelector('.report-version-content')).opacity,
        hiddenSections: [...document.querySelectorAll('.report-section-heading')].filter(node => getComputedStyle(node).opacity === '0').length,
        media: matchMedia('(prefers-reduced-motion: reduce)').matches
      })
    """)
    check("reduced-motion media active", reduced["media"], reduced)
    check("reduced-motion disables smooth scroll", reduced["scrollBehavior"] == "auto", reduced)
    check("reduced-motion keeps content visible", reduced["heroOpacity"] == "1" and reduced["reportOpacity"] == "1" and reduced["hiddenSections"] == 0, reduced)
    screenshot(page, "reduced-motion-390x844.png", full_page=True)
    context.close()

    browser.close()

unexpected_console = [item for item in results["console_errors"] if "401 (Unauthorized)" not in item["text"]]
if len(unexpected_console) != len(results["console_errors"]):
    results["notes"].append("The review tab intentionally probes the unauthenticated reviewer endpoint and receives the expected 401 before login.")
check("no unexpected console errors", not unexpected_console, unexpected_console)
check("no page errors", not results["page_errors"], results["page_errors"])
results["passed"] = all(item["passed"] for item in results["checks"])
(OUT / "acceptance.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"passed": results["passed"], "checks": len(results["checks"]), "failed": [item for item in results["checks"] if not item["passed"]], "notes": results["notes"], "console_errors": results["console_errors"], "page_errors": results["page_errors"]}, ensure_ascii=False, indent=2))
raise SystemExit(0 if results["passed"] else 1)
