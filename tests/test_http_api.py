from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.http_api import create_app


def _assert_localized_text(value: dict[str, str]) -> None:
    assert value["en"]
    assert value["zh"]


def _client() -> TestClient:
    return TestClient(create_app())


def _make_pdf(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    return pdf_path


def _base_openai_settings() -> CLIEnvSettingsModel:
    return CLIEnvSettingsModel(
        openai=True,
        openai_detail={"openai_api_key": "test-key"},
    )


def _build_frontend_default_payload(app_config: dict, *, service_name: str) -> dict:
    def build_values(fields):
        values = {}
        for field in fields:
            if field["default"] is not None:
                values[field["name"]] = field["default"]
            elif field["type"] == "boolean":
                values[field["name"]] = False
            else:
                values[field["name"]] = ""
        return values

    service = next(
        item for item in app_config["services"] if item["name"] == service_name
    )
    return {
        "translation": build_values(app_config["translation_fields"]),
        "pdf": build_values(app_config["pdf_fields"]),
        "engine_settings": build_values(service["fields"]),
    }


def test_healthz_returns_status_and_version():
    response = _client().get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"]
    assert payload["default_config_file"].endswith(".toml")


def test_engines_lists_known_services():
    response = _client().get("/engines")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_service"] == "SiliconFlowFree"
    assert any(item["name"] == "OpenAI" for item in payload["engines"])


def test_app_config_returns_frontend_form_schema():
    response = _client().get("/app/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_service"] == "SiliconFlowFree"
    assert payload["default_locale"] == "en"
    assert any(service["name"] == "OpenAI" for service in payload["services"])
    ignore_cache = next(
        field
        for field in payload["translation_fields"]
        if field["name"] == "ignore_cache"
    )
    _assert_localized_text(ignore_cache["label"])
    openai_api_key = next(
        field
        for service in payload["services"]
        if service["name"] == "OpenAI"
        for field in service["fields"]
        if field["name"] == "openai_api_key"
    )
    _assert_localized_text(openai_api_key["label"])
    english = next(
        item for item in payload["translation_languages"] if item["value"] == "en"
    )
    simplified_chinese = next(
        item for item in payload["translation_languages"] if item["value"] == "zh-CN"
    )
    assert english["label"]["en"] == "English"
    assert english["label"]["zh"] == "英语"
    assert simplified_chinese["label"]["zh"] == "简体中文"


def test_translation_language_labels_fall_back_when_langcodes_returns_blank(
    monkeypatch,
):
    from pdf2zh_next import web_localization

    original_get = web_localization.langcodes.Language.get

    class _BlankLanguage:
        def display_name(self, _locale: str) -> str:
            return ""

    def _fake_get(code: str):
        if code == "en":
            return _BlankLanguage()
        return original_get(code)

    monkeypatch.setattr(
        web_localization.langcodes.Language,
        "get",
        staticmethod(_fake_get),
    )

    english = next(
        item
        for item in web_localization.build_translation_language_options()
        if item["value"] == "en"
    )

    assert english["label"]["en"] == "English"
    assert english["label"]["zh"] == "English"


def test_ui_config_scrubs_sensitive_values(monkeypatch):
    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        lambda: CLIEnvSettingsModel(
            openai=True,
            openai_detail={
                "openai_api_key": "secret-key",
                "openai_base_url": "https://api.example.com/v1",
            },
        ),
    )

    response = _client().get("/api/ui-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["defaults"]["openai_detail"]["openai_api_key"] is None
    assert payload["defaults"]["openai_detail"]["openai_base_url"] is None
    assert any(item["name"] == "OpenAI" for item in payload["services"])
    translation_field = next(
        field
        for field in payload["translation_fields"]
        if field["name"] == "ignore_cache"
    )
    _assert_localized_text(translation_field["label"])


def test_translate_requires_exactly_one_source():
    response = _client().post(
        "/translate",
        json={"lang_in": "en", "lang_out": "zh"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "request_validation_failed"
    assert "exactly one" in str(payload["error"]["details"]).lower()


def test_translate_rejects_invalid_service(monkeypatch, tmp_path):
    pdf_path = _make_pdf(tmp_path)
    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    response = _client().post(
        "/translate",
        json={
            "input_file": str(pdf_path),
            "service": "NotARealEngine",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "invalid_service"
    assert "Use one of:" in payload["error"]["hint"]


def test_translate_returns_structured_success(monkeypatch, tmp_path):
    pdf_path = _make_pdf(tmp_path)
    mono_path = tmp_path / "paper-mono.pdf"
    mono_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    async def fake_translate_stream(settings, file_path, *, raise_on_error=True):
        assert raise_on_error is False
        assert str(file_path) == str(pdf_path)
        assert settings.translation.lang_in == "en"
        assert settings.translation.lang_out == "zh"
        yield {
            "type": "finish",
            "translate_result": SimpleNamespace(
                original_pdf_path=str(file_path),
                mono_pdf_path=mono_path,
                dual_pdf_path=None,
                auto_extracted_glossary_path=None,
                total_seconds=1.25,
            ),
            "token_usage": {
                "main": {
                    "total": 12,
                    "prompt": 8,
                    "completion": 4,
                    "cache_hit_prompt": 0,
                }
            },
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        fake_translate_stream,
    )

    response = _client().post(
        "/translate",
        json={
            "input_file": str(pdf_path),
            "service": "OpenAI",
            "lang_in": "en",
            "lang_out": "zh",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["service"] == "OpenAI"
    assert payload["input_file"] == str(pdf_path)
    assert payload["mono_pdf_path"] == mono_path.as_posix()
    assert payload["dual_pdf_path"] is None
    assert payload["token_usage"]["main"]["total"] == 12
    assert payload["mono_download_url"].startswith("/requests/")
    assert payload["artifacts"]["mono"]["url"] == payload["mono_download_url"]
    assert payload["artifacts"]["mono"]["preview_url"].endswith(
        "?disposition=inline"
    )
    assert payload["preview_url"] == payload["artifacts"]["mono"]["preview_url"]


def test_translate_returns_structured_failure(monkeypatch, tmp_path):
    pdf_path = _make_pdf(tmp_path)
    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    async def failing_translate_stream(_settings, _file_path, *, raise_on_error=True):
        assert raise_on_error is False
        yield {
            "type": "error",
            "error": "network timeout",
            "details": "connection reset by peer",
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        failing_translate_stream,
    )

    response = _client().post(
        "/translate",
        json={
            "input_file": str(pdf_path),
            "service": "OpenAI",
        },
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["code"] == "translation_failed"
    assert payload["error"]["message"] == "network timeout"
    assert "did not respond in time" in payload["error"]["hint"]


def test_save_config_keeps_existing_sensitive_values(monkeypatch):
    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )
    captured_settings = {}

    def capture(settings):
        captured_settings.update(settings.model_dump(mode="json"))

    monkeypatch.setattr(
        "pdf2zh_next.http_api.ConfigManager.write_user_default_config_file",
        Mock(side_effect=capture),
    )

    response = _client().post(
        "/api/config",
        json={
            "settings": {
                "openai": True,
                "openai_detail": {
                    "openai_api_key": "",
                    "openai_model": "gpt-4o-mini",
                },
                "translation": {
                    "qps": 9,
                },
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    assert captured_settings["openai_detail"]["openai_api_key"] == "test-key"
    assert captured_settings["translation"]["qps"] == 9


def test_stream_translate_upload_returns_progress_and_finish(monkeypatch, tmp_path):
    mono_path = tmp_path / "paper-mono.pdf"
    mono_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    async def fake_translate_stream(settings, file_path, *, raise_on_error=True):
        assert raise_on_error is False
        assert Path(file_path).suffix == ".pdf"
        assert settings.translation.lang_in == "en"
        yield {
            "type": "progress_update",
            "stage": "Layout analysis",
            "overall_progress": 50,
            "part_index": 1,
            "total_parts": 1,
            "stage_current": 2,
            "stage_total": 4,
        }
        yield {
            "type": "finish",
            "translate_result": SimpleNamespace(
                mono_pdf_path=mono_path,
                dual_pdf_path=None,
                auto_extracted_glossary_path=None,
                total_seconds=2.5,
            ),
            "token_usage": {"main": {"total": 10}},
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        fake_translate_stream,
    )

    response = _client().post(
        "/translate/file/stream",
        data={
            "request_json": json.dumps(
                {
                    "service": "OpenAI",
                    "lang_in": "en",
                    "lang_out": "zh",
                    "translation": {},
                    "pdf": {},
                    "engine_settings": {"openai_api_key": "test-key"},
                }
            )
        },
        files={"file": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert lines[0]["type"] == "progress"
    assert lines[0]["stage"] == "Layout analysis"
    assert lines[1]["type"] == "finish"
    assert lines[1]["result"]["mono_download_url"].startswith("/requests/")
    assert lines[1]["result"]["artifacts"]["mono"]["preview_url"].endswith(
        "?disposition=inline"
    )


def test_stream_translate_accepts_frontend_default_blank_optionals(
    monkeypatch,
    tmp_path,
):
    mono_path = tmp_path / "paper-mono.pdf"
    mono_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    async def fake_translate_stream(settings, _file_path, *, raise_on_error=True):
        assert raise_on_error is False
        assert settings.translation.pool_max_workers is None
        assert settings.translation.term_pool_max_workers is None
        assert settings.pdf.max_pages_per_part is None
        assert settings.translate_engine_settings.openai_timeout is None
        yield {
            "type": "finish",
            "translate_result": SimpleNamespace(
                mono_pdf_path=mono_path,
                dual_pdf_path=None,
                auto_extracted_glossary_path=None,
                total_seconds=1.0,
            ),
            "token_usage": {},
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        fake_translate_stream,
    )

    client = _client()
    app_config = client.get("/app/config").json()
    payload = _build_frontend_default_payload(app_config, service_name="OpenAI")
    payload["engine_settings"]["openai_api_key"] = "test-key"

    response = client.post(
        "/translate/file/stream",
        data={
            "request_json": json.dumps(
                {
                    "service": "OpenAI",
                    "lang_in": "en",
                    "lang_out": "zh",
                    "translation": payload["translation"],
                    "pdf": payload["pdf"],
                    "engine_settings": payload["engine_settings"],
                }
            )
        },
        files={"file": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert lines[-1]["type"] == "finish"
    assert lines[-1]["result"]["mono_download_url"].startswith("/requests/")
    assert lines[-1]["result"]["artifacts"]["mono"]["preview_url"].endswith(
        "?disposition=inline"
    )


def test_download_artifact_serves_registered_output(monkeypatch, tmp_path):
    pdf_path = _make_pdf(tmp_path)
    mono_path = tmp_path / "paper-mono.pdf"
    mono_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    async def fake_translate_stream(_settings, _file_path, *, raise_on_error=True):
        assert raise_on_error is False
        yield {
            "type": "finish",
            "translate_result": SimpleNamespace(
                mono_pdf_path=mono_path,
                dual_pdf_path=None,
                auto_extracted_glossary_path=None,
                total_seconds=1.25,
            ),
            "token_usage": {"main": {"total": 12}},
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        fake_translate_stream,
    )

    response = _client().post(
        "/translate",
        json={
            "input_file": str(pdf_path),
            "service": "OpenAI",
            "lang_in": "en",
            "lang_out": "zh",
        },
    )

    artifact_url = response.json()["mono_download_url"]
    download_response = _client().get(artifact_url)

    assert download_response.status_code == 200
    assert download_response.content == b"%PDF-1.4\n"
    assert "attachment" in download_response.headers["content-disposition"]


def test_download_artifact_supports_inline_preview(monkeypatch, tmp_path):
    pdf_path = _make_pdf(tmp_path)
    mono_path = tmp_path / "paper-mono.pdf"
    mono_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    async def fake_translate_stream(_settings, _file_path, *, raise_on_error=True):
        assert raise_on_error is False
        yield {
            "type": "finish",
            "translate_result": SimpleNamespace(
                mono_pdf_path=mono_path,
                dual_pdf_path=None,
                auto_extracted_glossary_path=None,
                total_seconds=1.25,
            ),
            "token_usage": {"main": {"total": 12}},
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        fake_translate_stream,
    )

    response = _client().post(
        "/translate",
        json={
            "input_file": str(pdf_path),
            "service": "OpenAI",
            "lang_in": "en",
            "lang_out": "zh",
        },
    )

    preview_url = response.json()["artifacts"]["mono"]["preview_url"]
    preview_response = _client().get(preview_url)

    assert preview_response.status_code == 200
    assert preview_response.content == b"%PDF-1.4\n"
    assert "inline" in preview_response.headers["content-disposition"]
    assert preview_response.headers["content-type"].startswith("application/pdf")
