from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import warnings
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient
from pdf2zh_next import http_api as http_api_module
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.http_api import HTTPServerSettings
from pdf2zh_next.http_api import _configure_runtime_noise_filters
from pdf2zh_next.http_api import _stream_job_events
from pdf2zh_next.http_api import create_app
from pdf2zh_next.translator.translator_impl.google import GoogleTranslator


def _assert_localized_text(value: dict[str, str]) -> None:
    assert value["en"]
    assert value["zh"]


def _client(
    *,
    server_settings: HTTPServerSettings | None = None,
) -> TestClient:
    class _ManagedTestClient(TestClient):
        def __del__(self):
            with suppress(Exception):
                self.close()

    if server_settings is None:
        server_settings = HTTPServerSettings(
            allow_local_input_file=True,
            enable_file_url=True,
        )
    client = _ManagedTestClient(create_app(server_settings=server_settings))
    client.__enter__()
    return client


def _make_pdf(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    return pdf_path


def _base_openai_settings() -> CLIEnvSettingsModel:
    return CLIEnvSettingsModel(
        openai=True,
        openai_detail={"openai_api_key": "test-key"},
    )


def _job_payload() -> str:
    return _job_payload_with_seat("1", "test-token")


def _job_payload_with_seat(seat_id: str, lease_token: str) -> str:
    return json.dumps(
        {
            "settings": {
                "openai": True,
                "openai_detail": {"openai_api_key": "test-key"},
            },
            "source_type": "file",
            "seat_id": seat_id,
            "lease_token": lease_token,
        }
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


def _claim_seat(
    client: TestClient,
    *,
    seat_id: str = "1",
    display_name: str = "Alice",
) -> tuple[str, str]:
    login = client.post("/seats/login", json={"display_name": display_name})
    assert login.status_code == 200
    claim = client.post(
        f"/seats/{seat_id}/claim",
        json={"display_name": login.json()["display_name"]},
    )
    assert claim.status_code == 200
    return claim.json()["seat"]["seat_id"], claim.json()["lease_token"]


def _set_seat_service(
    client: TestClient,
    seat_id: str,
    lease_token: str,
    service: str,
):
    response = client.post(
        f"/seats/{seat_id}/service",
        json={"lease_token": lease_token, "service": service},
    )
    assert response.status_code == 200
    return response.json()


def test_create_app_lifespan_starts_and_stops_job_manager():
    app = create_app()
    assert app.state.job_manager._started is False

    with TestClient(app):
        assert app.state.job_manager._started is True

    assert app.state.job_manager._started is False


def test_healthz_returns_status_and_version():
    response = _client().get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"]
    assert payload["default_config_file"].endswith(".toml")
    assert payload["running_jobs"] == 0
    assert payload["queued_jobs"] == 0
    assert payload["job_retention_minutes"] == 30


def test_translate_rejects_local_input_file_in_public_mode(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    client = _client(server_settings=HTTPServerSettings())

    response = client.post(
        "/translate",
        json={"input_file": str(pdf_path), "service": "OpenAI"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "feature_disabled"


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
    assert payload["seat_management"]["seat_count"] == 4
    assert payload["seat_management"]["lease_timeout_seconds"] == 120
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


def test_seat_claim_heartbeat_and_force_release():
    admin_token = secrets.token_urlsafe(12)
    client = _client(
        server_settings=HTTPServerSettings(admin_force_release_token=admin_token)  # noqa: S106
    )

    seat_id, lease_token = _claim_seat(client, seat_id="1", display_name="Alice")

    seats = client.get("/seats")
    assert seats.status_code == 200
    seat_payload = next(
        seat for seat in seats.json()["seats"] if seat["seat_id"] == seat_id
    )
    assert seat_payload["status"] == "occupied"
    assert seat_payload["occupant_name"] == "Alice"
    assert seat_payload["selected_service"] is None
    assert seats.json()["engine_usage"] == []

    occupied = client.post("/seats/1/claim", json={"display_name": "Bob"})
    assert occupied.status_code == 409
    assert occupied.json()["error"]["code"] == "seat_occupied"

    heartbeat = client.post(
        f"/seats/{seat_id}/heartbeat",
        json={"lease_token": lease_token},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["seat"]["seat_id"] == seat_id

    wrong_admin = client.post(
        "/admin/seats/1/force-release",
        json={"admin_token": "wrong"},
    )
    assert wrong_admin.status_code == 403

    released = client.post(
        "/admin/seats/1/force-release",
        json={"admin_token": admin_token},
    )
    assert released.status_code == 200
    assert released.json()["status"] == "available"
    assert released.json()["selected_service"] is None


def test_seat_service_selection_is_visible_and_cleared_on_release():
    client = _client()
    seat_id, lease_token = _claim_seat(client, seat_id="1", display_name="Alice")

    updated = _set_seat_service(client, seat_id, lease_token, "OpenAI")
    assert updated["selected_service"] == "OpenAI"

    seats = client.get("/seats")
    assert seats.status_code == 200
    seat_payload = next(
        seat for seat in seats.json()["seats"] if seat["seat_id"] == seat_id
    )
    assert seat_payload["selected_service"] == "OpenAI"
    assert seats.json()["engine_usage"] == [{"service": "OpenAI", "active_seats": 1}]

    released = client.post(
        f"/seats/{seat_id}/release",
        json={"lease_token": lease_token},
    )
    assert released.status_code == 200
    assert released.json()["selected_service"] is None

    seats_after_release = client.get("/seats")
    assert seats_after_release.status_code == 200
    released_payload = next(
        seat
        for seat in seats_after_release.json()["seats"]
        if seat["seat_id"] == seat_id
    )
    assert released_payload["status"] == "available"
    assert released_payload["selected_service"] is None
    assert seats_after_release.json()["engine_usage"] == []


def test_seat_engine_usage_counts_multiple_active_seats():
    client = _client()
    first_seat_id, first_lease_token = _claim_seat(
        client, seat_id="1", display_name="Alice"
    )
    second_seat_id, second_lease_token = _claim_seat(
        client, seat_id="2", display_name="Bob"
    )
    third_seat_id, third_lease_token = _claim_seat(
        client, seat_id="3", display_name="Carol"
    )

    _set_seat_service(client, first_seat_id, first_lease_token, "OpenAI")
    _set_seat_service(client, second_seat_id, second_lease_token, "OpenAI")
    _set_seat_service(client, third_seat_id, third_lease_token, "Google")

    seats = client.get("/seats")
    assert seats.status_code == 200
    assert seats.json()["engine_usage"] == [
        {"service": "OpenAI", "active_seats": 2},
        {"service": "Google", "active_seats": 1},
    ]


def test_stream_translate_requires_seat_claim(monkeypatch):
    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
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

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "seat_required"


def test_expired_seat_is_released_by_cleanup():
    client = _client()
    seat_id, _lease_token = _claim_seat(client, seat_id="1", display_name="Alice")

    seat = client.app.state.seat_manager._seats[seat_id]
    seat.last_heartbeat_at = seat.last_heartbeat_at - timedelta(seconds=121)

    client.portal.call(client.app.state.seat_manager.cleanup_expired_seats)

    seats = client.get("/seats").json()["seats"]
    released = next(item for item in seats if item["seat_id"] == seat_id)
    assert released["status"] == "available"


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


def test_translation_language_labels_use_builtin_zh_fallback_when_unlocalized(
    monkeypatch,
):
    from pdf2zh_next import web_localization

    original_get = web_localization.langcodes.Language.get

    class _EchoLanguage:
        def display_name(self, _locale: str) -> str:
            return "English"

    def _fake_get(code: str):
        if code == "en":
            return _EchoLanguage()
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
    assert english["label"]["zh"] == "英语"


def test_ui_bootstrap_disables_auto_term_extraction_for_non_llm_default_service(
    monkeypatch,
):
    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        lambda: CLIEnvSettingsModel(google=True),
    )

    response = _client().get("/ui/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["service"] == "Google"
    assert payload["settings"]["enable_auto_term_extraction"] is False


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
    assert payload["artifacts"]["mono"]["preview_url"].endswith("?disposition=inline")
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

    client = _client()
    seat_id, lease_token = _claim_seat(client)

    response = client.post(
        "/translate/file/stream",
        data={
            "request_json": json.dumps(
                {
                    "service": "OpenAI",
                    "seat_id": seat_id,
                    "lease_token": lease_token,
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
    status_line = next(line for line in lines if line["type"] == "status")
    progress_line = next(line for line in lines if line["type"] == "progress")
    finish_line = next(line for line in lines if line["type"] == "finish")
    assert lines[0]["type"] == "status"
    assert status_line["job"]["status"] in {"queued", "running"}
    assert progress_line["stage"] == "Layout analysis"
    assert finish_line["result"]["mono_download_url"].startswith("/requests/")
    assert finish_line["result"]["artifacts"]["mono"]["preview_url"].endswith(
        "?disposition=inline"
    )

    seats = client.get("/seats")
    assert seats.status_code == 200
    seat_payload = next(
        seat for seat in seats.json()["seats"] if seat["seat_id"] == seat_id
    )
    assert seat_payload["selected_service"] == "OpenAI"


def test_google_translator_uses_request_timeout_and_reraises_timeout(monkeypatch):
    settings = CLIEnvSettingsModel(
        google=True,
        google_detail={"google_timeout": "25"},
    ).to_settings_model()
    translator = GoogleTranslator(settings, Mock())
    calls = []

    def fake_get(*_args, **kwargs):
        calls.append(kwargs)
        raise requests.Timeout("network timeout")

    monkeypatch.setattr(translator.session, "get", fake_get)

    with pytest.raises(requests.Timeout, match="network timeout"):
        translator.do_translate("hello")

    assert len(calls) == 3
    assert translator.timeout == 25.0
    assert all(call["timeout"] == 25.0 for call in calls)


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
    seat_id, lease_token = _claim_seat(client)
    app_config = client.get("/app/config").json()
    payload = _build_frontend_default_payload(app_config, service_name="OpenAI")
    payload["engine_settings"]["openai_api_key"] = "test-key"

    response = client.post(
        "/translate/file/stream",
        data={
            "request_json": json.dumps(
                {
                    "service": "OpenAI",
                    "seat_id": seat_id,
                    "lease_token": lease_token,
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


def test_stream_translate_non_llm_service_disables_auto_term_extraction_and_logs(
    caplog,
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
        assert settings.basic.input_files == set()
        assert settings.translate_engine_settings.translate_engine_type == "Google"
        assert settings.translation.no_auto_extract_glossary is True
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
    seat_id, lease_token = _claim_seat(client)

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/translate/file/stream",
            data={
                "request_json": json.dumps(
                    {
                        "service": "Google",
                        "seat_id": seat_id,
                        "lease_token": lease_token,
                        "lang_in": "en",
                        "lang_out": "zh",
                        "translation": {},
                        "pdf": {},
                        "engine_settings": {},
                    }
                )
            },
            files={"file": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )

    assert response.status_code == 200
    assert "Automatic term extraction disabled for service=Google" in caplog.text
    assert "Accepted translation job" in caplog.text
    assert "service=Google auto_term_extraction=False" in caplog.text


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


def test_jobs_endpoint_returns_status_and_result(monkeypatch, tmp_path):
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
                total_seconds=1.0,
            ),
            "token_usage": {"main": {"total": 3}},
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        fake_translate_stream,
    )

    client = _client()
    try:
        seat_id, lease_token = _claim_seat(client)
        response = client.post(
            "/jobs",
            data={"payload": _job_payload_with_seat(seat_id, lease_token)},
            files={"file": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )

        assert response.status_code == 202
        job_payload = response.json()
        assert job_payload["status"] in {"queued", "running"}

        job_status = client.get(f"/jobs/{job_payload['job_id']}")
        assert job_status.status_code == 200
        payload = job_status.json()
        assert payload["service"] == "OpenAI"

        deadline = time.time() + 2
        while time.time() < deadline:
            current = client.get(f"/jobs/{job_payload['job_id']}").json()
            if current["status"] == "succeeded":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("job did not finish in time")

        assert current["result"]["mono_download_url"].startswith("/requests/")
    finally:
        client.close()


def test_jobs_queue_full(monkeypatch):
    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    async def slow_translate_stream(_settings, _file_path, *, raise_on_error=True):
        assert raise_on_error is False
        yield {
            "type": "progress_update",
            "stage": "Running",
            "overall_progress": 10,
            "part_index": 1,
            "total_parts": 1,
            "stage_current": 1,
            "stage_total": 2,
        }
        await asyncio.sleep(0.5)
        yield {
            "type": "finish",
            "translate_result": SimpleNamespace(
                mono_pdf_path=None,
                dual_pdf_path=None,
                auto_extracted_glossary_path=None,
                total_seconds=0.5,
            ),
            "token_usage": {},
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        slow_translate_stream,
    )

    settings = HTTPServerSettings(
        allow_local_input_file=True,
        enable_file_url=True,
        max_concurrent_jobs=1,
        max_queue_size=1,
    )
    client = _client(server_settings=settings)
    try:
        first_seat_id, first_lease_token = _claim_seat(client, seat_id="1")
        first = client.post(
            "/jobs",
            data={"payload": _job_payload_with_seat(first_seat_id, first_lease_token)},
            files={"file": ("paper1.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert first.status_code == 202

        deadline = time.time() + 2
        while time.time() < deadline:
            current = client.get(f"/jobs/{first.json()['job_id']}").json()
            if current["status"] == "running":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("first job did not start")

        second_seat_id, second_lease_token = _claim_seat(
            client,
            seat_id="2",
            display_name="Bob",
        )
        second = client.post(
            "/jobs",
            data={
                "payload": _job_payload_with_seat(second_seat_id, second_lease_token)
            },
            files={"file": ("paper2.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert second.status_code == 202
        assert second.json()["status"] == "queued"
        second_job_id = second.json()["job_id"]

        third_seat_id, third_lease_token = _claim_seat(
            client,
            seat_id="3",
            display_name="Carol",
        )
        third = client.post(
            "/jobs",
            data={"payload": _job_payload_with_seat(third_seat_id, third_lease_token)},
            files={"file": ("paper3.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert third.status_code == 429
        assert third.json()["error"]["code"] == "queue_full"

        cancelled = client.post(f"/jobs/{second_job_id}/cancel")
        assert cancelled.status_code == 200
    finally:
        client.close()


def test_cleanup_expires_job_artifacts(monkeypatch, tmp_path):
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
                total_seconds=0.1,
            ),
            "token_usage": {},
        }

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        fake_translate_stream,
    )

    client = _client()
    try:
        seat_id, lease_token = _claim_seat(client)
        response = client.post(
            "/jobs",
            data={"payload": _job_payload_with_seat(seat_id, lease_token)},
            files={"file": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        deadline = time.time() + 2
        while time.time() < deadline:
            current = client.get(f"/jobs/{job_id}").json()
            if current["status"] == "succeeded":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("job did not finish in time")

        request_id = current["request_id"]
        output_dir = Path(current["output_dir"])
        assert output_dir.exists()

        job = client.app.state.job_manager._jobs[job_id]
        job.expires_at = job.finished_at
        client.portal.call(client.app.state.job_manager.cleanup_expired_jobs)

        expired = client.get(f"/jobs/{job_id}")
        assert expired.status_code == 200
        assert expired.json()["status"] == "expired"
        assert not output_dir.exists()

        artifact_url = f"/requests/{request_id}/artifacts/source"
        missing = client.get(artifact_url)
        assert missing.status_code == 404
    finally:
        client.close()


def test_stream_disconnect_cancels_browser_job(monkeypatch):
    monkeypatch.setattr(
        "pdf2zh_next.http_api._load_base_cli_settings",
        _base_openai_settings,
    )

    async def slow_translate_stream(_settings, _file_path, *, raise_on_error=True):
        assert raise_on_error is False
        yield {
            "type": "progress_update",
            "stage": "Translation",
            "overall_progress": 10,
            "part_index": 1,
            "total_parts": 1,
            "stage_current": 1,
            "stage_total": 2,
        }
        await asyncio.sleep(60)

    monkeypatch.setattr(
        "pdf2zh_next.http_api.do_translate_async_stream",
        slow_translate_stream,
    )

    class _DisconnectingRequest:
        def __init__(self) -> None:
            self.calls = 0

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls >= 3

    client = _client()
    try:
        seat_id, lease_token = _claim_seat(client)
        response = client.post(
            "/jobs",
            data={"payload": _job_payload_with_seat(seat_id, lease_token)},
            files={"file": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        async def consume_until_disconnect():
            lines = []
            async for line in _stream_job_events(
                client.app.state.job_manager,
                job_id,
                legacy_format=True,
                request=_DisconnectingRequest(),
                cancel_on_disconnect=True,
            ):
                lines.append(json.loads(line))
            return lines

        lines = client.portal.call(consume_until_disconnect)
        assert lines
        assert lines[0]["type"] == "status"

        deadline = time.time() + 2
        while time.time() < deadline:
            current = client.get(f"/jobs/{job_id}").json()
            if current["status"] == "cancelled":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("job did not cancel after disconnect")

        assert current["status"] == "cancelled"
    finally:
        client.close()


def test_runtime_noise_filter_downgrades_known_babeldoc_font_parse_error(caplog):
    create_app()
    noisy_logger = logging.getLogger(
        "babeldoc.format.pdf.document_il.frontend.il_creater"
    )

    with caplog.at_level(logging.WARNING):
        noisy_logger.error(
            "failed to parse font xobj id 2592: FT_Exception: (invalid argument)"
        )
        noisy_logger.error("different babeldoc error")

    matching_record = next(
        record
        for record in caplog.records
        if "failed to parse font xobj id 2592" in record.getMessage()
    )
    assert matching_record.levelno == logging.WARNING

    other_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "different babeldoc error"
    )
    assert other_record.levelno == logging.ERROR


def test_runtime_noise_filter_ignores_specific_sklearn_parallel_warning():
    warning_message = (
        "`sklearn.utils.parallel.delayed` should be used with "
        "`sklearn.utils.parallel.Parallel` to make it possible to propagate "
        "the scikit-learn configuration of the current thread to the joblib workers."
    )

    with warnings.catch_warnings(record=True) as caught:
        http_api_module._RUNTIME_NOISE_FILTERS_CONFIGURED = False
        _configure_runtime_noise_filters()
        warnings.warn_explicit(
            warning_message,
            UserWarning,
            filename="parallel.py",
            lineno=144,
            module="sklearn.utils.parallel",
        )
    assert caught == []

    with warnings.catch_warnings(record=True) as caught:
        http_api_module._RUNTIME_NOISE_FILTERS_CONFIGURED = False
        _configure_runtime_noise_filters()
        warnings.warn_explicit(
            "another sklearn warning",
            UserWarning,
            filename="parallel.py",
            lineno=145,
            module="sklearn.utils.parallel",
        )
    assert len(caught) == 1
