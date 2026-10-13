"""Drive the local synthetic demo with Playwright; never navigates to a third party."""

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://127.0.0.1:8000/demo")
        page.get_by_role("button", name="Start synthetic demo").click()
        page.get_by_role("button", name="Create 30-second browser session").click()
        page.get_by_role("button", name="Expire last session now").click()
        page.get_by_role("button", name="Revoke last session").click()
        page.get_by_role("link", name="View dashboard").click()
        page.wait_for_load_state("domcontentloaded")
        assert page.locator("#dashboard").is_visible()
        print("Local browser demo completed: created, expired, and revoked a synthetic session.")
        browser.close()


if __name__ == "__main__":
    main()
