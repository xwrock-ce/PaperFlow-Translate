from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Literal
from typing import get_args
from typing import get_origin

from pydantic import BaseModel

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.model import PDFSettings
from pdf2zh_next.config.model import TranslationSettings
from pdf2zh_next.config.translate_engine_model import GUI_PASSWORD_FIELDS
from pdf2zh_next.config.translate_engine_model import GUI_SENSITIVE_FIELDS
from pdf2zh_next.config.translate_engine_model import TERM_EXTRACTION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
from pdf2zh_next.web_localization import build_translation_language_options
from pdf2zh_next.web_localization import field_options
from pdf2zh_next.web_localization import localize_field_description
from pdf2zh_next.web_localization import localize_field_label
from pdf2zh_next.web_localization import normalize_ui_locale

_TRANSLATION_FIELD_EXCLUDES = {
    "lang_in",
    "lang_out",
    "output",
    "glossaries",
}
_PDF_FIELD_EXCLUDES = set()
_SENSITIVE_FIELD_NAMES = set(GUI_PASSWORD_FIELDS) | set(GUI_SENSITIVE_FIELDS)


def _infer_field_type(annotation: Any) -> tuple[str, list[str] | None]:
    origin = get_origin(annotation)
    args = [arg for arg in get_args(annotation) if arg is not type(None)]

    if origin is Literal:
        return "enum", [str(item) for item in args]
    if origin is None:
        if annotation is bool:
            return "boolean", None
        if annotation in {int, float}:
            return "number", None
        return "string", None

    if bool in args:
        return "boolean", None
    if int in args or float in args:
        return "number", None
    for arg in args:
        if get_origin(arg) is Literal:
            return "enum", [str(item) for item in get_args(arg)]
    if str in args:
        return "string", None
    return "string", None


def _build_field_schema(
    *,
    model_type: type[BaseModel],
    detail_path: str,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for field_name, model_field in model_type.model_fields.items():
        if field_name in {"translate_engine_type", "support_llm"}:
            continue
        if exclude and field_name in exclude:
            continue

        field_type, options = _infer_field_type(model_field.annotation)
        input_type = "text"
        if field_name in GUI_PASSWORD_FIELDS:
            input_type = "password"
        elif field_name.endswith("url") or field_name.endswith("host"):
            input_type = "url"
        elif "prompt" in field_name or "pattern" in field_name or "domains" in field_name:
            input_type = "textarea"

        localized_options = field_options(field_name)
        if localized_options:
            field_type = "enum"
        if field_type == "enum" and not localized_options:
            raise ValueError(
                f"Missing localized WebUI choices for field `{field_name}`."
            )

        fields.append(
            {
                "path": f"{detail_path}.{field_name}",
                "name": field_name,
                "label": localize_field_label(field_name),
                "description": localize_field_description(field_name),
                "field_type": field_type,
                "input_type": input_type,
                "options": localized_options
                or (
                    [{"label": {"en": item, "zh": item}, "value": item} for item in options]
                    if options
                    else []
                ),
                "sensitive": field_name in GUI_SENSITIVE_FIELDS,
                "secret": field_name in GUI_PASSWORD_FIELDS,
            }
        )
    return fields


def build_ui_schema(default_settings: CLIEnvSettingsModel) -> dict[str, Any]:
    translation_fields = _build_field_schema(
        model_type=TranslationSettings,
        detail_path="translation",
        exclude=_TRANSLATION_FIELD_EXCLUDES,
    )
    pdf_fields = _build_field_schema(
        model_type=PDFSettings,
        detail_path="pdf",
        exclude=_PDF_FIELD_EXCLUDES,
    )

    engines = []
    for metadata in TRANSLATION_ENGINE_METADATA:
        engines.append(
            {
                "name": metadata.translate_engine_type,
                "flag_name": metadata.cli_flag_name,
                "detail_field_name": metadata.cli_detail_field_name,
                "support_llm": metadata.support_llm,
                "fields": _build_field_schema(
                    model_type=metadata.setting_model_type,
                    detail_path=metadata.cli_detail_field_name or metadata.cli_flag_name,
                )
                if metadata.cli_detail_field_name
                else [],
            }
        )

    term_engines = []
    for metadata in TERM_EXTRACTION_ENGINE_METADATA:
        detail_field_name = f"term_{metadata.cli_detail_field_name or metadata.cli_flag_name}"
        term_engines.append(
            {
                "name": metadata.translate_engine_type,
                "flag_name": f"term_{metadata.cli_flag_name}",
                "detail_field_name": detail_field_name,
                "fields": _build_field_schema(
                    model_type=metadata.term_setting_model_type,
                    detail_path=detail_field_name,
                )
                if metadata.cli_detail_field_name
                else [],
            }
        )

    default_engine = next(
        (
            metadata.translate_engine_type
            for metadata in TRANSLATION_ENGINE_METADATA
            if getattr(default_settings, metadata.cli_flag_name, False)
        ),
        "SiliconFlowFree",
    )

    return {
        "defaults": scrub_sensitive_settings(default_settings.model_dump(mode="json")),
        "default_locale": normalize_ui_locale(default_settings.gui_settings.ui_lang),
        "translation_languages": build_translation_language_options(),
        "page_presets": [
            {"label": {"en": "All Pages", "zh": "全部页面"}, "value": "all"},
            {"label": {"en": "First Page", "zh": "第一页"}, "value": "first"},
            {"label": {"en": "First 5 Pages", "zh": "前 5 页"}, "value": "first5"},
            {"label": {"en": "Custom Range", "zh": "自定义范围"}, "value": "custom"},
        ],
        "translation_fields": translation_fields,
        "pdf_fields": pdf_fields,
        "services": engines,
        "term_services": term_engines,
        "default_service": default_engine,
    }


def scrub_sensitive_settings(settings_dict: dict[str, Any]) -> dict[str, Any]:
    scrubbed = {}
    for key, value in settings_dict.items():
        if isinstance(value, dict):
            scrubbed[key] = scrub_sensitive_settings(value)
            continue
        if key in _SENSITIVE_FIELD_NAMES:
            scrubbed[key] = None
            continue
        scrubbed[key] = value
    return scrubbed


def drop_empty_sensitive_values(settings_dict: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in settings_dict.items():
        if isinstance(value, dict):
            nested = drop_empty_sensitive_values(value)
            if nested:
                cleaned[key] = nested
            continue
        if key in _SENSITIVE_FIELD_NAMES and value in (None, ""):
            continue
        cleaned[key] = value
    return cleaned


def get_frontend_dist_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"
