import asyncio


def test_letter_records_quality_rejection_without_smtp(monkeypatch):
    from core.mail import letter_writer as generator
    from core.scheduler.triggers import letter_writer

    events = []
    async def generate(*_args, **_kwargs):
        return "具体内容" * 50
    async def evaluate(_letter):
        return 1

    monkeypatch.setattr(generator, "generate_letter", generate)
    monkeypatch.setattr(generator, "evaluate_letter", evaluate)
    monkeypatch.setattr("core.mail.execution_ledger.append", lambda **row: events.append(row))
    result = asyncio.run(letter_writer._send_letter_if_worthy("u", "c", "reason", execution_id="exec-1"))

    assert result.sent is False
    assert [(row["stage"], row.get("failure_code", "")) for row in events] == [
        ("selected", ""), ("generated", ""), ("quality_rejected", "quality_rejected"),
    ]


def test_letter_records_smtp_failure_metadata(monkeypatch):
    from core.mail import mail_sender
    from core.mail import letter_writer as generator
    from core.scheduler.triggers import letter_writer

    events = []
    async def generate(*_args, **_kwargs):
        return "具体内容" * 50
    async def evaluate(_letter):
        return 5
    async def send(*_args, **_kwargs):
        return mail_sender.MailSendResult(False, "smtp_timeout", "TimeoutError")

    monkeypatch.setattr(generator, "generate_letter", generate)
    monkeypatch.setattr(generator, "evaluate_letter", evaluate)
    monkeypatch.setattr(mail_sender, "send_letter_detailed", send)
    monkeypatch.setattr("core.mail.execution_ledger.append", lambda **row: events.append(row))
    monkeypatch.setattr("core.scheduler.loop._record_attempt_failure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("core.scheduler.execution.write_execute_blocked", lambda *_args, **_kwargs: None)
    result = asyncio.run(letter_writer._send_letter_if_worthy("u", "c", "reason", execution_id="exec-2"))

    assert result.sent is False
    assert events[-1]["stage"] == "smtp_failed"
    assert events[-1]["failure_code"] == "smtp_timeout"
    assert events[-1]["exception_type"] == "TimeoutError"
