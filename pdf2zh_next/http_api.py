from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal
from typing import get_args
from typing import get_origin
from urllib.parse import urlparse

import requests
import uvicorn
from fastapi import FastAPI
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi import UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic import model_validator

from pdf2zh_next.config import ConfigManager
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.model import PDFSettings
from pdf2zh_next.config.model import TranslationSettings
from pdf2zh_next.config.translate_engine_model import GUI_PASSWORD_FIELDS
from pdf2zh_next.config.translate_engine_model import GUI_SENSITIVE_FIELDS
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA_MAP
from pdf2zh_next.const import DEFAULT_CONFIG_FILE
from pdf2zh_next.const import __version__
from pdf2zh_next.high_level import do_translate_async_stream
from pdf2zh_next.high_level import validate_pdf_file
from pdf2zh_next.web_localization import build_translation_language_options
from pdf2zh_next.web_localization import field_options
from pdf2zh_next.web_localization import localize_field_description
from pdf2zh_next.web_localization import localize_field_label
from pdf2zh_next.web_localization import normalize_ui_locale
from pdf2zh_next.web_schema import build_ui_schema
from pdf2zh_next.web_schema import drop_empty_sensitive_values

logger = logging.getLogger(__name__)

_HTTP_OUTPUT_ROOT = Path("pdf2zh_files") / "http_api"
_ARTIFACT_MANIFEST_NAME = "artifacts.json"
_SOURCE_ARTIFACT_NAME = "source"
_SOURCE_FILE_NAME = "source.pdf"
TERM_SERVICE_FOLLOW_MAIN = "Follow main translation engine"


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


class TranslationArtifact(BaseModel):
    name: str
    filename: str
    url: str
    size_bytes: int | None = None


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


class BrowserTranslateRequest(BaseModel):
    service: str | None = None
    lang_in: str = "en"
    lang_out: str = "zh"
    translation: dict[str, Any] = Field(default_factory=dict)
    pdf: dict[str, Any] = Field(default_factory=dict)
    engine_settings: dict[str, Any] = Field(default_factory=dict)


class WebTranslatePayload(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    source_type: str = Field(default="file", description="Either `file` or `link`.")
    file_url: str | None = Field(default=None)
    persist_settings: bool = Field(default=False)

    @model_validator(mode="after")
    def validate_source(self) -> WebTranslatePayload:
        if self.source_type not in {"file", "link"}:
            raise ValueError("`source_type` must be either `file` or `link`.")
        if self.source_type == "link" and not self.file_url:
            raise ValueError("Provide `file_url` when `source_type` is `link`.")
        return self


class WebConfigPayload(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class WebUIError(ValueError):
    """Validation error for the browser-facing WebUI payload."""


class WebUISettings(BaseModel):
    source_kind: Literal["upload", "url"] = "upload"
    file_url: str = ""
    service: str = "SiliconFlowFree"
    lang_in: str = "en"
    lang_out: str = "zh"
    page_mode: Literal["all", "first", "first5", "range"] = "all"
    page_range_text: str = ""
    only_include_translated_page: bool = False
    no_mono: bool = False
    no_dual: bool = False
    dual_translate_first: bool = False
    use_alternating_pages_dual: bool = False
    watermark_output_mode: Literal["watermarked", "no_watermark", "both"] = (
        "watermarked"
    )
    rate_limit_mode: Literal["RPM", "Concurrent Threads", "Custom"] = "Custom"
    rpm: int = 240
    concurrent_threads: int = 20
    qps: int = 4
    pool_max_workers: int | None = None
    min_text_length: int = 5
    custom_system_prompt: str = ""
    save_auto_extracted_glossary: bool = False
    enable_auto_term_extraction: bool = True
    primary_font_family: Literal["Auto", "serif", "sans-serif", "script"] = "Auto"
    skip_clean: bool = False
    disable_rich_text_translate: bool = False
    enhance_compatibility: bool = False
    split_short_lines: bool = False
    short_line_split_factor: float = 0.8
    translate_table_text: bool = True
    skip_scanned_detection: bool = False
    ignore_cache: bool = False
    ocr_workaround: bool = False
    auto_enable_ocr_workaround: bool = False
    max_pages_per_part: int | None = None
    formular_font_pattern: str = ""
    formular_char_pattern: str = ""
    merge_alternating_line_numbers: bool = True
    remove_non_formula_lines: bool = True
    non_formula_line_iou_threshold: float = 0.9
    figure_table_protection_threshold: float = 0.9
    skip_formula_offset_calculation: bool = False
    term_service: str = TERM_SERVICE_FOLLOW_MAIN
    term_rate_limit_mode: Literal["RPM", "Concurrent Threads", "Custom"] = "Custom"
    term_rpm: int = 240
    term_concurrent_threads: int = 20
    term_qps: int = 4
    term_pool_max_workers: int | None = None
    service_config: dict[str, Any] = Field(default_factory=dict)
    term_service_config: dict[str, Any] = Field(default_factory=dict)


class TranslateResponse(BaseModel):
    status: str
    request_id: str
    service: str
    input_file: str
    output_dir: str
    mono_pdf_path: str | None = None
    dual_pdf_path: str | None = None
    glossary_path: str | None = None
    mono_download_url: str | None = None
    dual_download_url: str | None = None
    glossary_download_url: str | None = None
    preview_url: str | None = None
    total_seconds: float | None = None
    token_usage: dict[str, Any] | None = None
    artifacts: dict[str, TranslationArtifact] = Field(default_factory=dict)
    downloads: dict[str, TranslationArtifact] = Field(default_factory=dict)


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


def _api_root_payload() -> dict[str, Any]:
    return {
        "name": "PDFMathTranslate Next HTTP API",
        "version": __version__,
        "docs": "/docs",
        "healthz": "/healthz",
        "engines": "/engines",
        "translate": "/translate",
        "app": "/app",
        "app_config": "/app/config",
        "ui_config": "/api/ui-config",
        "save_config": "/api/config",
        "upload_translate": "/translate/file",
        "stream_translate": "/api/translate/stream",
    }


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


def _build_full_cli_settings(settings_payload: dict[str, Any]) -> CLIEnvSettingsModel:
    config_manager = ConfigManager()
    base_settings = _load_base_cli_settings().model_dump(mode="json")
    cleaned_payload = drop_empty_sensitive_values(settings_payload)
    merged_settings = config_manager.merge_settings([cleaned_payload, base_settings])
    try:
        return config_manager._build_model_from_args(CLIEnvSettingsModel, merged_settings)
    except ValidationError as exc:
        raise APIError(
            status_code=422,
            code="invalid_translation_settings",
            message="The submitted settings are invalid.",
            details=exc.errors(),
        ) from exc


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


def _normalize_output_path(path: str | Path | None) -> str | None:
    if not path:
        return None
    return Path(path).as_posix()


def _download_pdf_from_url(file_url: str, output_dir: Path) -> Path:
    normalized_url = file_url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise APIError(
            status_code=400,
            code="invalid_file_url",
            message="`file_url` must be a direct http:// or https:// PDF link.",
        )

    file_path = output_dir / _SOURCE_FILE_NAME
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


async def _save_uploaded_pdf(upload: UploadFile, output_dir: Path) -> Path:
    if not upload.filename or not upload.filename.lower().endswith(".pdf"):
        raise APIError(
            status_code=400,
            code="invalid_upload",
            message="Upload a PDF file with a `.pdf` extension.",
        )

    file_path = output_dir / _SOURCE_FILE_NAME
    pdf_header = b""

    try:
        with file_path.open("wb") as output_file:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                if len(pdf_header) < 5:
                    missing = 5 - len(pdf_header)
                    pdf_header += chunk[:missing]
                output_file.write(chunk)
    finally:
        await upload.close()

    if pdf_header != b"%PDF-":
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=400,
            code="invalid_upload",
            message="The uploaded file is not a valid PDF document.",
        )

    try:
        return validate_pdf_file(file_path)
    except (FileNotFoundError, ValueError) as exc:
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=400,
            code="invalid_upload",
            message=str(exc),
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


def _field_type_name(annotation: Any) -> tuple[str, list[dict[str, Any]] | None]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    non_none_args = [arg for arg in args if arg is not type(None)]

    if origin is None:
        if annotation is bool:
            return "boolean", None
        if annotation is int:
            return "integer", None
        if annotation is float:
            return "number", None
        return "string", None

    if origin is Literal:
        return "select", [
            {"label": {"en": str(arg), "zh": str(arg)}, "value": str(arg)}
            for arg in non_none_args
        ]

    if origin in {list, dict, tuple, set}:
        return "string", None
    for arg in non_none_args:
        if get_origin(arg) is Literal:
            literal_values = [item for item in get_args(arg) if item is not type(None)]
            return "select", [
                {"label": {"en": str(item), "zh": str(item)}, "value": str(item)}
                for item in literal_values
            ]
    if bool in non_none_args:
        return "boolean", None
    if int in non_none_args:
        return "integer", None
    if float in non_none_args:
        return "number", None
    return "string", None


def _serialize_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _build_field_schema(model_type: type[BaseModel], field_name: str) -> dict[str, Any]:
    model_field = model_type.model_fields[field_name]
    field_type, choices = _field_type_name(model_field.annotation)
    localized_choices = field_options(field_name)
    if localized_choices:
        field_type = "select"
    if field_type == "select" and not localized_choices:
        raise ValueError(
            f"Missing localized WebUI choices for field `{field_name}`."
        )
    localized_choices = localized_choices or choices or []
    default_value = None
    if model_field.default_factory is not None:
        default_value = _serialize_default(model_field.default_factory())
    elif model_field.default is not None:
        default_value = _serialize_default(model_field.default)
    return {
        "name": field_name,
        "label": localize_field_label(field_name),
        "description": localize_field_description(field_name),
        "type": field_type,
        "required": model_field.is_required(),
        "default": default_value,
        "password": field_name in GUI_PASSWORD_FIELDS,
        "sensitive": field_name in GUI_SENSITIVE_FIELDS,
        "choices": localized_choices,
    }


def _build_model_schema(
    model_type: type[BaseModel],
    *,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded_fields = exclude or set()
    return [
        _build_field_schema(model_type, field_name)
        for field_name in model_type.model_fields
        if field_name not in excluded_fields
    ]


def _build_app_config() -> dict[str, Any]:
    cli_settings = _load_base_cli_settings()
    services = []
    for metadata in TRANSLATION_ENGINE_METADATA:
        services.append(
            {
                "name": metadata.translate_engine_type,
                "flag": metadata.cli_flag_name,
                "support_llm": metadata.support_llm,
                "description": metadata.setting_model_type.__doc__,
                "fields": _build_model_schema(
                    metadata.setting_model_type,
                    exclude={"translate_engine_type", "support_llm"},
                ),
            }
        )
    return {
        "name": "PaperFlow Translate",
        "version": __version__,
        "default_service": "SiliconFlowFree",
        "default_locale": normalize_ui_locale(cli_settings.gui_settings.ui_lang),
        "services": services,
        "translation_languages": build_translation_language_options(),
        "translation_fields": _build_model_schema(
            TranslationSettings,
            exclude={"lang_in", "lang_out", "output", "glossaries"},
        ),
        "pdf_fields": _build_model_schema(PDFSettings),
    }


def _annotation_to_service_field(
    *,
    name: str,
    description: str | None,
    annotation: Any,
    default: Any,
    secret: bool,
) -> dict[str, Any]:
    args = getattr(annotation, "__args__", ())
    if annotation is bool or bool in args:
        return {
            "name": name,
            "label": description or name,
            "control": "checkbox",
            "required": False,
            "secret": secret,
            "value_type": "boolean",
            "default": bool(default) if default is not None else False,
        }
    if annotation is int or int in args:
        return {
            "name": name,
            "label": description or name,
            "control": "number",
            "required": default is None,
            "secret": secret,
            "value_type": "integer",
            "default": default,
        }
    if annotation is float or float in args:
        return {
            "name": name,
            "label": description or name,
            "control": "number",
            "required": default is None,
            "secret": secret,
            "value_type": "number",
            "default": default,
        }
    return {
        "name": name,
        "label": description or name,
        "control": "password" if secret else "text",
        "required": default is None,
        "secret": secret,
        "value_type": "string",
        "default": default,
    }


def _build_bootstrap_services(
    _cli_settings: CLIEnvSettingsModel,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    services: list[dict[str, Any]] = []
    term_services: list[dict[str, Any]] = []
    for metadata in TRANSLATION_ENGINE_METADATA:
        fields = []
        for field_name, field in metadata.setting_model_type.model_fields.items():
            if field_name in {"translate_engine_type", "support_llm"}:
                continue
            fields.append(
                _annotation_to_service_field(
                    name=field_name,
                    description=field.description,
                    annotation=field.annotation,
                    default=field.default,
                    secret=field_name in GUI_PASSWORD_FIELDS,
                )
            )
        service = {
            "name": metadata.translate_engine_type,
            "support_llm": metadata.support_llm,
            "fields": fields,
        }
        services.append(service)
        if metadata.support_llm:
            term_services.append(service)
    return services, term_services


def _selected_service(cli_settings: CLIEnvSettingsModel) -> str:
    for metadata in TRANSLATION_ENGINE_METADATA:
        if getattr(cli_settings, metadata.cli_flag_name, False):
            return metadata.translate_engine_type
    return "SiliconFlowFree"


def _page_mode_from_pages(pages: str | None) -> tuple[str, str]:
    normalized = str(pages or "").strip()
    if not normalized:
        return "all", ""
    if normalized == "1":
        return "first", ""
    if normalized == "1,2,3,4,5":
        return "first5", ""
    return "range", normalized


def _build_bootstrap_service_config(
    cli_settings: CLIEnvSettingsModel,
    service_name: str,
) -> dict[str, Any]:
    metadata = TRANSLATION_ENGINE_METADATA_MAP.get(service_name)
    if not metadata or not metadata.cli_detail_field_name:
        return {}
    detail_settings = getattr(cli_settings, metadata.cli_detail_field_name, None)
    if detail_settings is None:
        return {}
    return {
        key: value
        for key, value in detail_settings.model_dump().items()
        if key not in {"translate_engine_type", "support_llm"}
    }


def _build_ui_bootstrap() -> dict[str, Any]:
    cli_settings = _load_base_cli_settings()
    services, term_services = _build_bootstrap_services(cli_settings)
    service = _selected_service(cli_settings)
    page_mode, page_range_text = _page_mode_from_pages(cli_settings.pdf.pages)
    return {
        "version": __version__,
        "default_service": "SiliconFlowFree",
        "settings": {
            "service": service,
            "lang_in": cli_settings.translation.lang_in,
            "lang_out": cli_settings.translation.lang_out,
            "page_mode": page_mode,
            "page_range_text": page_range_text,
            "only_include_translated_page": cli_settings.pdf.only_include_translated_page,
            "no_mono": cli_settings.pdf.no_mono,
            "no_dual": cli_settings.pdf.no_dual,
            "dual_translate_first": cli_settings.pdf.dual_translate_first,
            "use_alternating_pages_dual": cli_settings.pdf.use_alternating_pages_dual,
            "watermark_output_mode": cli_settings.pdf.watermark_output_mode,
            "qps": cli_settings.translation.qps or 4,
            "pool_max_workers": cli_settings.translation.pool_max_workers,
            "min_text_length": cli_settings.translation.min_text_length,
            "custom_system_prompt": cli_settings.translation.custom_system_prompt or "",
            "save_auto_extracted_glossary": cli_settings.translation.save_auto_extracted_glossary,
            "enable_auto_term_extraction": not cli_settings.translation.no_auto_extract_glossary,
            "primary_font_family": cli_settings.translation.primary_font_family or "Auto",
            "skip_clean": cli_settings.pdf.skip_clean,
            "disable_rich_text_translate": cli_settings.pdf.disable_rich_text_translate,
            "enhance_compatibility": cli_settings.pdf.enhance_compatibility,
            "split_short_lines": cli_settings.pdf.split_short_lines,
            "short_line_split_factor": cli_settings.pdf.short_line_split_factor,
            "translate_table_text": cli_settings.pdf.translate_table_text,
            "skip_scanned_detection": cli_settings.pdf.skip_scanned_detection,
            "ignore_cache": cli_settings.translation.ignore_cache,
            "ocr_workaround": cli_settings.pdf.ocr_workaround,
            "auto_enable_ocr_workaround": cli_settings.pdf.auto_enable_ocr_workaround,
            "max_pages_per_part": cli_settings.pdf.max_pages_per_part,
            "formular_font_pattern": cli_settings.pdf.formular_font_pattern or "",
            "formular_char_pattern": cli_settings.pdf.formular_char_pattern or "",
            "merge_alternating_line_numbers": not cli_settings.pdf.no_merge_alternating_line_numbers,
            "remove_non_formula_lines": not cli_settings.pdf.no_remove_non_formula_lines,
            "non_formula_line_iou_threshold": cli_settings.pdf.non_formula_line_iou_threshold,
            "figure_table_protection_threshold": cli_settings.pdf.figure_table_protection_threshold,
            "skip_formula_offset_calculation": cli_settings.pdf.skip_formula_offset_calculation,
            "term_service": TERM_SERVICE_FOLLOW_MAIN,
            "term_qps": cli_settings.translation.term_qps or cli_settings.translation.qps or 4,
            "term_pool_max_workers": cli_settings.translation.term_pool_max_workers,
            "service_config": _build_bootstrap_service_config(cli_settings, service),
            "term_service_config": {},
        },
        "translation_languages": build_translation_language_options(),
        "services": services,
        "term_services": term_services,
    }


def _parse_webui_payload(raw_payload: str) -> WebUISettings:
    try:
        data = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise WebUIError("The WebUI payload is not valid JSON.") from exc
    return WebUISettings.model_validate(data)


def _calculate_rate_limit_params(
    rate_limit_mode: str,
    *,
    rpm: int,
    concurrent_threads: int,
    qps: int,
    pool_max_workers: int | None,
    default_qps: int = 4,
) -> tuple[int, int | None]:
    if rate_limit_mode == "RPM":
        normalized_rpm = int(rpm)
        if normalized_rpm <= 0:
            raise WebUIError("RPM must be a positive integer.")
        computed_qps = max(1, normalized_rpm // 60)
        return computed_qps, min(1000, computed_qps * 10)
    if rate_limit_mode == "Concurrent Threads":
        normalized_threads = int(concurrent_threads)
        if normalized_threads <= 0:
            raise WebUIError("Concurrent threads must be a positive integer.")
        pool_workers = min(
            1000,
            max(1, min(int(normalized_threads * 0.9), max(1, normalized_threads - 20))),
        )
        return max(1, pool_workers), pool_workers

    normalized_qps = int(qps or default_qps)
    if normalized_qps <= 0:
        raise WebUIError("QPS must be a positive integer.")
    normalized_pool = (
        int(pool_max_workers)
        if pool_max_workers is not None and int(pool_max_workers) > 0
        else None
    )
    return normalized_qps, normalized_pool


def _coerce_webui_service_config(
    service_name: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    metadata = TRANSLATION_ENGINE_METADATA_MAP.get(service_name)
    if not metadata or not metadata.cli_detail_field_name:
        return {}
    model_fields = metadata.setting_model_type.model_fields
    result: dict[str, Any] = {}
    for key, field in model_fields.items():
        if key in {"translate_engine_type", "support_llm"} or key not in values:
            continue
        raw_value = values[key]
        args = getattr(field.annotation, "__args__", ())
        if field.annotation is int or int in args:
            result[key] = int(raw_value) if raw_value not in ("", None) else None
        elif field.annotation is bool or bool in args:
            result[key] = bool(raw_value)
        elif field.annotation is float or float in args:
            result[key] = float(raw_value) if raw_value not in ("", None) else None
        else:
            result[key] = raw_value
    return result


def _coerce_model_field_value(model_field: Any, raw_value: Any) -> Any:
    annotation = model_field.annotation
    args = get_args(annotation)

    if raw_value == "":
        if model_field.default_factory is not None:
            return model_field.default_factory()
        if not model_field.is_required():
            return model_field.default
        if annotation is str or str in args:
            return ""
        return None

    if annotation is bool or bool in args:
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
        return bool(raw_value)

    if annotation is int or int in args:
        return (
            int(raw_value)
            if raw_value is not None
            else (
                model_field.default_factory()
                if model_field.default_factory is not None
                else model_field.default
            )
        )

    if annotation is float or float in args:
        return (
            float(raw_value)
            if raw_value is not None
            else (
                model_field.default_factory()
                if model_field.default_factory is not None
                else model_field.default
            )
        )

    return raw_value


def _build_settings_from_webui(
    base_settings: CLIEnvSettingsModel,
    payload: WebUISettings,
    *,
    file_path: Path | None,
    output_dir: Path | None,
    for_saved_config: bool = False,
) -> tuple[CLIEnvSettingsModel, Any]:
    translate_settings = base_settings.clone()
    translate_settings.basic.gui = for_saved_config
    translate_settings.basic.input_files = {str(file_path)} if file_path else set()
    if output_dir is not None:
        translate_settings.translation.output = str(output_dir)

    if payload.service not in TRANSLATION_ENGINE_METADATA_MAP:
        raise WebUIError(f"Unsupported translation service: {payload.service}")
    if payload.no_mono and payload.no_dual:
        raise WebUIError("Select at least one output format before starting translation.")

    pages_map = {"all": None, "first": "1", "first5": "1,2,3,4,5", "range": None}
    pages = pages_map[payload.page_mode]
    if payload.page_mode == "range":
        pages = payload.page_range_text.strip() or None

    translate_settings.translation.lang_in = payload.lang_in
    translate_settings.translation.lang_out = payload.lang_out
    translate_settings.translation.ignore_cache = payload.ignore_cache
    translate_settings.translation.min_text_length = int(payload.min_text_length)
    translate_settings.translation.custom_system_prompt = (
        payload.custom_system_prompt.strip() or None
    )
    translate_settings.translation.save_auto_extracted_glossary = (
        payload.save_auto_extracted_glossary
    )
    translate_settings.translation.no_auto_extract_glossary = (
        not payload.enable_auto_term_extraction
    )
    translate_settings.translation.primary_font_family = (
        None if payload.primary_font_family == "Auto" else payload.primary_font_family
    )

    if payload.service != "SiliconFlowFree":
        qps, pool_max_workers = _calculate_rate_limit_params(
            payload.rate_limit_mode,
            rpm=payload.rpm,
            concurrent_threads=payload.concurrent_threads,
            qps=payload.qps,
            pool_max_workers=payload.pool_max_workers,
            default_qps=translate_settings.translation.qps or 4,
        )
        translate_settings.translation.qps = qps
        translate_settings.translation.pool_max_workers = pool_max_workers

    term_qps, term_pool_max_workers = _calculate_rate_limit_params(
        payload.term_rate_limit_mode,
        rpm=payload.term_rpm,
        concurrent_threads=payload.term_concurrent_threads,
        qps=payload.term_qps,
        pool_max_workers=payload.term_pool_max_workers,
        default_qps=translate_settings.translation.term_qps
        or translate_settings.translation.qps
        or 4,
    )
    translate_settings.translation.term_qps = term_qps
    translate_settings.translation.term_pool_max_workers = term_pool_max_workers

    translate_settings.pdf.pages = pages
    translate_settings.pdf.only_include_translated_page = (
        payload.only_include_translated_page
    )
    translate_settings.pdf.no_mono = payload.no_mono
    translate_settings.pdf.no_dual = payload.no_dual
    translate_settings.pdf.dual_translate_first = payload.dual_translate_first
    translate_settings.pdf.use_alternating_pages_dual = (
        payload.use_alternating_pages_dual
    )
    translate_settings.pdf.watermark_output_mode = payload.watermark_output_mode
    translate_settings.pdf.skip_clean = payload.skip_clean
    translate_settings.pdf.disable_rich_text_translate = (
        payload.disable_rich_text_translate
    )
    translate_settings.pdf.enhance_compatibility = payload.enhance_compatibility
    translate_settings.pdf.split_short_lines = payload.split_short_lines
    translate_settings.pdf.short_line_split_factor = float(
        payload.short_line_split_factor
    )
    translate_settings.pdf.translate_table_text = payload.translate_table_text
    translate_settings.pdf.skip_scanned_detection = payload.skip_scanned_detection
    translate_settings.pdf.ocr_workaround = payload.ocr_workaround
    translate_settings.pdf.auto_enable_ocr_workaround = (
        payload.auto_enable_ocr_workaround
    )
    translate_settings.pdf.max_pages_per_part = (
        int(payload.max_pages_per_part)
        if payload.max_pages_per_part and int(payload.max_pages_per_part) > 0
        else None
    )
    translate_settings.pdf.formular_font_pattern = (
        payload.formular_font_pattern.strip() or None
    )
    translate_settings.pdf.formular_char_pattern = (
        payload.formular_char_pattern.strip() or None
    )
    translate_settings.pdf.no_merge_alternating_line_numbers = (
        not payload.merge_alternating_line_numbers
    )
    translate_settings.pdf.no_remove_non_formula_lines = (
        not payload.remove_non_formula_lines
    )
    translate_settings.pdf.non_formula_line_iou_threshold = float(
        payload.non_formula_line_iou_threshold
    )
    translate_settings.pdf.figure_table_protection_threshold = float(
        payload.figure_table_protection_threshold
    )
    translate_settings.pdf.skip_formula_offset_calculation = (
        payload.skip_formula_offset_calculation
    )

    for metadata in TRANSLATION_ENGINE_METADATA:
        setattr(translate_settings, metadata.cli_flag_name, False)
    selected_metadata = TRANSLATION_ENGINE_METADATA_MAP[payload.service]
    setattr(translate_settings, selected_metadata.cli_flag_name, True)
    if selected_metadata.cli_detail_field_name:
        detail_settings = getattr(
            translate_settings,
            selected_metadata.cli_detail_field_name,
        )
        for key, value in _coerce_webui_service_config(
            payload.service,
            payload.service_config,
        ).items():
            setattr(detail_settings, key, value)

    settings_model = translate_settings.to_settings_model()
    settings_model.validate_settings()
    return translate_settings, settings_model


def _set_translation_service(
    cli_settings: CLIEnvSettingsModel,
    *,
    service_name: str | None,
    engine_settings: dict[str, Any],
) -> None:
    if service_name:
        selected_metadata = _resolve_service_metadata(service_name)
        for metadata in TRANSLATION_ENGINE_METADATA:
            setattr(cli_settings, metadata.cli_flag_name, False)
        setattr(cli_settings, selected_metadata.cli_flag_name, True)
    else:
        selected_metadata = TRANSLATION_ENGINE_METADATA_MAP["SiliconFlowFree"]

    if not engine_settings:
        return
    if not selected_metadata.cli_detail_field_name:
        raise APIError(
            status_code=400,
            code="unexpected_engine_settings",
            message=f"{selected_metadata.translate_engine_type} does not accept engine detail settings.",
        )

    detail_model = getattr(cli_settings, selected_metadata.cli_detail_field_name)
    model_fields = type(detail_model).model_fields
    merged_settings = detail_model.model_dump()
    for field_name, raw_value in engine_settings.items():
        if field_name not in model_fields:
            raise APIError(
                status_code=400,
                code="invalid_request_field",
                message=(
                    f"Unsupported field `{field_name}` in "
                    f"`{selected_metadata.translate_engine_type}` engine settings."
                ),
            )
        merged_settings[field_name] = _coerce_model_field_value(
            model_fields[field_name],
            raw_value,
        )
    merged_settings["translate_engine_type"] = selected_metadata.translate_engine_type
    setattr(
        cli_settings,
        selected_metadata.cli_detail_field_name,
        selected_metadata.setting_model_type(**merged_settings),
    )


def _apply_overrides(section: Any, overrides: dict[str, Any], *, section_name: str) -> None:
    model_fields = type(section).model_fields
    for field_name, value in overrides.items():
        if field_name not in model_fields:
            raise APIError(
                status_code=400,
                code="invalid_request_field",
                message=f"Unsupported field `{field_name}` in `{section_name}` settings.",
            )
        setattr(
            section,
            field_name,
            _coerce_model_field_value(model_fields[field_name], value),
        )


def _build_settings(
    *,
    file_path: Path,
    output_dir: Path,
    service_name: str | None,
    lang_in: str,
    lang_out: str,
    translation_overrides: dict[str, Any],
    pdf_overrides: dict[str, Any],
    engine_settings: dict[str, Any],
) -> Any:
    cli_settings = _load_base_cli_settings().clone()
    _set_translation_service(
        cli_settings,
        service_name=service_name,
        engine_settings=engine_settings,
    )
    cli_settings.basic.input_files = {str(file_path)}
    cli_settings.translation.lang_in = lang_in
    cli_settings.translation.lang_out = lang_out
    cli_settings.translation.output = str(output_dir)
    _apply_overrides(
        cli_settings.translation,
        translation_overrides,
        section_name="translation",
    )
    _apply_overrides(cli_settings.pdf, pdf_overrides, section_name="pdf")

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


def _build_request_settings(
    request: TranslateRequest,
    *,
    file_path: Path,
    output_dir: Path,
) -> Any:
    return _build_settings(
        file_path=file_path,
        output_dir=output_dir,
        service_name=request.service,
        lang_in=request.lang_in,
        lang_out=request.lang_out,
        translation_overrides={"ignore_cache": request.ignore_cache},
        pdf_overrides={
            "pages": request.pages,
            "no_mono": request.no_mono,
            "no_dual": request.no_dual,
        },
        engine_settings={},
    )


def _build_browser_request_settings(
    request: BrowserTranslateRequest,
    *,
    file_path: Path,
    output_dir: Path,
) -> Any:
    return _build_settings(
        file_path=file_path,
        output_dir=output_dir,
        service_name=request.service,
        lang_in=request.lang_in,
        lang_out=request.lang_out,
        translation_overrides=dict(request.translation),
        pdf_overrides=dict(request.pdf),
        engine_settings=dict(request.engine_settings),
    )


def _build_web_request_settings(
    payload: WebTranslatePayload,
    *,
    file_path: Path,
    output_dir: Path,
) -> Any:
    cli_settings = _build_full_cli_settings(payload.settings).clone()
    cli_settings.basic.input_files = {str(file_path)}
    cli_settings.translation.output = str(output_dir)
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

    if payload.persist_settings:
        ConfigManager().write_user_default_config_file(cli_settings.clone())

    return settings


def _artifact_manifest_path(output_dir: Path) -> Path:
    return output_dir / _ARTIFACT_MANIFEST_NAME


def _guess_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _artifact_url(request_id: str, artifact_name: str) -> str:
    return f"/requests/{request_id}/artifacts/{artifact_name}"


def _build_artifact(
    *,
    name: str,
    path: Path,
    request_id: str,
) -> TranslationArtifact:
    return TranslationArtifact(
        name=name,
        filename=path.name,
        url=_artifact_url(request_id, name),
        size_bytes=path.stat().st_size if path.exists() else None,
    )


def _build_artifacts(
    *,
    request_id: str,
    input_file_path: Path,
    result: Any,
) -> dict[str, TranslationArtifact]:
    artifacts = {
        _SOURCE_ARTIFACT_NAME: _build_artifact(
            name=_SOURCE_ARTIFACT_NAME,
            path=input_file_path,
            request_id=request_id,
        )
    }
    artifact_paths = {
        "mono": getattr(result, "mono_pdf_path", None),
        "dual": getattr(result, "dual_pdf_path", None),
        "glossary": getattr(result, "auto_extracted_glossary_path", None),
    }
    for name, raw_path in artifact_paths.items():
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        artifacts[name] = _build_artifact(name=name, path=path, request_id=request_id)
    return artifacts


def _build_downloads(
    artifacts: dict[str, TranslationArtifact],
) -> dict[str, TranslationArtifact]:
    return {
        name: artifact
        for name, artifact in artifacts.items()
        if name != _SOURCE_ARTIFACT_NAME
    }


def _write_artifact_manifest(
    output_dir: Path,
    input_file_path: Path,
    response: TranslateResponse,
) -> None:
    manifest = {
        "source_path": input_file_path.as_posix(),
        "artifacts": {
            name: {
                "path": (
                    input_file_path.as_posix()
                    if name == _SOURCE_ARTIFACT_NAME
                    else getattr(response, f"{name}_pdf_path", None)
                    or response.glossary_path
                ),
                "filename": artifact.filename,
                "content_type": _guess_content_type(
                    input_file_path if name == _SOURCE_ARTIFACT_NAME else Path(artifact.filename)
                ),
            }
            for name, artifact in response.artifacts.items()
        },
    }
    for name, artifact in response.artifacts.items():
        if name == _SOURCE_ARTIFACT_NAME:
            manifest["artifacts"][name]["path"] = input_file_path.as_posix()
            manifest["artifacts"][name]["content_type"] = _guess_content_type(
                input_file_path
            )
        elif name == "mono":
            manifest["artifacts"][name]["path"] = response.mono_pdf_path
            manifest["artifacts"][name]["content_type"] = "application/pdf"
        elif name == "dual":
            manifest["artifacts"][name]["path"] = response.dual_pdf_path
            manifest["artifacts"][name]["content_type"] = "application/pdf"
        elif name == "glossary":
            manifest["artifacts"][name]["path"] = response.glossary_path
            manifest["artifacts"][name]["content_type"] = _guess_content_type(
                Path(artifact.filename)
            )
    _artifact_manifest_path(output_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_artifact_manifest(output_dir: Path) -> dict[str, Any]:
    manifest_path = _artifact_manifest_path(output_dir)
    if not manifest_path.exists():
        raise APIError(
            status_code=404,
            code="artifact_manifest_not_found",
            message="No artifacts were recorded for this request.",
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _build_translate_response(
    *,
    settings: Any,
    file_path: Path,
    request_id: str,
    output_dir: Path,
    result: Any,
    token_usage: dict[str, Any] | None,
) -> TranslateResponse:
    artifacts = _build_artifacts(
        request_id=request_id,
        input_file_path=file_path,
        result=result,
    )
    response = TranslateResponse(
        status="completed",
        request_id=request_id,
        service=settings.translate_engine_settings.translate_engine_type,
        input_file=str(file_path),
        output_dir=str(settings.translation.output),
        mono_pdf_path=_normalize_output_path(getattr(result, "mono_pdf_path", None)),
        dual_pdf_path=_normalize_output_path(getattr(result, "dual_pdf_path", None)),
        glossary_path=_normalize_output_path(
            getattr(result, "auto_extracted_glossary_path", None)
        ),
        mono_download_url=artifacts.get("mono").url if "mono" in artifacts else None,
        dual_download_url=artifacts.get("dual").url if "dual" in artifacts else None,
        glossary_download_url=(
            artifacts.get("glossary").url if "glossary" in artifacts else None
        ),
        preview_url=(
            artifacts.get("mono").url
            if "mono" in artifacts
            else (artifacts.get("dual").url if "dual" in artifacts else None)
        ),
        total_seconds=getattr(result, "total_seconds", None),
        token_usage=token_usage or {},
        artifacts=artifacts,
        downloads=_build_downloads(artifacts),
    )
    _write_artifact_manifest(output_dir, file_path, response)
    return response


async def _translate_single_file(
    settings: Any,
    *,
    file_path: Path,
    request_id: str,
    output_dir: Path,
) -> TranslateResponse:
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
            return _build_translate_response(
                settings=settings,
                file_path=file_path,
                request_id=request_id,
                output_dir=output_dir,
                result=event["translate_result"],
                token_usage=event.get("token_usage", {}),
            )

    raise APIError(
        status_code=500,
        code="missing_translation_result",
        message="The translation finished without a result payload.",
    )


def _progress_message(event: dict[str, Any]) -> str:
    stage = event.get("stage") or "translation"
    part_index = event.get("part_index") or 1
    total_parts = event.get("total_parts") or 1
    return f"{stage} is running for part {part_index} of {total_parts}."


def _coerce_json_line(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")


async def _stream_translation_file(
    *,
    settings: Any,
    file_path: Path,
    request_id: str,
    output_dir: Path,
):
    async for event in do_translate_async_stream(
        settings,
        file_path,
        raise_on_error=False,
    ):
        event_type = event.get("type")
        if event_type in {"progress_start", "progress_update", "progress_end"}:
            yield _coerce_json_line(
                {
                    "type": "progress",
                    "stage": event.get("stage"),
                    "message": _progress_message(event),
                    "overall_progress": event.get("overall_progress"),
                    "part_index": event.get("part_index"),
                    "total_parts": event.get("total_parts"),
                    "stage_current": event.get("stage_current"),
                    "stage_total": event.get("stage_total"),
                }
            )
            continue

        if event_type == "error":
            error_message = str(event.get("error", "Translation failed."))
            yield _coerce_json_line(
                {
                    "type": "error",
                    "error": {
                        "code": "translation_failed",
                        "message": error_message,
                        "hint": _build_translation_hint(error_message),
                        "details": event.get("details"),
                    },
                }
            )
            return

        if event_type == "finish":
            response = _build_translate_response(
                settings=settings,
                file_path=file_path,
                request_id=request_id,
                output_dir=output_dir,
                result=event["translate_result"],
                token_usage=event.get("token_usage", {}),
            )
            yield _coerce_json_line(
                {
                    "type": "finish",
                    "result": response.model_dump(mode="json"),
                }
            )
            return

    yield _coerce_json_line(
        {
            "type": "error",
            "error": {
                "code": "missing_translation_result",
                "message": "The translation finished without a result payload.",
            },
        }
    )


def _frontend_dist_dir() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent / "frontend" / "dist",
        Path(__file__).with_name("webui_dist"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _serve_frontend(app: FastAPI) -> bool:
    dist_dir = _frontend_dist_dir()
    if dist_dir is None:
        logger.warning("Frontend dist directory not found.")
        return False

    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(dist_dir / "index.html")

    return True


def create_app(*, serve_frontend: bool = False, include_frontend: bool | None = None) -> FastAPI:
    if include_frontend is not None:
        serve_frontend = include_frontend

    app = FastAPI(
        title="PDFMathTranslate Next HTTP API",
        version=__version__,
        description=(
            "Minimal HTTP API for translating a single PDF with the current "
            "server configuration."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
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

    if not serve_frontend:

        @app.get("/", include_in_schema=False)
        async def root() -> dict[str, Any]:
            return _api_root_payload()

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

    @app.get("/app/config", tags=["meta"])
    async def app_config() -> dict[str, Any]:
        return _build_app_config()

    @app.get("/ui/bootstrap", tags=["meta"])
    async def ui_bootstrap() -> dict[str, Any]:
        return _build_ui_bootstrap()

    @app.get("/api/ui-config", tags=["frontend"])
    async def ui_config() -> dict[str, Any]:
        return build_ui_schema(_load_base_cli_settings())

    @app.post("/api/config", tags=["frontend"])
    async def save_ui_config(payload: WebConfigPayload) -> dict[str, str]:
        cli_settings = _build_full_cli_settings(payload.settings).clone()
        ConfigManager().write_user_default_config_file(cli_settings)
        return {"status": "saved", "config_file": str(DEFAULT_CONFIG_FILE)}

    @app.post("/settings/default", tags=["frontend"])
    async def save_default_settings(payload: WebUISettings) -> dict[str, str]:
        try:
            cli_settings, _ = _build_settings_from_webui(
                _load_base_cli_settings(),
                payload,
                file_path=None,
                output_dir=None,
                for_saved_config=True,
            )
        except WebUIError as exc:
            raise APIError(
                status_code=400,
                code="invalid_translation_settings",
                message=str(exc),
            ) from exc
        ConfigManager().write_user_default_config_file(cli_settings)
        return {"status": "saved", "config_file": str(DEFAULT_CONFIG_FILE)}

    async def _download_artifact_impl(
        request_id: str,
        artifact_name: str,
    ) -> FileResponse:
        output_dir = _HTTP_OUTPUT_ROOT / request_id
        manifest = _read_artifact_manifest(output_dir)
        artifact = manifest.get("artifacts", {}).get(artifact_name)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        file_path = Path(artifact["path"])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Artifact file not found.")
        return FileResponse(
            file_path,
            media_type=artifact.get("content_type") or _guess_content_type(file_path),
            filename=artifact.get("filename") or file_path.name,
        )

    @app.get("/artifacts/{request_id}/{artifact_name}", tags=["artifacts"])
    async def download_artifact(request_id: str, artifact_name: str) -> FileResponse:
        return await _download_artifact_impl(request_id, artifact_name)

    @app.get("/requests/{request_id}/artifacts/{artifact_name}", tags=["artifacts"])
    async def download_artifact_legacy(
        request_id: str,
        artifact_name: str,
    ) -> FileResponse:
        return await _download_artifact_impl(request_id, artifact_name)

    @app.get("/api/files/{request_id}/{artifact_name}", tags=["artifacts"])
    async def download_artifact_alias(
        request_id: str, artifact_name: str
    ) -> FileResponse:
        return await _download_artifact_impl(request_id, artifact_name)

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
        return await _translate_single_file(
            settings,
            file_path=file_path,
            request_id=request_id,
            output_dir=output_dir,
        )

    @app.post("/translate/file", response_model=TranslateResponse, tags=["translation"])
    async def translate_file(
        file: Annotated[UploadFile | None, File()] = None,
        file_url: Annotated[str | None, Form()] = None,
        request_json: Annotated[str, Form()] = "{}",
    ) -> TranslateResponse:
        try:
            request = BrowserTranslateRequest.model_validate_json(request_json)
        except ValidationError as exc:
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="The browser translation payload is invalid.",
                details=exc.errors(),
            ) from exc

        if bool(file) == bool(file_url):
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="Provide exactly one of uploaded `file` or `file_url`.",
            )

        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(request_id, None)
        file_path = (
            await _save_uploaded_pdf(file, output_dir)
            if file
            else _download_pdf_from_url(file_url or "", output_dir)
        )
        settings = _build_browser_request_settings(
            request,
            file_path=file_path,
            output_dir=output_dir,
        )
        return await _translate_single_file(
            settings,
            file_path=file_path,
            request_id=request_id,
            output_dir=output_dir,
        )

    @app.post("/translate/file/stream", tags=["translation"])
    async def translate_file_stream(
        file: Annotated[UploadFile | None, File()] = None,
        file_url: Annotated[str | None, Form()] = None,
        request_json: Annotated[str, Form()] = "{}",
    ) -> StreamingResponse:
        try:
            request = BrowserTranslateRequest.model_validate_json(request_json)
        except ValidationError as exc:
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="The browser translation payload is invalid.",
                details=exc.errors(),
            ) from exc

        if bool(file) == bool(file_url):
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="Provide exactly one of uploaded `file` or `file_url`.",
            )

        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(request_id, None)
        file_path = (
            await _save_uploaded_pdf(file, output_dir)
            if file
            else _download_pdf_from_url(file_url or "", output_dir)
        )
        settings = _build_browser_request_settings(
            request,
            file_path=file_path,
            output_dir=output_dir,
        )
        return StreamingResponse(
            _stream_translation_file(
                settings=settings,
                file_path=file_path,
                request_id=request_id,
                output_dir=output_dir,
            ),
            media_type="application/x-ndjson",
        )

    @app.post("/translate/upload/stream", tags=["translation"])
    async def translate_upload_stream(
        payload: Annotated[str, Form()],
        file: Annotated[UploadFile | None, File()] = None,
    ) -> StreamingResponse:
        if file is None:
            raise APIError(
                status_code=400,
                code="missing_upload",
                message="Upload a PDF file before starting translation.",
            )
        try:
            webui_payload = _parse_webui_payload(payload)
        except (ValidationError, WebUIError) as exc:
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message=str(exc),
            ) from exc

        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(request_id, None)
        file_path = await _save_uploaded_pdf(file, output_dir)
        try:
            _cli_settings, settings = _build_settings_from_webui(
                _load_base_cli_settings(),
                webui_payload,
                file_path=file_path,
                output_dir=output_dir,
            )
        except WebUIError as exc:
            raise APIError(
                status_code=400,
                code="invalid_translation_settings",
                message=str(exc),
            ) from exc

        async def legacy_stream():
            yield _coerce_json_line(
                {
                    "type": "start",
                    "request_id": request_id,
                    "service": settings.translate_engine_settings.translate_engine_type,
                }
            )
            async for line in _stream_translation_file(
                settings=settings,
                file_path=file_path,
                request_id=request_id,
                output_dir=output_dir,
            ):
                yield line

        return StreamingResponse(legacy_stream(), media_type="application/x-ndjson")

    @app.post("/api/translate/stream", tags=["frontend"])
    async def translate_stream(
        payload: Annotated[str, Form()],
        file: Annotated[UploadFile | None, File()] = None,
    ) -> StreamingResponse:
        try:
            translate_payload = WebTranslatePayload.model_validate_json(payload)
        except ValidationError as exc:
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="The React translation payload is invalid.",
                details=exc.errors(),
            ) from exc

        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(request_id, None)
        if translate_payload.source_type == "link":
            file_path = _download_pdf_from_url(translate_payload.file_url or "", output_dir)
        else:
            if file is None:
                raise APIError(
                    status_code=400,
                    code="missing_upload",
                    message="Upload a PDF file when `source_type` is `file`.",
                )
            file_path = await _save_uploaded_pdf(file, output_dir)

        settings = _build_web_request_settings(
            translate_payload,
            file_path=file_path,
            output_dir=output_dir,
        )
        return StreamingResponse(
            _stream_translation_file(
                settings=settings,
                file_path=file_path,
                request_id=request_id,
                output_dir=output_dir,
            ),
            media_type="application/x-ndjson",
        )

    if serve_frontend:
        frontend_served = _serve_frontend(app)
        if not frontend_served:
            logger.warning("Frontend was requested but no build output was found.")

            @app.get("/", include_in_schema=False)
            async def root_without_frontend() -> dict[str, Any]:
                return _api_root_payload()

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("pdf2zh_next.http_api:app", host="127.0.0.1", port=8000)
