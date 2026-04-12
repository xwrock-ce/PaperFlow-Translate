from __future__ import annotations

import asyncio
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.main import main


def build_settings():
    return CLIEnvSettingsModel().to_settings_model()


def test_main_without_input_files_prints_guidance(
    capsys,
    monkeypatch,
):
    settings = build_settings()
    parser = Mock()
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    monkeypatch.setattr("pdf2zh_next.main.build_args_parser", lambda: (parser, {}))
    warmup_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.babeldoc.assets.assets.warmup", warmup_mock)

    exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "No input PDF was provided." in captured.err
    parser.print_help.assert_called_once()
    warmup_mock.assert_not_called()


def test_main_warmup_mode_exits_after_warmup(capsys, monkeypatch):
    settings = build_settings()
    settings.basic.warmup = True
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    warmup_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.babeldoc.assets.assets.warmup", warmup_mock)
    translate_mock = AsyncMock()
    monkeypatch.setattr("pdf2zh_next.main.do_translate_file_async", translate_mock)

    exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "BabelDOC assets are ready." in captured.out
    warmup_mock.assert_called_once()
    translate_mock.assert_not_called()


def test_main_generates_offline_assets(monkeypatch):
    settings = build_settings()
    settings.basic.generate_offline_assets = "~/offline-assets"
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    generate_mock = Mock()
    monkeypatch.setattr(
        "pdf2zh_next.main.babeldoc.assets.assets.generate_offline_assets_package",
        generate_mock,
    )

    exit_code = asyncio.run(main())

    assert exit_code == 0
    generate_mock.assert_called_once_with(Path("~/offline-assets").expanduser())


def test_main_restores_offline_assets(monkeypatch):
    settings = build_settings()
    settings.basic.restore_offline_assets = "~/offline-assets.zip"
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    restore_mock = Mock()
    monkeypatch.setattr(
        "pdf2zh_next.main.babeldoc.assets.assets.restore_offline_assets_package",
        restore_mock,
    )

    exit_code = asyncio.run(main())

    assert exit_code == 0
    restore_mock.assert_called_once_with(Path("~/offline-assets.zip").expanduser())


def test_main_reports_gui_startup_failure(capsys, monkeypatch):
    settings = build_settings()
    settings.basic.gui = True
    settings.gui_settings.server_host = "0.0.0.0"
    settings.gui_settings.server_port = 9000
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    warmup_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.babeldoc.assets.assets.warmup", warmup_mock)
    setup_gui_mock = AsyncMock(side_effect=RuntimeError("no local port was available"))
    monkeypatch.setattr("pdf2zh_next.web.setup_gui", setup_gui_mock)

    exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Failed to start GUI: no local port was available" in captured.err
    assert "Retry the GUI with --server-port <free-port>" in captured.err
    warmup_mock.assert_not_called()
    setup_gui_mock.assert_awaited_once_with(server_host="0.0.0.0", server_port=9000)


def test_main_returns_non_zero_when_translation_reports_errors(monkeypatch, tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    settings = build_settings()
    settings.basic.input_files = {str(pdf_path)}
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    warmup_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.babeldoc.assets.assets.warmup", warmup_mock)
    translate_mock = AsyncMock(return_value=1)
    monkeypatch.setattr("pdf2zh_next.main.do_translate_file_async", translate_mock)

    exit_code = asyncio.run(main())

    assert exit_code == 1
    warmup_mock.assert_called_once()
    translate_mock.assert_awaited_once_with(settings, ignore_error=True)


def test_main_reports_connectivity_hint_for_default_service(
    capsys, monkeypatch, tmp_path
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    settings = build_settings()
    settings.basic.input_files = {str(pdf_path)}
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    warmup_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.babeldoc.assets.assets.warmup", warmup_mock)
    translate_mock = AsyncMock(
        side_effect=RuntimeError("ConnectError: [Errno 1] Operation not permitted")
    )
    monkeypatch.setattr("pdf2zh_next.main.do_translate_file_async", translate_mock)

    exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "SiliconFlowFree service could not be reached" in captured.err
    warmup_mock.assert_called_once()
    translate_mock.assert_awaited_once_with(settings, ignore_error=True)


def test_main_rejects_invalid_pdf_before_warmup(capsys, monkeypatch, tmp_path):
    fake_pdf = tmp_path / "broken.pdf"
    fake_pdf.write_text("not-a-real-pdf")

    settings = build_settings()
    settings.basic.input_files = {str(fake_pdf)}
    settings.translate_engine_settings = SimpleNamespace(
        validate_settings=lambda: None,
        translate_engine_type="OpenAI",
    )
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    warmup_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.babeldoc.assets.assets.warmup", warmup_mock)
    translate_mock = AsyncMock()
    monkeypatch.setattr("pdf2zh_next.main.do_translate_file_async", translate_mock)

    exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "not a valid PDF document" in captured.err
    assert "Pass an existing PDF file" in captured.err
    warmup_mock.assert_not_called()
    translate_mock.assert_not_called()


def test_main_expands_directory_inputs_before_translation(monkeypatch, tmp_path):
    pdf_directory = tmp_path / "pdfs"
    nested_directory = pdf_directory / "nested"
    nested_directory.mkdir(parents=True)
    first_pdf = pdf_directory / "a.pdf"
    second_pdf = nested_directory / "b.PDF"
    first_pdf.write_bytes(b"%PDF-1.4\n")
    second_pdf.write_bytes(b"%PDF-1.4\n")

    settings = build_settings()
    settings.basic.input_files = {str(pdf_directory)}
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    warmup_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.babeldoc.assets.assets.warmup", warmup_mock)

    async def fake_translate(resolved_settings, ignore_error):
        assert ignore_error is True
        assert resolved_settings.basic.input_files == {
            str(first_pdf),
            str(second_pdf),
        }
        return 0

    translate_mock = AsyncMock(side_effect=fake_translate)
    monkeypatch.setattr("pdf2zh_next.main.do_translate_file_async", translate_mock)

    exit_code = asyncio.run(main())

    assert exit_code == 0
    warmup_mock.assert_called_once()
    translate_mock.assert_awaited_once()


def test_main_reports_empty_input_directory(capsys, monkeypatch, tmp_path):
    empty_directory = tmp_path / "empty"
    empty_directory.mkdir()

    settings = build_settings()
    settings.basic.input_files = {str(empty_directory)}
    init_config = Mock(return_value=settings)
    monkeypatch.setattr(
        "pdf2zh_next.main.ConfigManager.initialize_config",
        init_config,
    )
    warmup_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.babeldoc.assets.assets.warmup", warmup_mock)
    translate_mock = AsyncMock()
    monkeypatch.setattr("pdf2zh_next.main.do_translate_file_async", translate_mock)

    exit_code = asyncio.run(main())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "No PDF files were found in directory" in captured.err
    assert "Run `pdf2zh_next --help` for usage details." in captured.err
    warmup_mock.assert_not_called()
    translate_mock.assert_not_called()


def test_python_module_entrypoint_calls_cli(monkeypatch):
    cli_mock = Mock()
    monkeypatch.setattr("pdf2zh_next.main.cli", cli_mock)

    runpy.run_module("pdf2zh_next", run_name="__main__")

    cli_mock.assert_called_once_with()
