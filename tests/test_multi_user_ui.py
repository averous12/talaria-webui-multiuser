from talaria.auth import issue_cookie

from .test_app import signed_in


def test_regular_user_settings_are_limited_to_three_sections(browser, live_app):
    url, _, app = live_app
    with signed_in(url) as admin:
        created = admin.post(
            "/api/users",
            json={
                "username": "settings-user",
                "password": "settings-password",
                "role": "user",
                "profile_id": "default",
            },
        )
        assert created.status_code == 201
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    context.add_cookies([
        {
            "name": app.state.cookie_name,
            "value": issue_cookie(app.state.settings, str(created.json()["id"])),
            "url": url,
            "httpOnly": True,
            "sameSite": "Strict",
        }
    ])
    page = context.new_page()
    try:
        page.goto(url)
        page.locator(".topbar-title").wait_for()
        page.get_by_role("button", name="Settings").click()
        assert page.get_by_role("tab").all_inner_texts() == [
            "Your agent", "Appearance", "Notifications"
        ]
        page.get_by_role("button", name="Close dialog").click()
        assert page.locator(".agent-switcher").count() == 0
    finally:
        context.close()


def test_user_agent_presentation_overlays_branding(page):
    page.evaluate(
        """async () => {
        const bootstrap = await fetch('/api/bootstrap').then((response) => response.json());
        const response = await fetch('/api/agent/presentation', {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': bootstrap.csrf,
                'X-Talaria-Request': '1',
            },
            body: JSON.stringify({ name: 'Aurora User', icon: 'prism' }),
        });
        if (!response.ok) throw new Error(await response.text());
        }"""
    )
    page.reload()
    page.locator(".topbar-title").wait_for()
    assert page.locator(".profile-button .avatar svg path").get_attribute("d") == (
        "M6 4h12l3 6-9 10-9-10zM6 4l6 6 6-6M12 10v10M3 10h18"
    )
    page.get_by_role("button", name="Settings").click()
    assert page.locator(".agent-identity h3").inner_text() == "Aurora User"
    assert page.locator(".agent-monogram svg path").get_attribute("d") == (
        "M6 4h12l3 6-9 10-9-10zM6 4l6 6 6-6M12 10v10M3 10h18"
    )
    page.get_by_role("button", name="Close dialog").click()
    assert page.locator("textarea[placeholder='Message Aurora User']").count() == 1


def test_admin_settings_new_surfaces_match_existing_dialog(page):
    page.get_by_role("button", name="Settings").click()
    page.get_by_role("tab", name="Users").click()
    page.locator(".users-panel").wait_for()
    page.locator(".user-row").first.wait_for()
    assert page.locator(".user-monogram").count() >= 1
    assert page.locator(".user-actions .status-badge").count() >= 1
    page.get_by_role("tab", name="Notifications").click()
    page.locator(".notification-settings").wait_for()
    assert (
        page.locator(".settings-status-group").count() == 1
        or page.locator(".setting-actions").count() >= 1
        or page.get_by_role("button", name="Enable browser notifications").count() == 1
        or page.get_by_text("This browser does not support native notifications.").count() == 1
        or page.get_by_text(
            "Notifications are blocked. Allow them in your browser settings."
        ).count() == 1
    )
