"""Offline Playwright duration/delete acceptance; never touches real archives."""

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reports/taskj/playwright-runtime"))

OUT = ROOT / "reports/taskj/ui"
SIZES = [(1440, 900), (1366, 768), (1024, 768), (768, 1024), (390, 844), (360, 640), (844, 390)]
RESULT = {"scenarios": [], "errors": [], "expected_409": [], "screenshots": []}


def detail(iid, title):
    return {
        "investigation_id": iid,
        "title": title,
        "event_description": title,
        "investigation_goal": "核验公开材料",
        "scope": {},
        "questions": [],
        "created_at": "2026-10-02T00:00:00Z",
        "updated_at": "2026-10-02T00:00:00Z",
        "counts": {"sources": 0, "evidence": 0, "claims": 0, "conflicts": 0, "open_gaps": 0},
        "run_count": 0,
    }


def snapshot(page, name):
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    RESULT["screenshots"].append(str(path.relative_to(ROOT)))


def no_overflow(page):
    return page.evaluate("""() => ({document:document.documentElement.scrollWidth <= innerWidth,
        dialog: [...document.querySelectorAll('dialog[open]')].every(d => {
          const r=d.getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth+1 &&
            r.top>=0 && r.bottom<=innerHeight+1 && d.scrollWidth<=d.clientWidth+1;
        })})""")


def drawer(page, width):
    if width < 768:
        page.get_by_role("button", name="打开调查档案", exact=True).click()


def run_case(browser, size, theme, reduced):
    width, height = size
    prefix = f"{width}x{height}-{theme}-{reduced}"
    context = browser.new_context(
        viewport={"width": width, "height": height}, reduced_motion=reduced, color_scheme=theme
    )
    context.add_init_script(f"localStorage.setItem('search-report-theme', '{theme}')")
    page = context.new_page()
    page.on("pageerror", lambda error: RESULT["errors"].append(str(error)))

    def console_message(msg):
        if msg.type == "error":
            target = "expected_409" if "409 (Conflict)" in msg.text else "errors"
            RESULT[target].append(msg.text)

    page.on("console", console_message)
    archives = [detail("INV-ARCHIVE", "待删除的历史调查卷宗")]
    requests = []
    blocked = [False]

    def route_api(route):
        request = route.request
        path = urlparse(request.url).path
        if not path.startswith("/api/"):
            route.continue_()
            return
        if request.method == "DELETE":
            requests.append({"method": "DELETE", "path": path})
            if blocked[0]:
                route.fulfill(
                    status=409,
                    json={
                        "detail": {
                            "code": "INVESTIGATION_ACTIVE",
                            "message": "调查仍在运行，请先停止。",
                        }
                    },
                )
            else:
                iid = path.rsplit("/", 1)[-1]
                archives[:] = [item for item in archives if item["investigation_id"] != iid]
                route.fulfill(json={"deleted": True, "already_deleted": False})
        elif path == "/api/investigations" and request.method == "POST":
            payload = request.post_data_json
            requests.append(payload)
            created = detail(f"INV-NEW-{len(archives)}", payload["title"])
            archives.append(created)
            route.fulfill(status=201, json=created)
        elif path == "/api/investigations":
            route.fulfill(json=archives)
        elif path.endswith("/runs"):
            route.fulfill(json=[])
        elif "/investigations/" in path:
            iid = path.rsplit("/", 1)[-1]
            route.fulfill(json=next(item for item in archives if item["investigation_id"] == iid))
        else:
            route.fulfill(json={})

    page.route("**/api/**", route_api)
    try:
        page.goto("http://127.0.0.1:5187", wait_until="networkidle")
        if not RESULT["scenarios"]:
            snapshot(page, "initial-dom")
            (OUT / "initial-dom.html").write_text(page.content(), encoding="utf-8")
            print(page.get_by_role("button").all_text_contents(), flush=True)
        # DOM observation before interaction also confirms the new entry point is mounted.
        assert page.locator("button").filter(has_text="新建调查").count() == 1
        assert page.evaluate("document.documentElement.dataset.theme") == theme
        for depth, label in [("quick", "快速"), ("standard", "标准"), ("deep", "深度")]:
            drawer(page, width)
            page.get_by_role("button", name="新建调查", exact=True).click()
            dialog = page.get_by_role("dialog", name="新建事件调查")
            dialog.wait_for(state="visible")
            assert dialog.get_by_role("radio", name="标准", exact=False).is_checked()
            dialog.get_by_role("radio", name=label, exact=False).check()
            dialog.get_by_role("textbox", name="调查标题", exact=True).fill(
                "Gemini 4 Argon 长话题公开资料核验"
            )
            dialog.get_by_role("textbox", name="事件描述", exact=True).fill(
                "公开材料的评测与事实核验"
            )
            dialog.get_by_role("textbox", name="调查目标", exact=True).fill("区分已验证结论与缺口")
            assert all(no_overflow(page).values()), (prefix, no_overflow(page))
            if reduced == "reduce":
                assert dialog.evaluate("d => getComputedStyle(d).opacity") == "1"
            snapshot(page, f"{prefix}-{depth}")
            dialog.get_by_role("button", name="创建调查", exact=True).click()
            dialog.wait_for(state="detached")
            assert requests[-1]["depth"] == depth
        drawer(page, width)
        page.get_by_role("button", name="删除卷宗：待删除的历史调查卷宗", exact=True).click()
        dialog = page.get_by_role("dialog", name="删除卷宗", exact=True)
        dialog.wait_for(state="visible")
        confirm = dialog.get_by_role("button", name="永久删除", exact=True)
        assert confirm.is_disabled()
        assert not any(r.get("method") == "DELETE" for r in requests)
        dialog.get_by_role("checkbox").check()
        assert confirm.is_enabled()
        assert all(no_overflow(page).values())
        snapshot(page, f"{prefix}-delete")
        # 409 must retain the archive and readable error, never show false success.
        blocked[0] = True
        confirm.click()
        dialog.get_by_role("alert").wait_for(state="visible")
        assert "请先停止" in dialog.get_by_role("alert").inner_text()
        blocked[0] = False
        confirm.click()
        dialog.wait_for(state="detached")
        page.get_by_role("status").filter(has_text="卷宗及关联记录已删除").wait_for(state="visible")
        assert (
            page.get_by_role("button", name="删除卷宗：待删除的历史调查卷宗", exact=True).count()
            == 0
        )
        RESULT["scenarios"].append(
            {
                "viewport": size,
                "theme": theme,
                "reduced_motion": reduced,
                "depths": ["quick", "standard", "deep"],
                "delete_409_then_success": True,
                "overflow": no_overflow(page),
                "passed": True,
            }
        )
    finally:
        context.close()


def main():
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                headless=True,
            )
            try:
                for size in SIZES:
                    for theme in ["light", "dark"]:
                        for reduced in ["no-preference", "reduce"]:
                            run_case(browser, size, theme, reduced)
                            (OUT / "acceptance.json").write_text(
                                json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8"
                            )
            finally:
                browser.close()
        assert not RESULT["errors"], RESULT["errors"]
        print(
            json.dumps(
                {
                    "scenarios": len(RESULT["scenarios"]),
                    "screenshots": len(RESULT["screenshots"]),
                    "errors": RESULT["errors"],
                }
            )
        )
    finally:
        (OUT / "acceptance.json").write_text(
            json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
