"""
MYVOICE — SECURE EMAIL DELIVERY

Sends security notification emails (Developer Recovery Credential delivery and
post-recovery alerts) to the authorized developer's security email address.

Configuration is read exclusively from environment variables so that SMTP
credentials are never committed to source control::

    MYVOICE_SECURITY_EMAIL     Recipient developer security email
    MYVOICE_SMTP_HOST          SMTP server hostname (e.g. smtp.gmail.com)
    MYVOICE_SMTP_PORT          SMTP port (default 587)
    MYVOICE_SMTP_USER          SMTP username (often the sender address)
    MYVOICE_SMTP_PASSWORD      SMTP password / application password
    MYVOICE_SMTP_FROM          From address (defaults to SMTP_USER)

If no SMTP host is configured the system falls back to writing the message to
the secure server log so the developer can retrieve it without ever exposing
the credential to the frontend or persisting it in the database.
"""

import os
import smtplib
from email.message import EmailMessage

DEV_SECURITY_EMAIL_ENV = "MYVOICE_SECURITY_EMAIL"
DEV_SECURITY_EMAIL_FALLBACK = "mbonyimagervais@gmail.com"


def developer_security_email():
    """Return the configured developer security email (recipient)."""
    return os.environ.get(
        DEV_SECURITY_EMAIL_ENV,
        DEV_SECURITY_EMAIL_FALLBACK
    )


def is_smtp_configured():
    return bool(os.environ.get("MYVOICE_SMTP_HOST", "").strip())


def _is_smtp_configured():
    return is_smtp_configured()


def _send_via_smtp(subject, text_body, recipient):
    """Deliver a message through SMTP. Returns True on success, False on failure."""
    host = os.environ.get("MYVOICE_SMTP_HOST")
    port = int(os.environ.get("MYVOICE_SMTP_PORT", "587"))
    user = os.environ.get("MYVOICE_SMTP_USER", "").strip()
    password = os.environ.get("MYVOICE_SMTP_PASSWORD", "")
    from_addr = (
        os.environ.get("MYVOICE_SMTP_FROM", "").strip()
        or (user or "no-reply@myvoice.local")
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = recipient
    msg.set_content(text_body)

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.ehlo()
        if server.has_extn("STARTTLS"):
            server.starttls()
            server.ehlo()
        if user:
            server.login(user, password)
        server.send_message(msg)
    return True


def send_email(subject, text_body, to_email):
    """Send a general email to any recipient.

    Returns a tuple (sent: bool, error: str|None).

    - If SMTP is NOT configured: the message is written to the secure server
      console so a developer can see it during local development. This is a
      visible fallback — the system never claims the email was delivered.
    - If SMTP IS configured but sending fails: (False, error) is returned and
      the caller records the failure in the audit log.
    """
    recipient = (to_email or "").strip()
    if not recipient:
        return False, "No recipient address provided."

    if not is_smtp_configured():
        print("[MYVOICE-EMAIL] *** SMTP NOT CONFIGURED - development fallback ***")
        print("[MYVOICE-EMAIL] To: %s" % recipient)
        print("[MYVOICE-EMAIL] Subject: %s" % subject)
        print("[MYVOICE-EMAIL] Body:\n%s" % text_body)
        return False, "SMTP is not configured."

    try:
        _send_via_smtp(subject, text_body, recipient)
        return True, None
    except Exception as exc:  # noqa: BLE001 - must never break the auth flow
        print("[MYVOICE-EMAIL] Failed to send email to %s: %s" % (recipient, exc))
        return False, str(exc)


def send_password_reset_email(to_email, reset_url, account_name, account_label):
    """Send a secure single-use password reset link.

    Returns True only when the email was actually delivered by SMTP. The
    reset token is never stored in plaintext and is never shown in the body of
    any email other than the secure reset link URL.
    """
    subject = "MyVoice — Password Reset Request"
    body = (
        "MYVOICE — PASSWORD RESET\n\n"
        "Hello {0},\n\n"
        "A password reset was requested for your {1} account.\n\n"
        "Open this link to choose a new password (it expires in 30 minutes and "
        "can only be used once):\n\n{2}\n\n"
        "If you did not request a password reset, you can safely ignore this "
        "message. Your password has not been changed.\n\n"
        "Security note: MyVoice never stores or emails plain-text passwords."
    ).format(account_name or "there", account_label, reset_url)

    sent, error = send_email(subject, body, to_email)
    return sent


def send_security_email(subject, text_body, to_email=None):
    """
    Deliver a security notification message.

    Returns True if the message was sent successfully (or was written to the
    secure server log as a development fallback), False otherwise. The plaintext
    delivered here (which may contain the recovery credential) is intentionally
    NOT written to the database, browser, session, cookie, or frontend.
    """
    recipient = (to_email or developer_security_email()).strip()
    if not recipient:
        return False

    if not _is_smtp_configured():
        # Development / no-SMTP fallback: secure server log only.
        print("[MYVOICE-SECURITY-EMAIL] To: %s" % recipient)
        print("[MYVOICE-SECURITY-EMAIL] Subject: %s" % subject)
        print("[MYVOICE-SECURITY-EMAIL] Body:\n%s" % text_body)
        return True

    try:
        host = os.environ.get("MYVOICE_SMTP_HOST")
        port = int(os.environ.get("MYVOICE_SMTP_PORT", "587"))
        user = os.environ.get("MYVOICE_SMTP_USER", "").strip()
        password = os.environ.get("MYVOICE_SMTP_PASSWORD", "")
        from_addr = (
            os.environ.get("MYVOICE_SMTP_FROM", "").strip()
            or (user or "no-reply@myvoice.local")
        )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = recipient
        msg.set_content(text_body)

        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            if server.has_extn("STARTTLS"):
                server.starttls()
                server.ehlo()
            if user:
                server.login(user, password)
            server.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 - must never break recovery UX
        print("[MYVOICE-SECURITY-EMAIL] Failed to send email: %s" % exc)
        return False
