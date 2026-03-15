from __future__ import annotations

import asyncio
import contextlib
import logging
from types import SimpleNamespace

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.high_level import do_translate_file_async


def _build_settings(*input_files: str):
    return CLIEnvSettingsModel(
        openai=True,
        openai_detail={"openai_api_key": "test-key"},
        basic={"input_files": set(input_files)},
    ).to_settings_model()


def test_do_translate_file_async_processes_files_in_sorted_order_and_logs_summary(
    monkeypatch,
    caplog,
):
    settings = _build_settings("b.pdf", "a.pdf")
    processed_files = []

    async def fake_do_translate_async_stream(_settings, file, *, raise_on_error=True):
        assert raise_on_error is False
        processed_files.append(str(file))
        if str(file) == "a.pdf":
            yield {
                "type": "finish",
                "translate_result": SimpleNamespace(
                    original_pdf_path="a.pdf",
                    total_seconds=1.25,
                    mono_pdf_path="a-mono.pdf",
                    dual_pdf_path=None,
                ),
                "token_usage": {},
            }
            return

        yield {
            "type": "error",
            "error": "network timeout",
            "error_type": "TimeoutError",
            "details": "",
        }

    monkeypatch.setattr(
        "pdf2zh_next.high_level.create_progress_handler",
        lambda _config: (contextlib.nullcontext(), lambda _event: None),
    )
    monkeypatch.setattr(
        "pdf2zh_next.high_level.do_translate_async_stream",
        fake_do_translate_async_stream,
    )

    with caplog.at_level(logging.INFO):
        error_count = asyncio.run(do_translate_file_async(settings, ignore_error=True))

    assert error_count == 1
    assert processed_files == ["a.pdf", "b.pdf"]
    assert "Batch translation summary: 1 succeeded, 1 failed." in caplog.text
    assert "OK a.pdf | mono=a-mono.pdf | dual=None" in caplog.text
    assert "FAIL b.pdf | network timeout" in caplog.text


def test_do_translate_file_async_keeps_original_input_files_and_uses_error_events(
    monkeypatch,
):
    settings = _build_settings("paper.pdf")

    async def fake_do_translate_async_stream(_settings, file, *, raise_on_error=True):
        assert _settings.basic.input_files == set()
        assert raise_on_error is False
        yield {
            "type": "finish",
            "translate_result": SimpleNamespace(
                original_pdf_path=str(file),
                total_seconds=0.5,
                mono_pdf_path="paper-mono.pdf",
                dual_pdf_path=None,
            ),
            "token_usage": {},
        }

    monkeypatch.setattr(
        "pdf2zh_next.high_level.create_progress_handler",
        lambda _config: (contextlib.nullcontext(), lambda _event: None),
    )
    monkeypatch.setattr(
        "pdf2zh_next.high_level.do_translate_async_stream",
        fake_do_translate_async_stream,
    )

    error_count = asyncio.run(do_translate_file_async(settings, ignore_error=True))

    assert error_count == 0
    assert settings.basic.input_files == {"paper.pdf"}


def test_do_translate_file_async_hides_verbose_error_details_without_debug(
    monkeypatch,
    caplog,
):
    settings = _build_settings("paper.pdf")

    async def fake_do_translate_async_stream(_settings, file, *, raise_on_error=True):
        assert str(file) == "paper.pdf"
        assert raise_on_error is False
        yield {
            "type": "error",
            "error": "network timeout",
            "error_type": "SubprocessError",
            "details": "Traceback: stack line 1\nstack line 2",
        }

    monkeypatch.setattr(
        "pdf2zh_next.high_level.create_progress_handler",
        lambda _config: (contextlib.nullcontext(), lambda _event: None),
    )
    monkeypatch.setattr(
        "pdf2zh_next.high_level.do_translate_async_stream",
        fake_do_translate_async_stream,
    )

    with caplog.at_level(logging.ERROR):
        error_count = asyncio.run(do_translate_file_async(settings, ignore_error=True))

    assert error_count == 1
    assert "Error details hidden. Rerun with --debug for full details." in caplog.text
    assert "Traceback: stack line 1" not in caplog.text
