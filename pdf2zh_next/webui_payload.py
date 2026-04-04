from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA_MAP
from pdf2zh_next.web_schema import build_ui_schema
from pdf2zh_next.web_schema import drop_empty_sensitive_values


class WebUIError(ValueError):
    pass


class WebUISettings(BaseModel):
    service: str | None = None
    lang_in: str = "en"
    lang_out: str = "zh"
    translation: dict[str, Any] = Field(default_factory=dict)
    pdf: dict[str, Any] = Field(default_factory=dict)
    engine_settings: dict[str, Any] = Field(default_factory=dict)


class WebUIBootstrapPayload(BaseModel):
    name: str
    version: str
    default_service: str
    default_locale: str
    services: list[dict[str, Any]]
    translation_languages: list[dict[str, Any]]
    translation_fields: list[dict[str, Any]]
    pdf_fields: list[dict[str, Any]]
    defaults: dict[str, Any]


def build_bootstrap_payload(
    base_settings: CLIEnvSettingsModel,
    *,
    version: str,
) -> WebUIBootstrapPayload:
    ui_schema = build_ui_schema(base_settings)
    return WebUIBootstrapPayload(
        name="PaperFlow Translate",
        version=version,
        default_service=ui_schema["default_service"],
        default_locale=ui_schema["default_locale"],
        services=ui_schema["services"],
        translation_languages=ui_schema["translation_languages"],
        translation_fields=ui_schema["translation_fields"],
        pdf_fields=ui_schema["pdf_fields"],
        defaults=ui_schema["defaults"],
    )


def parse_payload_json(payload: str) -> WebUISettings:
    try:
        return WebUISettings.model_validate_json(payload)
    except ValidationError as exc:
        raise WebUIError(str(exc)) from exc


def _apply_overrides(
    section: Any,
    overrides: dict[str, Any],
    *,
    section_name: str,
) -> None:
    for field_name, value in overrides.items():
        if field_name not in type(section).model_fields:
            raise WebUIError(
                f"Unsupported field `{field_name}` in `{section_name}` settings."
            )
        setattr(section, field_name, value)


def build_settings_from_webui(
    base_settings: CLIEnvSettingsModel,
    payload: WebUISettings,
    *,
    file_path: Path | None,
    output_dir: Path | None,
    for_saved_config: bool = False,
) -> tuple[CLIEnvSettingsModel, Any]:
    cli_settings = base_settings.clone()

    if payload.service:
        if payload.service not in TRANSLATION_ENGINE_METADATA_MAP:
            raise WebUIError(f"Unsupported translation service: {payload.service}")
        for metadata in TRANSLATION_ENGINE_METADATA:
            setattr(cli_settings, metadata.cli_flag_name, False)
        selected_metadata = TRANSLATION_ENGINE_METADATA_MAP[payload.service]
        setattr(cli_settings, selected_metadata.cli_flag_name, True)
        if payload.engine_settings:
            if not selected_metadata.cli_detail_field_name:
                raise WebUIError(
                    f"{selected_metadata.translate_engine_type} does not accept engine settings."
                )
            detail_model = getattr(cli_settings, selected_metadata.cli_detail_field_name)
            merged_engine_settings = detail_model.model_dump()
            merged_engine_settings.update(
                drop_empty_sensitive_values(payload.engine_settings)
            )
            merged_engine_settings["translate_engine_type"] = (
                selected_metadata.translate_engine_type
            )
            setattr(
                cli_settings,
                selected_metadata.cli_detail_field_name,
                selected_metadata.setting_model_type(**merged_engine_settings),
            )

    cli_settings.translation.lang_in = payload.lang_in
    cli_settings.translation.lang_out = payload.lang_out
    _apply_overrides(
        cli_settings.translation,
        dict(payload.translation),
        section_name="translation",
    )
    _apply_overrides(cli_settings.pdf, dict(payload.pdf), section_name="pdf")

    if file_path is not None:
        cli_settings.basic.input_files = {str(file_path)}
    if output_dir is not None:
        cli_settings.translation.output = str(output_dir)

    try:
        settings = cli_settings.to_settings_model()
        settings.validate_settings()
    except ValueError as exc:
        raise WebUIError(str(exc)) from exc

    if for_saved_config:
        cli_settings.basic.input_files = set()
        cli_settings.translation.output = None

    return cli_settings, settings
