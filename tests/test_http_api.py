from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.http_api import create_app


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
