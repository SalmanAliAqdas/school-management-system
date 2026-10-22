"""Smoke-test a running local demo with installed Chrome (optional tooling)."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def preview_base_url(value):
    value = value.rstrip("/")
    parts = urlsplit(value)
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "localhost"}
        or parts.port is None
        or parts.username is not None
        or parts.password is not None
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Browser verification is restricted to a local development server.")
    return value


def main():
    try:
        base_url = preview_base_url(os.getenv("SCHOOLOS_PREVIEW_URL", "http://127.0.0.1:8000"))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    password = os.getenv("DEMO_PASSWORD")
    if not password:
        raise SystemExit("An explicitly seeded local demo and DEMO_PASSWORD are required.")
    output = ROOT / ".local" / "previews"
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        response = page.goto(f"{base_url}/accounts/login/")
        assert response.status == 200
        assert page.get_by_text("Demonstration environment", exact=False).is_visible()
        page.screenshot(path=str(output / "login-desktop.png"), full_page=True)
        page.get_by_label("Username", exact=False).fill("demo.admin")
        page.get_by_label("Password", exact=False).fill(password)
        page.get_by_role("button", name="Sign in to workspace").click()
        page.wait_for_url("**/dashboard/admin/")
        page.locator("#enrollment-chart").wait_for()
        page.wait_for_timeout(800)
        assert page.locator("#enrollment-chart").evaluate("el => !!Chart.getChart(el)")
        assert page.locator(".stat-value").first.text_content() == "6"
        page.screenshot(path=str(output / "dashboard-desktop.png"), full_page=True)
        # Every rendered navigation link must resolve successfully for this role.
        links = page.locator(".sidebar a").evaluate_all(
            "els => [...new Set(els.map(el => el.href))]"
        )
        for link in links:
            assert context.request.get(link).status == 200, link
        page.get_by_role("link", name="Students", exact=True).click()
        page.get_by_role("searchbox").fill("DEMO-0001")
        page.get_by_role("button", name="Apply filters").click()
        assert page.locator("tbody tr").count() == 1
        page.locator("tbody .student-cell a").click()
        assert page.get_by_role("heading", name="Academic journey").is_visible()
        page.goto(f"{base_url}/dashboard/admin/")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(400)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("#sidebar").evaluate("el => el.getBoundingClientRect().right <= 0")
        page.screenshot(path=str(output / "dashboard-mobile.png"), full_page=True)
        toggle = page.get_by_role("button", name="Open navigation")
        toggle.click()
        assert toggle.get_attribute("aria-expanded") == "true"
        assert page.locator(".main-column").evaluate("el => el.inert")
        page.keyboard.press("Escape")
        assert toggle.get_attribute("aria-expanded") == "false"
        assert page.locator("#sidebar").evaluate("el => el.inert")
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url("**/accounts/login/")
        assert page.get_by_role("heading", name="Welcome back.").is_visible()
        page.screenshot(path=str(output / "login-mobile.png"), full_page=True)
        for username, dashboard in [
            ("demo.teacher", "teacher"),
            ("demo.student", "student"),
            ("demo.parent", "parent"),
        ]:
            page.get_by_label("Username", exact=False).fill(username)
            page.get_by_label("Password", exact=False).fill(password)
            page.get_by_role("button", name="Sign in to workspace").click()
            page.wait_for_url(f"**/dashboard/{dashboard}/")
            page.get_by_role("button", name="Sign out").click()
            page.wait_for_url("**/accounts/login/")
        browser.close()
    if errors:
        raise AssertionError(json.dumps(errors))
    print(
        "Browser smoke passed: four roles, charts, navigation, search, detail, logout, mobile menu."
    )
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    main()
