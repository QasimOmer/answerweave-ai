"""
Browser tests (Playwright) against a running Hi Bot.

    pytest tests/e2e --base-url https://answerweave-ai.vercel.app

They're skipped unless --base-url is given, so `pytest` alone stays fast and offline.
"""
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _need_base_url(base_url):
    if not base_url:
        pytest.skip("pass --base-url to run browser tests")


def test_landing_page(page: Page, base_url):
    page.goto(base_url + "/")
    expect(page).to_have_title(re.compile("Hi Bot"))
    expect(page.locator("h1").first).to_be_visible()


def test_sign_in_dialog_opens(page: Page, base_url):
    page.goto(base_url + "/?login=1")
    form = page.locator("#loginForm")
    expect(form).to_be_visible()
    expect(form.get_by_label("Email", exact=True)).to_be_visible()
    expect(form.get_by_label("Password", exact=True)).to_be_visible()


def test_wrong_password_shows_error_and_stays_signed_out(page: Page, base_url):
    page.goto(base_url + "/?login=1")
    form = page.locator("#loginForm")
    form.get_by_label("Email", exact=True).fill("nobody@example.com")
    form.get_by_label("Password", exact=True).fill("definitely-wrong-password")
    form.get_by_role("button", name=re.compile("^Sign in$")).click()
    expect(page.get_by_role("alert").filter(has_text=re.compile("Invalid email or password", re.I))).to_be_visible()
    expect(page).not_to_have_url(re.compile("/dashboard"))


def test_dashboard_redirects_signed_out_visitors(page: Page, base_url):
    page.goto(base_url + "/dashboard")
    expect(page).to_have_url(re.compile(r"login=1"))


@pytest.mark.parametrize("width,height", [(390, 844), (768, 1024), (1440, 900)])
def test_landing_has_no_horizontal_scroll(page: Page, base_url, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + "/")
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"page is {overflow}px wider than a {width}px screen"


def test_widget_loads_on_demo_page(page: Page, base_url):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url + "/demo")
    page.wait_for_load_state("networkidle")
    assert not errors, f"JavaScript errors on the demo page: {errors}"
