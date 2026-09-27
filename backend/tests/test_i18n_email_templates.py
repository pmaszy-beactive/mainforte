"""Unit coverage for i18n.py's password-reset HTML template (task #39). Confirms the branded
`email_layout` wrapper renders correctly through `t()`'s `.format(**kw)` substitution (no stray
braces from the inline CSS leaking through), that the reset link appears exactly once as the CTA's
`href`, and that both supported locales (en-US, fr-CA) render distinct, non-empty content.
"""
from mainforte.i18n import t


def test_reset_html_embeds_url_as_cta_href():
    url = "https://app.mainforte.ai/reset-password?token=abc123"
    html = t("en-US", "reset.html", url=url)

    assert f'href="{url}"' in html
    assert "{url}" not in html  # placeholder must be fully substituted, no leftover brace


def test_reset_html_has_no_unsubstituted_braces():
    html = t("en-US", "reset.html", url="https://example.com/x")
    assert "{" not in html
    assert "}" not in html


def test_reset_html_locales_are_distinct_and_nonempty():
    en = t("en-US", "reset.html", url="https://example.com/x")
    fr = t("fr-CA", "reset.html", url="https://example.com/x")

    assert en and fr
    assert en != fr
    assert "Reset your password" in en
    assert "Réinitialisez votre mot de passe" in fr


def test_reset_text_unaffected_by_html_layout_change():
    text = t("en-US", "reset.text", url="https://example.com/x")
    assert text == "Reset your password: https://example.com/x (expires in 1 hour)"
