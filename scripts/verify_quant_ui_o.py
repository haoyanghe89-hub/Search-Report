"""Native Playwright against the real local HTTP server; no mocked API numbers."""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reports/taskj/playwright-runtime"))
from playwright.sync_api import sync_playwright  # noqa: E402


def verify(url, source, output, entry_only=False, lineage_only=False):
    output = output.resolve()
    if not output.is_relative_to(ROOT / ".phase3-quant-o") or output.exists():
        raise ValueError("new private Task O UI output required")
    output.mkdir(parents=True)
    records = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    result = {"scenarios": [], "errors": [], "screenshots": [], "cell_lineage": []}
    for index, record in enumerate(records):
        detail = json.loads((source / f"run-{index}.json").read_text(encoding="utf-8"))
        cells = {v["metric_path"]: v for v in detail["values"]}
        count = 0
        for chart in detail["charts"]:
            for series in chart["series"]:
                for point in series["points"]:
                    cell = cells[point["metric_path"]]
                    assert point["value"] == cell["value"]
                    assert point["cell_hash"] == cell["cell_hash"]
                    assert series["unit"] == cell["unit"]
                    assert chart["artifact_id"] == cell["artifact_id"]
                    count += 1
        result["cell_lineage"].append(dict(run_id=record["run_id"], chart_points=count))
    if lineage_only:
        (output / "summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result["cell_lineage"]))
        return
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in () if entry_only else ((375, 844), (768, 1024), (1440, 900)):
            for theme in ("light", "dark"):
                for reduced in ("reduce", "no-preference"):
                    context = browser.new_context(
                        viewport={"width": width, "height": height}, reduced_motion=reduced
                    )
                    context.add_init_script(
                        f"localStorage.setItem('search-report-theme', '{theme}')"
                    )
                    page = context.new_page()
                    page.on("pageerror", lambda error: result["errors"].append(str(error)))
                    page.goto(url, wait_until="networkidle")
                    if width < 768:
                        page.get_by_role("button", name="打开调查档案", exact=True).click()
                    page.locator(".case-select").filter(
                        has_text=records[0]["investigation_id"]
                    ).click()
                    page.locator('[data-tab-key="report"]').click()
                    page.locator(".chart-canvas canvas").first.wait_for(timeout=60000)
                    assert page.locator(".quant-exhibit").count() == 3
                    assert page.locator(".report-appendices").get_attribute("open") is None
                    assert page.locator(".report-section").count() == 4
                    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    assert not overflow, (width, theme, reduced, "page overflow")
                    animation = page.locator(".chart-canvas").first.get_attribute(
                        "data-chart-animation"
                    )
                    assert animation == ("false" if reduced == "reduce" else "true")
                    name = f"report-{width}-{theme}-{reduced}.png"
                    page.screenshot(path=str(output / name), full_page=True)
                    result["screenshots"].append(name)
                    price = page.locator(".quant-exhibit").first
                    price.get_by_role("button", name="hfq", exact=True).click()
                    price.locator(".chart-data summary").click()
                    price.get_by_role("button", name="/values/", exact=False).first.click()
                    assert page.locator(".cell-detail").inner_text().find("cell_hash") >= 0
                    page.locator(".cell-detail").get_by_role("button", name="关闭单元格").click()
                    price.locator(".chart-data summary").click()
                    page.locator(".citation-link").first.click()
                    page.locator("dialog[open]").get_by_text(
                        "冻结计算单元格（不是网页引文）"
                    ).wait_for()
                    page.locator("dialog[open]").get_by_role(
                        "button", name="关闭", exact=True
                    ).click()
                    result["scenarios"].append(
                        dict(
                            width=width,
                            theme=theme,
                            reduced=reduced,
                            charts=3,
                            no_page_overflow=True,
                            technical_folded=True,
                            cell_locator=True,
                            latest_citation=True,
                            chart_animation=animation,
                        )
                    )
                    context.close()
        # Actual entry -> HTTP -> report, with an explicit historical frozen preset.
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}, reduced_motion="reduce"
        )
        page = context.new_page()
        page.on("pageerror", lambda error: result["errors"].append(str(error)))
        page.goto(url, wait_until="networkidle")
        page.get_by_role("button", name="新建调查", exact=True).click()
        page.get_by_role("button", name="量化投研", exact=True).click()
        page.get_by_placeholder("代码或名称").fill("000001")
        page.locator(".suggestions button").first.click()
        window = page.get_by_label("数据窗口 · 显式冻结选择")
        window.locator("option").nth(1).wait_for(state="attached")
        frozen_id = window.locator("option").nth(1).get_attribute("value")
        window.select_option(frozen_id)
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/api/quant/runs")
        ) as started:
            page.get_by_role("button", name="启动量化投研", exact=True).click()
        response = started.value
        assert response.status == 202
        new = response.json()
        until = __import__("time").monotonic() + 300
        detail = None
        while __import__("time").monotonic() < until:
            with urlopen(url + "/api/quant/runs/" + new["run_id"], timeout=30) as handle:
                detail = json.load(handle)
            if detail["run"]["status"] == "COMPLETED":
                break
            page.wait_for_timeout(500)
        assert detail and detail["report_id"] and len(detail["charts"]) == 3
        page.get_by_role("button", name="阅读报告", exact=True).click(timeout=60000)
        try:
            page.locator(".chart-canvas canvas").first.wait_for(timeout=60000)
        except Exception:
            page.screenshot(path=str(output / "entry-failure.png"), full_page=True)
            (output / "entry-failure.html").write_text(page.content(), encoding="utf-8")
            print(
                json.dumps(
                    dict(
                        run=new,
                        detail=detail["run"],
                        active_tab=page.locator(".nav-tab.active").get_attribute("data-tab-key"),
                    ),
                    ensure_ascii=False,
                )
            )
            raise
        page.screenshot(path=str(output / "entry-real-frozen-run.png"), full_page=True)
        result["entry_run"] = new
        result["entry_run"]["report_id"] = detail["report_id"]
        result["entry_run"]["source"] = "real historical frozen preset, no synthetic input"
        context.close()
        browser.close()
    assert not result["errors"], result["errors"]
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            dict(
                scenarios=len(result["scenarios"]),
                errors=result["errors"],
                entry_run=result["entry_run"],
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8830")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entry-only", action="store_true")
    parser.add_argument("--lineage-only", action="store_true")
    args = parser.parse_args()
    verify(args.url, args.source, args.output, args.entry_only, args.lineage_only)
