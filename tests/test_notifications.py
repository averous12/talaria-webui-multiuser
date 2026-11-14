def test_native_notification_transition_decisions(browser, live_app):
    address, _, _ = live_app
    page = browser.new_page()
    try:
        page.goto(address)
        result = page.evaluate(
            """
            async () => {
              const n = await import('/static/notifications.js');
              const completed = n.notificationForTransition(
                { id: 'run-1', status: 'running' },
                { id: 'run-1', status: 'completed' },
                { title: 'Recipe chat' },
              );
              const clarification = n.notificationForTransition(
                { id: 'run-2', status: 'running', clarification: null },
                { id: 'run-2', status: 'waiting_for_input', clarification: {
                  request_id: 'question-1', question: 'Which citrus should I use?'
                } },
                { title: 'Recipe chat' },
              );
              const repeat = n.notificationForTransition(
                { id: 'run-1', status: 'completed' },
                { id: 'run-1', status: 'completed' },
                { title: 'Recipe chat' },
              );
              return { completed, clarification, repeat };
            }
            """
        )
        assert result["completed"] == {
            "kind": "completed",
            "tag": "run-complete-run-1",
            "title": "Response complete",
            "body": "Recipe chat is ready.",
        }
        assert result["clarification"] == {
            "kind": "clarification",
            "tag": "clarification-question-1",
            "title": "Your agent needs input",
            "body": "Which citrus should I use?",
        }
        assert result["repeat"] is None
    finally:
        page.close()


def test_native_notification_only_shows_when_unfocused_and_granted(browser, live_app):
    address, _, _ = live_app
    page = browser.new_page()
    try:
        page.goto(address)
        result = page.evaluate(
            """
            async () => {
              const n = await import('/static/notifications.js');
              const original = window.Notification;
              const calls = [];
              window.Notification = class {
                static permission = 'granted';
                constructor(title, options) { calls.push({ title, options }); }
              };
              const unfocused = n.showNotificationForTransition(
                'sid-1', { id: 'run-1', status: 'running' },
                { id: 'run-1', status: 'completed' }, { title: 'Recipe chat' },
                { focused: false },
              );
              const focused = n.showNotificationForTransition(
                'sid-2', { id: 'run-2', status: 'running' },
                { id: 'run-2', status: 'completed' }, { title: 'Focused chat' },
                { focused: true },
              );
              window.Notification = original;
              return { unfocused, focused, calls };
            }
            """
        )
        assert result["unfocused"] is True
        assert result["focused"] is False
        assert len(result["calls"]) == 1
        assert result["calls"][0] == {
            "title": "Response complete",
            "options": {
                "body": "Recipe chat is ready.",
                "tag": "run-complete-run-1",
            },
        }
    finally:
        page.close()
