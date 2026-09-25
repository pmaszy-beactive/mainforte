from __future__ import annotations

import logging

from mainforte.config import get_settings
from mainforte.i18n import t

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    s = get_settings()
    if not s.sendgrid_api_key:
        log.warning("SENDGRID_API_KEY unset; email to %s not sent.\nSubject: %s\n%s", to, subject, text or html)
        return False
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    msg = Mail(from_email=s.mail_default_sender, to_emails=to, subject=subject, html_content=html, plain_text_content=text)
    try:
        resp = SendGridAPIClient(s.sendgrid_api_key).send(msg)
        return 200 <= resp.status_code < 300
    except Exception:
        log.exception("sendgrid send failed")
        return False


def send_magic_link(to: str, url: str, *, locale: str | None = None) -> bool:
    return send_email(to, t(locale, "magic.subject"), t(locale, "magic.html", url=url), t(locale, "magic.text", url=url))


def send_password_reset(to: str, url: str, *, locale: str | None = None) -> bool:
    return send_email(to, t(locale, "reset.subject"), t(locale, "reset.html", url=url), t(locale, "reset.text", url=url))
