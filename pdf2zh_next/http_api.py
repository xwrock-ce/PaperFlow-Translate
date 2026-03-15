from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import uvicorn
from fastapi import FastAPI
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from pdf2zh_next.config import ConfigManager
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
from pdf2zh_next.const import DEFAULT_CONFIG_FILE
from pdf2zh_next.const import __version__
from pdf2zh_next.high_level import do_translate_async_stream
from pdf2zh_next.high_level import validate_pdf_file

logger = logging.getLogger(__name__)

_HTTP_OUTPUT_ROOT = Path("pdf2zh_files") / "http_api"


class APIError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        hint: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details


class EngineInfo(BaseModel):
    name: str
    flag: str
    support_llm: bool
    description: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    default_config_file: str


class TranslateRequest(BaseModel):
    input_file: str | None = Field(
        default=None,
        description="Existing local PDF path on the server.",
    )
    file_url: str | None = Field(
        default=None,
        description="Direct http:// or https:// URL to a PDF file.",
    )
    service: str | None = Field(
        default=None,
        description="Translation service name, such as OpenAI or SiliconFlowFree.",
    )
    lang_in: str = Field(default="en", description="Source language code.")
    lang_out: str = Field(default="zh", description="Target language code.")
    output_dir: str | None = Field(
        default=None,
        description="Optional output directory for generated files.",
    )
    pages: str | None = Field(
        default=None,
        description="Optional page range, for example 1,3,5-7.",
    )
    no_mono: bool = Field(default=False)
    no_dual: bool = Field(default=False)
    ignore_cache: bool = Field(default=False)

    @model_validator(mode="after")
    def validate_source(self) -> TranslateRequest:
        if bool(self.input_file) == bool(self.file_url):
            raise ValueError("Provide exactly one of `input_file` or `file_url`.")
        return self


class TranslateResponse(BaseModel):
    status: str
    request_id: str
    service: str
    input_file: str
    output_dir: str
    mono_pdf_path: str | None = None
    dual_pdf_path: str | None = None
    glossary_path: str | None = None
    total_seconds: float | None = None
    token_usage: dict[str, Any] | None = None


def _error_payload(
    *,
    code: str,
    message: str,
    hint: str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if hint:
        payload["error"]["hint"] = hint
    if details not in (None, "", [], {}):
        payload["error"]["details"] = details
    return payload


def _build_request_validation_hint() -> str:
    return "Provide exactly one of `input_file` or `file_url`, then retry."


def _build_settings_hint(message: str) -> str | None:
    searchable_message = message.lower()
    if "api key" in searchable_message or "credential" in searchable_message:
        return (
            "Configure the selected engine in the default config file or via "
            "`PDF2ZH_*` environment variables, then retry."
        )
    if "error parsing pages parameter" in searchable_message:
        return "Use `pages` like `1,3,5-7`."
    if "cannot disable both dual and mono" in searchable_message:
        return "Leave at least one output enabled by keeping `no_mono` or `no_dual` false."
    if "file does not exist" in searchable_message:
        return "Pass an existing PDF path in `input_file`."
    return None


def _build_translation_hint(message: str) -> str | None:
    searchable_message = message.lower()
    if any(token in searchable_message for token in ("api key", "credential", "auth")):
        return (
            "Check the configured translation engine credentials, then retry the request."
        )
    if any(
        token in searchable_message
        for token in ("timeout", "timed out", "connection reset", "network")
    ):
        return (
            "The translation service did not respond in time. Check the network "
            "connection or lower the rate limit."
        )
    if "not a valid pdf" in searchable_message:
        return "Use a readable PDF file or a direct PDF download URL."
    return None


def _load_base_cli_settings() -> CLIEnvSettingsModel:
    config_manager = ConfigManager()
    default_config = config_manager._read_toml_file(DEFAULT_CONFIG_FILE)
    if default_config and not config_manager.test_config(default_config):
        logger.warning("Ignoring invalid default config file: %s", DEFAULT_CONFIG_FILE)
        default_config = {}

    env_settings = config_manager.parse_env_vars()
    merged_settings = config_manager.merge_settings([env_settings, default_config])
    if not merged_settings:
        return CLIEnvSettingsModel()
    return config_manager._build_model_from_args(CLIEnvSettingsModel, merged_settings)


def _resolve_service_metadata(service_name: str):
    normalized_name = service_name.strip().lower()
    for metadata in TRANSLATION_ENGINE_METADATA:
        if normalized_name in {
            metadata.translate_engine_type.lower(),
            metadata.cli_flag_name.lower(),
        }:
            return metadata

    available_services = ", ".join(
        metadata.translate_engine_type for metadata in TRANSLATION_ENGINE_METADATA
    )
    raise APIError(
        status_code=400,
        code="invalid_service",
        message=f"Unsupported translation service: {service_name}",
        hint=f"Use one of: {available_services}",
    )


def _prepare_request_output_dir(request_id: str, requested_output_dir: str | None) -> Path:
    if requested_output_dir:
        output_dir = Path(requested_output_dir).expanduser()
    else:
        output_dir = _HTTP_OUTPUT_ROOT / request_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _download_pdf_from_url(file_url: str, output_dir: Path) -> Path:
    normalized_url = file_url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise APIError(
            status_code=400,
            code="invalid_file_url",
            message="`file_url` must be a direct http:// or https:// PDF link.",
        )

    file_name = Path(parsed.path).name or "downloaded.pdf"
    file_path = output_dir / f"{Path(file_name).stem or 'downloaded'}.pdf"
    pdf_header = b""

    try:
        with requests.get(normalized_url, stream=True, timeout=15) as response:
            response.raise_for_status()
            with file_path.open("wb") as output_file:
                for chunk in response.iter_content(chunk_size=1024):
                    if not chunk:
                        continue
                    if len(pdf_header) < 5:
                        missing = 5 - len(pdf_header)
                        pdf_header += chunk[:missing]
                    output_file.write(chunk)
    except requests.RequestException as exc:
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=502,
            code="file_download_failed",
            message=f"Could not download the PDF from {normalized_url}.",
            hint="Check that `file_url` is reachable and points directly to a PDF file.",
            details=str(exc),
        ) from exc

    if pdf_header != b"%PDF-":
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=400,
            code="invalid_pdf_download",
            message="The downloaded file is not a valid PDF document.",
            hint="Use a direct PDF download URL in `file_url`.",
        )

    try:
        return validate_pdf_file(file_path)
    except (FileNotFoundError, ValueError) as exc:
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=400,
            code="invalid_pdf_download",
            message=str(exc),
            hint="Use a direct PDF download URL in `file_url`.",
        ) from exc


def _prepare_request_source(request: TranslateRequest, output_dir: Path) -> Path:
    if request.input_file:
        input_path = Path(request.input_file).expanduser()
        try:
            return validate_pdf_file(input_path)
        except FileNotFoundError as exc:
            raise APIError(
                status_code=400,
                code="input_file_not_found",
                message=str(exc),
                hint="Pass an existing PDF path in `input_file`.",
            ) from exc
        except ValueError as exc:
            raise APIError(
                status_code=400,
                code="invalid_input_file",
                message=str(exc),
                hint="Pass a readable PDF path in `input_file`.",
            ) from exc

    return _download_pdf_from_url(request.file_url or "", output_dir)


def _build_request_settings(
    request: TranslateRequest,
    *,
    file_path: Path,
    output_dir: Path,
):
    cli_settings = _load_base_cli_settings().clone()

    if request.service:
        selected_metadata = _resolve_service_metadata(request.service)
        for metadata in TRANSLATION_ENGINE_METADATA:
            setattr(cli_settings, metadata.cli_flag_name, False)
        setattr(cli_settings, selected_metadata.cli_flag_name, True)

    cli_settings.basic.input_files = {str(file_path)}
    cli_settings.translation.lang_in = request.lang_in
    cli_settings.translation.lang_out = request.lang_out
    cli_settings.translation.output = str(output_dir)
    cli_settings.translation.ignore_cache = request.ignore_cache
    cli_settings.pdf.pages = request.pages
    cli_settings.pdf.no_mono = request.no_mono
    cli_settings.pdf.no_dual = request.no_dual

    try:
        settings = cli_settings.to_settings_model()
        settings.validate_settings()
    except ValueError as exc:
        raise APIError(
            status_code=400,
            code="invalid_translation_settings",
            message=str(exc),
            hint=_build_settings_hint(str(exc)),
        ) from exc

    return settings


def _normalize_output_path(path: str | Path | None) -> str | None:
    if not path:
        return None
    return Path(path).as_posix()


async def _translate_single_file(settings, file_path: Path, request_id: str) -> TranslateResponse:
    last_progress: dict[str, Any] | None = None

    async for event in do_translate_async_stream(
        settings,
        file_path,
        raise_on_error=False,
    ):
        event_type = event.get("type")
        if event_type in {"progress_start", "progress_update", "progress_end"}:
            last_progress = {
                "stage": event.get("stage"),
                "overall_progress": event.get("overall_progress"),
            }
            continue

        if event_type == "error":
            error_message = str(event.get("error", "Translation failed."))
            raise APIError(
                status_code=502,
                code="translation_failed",
                message=error_message,
                hint=_build_translation_hint(error_message),
                details=event.get("details") or last_progress,
            )

        if event_type == "finish":
            result = event["translate_result"]
            return TranslateResponse(
                status="completed",
                request_id=request_id,
                service=settings.translate_engine_settings.translate_engine_type,
                input_file=str(file_path),
                output_dir=str(settings.translation.output),
                mono_pdf_path=_normalize_output_path(result.mono_pdf_path),
                dual_pdf_path=_normalize_output_path(result.dual_pdf_path),
                glossary_path=_normalize_output_path(
                    getattr(result, "auto_extracted_glossary_path", None)
                ),
                total_seconds=getattr(result, "total_seconds", None),
                token_usage=event.get("token_usage", {}),
            )

    raise APIError(
        status_code=500,
        code="missing_translation_result",
        message="The translation finished without a result payload.",
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="PDFMathTranslate Next HTTP API",
        version=__version__,
        description=(
            "Minimal HTTP API for translating a single PDF with the current "
            "server configuration."
        ),
    )

    @app.exception_handler(APIError)
    async def api_error_handler(
        _request: Request,
        exc: APIError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(
                code=exc.code,
                message=exc.message,
                hint=exc.hint,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                code="request_validation_failed",
                message="The request body is invalid.",
                hint=_build_request_validation_hint(),
                details=details,
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled HTTP API error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                code="internal_error",
                message="The server hit an unexpected error while processing the request.",
            ),
        )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {
            "name": "PDFMathTranslate Next HTTP API",
            "version": __version__,
            "docs": "/docs",
            "healthz": "/healthz",
            "engines": "/engines",
            "translate": "/translate",
        }

    @app.get("/healthz", response_model=HealthResponse, tags=["meta"])
    async def healthz() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            default_config_file=str(DEFAULT_CONFIG_FILE),
        )

    @app.get("/engines", tags=["meta"])
    async def list_engines() -> dict[str, Any]:
        return {
            "default_service": "SiliconFlowFree",
            "engines": [
                EngineInfo(
                    name=metadata.translate_engine_type,
                    flag=metadata.cli_flag_name,
                    support_llm=metadata.support_llm,
                    description=metadata.setting_model_type.__doc__,
                ).model_dump()
                for metadata in TRANSLATION_ENGINE_METADATA
            ],
        }

    @app.post("/translate", response_model=TranslateResponse, tags=["translation"])
    async def translate(request: TranslateRequest) -> TranslateResponse:
        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(request_id, request.output_dir)
        file_path = _prepare_request_source(request, output_dir)
        settings = _build_request_settings(
            request,
            file_path=file_path,
            output_dir=output_dir,
        )
        return await _translate_single_file(settings, file_path, request_id)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("pdf2zh_next.http_api:app", host="127.0.0.1", port=8000)
