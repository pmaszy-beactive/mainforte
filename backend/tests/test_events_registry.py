from mainforte.events.registry import handlers_for, on
from mainforte.events.types import EVENT_TYPES, is_known


def test_taxonomy_has_every_namespace():
    prefixes = {t.split(".")[0] for t in EVENT_TYPES}
    for ns in ("connection", "session", "user", "workspace", "billing", "chat", "persona", "task",
               "agent", "tool", "browser", "build", "widget", "worker", "system"):
        assert ns in prefixes, ns
    assert is_known("chat.message.created")
    assert not is_known("nope.nothing")


def test_glob_registration():
    calls = []

    @on("task.*", sync=True)
    def h(ev):
        calls.append(ev["type"])

    names = [r.name for r in handlers_for("task.blocked")]
    assert any(n.endswith("test_glob_registration.<locals>.h") for n in names)
    assert not any(n.endswith("test_glob_registration.<locals>.h") for n in [r.name for r in handlers_for("chat.message.created")])


def test_i18n_normalize():
    from mainforte.i18n import normalize_locale, t, valid_timezone
    assert normalize_locale("fr") == "fr-CA"
    assert normalize_locale("fr-FR") == "fr-CA"
    assert normalize_locale("en-GB") == "en-US"
    assert normalize_locale(None) == "en-US"
    assert valid_timezone("America/Toronto") and not valid_timezone("Mars/Olympus")
    assert "lien" in t("fr-CA", "magic.subject")
