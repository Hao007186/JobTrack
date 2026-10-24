import logging
import smtplib
from email.message import EmailMessage as MimeMessage
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.notifications.email import (
    ConsoleEmailSender,
    EmailError,
    EmailMessage,
    SmtpEmailSender,
    get_email_sender,
)

PASSWORD = "secret-pw"
MESSAGE = EmailMessage(
    to="alice@example.com", subject="TPE→NRT：跌破目標價", text="目前最低價 NT$9,000。"
)


class FakeSMTP:
    instances: list[FakeSMTP] = []
    fail_login: Exception | None = None

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.login_args: tuple[str, str] | None = None
        self.sent: list[MimeMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("quit")

    def starttls(self, **kwargs: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append("login")
        if FakeSMTP.fail_login is not None:
            raise FakeSMTP.fail_login
        self.login_args = (user, password)

    def send_message(self, msg: MimeMessage) -> None:
        self.calls.append("send_message")
        self.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.fail_login = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def _sender() -> SmtpEmailSender:
    return SmtpEmailSender(
        host="smtp.resend.com",
        port=587,
        username="resend",
        password=SecretStr(PASSWORD),
        from_addr="FareWatch <alert@example.com>",
    )


async def test_get_email_sender() -> None:
    assert isinstance(get_email_sender(Settings(_env_file=None)), ConsoleEmailSender)
    smtp_settings = Settings(
        _env_file=None,
        email_sender="smtp",
        smtp_host="smtp.resend.com",
        smtp_username="resend",
        smtp_password=SecretStr(PASSWORD),
        email_from="FareWatch <alert@example.com>",
    )
    assert isinstance(get_email_sender(smtp_settings), SmtpEmailSender)


async def test_console_sender_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        await ConsoleEmailSender().send(MESSAGE)
    assert "alice@example.com" in caplog.text
    assert MESSAGE.subject in caplog.text


async def test_smtp_sender_sends(fake_smtp: type[FakeSMTP]) -> None:
    await _sender().send(MESSAGE)

    smtp = fake_smtp.instances[0]
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.resend.com", 587, 30)
    assert smtp.calls == ["starttls", "login", "send_message", "quit"]
    assert smtp.login_args == ("resend", PASSWORD)
    msg = smtp.sent[0]
    assert msg["From"] == "FareWatch <alert@example.com>"
    assert msg["To"] == "alice@example.com"
    assert msg["Subject"] == MESSAGE.subject
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content().strip() == MESSAGE.text


async def test_smtp_error_masks_password(fake_smtp: type[FakeSMTP]) -> None:
    fake_smtp.fail_login = smtplib.SMTPAuthenticationError(535, f"bad {PASSWORD}".encode())
    with pytest.raises(EmailError) as exc:
        await _sender().send(MESSAGE)
    assert PASSWORD not in str(exc.value)
    assert "***" in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__

    fake_smtp.fail_login = OSError(f"connection reset {PASSWORD}")
    with pytest.raises(EmailError) as exc:
        await _sender().send(MESSAGE)
    assert PASSWORD not in str(exc.value)
