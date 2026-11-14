from playwright.sync_api import expect


def test_chrome_109_uses_simple_motion_and_dom_find_highlights(browser, live_app):
    address, _, _ = live_app
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    context.add_init_script("""
      AbortSignal.any = undefined;
      Array.prototype.toSorted = undefined;
      Array.prototype.toReversed = undefined;
      window.CSS = undefined;
      window.Highlight = undefined;
    """)
    page = context.new_page()
    try:
        page.goto(address)
        expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
        result = page.evaluate("""() => ({
          compat: typeof window.TalariaCompat,
          simpleMotion: window.TalariaCompat?.simpleMotion,
          motion: document.documentElement.dataset.motion,
          spinnerRule: getComputedStyle(document.body).getPropertyValue('--talaria-motion-mode'),
          workingRule: getComputedStyle(document.documentElement).getPropertyValue('--talaria-motion-mode'),
          highlights: typeof CSS !== 'undefined' && !!CSS.highlights,
        })""")
        assert result == {
            "compat": "object",
            "simpleMotion": True,
            "motion": "simple",
            "spinnerRule": "simple",
            "workingRule": "simple",
            "highlights": False,
        }
    finally:
        context.close()
