from __future__ import annotations

import asyncio
import importlib
import socket
import sys
from unittest.mock import Mock

import pytest
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel


@pytest.fixture(scope="module")
def gui_module():
    original_argv = sys.argv[:]
    try:
        sys.argv = ["gui-test"]
        module = importlib.import_module("pdf2zh_next.gui")
        return importlib.reload(module)
    finally:
        sys.argv = original_argv


def test_decode_uploaded_text_file_reports_missing_encoding(gui_module, monkeypatch):
    monkeypatch.setattr(gui_module.chardet, "detect", lambda _: {})

    with pytest.raises(gui_module.gr.Error, match="Could not detect the encoding"):
        gui_module._decode_uploaded_text_file(b"source,target", file_label="glossary")


def test_build_glossary_list_creates_temp_csv_for_valid_upload(gui_module, monkeypatch):
    monkeypatch.setattr(gui_module.chardet, "detect", lambda _: {"encoding": "utf-8"})

    glossary_csv = "source,target\nhello,你好\n".encode()
    glossary_paths = gui_module._build_glossary_list([glossary_csv], "OpenAI")

    assert glossary_paths is not None
    assert glossary_paths.endswith(".csv")


def test_prepare_input_file_rejects_invalid_uploaded_pdf(gui_module, tmp_path):
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("not-a-real-pdf")

    with pytest.raises(gui_module.gr.Error, match="not a valid PDF"):
        gui_module._prepare_input_file("File", str(fake_pdf), "", tmp_path)


def test_prepare_input_file_rejects_invalid_link_format(gui_module, tmp_path):
    with pytest.raises(gui_module.gr.Error, match="http:// or https://"):
        gui_module._prepare_input_file("Link", "", "example.com/file.pdf", tmp_path)


def test_download_with_limit_rejects_non_pdf_content(gui_module, monkeypatch, tmp_path):
    class _FakeResponse:
        headers = {"Content-Disposition": 'attachment; filename="paper.pdf"'}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024):
            del chunk_size
            yield b"<html>not a pdf</html>"

    def _fake_get(*_args, **_kwargs):
        return _FakeResponse()

    monkeypatch.setattr(gui_module.requests, "get", _fake_get)

    with pytest.raises(gui_module.gr.Error, match="direct PDF link"):
        gui_module.download_with_limit("https://example.com/file.pdf", tmp_path)


def test_find_available_port_skips_busy_port(gui_module):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            busy_port = sock.getsockname()[1]

            available_port = gui_module._find_available_port(busy_port, search_window=5)
    except PermissionError:
        pytest.skip("Local socket binding is not available in this environment.")

    assert available_port is not None
    assert available_port != busy_port


def test_launch_demo_reports_blocked_port_probe(gui_module, monkeypatch):
    launch_mock = Mock(
        side_effect=OSError("Cannot find empty port in range: 7860-7860")
    )
    monkeypatch.setattr(gui_module.demo, "launch", launch_mock)
    monkeypatch.setattr(
        gui_module,
        "_find_available_port",
        Mock(
            side_effect=RuntimeError(
                "Local port probing is blocked in this environment."
            )
        ),
    )

    with pytest.raises(RuntimeError, match="fallback port probing is blocked"):
        gui_module._launch_demo_with_recovery(
            share=False,
            auth=None,
            auth_message=None,
            server_port=7860,
            inbrowser=False,
        )


def test_calculate_rate_limit_params_uses_current_concurrent_threads_key(gui_module):
    qps, pool_workers = gui_module._calculate_rate_limit_params(
        "Concurrent Threads",
        {"concurrent_threads": 55},
    )

    assert qps == 35
    assert pool_workers == 35


def test_calculate_rate_limit_params_uses_current_custom_keys(gui_module):
    qps, pool_workers = gui_module._calculate_rate_limit_params(
        "Custom",
        {"custom_qps": 17, "custom_pool_workers": 23},
    )

    assert qps == 17
    assert pool_workers == 23


def _build_base_gui_settings():
    return CLIEnvSettingsModel(
        openai=True,
        openai_detail={"openai_api_key": "test-key"},
    )


def _build_ui_inputs(base_settings, **overrides):
    ui_inputs = {
        "service": "OpenAI",
        "lang_from": "English",
        "lang_to": "Simplified Chinese",
        "page_range": "All",
        "page_input": "",
        "prompt": "",
        "ignore_cache": False,
        "no_mono": False,
        "no_dual": False,
        "dual_translate_first": False,
        "use_alternating_pages_dual": False,
        "watermark_output_mode": "Watermarked",
        "rate_limit_mode": "Custom",
        "min_text_length": 5,
        "rpc_doclayout": "",
        "enable_auto_term_extraction": True,
        "primary_font_family": "Auto",
        "skip_clean": False,
        "disable_rich_text_translate": False,
        "enhance_compatibility": False,
        "split_short_lines": False,
        "short_line_split_factor": 0.8,
        "translate_table_text": True,
        "skip_scanned_detection": False,
        "ocr_workaround": False,
        "max_pages_per_part": 0,
        "formular_font_pattern": "",
        "formular_char_pattern": "",
        "auto_enable_ocr_workaround": False,
        "only_include_translated_page": False,
        "merge_alternating_line_numbers": True,
        "remove_non_formula_lines": True,
        "non_formula_line_iou_threshold": 0.9,
        "figure_table_protection_threshold": 0.9,
        "skip_formula_offset_calculation": False,
        "term_service": "Follow main translation engine",
        "term_rate_limit_mode": "Custom",
        "term_rpm_input": 240,
        "term_concurrent_threads": 20,
        "term_custom_qps": 4,
        "term_custom_pool_workers": None,
        "custom_system_prompt_input": "",
        "glossaries": None,
        "save_auto_extracted_glossary": False,
    }
    ui_inputs.update(base_settings.openai_detail.model_dump())
    ui_inputs.update(overrides)
    return ui_inputs


def test_build_translate_settings_rejects_all_outputs_disabled(gui_module, tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    base_settings = _build_base_gui_settings()
    ui_inputs = _build_ui_inputs(base_settings, no_mono=True, no_dual=True)

    with pytest.raises(gui_module.gr.Error, match="Select at least one output format"):
        gui_module._build_translate_settings(
            base_settings,
            pdf_path,
            tmp_path,
            gui_module.SaveMode.never,
            ui_inputs,
        )


def test_build_page_range_feedback_surfaces_invalid_ranges(gui_module):
    update = gui_module._build_page_range_feedback("Range", "5-3")

    assert update["visible"] is True
    assert "Page range format is invalid" in update["value"]
    assert "Start page 5 is greater than end page 3" in update["value"]


def test_build_translate_settings_rejects_invalid_page_range_early(
    gui_module,
    tmp_path,
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    base_settings = _build_base_gui_settings()
    ui_inputs = _build_ui_inputs(
        base_settings,
        page_range="Range",
        page_input="abc",
    )

    with pytest.raises(gui_module.gr.Error, match="Page range format is invalid"):
        gui_module._build_translate_settings(
            base_settings,
            pdf_path,
            tmp_path,
            gui_module.SaveMode.never,
            ui_inputs,
        )


def test_build_term_extraction_visibility_updates_toggle_group(gui_module):
    info_update, group_update = gui_module._build_term_extraction_visibility_updates(
        False
    )

    assert info_update["visible"] is True
    assert group_update["visible"] is False


def test_build_hero_html_uses_translatable_copy(gui_module, monkeypatch):
    monkeypatch.setattr(gui_module, "_", lambda text: f"T:{text}")

    hero_html = gui_module.build_hero_html()

    assert "T:PDF Translation Workspace" in hero_html
    assert "T:PaperFlow Translate" in hero_html
    assert "T:Layout-safe output" in hero_html
    assert "T:Live progress pinned" in hero_html


def test_build_workspace_summary_uses_translatable_labels(gui_module, monkeypatch):
    monkeypatch.setattr(gui_module, "_", lambda text: f"T:{text}")

    summary_html = gui_module.build_workspace_summary(
        "File",
        None,
        None,
        "OpenAI",
        "English",
        "Simplified Chinese",
        False,
        False,
        "All",
        "",
        "No Watermark",
    )

    assert "summary-pill-source" in summary_html
    assert "T:Source" in summary_html
    assert "T:No source selected" in summary_html
    assert "T:Output" in summary_html
    assert "T:Mono + Dual" in summary_html
    assert "T:Watermark" in summary_html


def test_on_lang_selector_change_updates_static_copy(gui_module, monkeypatch):
    monkeypatch.setattr(gui_module, "_", lambda text: f"T:{text}")
    monkeypatch.setattr(gui_module, "update_current_languages", lambda _lang: None)
    monkeypatch.setattr(
        gui_module.config_manager,
        "write_user_default_config_file",
        lambda settings: settings,
    )

    updates = gui_module.on_lang_selector_change(
        "en",
        "File",
        None,
        None,
        "OpenAI",
        "English",
        "Simplified Chinese",
        False,
        False,
        "All",
        "",
        "Watermarked",
    )

    assert "T:PDF Translation Workspace" in updates[0]["value"]
    assert updates[1]["value"] == "## T:UI Language"
    assert updates[3]["value"] == "## T:Source & Pages"
    assert updates[17]["value"] == "T:## Preview"
    assert updates[18]["label"] == "T:Document Preview"
    assert "T:Source" in updates[19]


def test_i18n_lang_change_does_not_target_root_blocks(gui_module):
    on_lang_change_fns = [
        fn for fn in gui_module.demo.fns.values() if getattr(fn, "name", None) == "on_lang_change"
    ]

    assert on_lang_change_fns
    assert all(gui_module.demo not in fn.outputs for fn in on_lang_change_fns)


def test_stop_translate_file_uses_translatable_meta_labels(gui_module, monkeypatch):
    monkeypatch.setattr(gui_module, "_", lambda text: f"T:{text}")

    status_html, *_rest = gui_module.stop_translate_file(
        "OpenAI",
        "English",
        "Simplified Chinese",
    )

    assert "T:Engine" in status_html
    assert "T:Route" in status_html


def test_stop_translate_file_keeps_actions_disabled_until_task_stops(gui_module):
    _status, translate_update, cancel_update, save_update = (
        gui_module.stop_translate_file(
            "OpenAI",
            "English",
            "Simplified Chinese",
        )
    )

    assert translate_update["value"] == "Cancelling..."
    assert translate_update["interactive"] is False
    assert cancel_update["interactive"] is False
    assert save_update["interactive"] is False


def test_format_user_facing_error_hides_traceback_details(gui_module):
    message = gui_module._format_user_facing_error(
        "Engine initialization failed",
        "Traceback: stack line 1\nstack line 2",
    )

    assert "Traceback" not in message
    assert "Check the selected engine credentials" not in message


def test_format_user_facing_error_adds_default_service_network_hint(gui_module):
    message = gui_module._format_user_facing_error(
        "Translation subprocess initialization error: RetryError",
        "ConnectError: [Errno 1] Operation not permitted",
    )

    assert "SiliconFlowFree service could not be reached" in message


def test_translate_file_restores_source_preview_when_translation_fails(
    gui_module,
    monkeypatch,
    tmp_path,
):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        gui_module,
        "build_ui_inputs",
        lambda *_args: {
            "service": "OpenAI",
            "lang_from": "English",
            "lang_to": "Simplified Chinese",
        },
    )
    monkeypatch.setattr(
        gui_module,
        "_prepare_input_file",
        lambda *_args: pdf_path,
    )
    monkeypatch.setattr(
        gui_module,
        "_build_translate_settings",
        lambda *_args: object(),
    )

    async def failing_translation_task(*_args, **_kwargs):
        raise gui_module.gr.Error("network timeout")

    monkeypatch.setattr(gui_module, "_run_translation_task", failing_translation_task)

    async def collect_updates():
        updates = []
        with pytest.raises(gui_module.gr.Error, match="network timeout"):
            async for item in gui_module.translate_file(
                "File",
                str(pdf_path),
                "",
                progress=lambda *_args, **_kwargs: None,
            ):
                updates.append(item)
        return updates

    updates = asyncio.run(collect_updates())

    assert updates[-1][1] == str(pdf_path)


def test_translate_file_hides_raw_internal_errors(gui_module, monkeypatch, tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        gui_module,
        "build_ui_inputs",
        lambda *_args: {
            "service": "OpenAI",
            "lang_from": "English",
            "lang_to": "Simplified Chinese",
        },
    )

    def failing_prepare(*_args, **_kwargs):
        raise RuntimeError("database DSN=secret-value")

    monkeypatch.setattr(gui_module, "_prepare_input_file", failing_prepare)

    async def collect_updates():
        updates = []
        with pytest.raises(
            gui_module.gr.Error,
            match="unexpected internal error",
        ) as exc_info:
            async for item in gui_module.translate_file(
                "File",
                str(pdf_path),
                "",
                progress=lambda *_args, **_kwargs: None,
            ):
                updates.append(item)
        return updates, exc_info.value

    updates, error = asyncio.run(collect_updates())

    assert updates
    assert "database DSN=secret-value" not in str(error)
