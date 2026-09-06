"""Browser regression and screenshots against the running mock workbench."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8021")
    args = parser.parse_args()
    directory = Path("artifacts/ui")
    directory.mkdir(parents=True, exist_ok=True)
    checks = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for name, width, height in [
            ("desktop", 1440, 1000),
            ("mobile", 390, 844),
            ("narrow", 320, 740),
            ("wide", 1920, 1080),
        ]:
            context = browser.new_context(
                viewport={"width": width, "height": height}, device_scale_factor=1
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
            page.goto(args.url, wait_until="networkidle")
            expect(page.locator("#connection")).to_contain_text("MCP")
            assert page.locator(".brand img").evaluate(
                "img => img.complete && img.naturalWidth > 0"
            )
            assert page.locator("svg.lucide").count() > 5
            page.locator("#allow-writes").check()
            page.locator("#run").click()
            expect(page.locator("#task-status")).to_have_text("等待审批", timeout=60000)
            expect(page.locator("#summary")).to_contain_text("Login")
            expect(page.locator(".action")).to_have_count(2)
            page.locator(".trace-item").first.locator("summary").click()
            page.screenshot(path=str(directory / f"{name}.png"), full_page=True)
            overflow = page.evaluate("""() => ({
                page:document.documentElement.scrollWidth>innerWidth,
                controls:[...document.querySelectorAll('button,input,select,textarea')].filter(el=>{
                    const r=el.getBoundingClientRect();
                    return r.width>0 && (r.left<0 || r.right>innerWidth+1)
                }).map(el=>el.id || el.textContent)})""")
            assert not overflow["page"] and not overflow["controls"], overflow
            page.locator(".reject").first.click()
            expect(page.locator(".action .rejected")).to_have_count(1, timeout=30000)
            page.locator("#audit-tab").click()
            expect(page.locator("#audit-panel")).to_contain_text("REJECTED")
            page.reload(wait_until="networkidle")
            expect(page.locator("#summary")).to_contain_text("Login")
            assert not errors, errors
            checks.append(
                {
                    "viewport": name,
                    "width": width,
                    "height": height,
                    "overflow": overflow,
                    "javascript_errors": errors,
                    "reload_persistence": True,
                }
            )
            context.close()
        # Exercise the visible approval button and the error/degradation states.
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(args.url, wait_until="networkidle")
        page.locator(".manual summary").click()
        page.locator("#manual-args").fill(
            json.dumps(
                {
                    "repo": "student-lab/course-project",
                    "issue_number": 1,
                    "body": "Browser verification comment",
                }
            )
        )
        page.locator("#manual-form button").click()
        expect(page.locator(".approve")).to_have_count(1)
        page.locator(".approve").click()
        expect(page.locator(".action .succeeded, .action .duplicate")).to_have_count(
            1, timeout=30000
        )
        page.locator("#issue").fill("429")
        page.locator("#run").click()
        expect(page.locator("#task-status")).to_have_text("已停止", timeout=60000)
        expect(page.locator("#notice")).to_contain_text("限流")
        page.screenshot(path=str(directory / "rate-limit.png"), full_page=True)
        page.locator("#issue").fill("4")
        page.locator('input[value="provider"]').check()
        page.locator("#run").click()
        expect(page.locator("#task-status")).to_have_text("分析完成", timeout=60000)
        expect(page.locator("#agent-mode")).to_have_text("OFFLINE")
        expect(page.locator("#notice")).to_contain_text("模型未配置")
        assert page.locator("#analysis script").count() == 0
        checks.append(
            {"approval_click": True, "rate_limit_state": True, "explicit_offline_degradation": True}
        )
        browser.close()
    (directory / "verification.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
