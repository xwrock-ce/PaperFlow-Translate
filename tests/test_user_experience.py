from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.main import build_args_parser
from pdf2zh_next.high_level import validate_pdf_file
from pdf2zh_next.main import main


class _DummyParser:
    def print_help(self, file) -> None:
        print("usage: pdf2zh_next [options] input.pdf", file=file)


def _make_temp_pdf(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    return pdf_path


def _make_invalid_pdf(tmp_path):
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_text("not-a-real-pdf")
    return pdf_path


def _make_openai_settings(**kwargs):
    return CLIEnvSettingsModel(
        openai=True,
        openai_detail={"openai_api_key": "test-key"},
        **kwargs,
    ).to_settings_model()


def test_validate_settings_allows_gui_without_translation_engine():
    settings = CLIEnvSettingsModel(basic={"gui": True})
    settings.validate_settings()


def test_validate_settings_allows_version_without_translation_engine():
    settings = CLIEnvSettingsModel(basic={"version": True})
    settings.validate_settings()


def test_validate_settings_rejects_invalid_pages_early(tmp_path):
    temp_pdf_file = _make_temp_pdf(tmp_path)
    settings = _make_openai_settings(
        basic={"input_files": {str(temp_pdf_file)}},
        pdf={"pages": "abc"},
    )

    with pytest.raises(ValueError, match="Error parsing pages parameter"):
        settings.validate_settings()


def test_validate_pdf_file_rejects_fake_pdf_content(tmp_path):
    fake_pdf = _make_invalid_pdf(tmp_path)

    with pytest.raises(ValueError, match="valid PDF document"):
        validate_pdf_file(fake_pdf)


def test_main_returns_usage_error_without_input(capsys):
    settings = _make_openai_settings()
    parser = _DummyParser()

    with (
        patch("pdf2zh_next.main.ConfigManager.initialize_config", return_value=settings),
        patch("pdf2zh_next.main.build_args_parser", return_value=(parser, {})),
        patch("pdf2zh_next.main.babeldoc.assets.assets.warmup") as warmup_mock,
    ):
        exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "No input PDF was provided." in captured.err
    assert "usage: pdf2zh_next" in captured.err
    warmup_mock.assert_not_called()


def test_main_warmup_mode_skips_input_requirement():
    settings = CLIEnvSettingsModel(basic={"warmup": True}).to_settings_model()

    with patch(
        "pdf2zh_next.main.ConfigManager.initialize_config", return_value=settings
    ), patch("pdf2zh_next.main.babeldoc.assets.assets.warmup") as warmup_mock:
        exit_code = asyncio.run(main())

    assert exit_code == 0
    warmup_mock.assert_called_once()


def test_main_returns_non_zero_when_translation_reports_failures(
    capsys,
    tmp_path,
):
    temp_pdf_file = _make_temp_pdf(tmp_path)
    settings = _make_openai_settings(basic={"input_files": {str(temp_pdf_file)}})

    with (
        patch("pdf2zh_next.main.ConfigManager.initialize_config", return_value=settings),
        patch("pdf2zh_next.main.babeldoc.assets.assets.warmup"),
        patch("pdf2zh_next.main.do_translate_file_async", return_value=2),
    ):
        exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Translation finished with 2 failed file(s)." in captured.err


def test_main_reports_configuration_errors_cleanly(capsys):
    with patch(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        side_effect=ValueError("Must provide a translation service"),
    ):
        exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Error: Must provide a translation service" in captured.err
    assert "Run `pdf2zh_next --help` for usage details." in captured.err


def test_cli_help_highlights_folder_input_for_first_run():
    parser, _ = build_args_parser()

    help_text = parser.format_help()

    assert "Quick start:" in help_text
    assert "pdf2zh_next ./papers --output ./translated" in help_text
    assert "folders of PDFs" in help_text
