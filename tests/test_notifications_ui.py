from playwright.sync_api import expect

from tests.conftest import issue_cookie


def test_notification_settings_show_native_permission_state(browser, live_app):
    address, _, app = live_app
    context = browser.new_context(viewport={"width": 1440, "height": 960})
    context.grant_permissions(["notifications"], origin=address)
    context.add_init_script("""
      (() => {
        class TestNotification {
          static permission = 'default';
          static requestPermission = () => {
            TestNotification.permission = 'granted';
            return Promise.resolve('granted');
          };
          constructor() {}
          close() {}
        }
        Object.defineProperty(window, 'Notification', {
          configurable: true, value: TestNotification,
        });
      })();
    """)
    context.add_cookies([
        {
            "name": app.state.cookie_name,
            "value": issue_cookie(app.state.settings),
            "url": address,
            "httpOnly": True,
            "sameSite": "Strict",
        }
    ])
    page = context.new_page()
    try:
        page.goto(address)
        page.locator(".topbar-title").wait_for()
        page.get_by_role("button", name="Settings").click()
        page.get_by_role("tab", name="Notifications", exact=True).click()
        page.get_by_role("button", name="Enable browser notifications", exact=True).click()
        expect(page.get_by_text("Browser notifications are enabled.", exact=True)).to_be_visible()
        expect(
            page.get_by_role("button", name="Enable browser notifications", exact=True)
        ).to_have_count(0)
        page.screenshot(
            path="test-results/notifications-settings.png",
            full_page=True,
            animations="disabled",
        )
    finally:
        context.close()

