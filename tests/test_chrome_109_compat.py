from playwright.sync_api import expect


def test_chrome_109_bootstrap_with_missing_modern_apis(browser, live_app):
    address, _, _ = live_app
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    context.add_init_script("""
      AbortSignal.any = undefined;
      Array.prototype.toSorted = undefined;
      Array.prototype.toReversed = undefined;
    """)
    page = context.new_page()
    try:
        page.goto(address)
        expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
        expect(page.get_by_label("Password")).to_be_visible()
        values = page.evaluate("""() => ({
          any: typeof AbortSignal.any,
          sorted: [3, 1, 2].toSorted().join(','),
          reversed: [1, 2, 3].toReversed().join(','),
        })""")
        assert values == {"any": "function", "sorted": "1,2,3", "reversed": "3,2,1"}
    finally:
        context.close()
