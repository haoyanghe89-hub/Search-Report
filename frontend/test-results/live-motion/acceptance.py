import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(r"D:\deepsearch")
OUT = ROOT / "frontend" / "test-results" / "live-motion"
sys.path.insert(0, str(ROOT / "frontend" / ".playwright-runtime"))

from playwright.sync_api import sync_playwright

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = os.environ.get('LIVE_MOTION_BASE_URL', 'http://127.0.0.1:5183')
HARNESS = f"{BASE}/test-results/live-motion/harness.html"
results = {"checks": [], "console_errors": [], "page_errors": [], "http_errors": [], "screenshots": [], "samples": {}, "notes": []}
sys.stdout.reconfigure(encoding="utf-8")


def check(name, passed, details=None):
    results["checks"].append({"name": name, "passed": bool(passed), "details": details})


def capture_errors(page, label):
    page.on("console", lambda message: results["console_errors"].append({"page": label, "text": message.text}) if message.type == "error" else None)
    page.on("pageerror", lambda error: results["page_errors"].append({"page": label, "text": str(error)}))
    page.on("response", lambda response: results["http_errors"].append({"page": label, "status": response.status, "url": response.url}) if response.status >= 400 else None)


def shot(page, name, full=False):
    path = OUT / name
    page.screenshot(path=str(path), full_page=full)
    results["screenshots"].append(str(path.relative_to(ROOT)))


def style(page, selector):
    return page.locator(selector).evaluate("node => ({opacity:getComputedStyle(node).opacity, transform:getComputedStyle(node).transform, display:getComputedStyle(node).display})")


def open_case(page):
    page.goto(BASE, wait_until="networkidle")
    if page.locator(".section-nav").count():
        return
    if page.locator(".mobile-menu-trigger").is_visible():
        page.locator(".mobile-menu-trigger").click()
    page.locator(".case-card").first.click()
    page.wait_for_selector(".section-nav")
    page.wait_for_load_state("networkidle")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path=EDGE)

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    capture_errors(page, "motion-harness")
    page.goto(HARNESS, wait_until="networkidle")
    page.wait_for_timeout(300)
    harness_state = page.evaluate("({api: typeof window.liveHarness, moduleType: window.__runProgressModule?.type, moduleKeys: window.__runProgressModule?.keys, root: Boolean(document.querySelector('.run-progress')), app: document.querySelector('#app')?.innerHTML || ''})")
    if harness_state["api"] != "object" or not harness_state["root"]:
        raise RuntimeError(json.dumps({"harness": harness_state, "console": results["console_errors"], "page": results["page_errors"]}, ensure_ascii=False))
    page.evaluate("liveHarness.reset()")
    page.evaluate("liveHarness.addFirst()")
    page.wait_for_timeout(60)
    entry_sample = style(page, "[data-step-id='STEP-01']")
    scan_a = style(page, "[data-step-id='STEP-01'] .step-scan")
    page.wait_for_timeout(180)
    scan_b = style(page, "[data-step-id='STEP-01'] .step-scan")
    page.wait_for_timeout(420)
    entry_final = style(page, "[data-step-id='STEP-01']")
    check("new step archives with transform/opacity entry", entry_sample["opacity"] != "1" or entry_sample["transform"] != "none", entry_sample)
    check("new step settles fully visible", entry_final["opacity"] == "1" and entry_final["transform"] == "none", entry_final)
    check("active step scan advances", scan_a["transform"] != scan_b["transform"], {"before": scan_a, "after": scan_b})

    page.evaluate("liveHarness.completeFirst()")
    page.wait_for_timeout(50)
    stamp_mid = style(page, "[data-step-id='STEP-01'] .step-status")
    page.wait_for_timeout(380)
    stamp_final = style(page, "[data-step-id='STEP-01'] .step-status")
    scan_stopped = style(page, "[data-step-id='STEP-01'] .step-scan")
    check("completion stamp has a transient transform", stamp_mid["transform"] != "none" or stamp_mid["opacity"] != "1", stamp_mid)
    check("completion stamp settles", stamp_final["opacity"] == "1" and stamp_final["transform"] == "none", stamp_final)
    check("completed step scan stops", scan_stopped["opacity"] == "0", scan_stopped)

    page.evaluate("liveHarness.addSecond()")
    page.wait_for_timeout(90)
    budget_mid = page.locator("[data-budget-key='search']").inner_text()
    phase_mid = style(page, ".phase-value")
    page.wait_for_timeout(500)
    budget_final = page.locator("[data-budget-key='search']").inner_text()
    phase_final = style(page, ".phase-value")
    check("budget counter animates toward the new value", budget_mid != "4", {"mid": budget_mid, "final": budget_final})
    check("budget counter reaches the persisted value", budget_final == "4", budget_final)
    check("phase change reveals then settles", (phase_mid["opacity"] != "1" or phase_mid["transform"] != "none") and phase_final["opacity"] == "1", {"mid": phase_mid, "final": phase_final})
    check("worker cards use stable grid geometry", page.locator("[data-worker-name]").count() == 2, page.locator("[data-worker-name]").count())
    check("desktop has no horizontal overflow", page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), page.evaluate("({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth})"))
    shot(page, "live-1440x900-dark.png", True)
    results["samples"].update({"entry": entry_sample, "stamp": stamp_mid, "phase": phase_mid, "budget_mid": budget_mid})
    context.close()

    for theme in ("dark", "light"):
        context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        page = context.new_page()
        capture_errors(page, f"mobile-{theme}")
        page.goto(HARNESS, wait_until="networkidle")
        page.evaluate(f"liveHarness.setTheme('{theme}'); liveHarness.addFirst(); liveHarness.addSecond()")
        page.wait_for_timeout(650)
        mobile_metrics = page.evaluate("({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth,theme:document.documentElement.dataset.theme})")
        scan_touch_a = style(page, "[data-step-id='STEP-01'] .step-scan")
        page.wait_for_timeout(180)
        scan_touch_b = style(page, "[data-step-id='STEP-01'] .step-scan")
        check(f"390x844 {theme}: no horizontal overflow", mobile_metrics["scroll"] <= mobile_metrics["client"], mobile_metrics)
        check(f"390x844 {theme}: theme applied", mobile_metrics["theme"] == theme, mobile_metrics)
        check(f"390x844 {theme}: touch disables ambient scan", scan_touch_a["transform"] == scan_touch_b["transform"], {"before": scan_touch_a, "after": scan_touch_b})
        shot(page, f"live-390x844-{theme}.png", True)
        context.close()

    context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = context.new_page()
    capture_errors(page, "reduced-motion")
    page.goto(HARNESS, wait_until="networkidle")
    page.evaluate("liveHarness.addFirst(); liveHarness.addSecond(); liveHarness.completeFirst()")
    page.wait_for_timeout(70)
    reduced_step = style(page, "[data-step-id='STEP-02']")
    reduced_stamp = style(page, "[data-step-id='STEP-01'] .step-status")
    reduced_scan = style(page, "[data-step-id='STEP-02'] .step-scan")
    reduced_budget = page.locator("[data-budget-key='search']").inner_text()
    check("reduced motion keeps new steps immediately visible", reduced_step["opacity"] == "1" and reduced_step["transform"] == "none", reduced_step)
    check("reduced motion keeps stamps static and visible", reduced_stamp["opacity"] == "1" and reduced_stamp["transform"] == "none", reduced_stamp)
    check("reduced motion disables scan lines", reduced_scan["display"] == "none", reduced_scan)
    check("reduced motion updates counters immediately", reduced_budget == "4", reduced_budget)
    shot(page, "live-390x844-reduced.png", True)
    context.close()

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    capture_errors(page, "mock-live-polling")
    page.add_init_script("localStorage.setItem('search-report-theme', 'dark')")
    live_state = {"poll": 0}

    def live_api(route):
        path = urlparse(route.request.url).path.rstrip('/')
        status = "RUNNING" if live_state["poll"] < 3 else "READY_FOR_REPORT"
        phase = "SEARCHING" if live_state["poll"] < 2 else "VERIFYING"
        run = {
            "run_id": "RUN-LIVE-MOTION",
            "investigation_id": "INV-LIVE-MOTION",
            "status": status,
            "mode": "LIVE",
            "current_phase": phase,
            "state_version": live_state["poll"],
            "created_at": "2026-10-01T12:00:00Z",
            "updated_at": "2026-10-01T12:00:04Z"
        }
        if path == "/api/investigations":
            payload = [{"investigation_id": "INV-LIVE-MOTION", "title": "实时证据归档验收", "run_count": 1}]
        elif path == "/api/investigations/INV-LIVE-MOTION":
            payload = {"investigation_id": "INV-LIVE-MOTION", "title": "实时证据归档验收", "investigation_goal": "验证调查过程中的归档、盖章与合卷动效。"}
        elif path == "/api/investigations/INV-LIVE-MOTION/runs":
            payload = [run]
        elif path == "/api/runs/RUN-LIVE-MOTION":
            live_state["poll"] += 1
            status = "RUNNING" if live_state["poll"] < 3 else "READY_FOR_REPORT"
            run = {**run, "status": status, "state_version": live_state["poll"], "current_phase": "VERIFYING" if live_state["poll"] >= 2 else "SEARCHING"}
            payload = {
                "run": run,
                "workers": {"official": "SUCCEEDED" if live_state["poll"] >= 2 else "RUNNING", "technical": "SUCCEEDED" if live_state["poll"] >= 3 else "VERIFYING"},
                "budget": {"search_calls_used": live_state["poll"], "max_search_calls": 12, "fetch_calls_used": max(0, live_state["poll"] - 1), "max_fetch_calls": 8, "model_calls_used": max(0, live_state["poll"] - 2), "max_model_calls": 5}
            }
        elif path == "/api/runs/RUN-LIVE-MOTION/steps":
            payload = [{"step_id": "STEP-LIVE-01", "agent_role": "official", "step_type": "SEARCH", "status": "COMPLETED" if live_state["poll"] >= 2 else "RUNNING"}]
            if live_state["poll"] >= 2:
                payload.append({"step_id": "STEP-LIVE-02", "agent_role": "technical", "step_type": "VERIFY", "status": "SUCCEEDED" if live_state["poll"] >= 3 else "VERIFYING"})
        elif path.startswith("/api/runs/RUN-LIVE-MOTION/"):
            payload = []
        else:
            route.fulfill(status=404, content_type="application/json", body=json.dumps({"detail": path}))
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

    page.route(f"{BASE}/api/**", live_api)
    page.goto(BASE, wait_until="networkidle")
    if not page.locator('.case-card').count():
        raise RuntimeError(json.dumps({"body": page.locator('body').inner_text(), "console": results['console_errors'], "errors": results['page_errors'], "http": results['http_errors']}, ensure_ascii=False))
    page.locator(".case-card").first.click()
    page.wait_for_selector(".run-progress")
    page.evaluate("""
      window.__runSequence = { seen: false, leave: false, resultDuringLeave: false, resultAfter: false };
      window.__runSequenceTimer = setInterval(() => {
        const run = document.querySelector('.run-progress');
        const results = document.querySelector('.section-nav');
        if (run) {
          window.__runSequence.seen = true;
          if (Number(getComputedStyle(run).opacity) < 0.98) {
            window.__runSequence.leave = true;
            if (results) window.__runSequence.resultDuringLeave = true;
          }
        } else if (window.__runSequence.seen && results) {
          window.__runSequence.resultAfter = true;
        }
      }, 16);
    """)
    shot(page, "mock-live-polling.png", True)
    page.wait_for_selector("[data-step-id='STEP-LIVE-02']", timeout=10000)
    page.wait_for_selector(".run-progress", state="detached", timeout=15000)
    page.wait_for_selector(".section-nav", timeout=15000)
    page.wait_for_timeout(100)
    sequence = page.evaluate("clearInterval(window.__runSequenceTimer); window.__runSequence")
    check("mock polling renders the live progress component", sequence["seen"], sequence)
    check("terminal polling uses the dossier-close leave motion", sequence["leave"], sequence)
    check("results wait until the close motion completes", not sequence["resultDuringLeave"] and sequence["resultAfter"], sequence)
    check("mock live app has no horizontal overflow", page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), None)
    context.close()
    browser.close()

check("no console errors", not results["console_errors"], results["console_errors"])
check("no page errors", not results["page_errors"], results["page_errors"])
results["passed"] = all(item["passed"] for item in results["checks"])
(OUT / "acceptance.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"passed": results["passed"], "checks": len(results["checks"]), "failed": [item for item in results["checks"] if not item["passed"]], "notes": results["notes"], "console_errors": results["console_errors"], "page_errors": results["page_errors"], "http_errors": results["http_errors"]}, ensure_ascii=False, indent=2))
raise SystemExit(0 if results["passed"] else 1)
