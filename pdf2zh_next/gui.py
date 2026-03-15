import asyncio
import cgi
import csv
import html
import io
import logging
import shutil
import socket
import tempfile
import typing
import uuid
from enum import Enum
from pathlib import Path
from string import Template
from urllib.parse import urlparse

import chardet
import gradio as gr
import requests
import yaml
from gradio_i18n import Translate
from gradio_pdf import PDF

from pdf2zh_next.config import ConfigManager
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import GUI_PASSWORD_FIELDS
from pdf2zh_next.config.translate_engine_model import GUI_SENSITIVE_FIELDS
from pdf2zh_next.config.translate_engine_model import TERM_EXTRACTION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import (
    TERM_EXTRACTION_ENGINE_METADATA_MAP,
)
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA_MAP
from pdf2zh_next.const import DEFAULT_CONFIG_DIR
from pdf2zh_next.const import DEFAULT_CONFIG_FILE
from pdf2zh_next.high_level import TranslationError
from pdf2zh_next.high_level import do_translate_async_stream
from pdf2zh_next.high_level import validate_pdf_file
from pdf2zh_next.i18n import LANGUAGES
from pdf2zh_next.i18n import gettext as _
from pdf2zh_next.i18n import update_current_languages

logger = logging.getLogger(__name__)


class SaveMode(Enum):
    """Enum for configuration save behavior."""

    follow_settings = "follow_settings"  # Follow disable_config_auto_save setting
    never = "never"  # Never save
    always = "always"  # Always save regardless of disable_config_auto_save


def get_translation_dic(file_path: Path):
    with file_path.open(encoding="utf-8", newline="\n") as f:
        return yaml.safe_load(f)


__gui_service_arg_names = []
__gui_term_service_arg_names = []
LLM_support_index_map = {}
# The following variables associate strings with specific languages
lang_map = {
    "English": "en",
    "Simplified Chinese": "zh-CN",
    "Traditional Chinese - Hong Kong": "zh-HK",
    "Traditional Chinese - Taiwan": "zh-TW",
    "Japanese": "ja",
    "Korean": "ko",
    "Polish": "pl",
    "Russian": "ru",
    "Spanish": "es",
    "Portuguese": "pt",
    "Brazilian Portuguese": "pt-BR",
    "French": "fr",
    "Malay": "ms",
    "Indonesian": "id",
    "Turkmen": "tk",
    "Filipino (Tagalog)": "tl",
    "Vietnamese": "vi",
    "Kazakh (Latin)": "kk",
    "German": "de",
    "Dutch": "nl",
    "Irish": "ga",
    "Italian": "it",
    "Greek": "el",
    "Swedish": "sv",
    "Danish": "da",
    "Norwegian": "no",
    "Icelandic": "is",
    "Finnish": "fi",
    "Ukrainian": "uk",
    "Czech": "cs",
    "Romanian": "ro",  # Covers Romanian, Moldovan, Moldovan (Cyrillic)
    "Hungarian": "hu",
    "Slovak": "sk",
    "Croatian": "hr",  # Also listed later, keep first
    "Estonian": "et",
    "Latvian": "lv",
    "Lithuanian": "lt",
    "Belarusian": "be",
    "Macedonian": "mk",
    "Albanian": "sq",
    "Serbian (Cyrillic)": "sr",  # Covers Serbian (Latin) too
    "Slovenian": "sl",
    "Catalan": "ca",
    "Bulgarian": "bg",
    "Maltese": "mt",
    "Swahili": "sw",
    "Amharic": "am",
    "Oromo": "om",
    "Tigrinya": "ti",
    "Haitian Creole": "ht",
    "Latin": "la",
    "Lao": "lo",
    "Malayalam": "ml",
    "Gujarati": "gu",
    "Thai": "th",
    "Burmese": "my",
    "Tamil": "ta",
    "Telugu": "te",
    "Oriya": "or",  # Also listed later, keep first
    "Armenian": "hy",
    "Mongolian (Cyrillic)": "mn",
    "Georgian": "ka",
    "Khmer": "km",
    "Bosnian": "bs",
    "Luxembourgish": "lb",
    "Romansh": "rm",
    "Turkish": "tr",
    "Sinhala": "si",
    "Uzbek": "uz",
    "Kyrgyz": "ky",  # Listed as Kirghiz later, keep this one
    "Tajik": "tg",
    "Abkhazian": "ab",
    "Afar": "aa",
    "Afrikaans": "af",
    "Akan": "ak",
    "Aragonese": "an",
    "Avaric": "av",
    "Ewe": "ee",
    "Aymara": "ay",
    "Ojibwa": "oj",
    "Occitan": "oc",
    "Ossetian": "os",
    "Pali": "pi",
    "Bashkir": "ba",
    "Basque": "eu",
    "Breton": "br",
    "Chamorro": "ch",
    "Chechen": "ce",
    "Chuvash": "cv",
    "Tswana": "tn",
    "Ndebele, South": "nr",
    "Ndonga": "ng",
    "Faroese": "fo",
    "Fijian": "fj",
    "Frisian, Western": "fy",
    "Ganda": "lg",
    "Kongo": "kg",
    "Kalaallisut": "kl",
    "Church Slavic": "cu",
    "Guarani": "gn",
    "Interlingua": "ia",
    "Herero": "hz",
    "Kikuyu": "ki",
    "Rundi": "rn",
    "Kinyarwanda": "rw",
    "Galician": "gl",
    "Kanuri": "kr",
    "Cornish": "kw",
    "Komi": "kv",
    "Xhosa": "xh",
    "Corsican": "co",
    "Cree": "cr",
    "Quechua": "qu",
    "Kurdish (Latin)": "ku",
    "Kuanyama": "kj",
    "Limburgan": "li",
    "Lingala": "ln",
    "Manx": "gv",
    "Malagasy": "mg",
    "Marshallese": "mh",
    "Maori": "mi",
    "Navajo": "nv",
    "Nauru": "na",
    "Nyanja": "ny",
    "Norwegian Nynorsk": "nn",
    "Sardinian": "sc",
    "Northern Sami": "se",
    "Samoan": "sm",
    "Sango": "sg",
    "Shona": "sn",
    "Esperanto": "eo",
    "Scottish Gaelic": "gd",
    "Somali": "so",
    "Southern Sotho": "st",
    "Tatar": "tt",
    "Tahitian": "ty",
    "Tongan": "to",
    "Twi": "tw",
    "Walloon": "wa",
    "Welsh": "cy",
    "Venda": "ve",
    "Volapük": "vo",
    "Interlingue": "ie",
    "Hiri Motu": "ho",
    "Igbo": "ig",
    "Ido": "io",
    "Inuktitut": "iu",
    "Inupiaq": "ik",
    "Sichuan Yi": "ii",
    "Yoruba": "yo",
    "Zhuang": "za",
    "Tsonga": "ts",
    "Zulu": "zu",
}

rev_lang_map = {v: k for k, v in lang_map.items()}

# The following variable associate strings with page ranges
# Page map with fixed internal keys
page_map = {
    "All": None,
    "First": [0],
    "First 5 pages": list(range(0, 5)),
    "Range": None,  # User-defined range
}


def get_page_choices():
    """Get page range choices with translated labels"""
    return [
        (_("All"), "All"),
        (_("First"), "First"),
        (_("First 5 pages"), "First 5 pages"),
        (_("Range"), "Range"),
    ]


# Load configuration
config_manager = ConfigManager()
try:
    # Load configuration from files and environment variables
    settings = config_manager.initialize_cli_config()
    # Check if sensitive inputs should be disabled in GUI
    disable_sensitive_input = settings.gui_settings.disable_gui_sensitive_input
except Exception as e:
    logger.warning(f"Could not load initial config: {e}")
    settings = CLIEnvSettingsModel()
    disable_sensitive_input = False

# Define default values
default_lang_from = rev_lang_map.get(settings.translation.lang_in, "English")

default_lang_to = settings.translation.lang_out
for display_name, code in lang_map.items():
    if code == default_lang_to:
        default_lang_to = display_name
        break
else:
    default_lang_to = "Simplified Chinese"  # Fallback

# Available translation services
# This will eventually be dynamically determined based on available translators
available_services = [x.translate_engine_type for x in TRANSLATION_ENGINE_METADATA]

if settings.gui_settings.enabled_services:
    enabled_services = {
        x.lower() for x in settings.gui_settings.enabled_services.split(",")
    }
    available_services = [
        x for x in available_services if x.lower() in enabled_services
    ]

assert available_services, "No translation service is enabled"


disable_gui_sensitive_input = settings.gui_settings.disable_gui_sensitive_input


def _validate_pdf_link(url: str) -> str:
    normalized_url = url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise gr.Error(
            _("Enter a direct PDF link that starts with http:// or https://.")
        )
    return normalized_url


def download_with_limit(url: str, save_path: str, size_limit: int = None) -> str:
    """
    This function downloads a file from a URL and saves it to a specified path.

    Inputs:
        - url: The URL to download the file from
        - save_path: The path to save the file to
        - size_limit: The maximum size of the file to download

    Returns:
        - The path of the downloaded file
    """
    chunk_size = 1024
    total_size = 0
    pdf_header = b""
    with requests.get(url, stream=True, timeout=10) as response:
        response.raise_for_status()
        content = response.headers.get("Content-Disposition")
        try:  # filename from header
            _value, params = cgi.parse_header(content)
            filename = params["filename"]
        except Exception:  # filename from url
            filename = Path(urlparse(url).path).name
        filename = f"{Path(filename).stem or 'download'}.pdf"
        save_path = Path(save_path).resolve()
        file_path = save_path / filename
        if not file_path.resolve().is_relative_to(save_path):
            raise gr.Error(_("The downloaded filename was invalid."))
        try:
            with file_path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    total_size += len(chunk)
                    if size_limit and total_size > size_limit:
                        raise gr.Error(
                            _("The downloaded file exceeded the size limit.")
                        )

                    if len(pdf_header) < 5:
                        missing_bytes = 5 - len(pdf_header)
                        pdf_header += chunk[:missing_bytes]
                        if len(pdf_header) == 5 and pdf_header != b"%PDF-":
                            raise gr.Error(
                                _(
                                    "The downloaded file is not a valid PDF. Please provide a direct PDF link."
                                )
                            )
                    file.write(chunk)

                if total_size == 0 or pdf_header != b"%PDF-":
                    raise gr.Error(
                        _(
                            "The downloaded file is not a valid PDF. Please provide a direct PDF link."
                        )
                    )
        except Exception:
            file_path.unlink(missing_ok=True)
            raise
    return file_path


def _prepare_input_file(
    file_type: str, file_input: str, link_input: str, output_dir: Path
) -> Path:
    """
    This function prepares the input file for translation.

    Inputs:
        - file_type: The type of file to translate (File or Link)
        - file_input: The path to the file to translate
        - link_input: The link to the file to translate
        - output_dir: The directory to save the file to

    Returns:
        - The path of the input file
    """
    if file_type == "File":
        if not file_input:
            raise gr.Error(_("Please upload a PDF file before starting translation."))
        source_path = Path(file_input)
        if source_path.suffix.lower() != ".pdf":
            raise gr.Error(_("Please upload a PDF file."))
        try:
            validate_pdf_file(source_path)
        except FileNotFoundError as exc:
            raise gr.Error(
                _("The uploaded file is no longer available. Please upload it again.")
            ) from exc
        except ValueError as exc:
            raise gr.Error(
                _(
                    "The uploaded file is not a valid PDF. Please choose a real PDF document."
                )
            ) from exc
        file_path = shutil.copy(source_path, output_dir)
    else:
        if not link_input:
            raise gr.Error(
                _("Please paste a direct PDF link before starting translation.")
            )
        normalized_link = _validate_pdf_link(link_input)
        try:
            file_path = download_with_limit(normalized_link, output_dir)
        except gr.Error:
            raise
        except requests.RequestException as exc:
            raise gr.Error(
                _("Could not download the PDF: {error}").format(error=exc)
            ) from exc
        except Exception as exc:
            raise gr.Error(
                _("Could not prepare the PDF from the provided link: {error}").format(
                    error=exc
                )
            ) from exc

    prepared_file = Path(file_path)
    try:
        validate_pdf_file(prepared_file)
    except FileNotFoundError as exc:
        raise gr.Error(_("The prepared PDF could not be found. Please retry.")) from exc
    except ValueError as exc:
        raise gr.Error(
            _(
                "The selected source is not a valid PDF. Upload the original PDF or use a direct PDF link."
            )
        ) from exc

    return prepared_file


def _validate_rate_limit_inputs(
    true_rate_limit_mode: str, **inputs
) -> tuple[bool, str]:
    """
    Validate rate limit inputs

    Returns:
        tuple: (is_valid, error_message)
    """
    if true_rate_limit_mode == "RPM":
        rpm = inputs.get("rpm_input", 0)
        if not isinstance(rpm, int | float) or rpm <= 0:
            return False, "RPM must be a positive integer"

        if isinstance(rpm, float):
            if not rpm.is_integer():
                return False, "RPM must be a positive integer"

    elif true_rate_limit_mode == "Concurrent Threads":
        threads = inputs.get(
            "concurrent_threads", inputs.get("concurrent_threads_input", 0)
        )
        if not isinstance(threads, int | float) or threads <= 0:
            return False, "Concurrent threads must be a positive integer"

        if isinstance(threads, float):
            if not threads.is_integer():
                return False, "Concurrent threads must be a positive integer"

    elif true_rate_limit_mode == "Custom":
        qps = inputs.get("custom_qps", inputs.get("custom_qps_input", 0))
        pool_workers = inputs.get(
            "custom_pool_workers", inputs.get("custom_pool_max_workers_input")
        )

        if not isinstance(qps, int | float) or qps <= 0:
            return False, "QPS must be a positive integer"

        if isinstance(qps, float):
            if not qps.is_integer():
                return False, "QPS must be a positive integer"

        if pool_workers is not None and (
            not isinstance(pool_workers, int | float) or pool_workers < 0
        ):
            return False, "Pool workers must be a non-negative integer"

        if isinstance(pool_workers, float):
            if not pool_workers.is_integer():
                return False, "Pool workers must be a non-negative integer"

    return True, ""


def _calculate_rate_limit_params(
    rate_limit_mode: str, ui_inputs: dict, default_qps: int = 4
) -> tuple[int, int | None]:
    """
    Calculate QPS and pool workers based on rate limit mode

    Args:
        rate_limit_mode: Rate limit mode ("RPM", "Concurrent Threads", "Custom")
        ui_inputs: User input parameters dictionary
        default_qps: Default QPS value

    Returns:
        tuple: (qps, pool_max_workers)

    Raises:
        ValueError: When input parameter validation fails
    """
    # Validate input parameters
    is_valid, error_msg = _validate_rate_limit_inputs(
        true_rate_limit_mode=rate_limit_mode, **ui_inputs
    )
    if not is_valid:
        logger.warning(f"Rate limit validation failed: {error_msg}")
        raise ValueError(error_msg)

    if rate_limit_mode == "RPM":
        rpm: int = ui_inputs.get("rpm_input", 240)
        qps = max(1, rpm // 60)
        pool_workers = min(1000, qps * 10)

    elif rate_limit_mode == "Concurrent Threads":
        threads: int = ui_inputs.get(
            "concurrent_threads", ui_inputs.get("concurrent_threads_input", 40)
        )
        # Ensure at least 1 worker, at most 1000 workers, using a safer calculation method
        pool_workers = min(1000, max(1, min(int(threads * 0.9), max(1, threads - 20))))
        qps = max(1, pool_workers)

    else:  # Custom
        qps = ui_inputs.get(
            "custom_qps", ui_inputs.get("custom_qps_input", default_qps)
        )
        pool_workers = ui_inputs.get(
            "custom_pool_workers",
            ui_inputs.get("custom_pool_max_workers_input"),
        )
        qps = int(qps)
        pool_workers = int(pool_workers) if pool_workers and pool_workers > 0 else None

    logger.info(f"QPS: {qps}, Pool Workers: {pool_workers}")

    return qps, pool_workers if pool_workers and pool_workers > 0 else None


def _parse_page_range_text(
    page_range_value: str | None,
) -> list[tuple[int, int]] | None:
    normalized_value = str(page_range_value or "").strip()
    if not normalized_value:
        return None

    ranges: list[tuple[int, int]] = []
    try:
        for part in normalized_value.split(","):
            part = part.strip()
            if not part:
                raise ValueError(_("Found an empty page entry."))

            if "-" in part:
                start_end = part.split("-", maxsplit=1)
                if len(start_end) != 2:
                    raise ValueError(
                        _("Invalid page number format in range: {part}").format(
                            part=part
                        )
                    )
                start, end = start_end
                try:
                    start_as_int = int(start) if start else 1
                    end_as_int = int(end) if end else -1
                    if start_as_int < 1 and start:
                        raise ValueError(
                            _("Invalid start page number: {page}").format(page=start)
                        )
                    if end_as_int < -1:
                        raise ValueError(
                            _("Invalid end page number: {page}").format(page=end)
                        )
                    if end_as_int != -1 and start_as_int > end_as_int:
                        raise ValueError(
                            _(
                                "Start page {start} is greater than end page {end}"
                            ).format(
                                start=start,
                                end=end,
                            )
                        )
                    ranges.append((start_as_int, end_as_int))
                except ValueError as exc:
                    if "invalid literal for int()" in str(exc):
                        raise ValueError(
                            _("Invalid page number format in range: {part}").format(
                                part=part
                            )
                        ) from exc
                    raise
            else:
                try:
                    page = int(part)
                    if page < 1:
                        raise ValueError(
                            _("Invalid page number: {page}").format(page=page)
                        )
                    ranges.append((page, page))
                except ValueError as exc:
                    if "invalid literal for int()" in str(exc):
                        raise ValueError(
                            _("Invalid page number format: {part}").format(part=part)
                        ) from exc
                    raise
    except ValueError as exc:
        raise ValueError(
            _("Error parsing pages parameter: {error}").format(error=exc)
        ) from exc

    return ranges


def _validate_manual_page_range(page_range_value: str | None) -> str:
    normalized_value = str(page_range_value or "").strip()
    if not normalized_value:
        raise gr.Error(_("Enter a page range before starting translation."))

    try:
        _parse_page_range_text(normalized_value)
    except ValueError as exc:
        raise gr.Error(
            _(
                "Page range format is invalid: {error}\nUse examples such as 1,3,5-10,-5."
            ).format(error=exc)
        ) from exc

    return normalized_value


def _get_gradio_error_message(error: gr.Error) -> str:
    return str(getattr(error, "message", error)).strip()


def _build_page_range_feedback(page_range_value: str, page_input_value: str | None):
    if page_range_value != "Range":
        return gr.update(value="", visible=False)

    normalized_value = str(page_input_value or "").strip()
    if not normalized_value:
        return gr.update(
            value=_("Enter pages like 1,3,5-10,-5 to limit the translation scope."),
            visible=True,
        )

    try:
        validated_value = _validate_manual_page_range(normalized_value)
    except gr.Error as exc:
        return gr.update(value=_get_gradio_error_message(exc), visible=True)

    return gr.update(
        value=_("Page range ready: {pages}").format(pages=validated_value),
        visible=True,
    )


def _validate_output_selection(*, no_mono: bool, no_dual: bool) -> None:
    if no_mono and no_dual:
        raise gr.Error(
            _("Select at least one output format before starting translation.")
        )


def _build_term_extraction_visibility_updates(enabled: bool):
    return (
        gr.update(visible=not enabled),
        gr.update(visible=enabled),
    )


def _build_translate_settings(
    base_settings: CLIEnvSettingsModel,
    file_path: Path,
    output_dir: Path,
    save_mode: SaveMode,
    ui_inputs: dict,
) -> SettingsModel:
    """
    This function builds translation settings from UI inputs.

    Inputs:
        - base_settings: The base settings model to build upon
        - file_path: The path to the input file
        - output_dir: The output directory
        - save_mode: SaveMode enum indicating when to save config
        - ui_inputs: A dictionary of UI inputs

    Returns:
        - A configured SettingsModel instance
    """
    # Clone base settings to avoid modifying the original
    translate_settings = base_settings.clone()
    original_output = translate_settings.translation.output
    original_pages = translate_settings.pdf.pages
    original_gui_settings = config_manager.config_cli_settings.gui_settings

    # Extract UI values
    service = ui_inputs.get("service")
    lang_from = ui_inputs.get("lang_from")
    lang_to = ui_inputs.get("lang_to")
    page_range = ui_inputs.get("page_range")
    page_input = ui_inputs.get("page_input")
    prompt = ui_inputs.get("prompt")
    ignore_cache = ui_inputs.get("ignore_cache")

    # PDF Output Options
    no_mono = ui_inputs.get("no_mono")
    no_dual = ui_inputs.get("no_dual")
    dual_translate_first = ui_inputs.get("dual_translate_first")
    use_alternating_pages_dual = ui_inputs.get("use_alternating_pages_dual")
    watermark_output_mode = ui_inputs.get("watermark_output_mode")

    # Rate Limit Options
    rate_limit_mode = ui_inputs.get("rate_limit_mode")

    # Advanced Translation Options
    min_text_length = ui_inputs.get("min_text_length")
    rpc_doclayout = ui_inputs.get("rpc_doclayout")
    enable_auto_term_extraction = ui_inputs.get("enable_auto_term_extraction")
    primary_font_family = ui_inputs.get("primary_font_family")

    # Advanced PDF Options
    skip_clean = ui_inputs.get("skip_clean")
    disable_rich_text_translate = ui_inputs.get("disable_rich_text_translate")
    enhance_compatibility = ui_inputs.get("enhance_compatibility")
    split_short_lines = ui_inputs.get("split_short_lines")
    short_line_split_factor = ui_inputs.get("short_line_split_factor")
    translate_table_text = ui_inputs.get("translate_table_text")
    skip_scanned_detection = ui_inputs.get("skip_scanned_detection")
    ocr_workaround = ui_inputs.get("ocr_workaround")
    max_pages_per_part = ui_inputs.get("max_pages_per_part")
    formular_font_pattern = ui_inputs.get("formular_font_pattern")
    formular_char_pattern = ui_inputs.get("formular_char_pattern")
    auto_enable_ocr_workaround = ui_inputs.get("auto_enable_ocr_workaround")
    only_include_translated_page = ui_inputs.get("only_include_translated_page")

    # BabelDOC v0.5.1 new options
    merge_alternating_line_numbers = ui_inputs.get("merge_alternating_line_numbers")
    remove_non_formula_lines = ui_inputs.get("remove_non_formula_lines")
    non_formula_line_iou_threshold = ui_inputs.get("non_formula_line_iou_threshold")
    figure_table_protection_threshold = ui_inputs.get(
        "figure_table_protection_threshold"
    )
    skip_formula_offset_calculation = ui_inputs.get("skip_formula_offset_calculation")

    # Term extraction options
    term_service = ui_inputs.get("term_service")
    term_rate_limit_mode = ui_inputs.get("term_rate_limit_mode")
    term_rpm_input = ui_inputs.get("term_rpm_input")
    term_concurrent_threads = ui_inputs.get("term_concurrent_threads")
    term_custom_qps = ui_inputs.get("term_custom_qps")
    term_custom_pool_workers = ui_inputs.get("term_custom_pool_workers")

    # New input for custom_system_prompt
    custom_system_prompt_input = ui_inputs.get("custom_system_prompt_input")
    glossaries = ui_inputs.get("glossaries")
    save_auto_extracted_glossary = ui_inputs.get("save_auto_extracted_glossary")

    # Map UI language selections to language codes
    source_lang = lang_map.get(lang_from, "auto")
    target_lang = lang_map.get(lang_to, "zh")

    # Set up page selection
    if page_range == "Range":
        pages = _validate_manual_page_range(page_input)
    else:
        # Use predefined ranges from page_map
        selected_pages = page_map[page_range]
        if selected_pages is None:
            pages = None  # All pages
        else:
            # Convert page indices to comma-separated string
            pages = ",".join(
                str(p + 1) for p in selected_pages
            )  # +1 because UI is 1-indexed

    # Update settings with UI values
    translate_settings.basic.input_files = {str(file_path)}
    translate_settings.report_interval = 0.2
    translate_settings.translation.lang_in = source_lang
    translate_settings.translation.lang_out = target_lang
    translate_settings.translation.output = str(output_dir)
    translate_settings.translation.ignore_cache = ignore_cache

    _validate_output_selection(no_mono=no_mono, no_dual=no_dual)

    # Update Translation Settings
    if min_text_length is not None:
        translate_settings.translation.min_text_length = int(min_text_length)
    if rpc_doclayout:
        translate_settings.translation.rpc_doclayout = rpc_doclayout

    # UI uses positive switch, config uses negative flag, so we invert here
    if enable_auto_term_extraction is not None:
        translate_settings.translation.no_auto_extract_glossary = (
            not enable_auto_term_extraction
        )
    if primary_font_family:
        if primary_font_family == "Auto":
            translate_settings.translation.primary_font_family = None
        else:
            translate_settings.translation.primary_font_family = primary_font_family

    # Calculate and update rate limit settings
    if service != "SiliconFlowFree":
        qps, pool_workers = _calculate_rate_limit_params(
            rate_limit_mode, ui_inputs, translate_settings.translation.qps or 4
        )

        # Update translation settings
        translate_settings.translation.qps = int(qps)
        translate_settings.translation.pool_max_workers = (
            int(pool_workers) if pool_workers is not None else None
        )

    # Calculate and update term extraction rate limit settings
    if term_rate_limit_mode:
        term_rate_inputs = {
            "rpm_input": term_rpm_input,
            "concurrent_threads": term_concurrent_threads,
            "custom_qps": term_custom_qps,
            "custom_pool_workers": term_custom_pool_workers,
        }
        term_qps, term_pool_workers = _calculate_rate_limit_params(
            term_rate_limit_mode,
            term_rate_inputs,
            translate_settings.translation.term_qps
            or translate_settings.translation.qps
            or 4,
        )
        translate_settings.translation.term_qps = int(term_qps)
        translate_settings.translation.term_pool_max_workers = (
            int(term_pool_workers) if term_pool_workers is not None else None
        )

    # Reset all term extraction engine flags
    for term_metadata in TERM_EXTRACTION_ENGINE_METADATA:
        term_flag_name = f"term_{term_metadata.cli_flag_name}"
        if hasattr(translate_settings, term_flag_name):
            setattr(translate_settings, term_flag_name, False)

    # Configure term extraction engine settings from UI when not following main engine
    if (
        term_service
        and term_service != "Follow main translation engine"
        and not translate_settings.translation.no_auto_extract_glossary
        and term_service in TERM_EXTRACTION_ENGINE_METADATA_MAP
    ):
        term_metadata = TERM_EXTRACTION_ENGINE_METADATA_MAP[term_service]

        # Enable selected term extraction engine flag
        term_flag_name = f"term_{term_metadata.cli_flag_name}"
        if hasattr(translate_settings, term_flag_name):
            setattr(translate_settings, term_flag_name, True)

        # Update term extraction engine detail settings
        if term_metadata.cli_detail_field_name:
            term_detail_field_name = f"term_{term_metadata.cli_detail_field_name}"
            term_detail_settings = getattr(translate_settings, term_detail_field_name)
            term_model_type = term_metadata.term_setting_model_type

            for field_name, field in term_model_type.model_fields.items():
                if field_name in ("translate_engine_type", "support_llm"):
                    continue

                value = ui_inputs.get(field_name)
                if value is None:
                    continue

                type_hint = field.annotation
                original_type = typing.get_origin(type_hint)
                type_args = typing.get_args(type_hint)

                if type_hint is str or str in type_args:
                    pass
                elif type_hint is int or int in type_args:
                    value = int(value)
                elif type_hint is bool or bool in type_args:
                    value = bool(value)
                else:
                    raise Exception(
                        f"Unsupported type {type_hint} for field {field_name} in gui term extraction engine settings"
                    )

                setattr(term_detail_settings, field_name, value)

    # Update PDF Settings
    translate_settings.pdf.pages = pages
    translate_settings.pdf.no_mono = no_mono
    translate_settings.pdf.no_dual = no_dual
    translate_settings.pdf.dual_translate_first = dual_translate_first
    translate_settings.pdf.use_alternating_pages_dual = use_alternating_pages_dual

    # Map watermark mode from UI to enum
    translate_settings.pdf.watermark_output_mode = (
        watermark_output_mode.lower().replace(" ", "_")
    )

    # Update Advanced PDF Settings
    translate_settings.pdf.skip_clean = skip_clean
    translate_settings.pdf.disable_rich_text_translate = disable_rich_text_translate
    translate_settings.pdf.enhance_compatibility = enhance_compatibility
    translate_settings.pdf.split_short_lines = split_short_lines
    translate_settings.pdf.ocr_workaround = ocr_workaround
    if short_line_split_factor is not None:
        translate_settings.pdf.short_line_split_factor = float(short_line_split_factor)

    translate_settings.pdf.translate_table_text = translate_table_text
    translate_settings.pdf.skip_scanned_detection = skip_scanned_detection
    translate_settings.pdf.auto_enable_ocr_workaround = auto_enable_ocr_workaround
    translate_settings.pdf.only_include_translated_page = only_include_translated_page

    if max_pages_per_part is not None and max_pages_per_part > 0:
        translate_settings.pdf.max_pages_per_part = int(max_pages_per_part)

    if formular_font_pattern:
        translate_settings.pdf.formular_font_pattern = formular_font_pattern

    if formular_char_pattern:
        translate_settings.pdf.formular_char_pattern = formular_char_pattern

    # Apply BabelDOC v0.5.1 new options
    translate_settings.pdf.no_merge_alternating_line_numbers = (
        not merge_alternating_line_numbers
    )
    translate_settings.pdf.no_remove_non_formula_lines = not remove_non_formula_lines
    if non_formula_line_iou_threshold is not None:
        translate_settings.pdf.non_formula_line_iou_threshold = float(
            non_formula_line_iou_threshold
        )
    if figure_table_protection_threshold is not None:
        translate_settings.pdf.figure_table_protection_threshold = float(
            figure_table_protection_threshold
        )
    translate_settings.pdf.skip_formula_offset_calculation = (
        skip_formula_offset_calculation
    )

    assert service in TRANSLATION_ENGINE_METADATA_MAP, "UNKNOW TRANSLATION ENGINE!"

    for metadata in TRANSLATION_ENGINE_METADATA:
        cli_flag = metadata.cli_flag_name
        setattr(translate_settings, cli_flag, False)

    metadata = TRANSLATION_ENGINE_METADATA_MAP[service]
    cli_flag = metadata.cli_flag_name
    setattr(translate_settings, cli_flag, True)
    if metadata.cli_detail_field_name:
        detail_setting = getattr(translate_settings, metadata.cli_detail_field_name)
        if metadata.setting_model_type:
            for field_name in metadata.setting_model_type.model_fields:
                if field_name == "translate_engine_type" or field_name == "support_llm":
                    continue
                if disable_gui_sensitive_input:
                    if field_name in GUI_PASSWORD_FIELDS:
                        continue
                    if field_name in GUI_SENSITIVE_FIELDS:
                        continue
                value = ui_inputs.get(field_name)
                type_hint = detail_setting.model_fields[field_name].annotation
                original_type = typing.get_origin(type_hint)
                type_args = typing.get_args(type_hint)
                if type_hint is str or str in type_args:
                    pass
                elif type_hint is int or int in type_args:
                    value = int(value)
                elif type_hint is bool or bool in type_args:
                    value = bool(value)
                else:
                    raise Exception(
                        f"Unsupported type {type_hint} for field {field_name} in gui translation engine settings"
                    )
                setattr(detail_setting, field_name, value)

    # Add custom prompt if provided
    if prompt:
        # This might need adjustment based on how prompt is handled in the new system
        translate_settings.custom_prompt = Template(prompt)

    # Add custom system prompt if provided
    if custom_system_prompt_input:
        translate_settings.translation.custom_system_prompt = custom_system_prompt_input
    else:
        translate_settings.translation.custom_system_prompt = None

    if glossaries:
        translate_settings.translation.glossaries = glossaries
    else:
        translate_settings.translation.glossaries = None

    translate_settings.translation.save_auto_extracted_glossary = (
        save_auto_extracted_glossary
    )

    # Validate settings before proceeding
    try:
        translate_settings.validate_settings()
        temp_settings = translate_settings.to_settings_model()
        translate_settings.translation.output = original_output
        translate_settings.pdf.pages = original_pages
        translate_settings.gui_settings = original_gui_settings
        translate_settings.basic.gui = False
        translate_settings.basic.debug = False
        translate_settings.translation.glossaries = None

        # Determine if config should be saved based on save_mode
        should_save = False
        if save_mode == SaveMode.always:
            should_save = True
        elif save_mode == SaveMode.follow_settings:
            should_save = not temp_settings.gui_settings.disable_config_auto_save
        # SaveMode.never: should_save remains False

        if should_save:
            config_manager.write_user_default_config_file(settings=translate_settings)
            global settings
            settings = translate_settings
        temp_settings.validate_settings()
        temp_settings.parse_pages()
        return temp_settings
    except ValueError as e:
        raise gr.Error(
            _format_user_facing_error(_("Invalid translation settings."), str(e))
        ) from e


def _build_glossary_list(glossary_file, service_name=None):
    if not LLM_support_index_map.get(service_name, False):
        return None
    glossary_list = []
    if glossary_file is None:
        return None
    for file in glossary_file:
        try:
            f = io.StringIO(
                _decode_uploaded_text_file(file, file_label=_("glossary file"))
            )
            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".csv"
            ) as temp_file:
                temp_file.write(f.getvalue())
                f.close()
            glossary_list.append(temp_file.name)
        except gr.Error:
            raise
        except (UnicodeDecodeError, csv.Error, KeyError, ValueError) as e:
            logger.error(f"Error processing glossary file: {e}")
            raise gr.Error(
                _(
                    "Failed to process glossary CSV. Check the file encoding and column format, then retry.\n{details}"
                ).format(details=e)
            ) from e
    return ",".join(glossary_list)


def build_ui_inputs(*args):
    """
    Build ui_inputs dictionary from *args.

    Args:
        *args: UI setting controls in the following order:
            service, lang_from, lang_to, page_range, page_input,
            no_mono, no_dual, dual_translate_first, use_alternating_pages_dual, watermark_output_mode,
            rate_limit_mode, rpm_input, concurrent_threads_input, custom_qps_input, custom_pool_max_workers_input,
            prompt, min_text_length, rpc_doclayout, custom_system_prompt_input, glossary_file,
            save_auto_extracted_glossary, enable_auto_term_extraction, primary_font_family, skip_clean,
            disable_rich_text_translate, enhance_compatibility, split_short_lines, short_line_split_factor,
            translate_table_text, skip_scanned_detection, max_pages_per_part, formular_font_pattern,
            formular_char_pattern, ignore_cache, ocr_workaround, auto_enable_ocr_workaround,
            only_include_translated_page, merge_alternating_line_numbers, remove_non_formula_lines,
            non_formula_line_iou_threshold, figure_table_protection_threshold, skip_formula_offset_calculation,
            term_service, term_rate_limit_mode, term_rpm_input, term_concurrent_threads_input,
            term_custom_qps_input, term_custom_pool_max_workers_input, *translation_engine_arg_inputs

    Returns:
        dict: ui_inputs dictionary with all UI settings
    """
    # Fixed parameter names in order (excluding translation_engine_arg_inputs)
    fixed_param_names = [
        "service",
        "lang_from",
        "lang_to",
        "page_range",
        "page_input",
        "no_mono",
        "no_dual",
        "dual_translate_first",
        "use_alternating_pages_dual",
        "watermark_output_mode",
        "rate_limit_mode",
        "rpm_input",
        "concurrent_threads",  # mapped from concurrent_threads_input
        "custom_qps",  # mapped from custom_qps_input
        "custom_pool_workers",  # mapped from custom_pool_max_workers_input
        "prompt",
        "min_text_length",
        "rpc_doclayout",
        "custom_system_prompt_input",
        "glossary_file",  # will be converted to glossaries
        "save_auto_extracted_glossary",
        "enable_auto_term_extraction",
        "primary_font_family",
        "skip_clean",
        "disable_rich_text_translate",
        "enhance_compatibility",
        "split_short_lines",
        "short_line_split_factor",
        "translate_table_text",
        "skip_scanned_detection",
        "max_pages_per_part",
        "formular_font_pattern",
        "formular_char_pattern",
        "ignore_cache",
        "ocr_workaround",
        "auto_enable_ocr_workaround",
        "only_include_translated_page",
        "merge_alternating_line_numbers",
        "remove_non_formula_lines",
        "non_formula_line_iou_threshold",
        "figure_table_protection_threshold",
        "skip_formula_offset_calculation",
        "term_service",
        "term_rate_limit_mode",
        "term_rpm_input",
        "term_concurrent_threads",
        "term_custom_qps",
        "term_custom_pool_workers",
    ]

    # Split args into fixed params and translation_engine_arg_inputs
    num_fixed = len(fixed_param_names)
    fixed_args = args[:num_fixed]
    translation_engine_arg_inputs = args[num_fixed:]

    # Build ui_inputs dictionary
    ui_inputs = {}
    for param_name, arg_value in zip(fixed_param_names, fixed_args, strict=False):
        ui_inputs[param_name] = arg_value

    # Convert glossary_file to glossaries
    service = ui_inputs["service"]
    glossary_file = ui_inputs["glossary_file"]
    ui_inputs["glossaries"] = _build_glossary_list(glossary_file, service)

    # Add translation engine args (main translator + term translator detail settings)
    main_detail_count = len(__gui_service_arg_names)
    term_detail_count = len(__gui_term_service_arg_names)

    main_detail_inputs = translation_engine_arg_inputs[:main_detail_count]
    term_detail_inputs = translation_engine_arg_inputs[
        main_detail_count : main_detail_count + term_detail_count
    ]

    for arg_name, arg_input in zip(
        __gui_service_arg_names, main_detail_inputs, strict=False
    ):
        ui_inputs[arg_name] = arg_input

    for arg_name, arg_input in zip(
        __gui_term_service_arg_names, term_detail_inputs, strict=False
    ):
        ui_inputs[arg_name] = arg_input

    return ui_inputs


_UNCHANGED = object()
_GUI_PROGRESS = gr.Progress()


def _decode_uploaded_text_file(file_content: bytes, *, file_label: str) -> str:
    detected_encoding = (chardet.detect(file_content) or {}).get("encoding")
    if not detected_encoding:
        raise gr.Error(
            _(
                "Could not detect the encoding for the uploaded {file_label}. Please save it as UTF-8 and try again."
            ).format(file_label=file_label)
        )

    try:
        return file_content.decode(detected_encoding)
    except UnicodeDecodeError as exc:
        raise gr.Error(
            _("Failed to decode the uploaded {file_label}: {error}").format(
                file_label=file_label,
                error=exc,
            )
        ) from exc


def _normalize_output_path(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    return path.as_posix()


def _component_update(*, visible=_UNCHANGED, value=_UNCHANGED):
    if visible is _UNCHANGED and value is _UNCHANGED:
        return gr.skip()

    update_kwargs = {}
    if visible is not _UNCHANGED:
        update_kwargs["visible"] = visible
    if value is not _UNCHANGED:
        update_kwargs["value"] = value
    return gr.update(**update_kwargs)


def _button_update(*, value=_UNCHANGED, interactive=_UNCHANGED, variant=_UNCHANGED):
    if value is _UNCHANGED and interactive is _UNCHANGED and variant is _UNCHANGED:
        return gr.skip()

    update_kwargs = {}
    if value is not _UNCHANGED:
        update_kwargs["value"] = value
    if interactive is not _UNCHANGED:
        update_kwargs["interactive"] = interactive
    if variant is not _UNCHANGED:
        update_kwargs["variant"] = variant
    return gr.update(**update_kwargs)


def _build_action_button_updates(*, is_running: bool):
    if is_running:
        return (
            _button_update(
                value=_("Translating..."),
                interactive=False,
                variant="primary",
            ),
            _button_update(interactive=True, variant="stop"),
            _button_update(interactive=False, variant="secondary"),
        )

    return (
        _button_update(value=_("Translate"), interactive=True, variant="primary"),
        _button_update(interactive=False, variant="stop"),
        _button_update(interactive=True, variant="secondary"),
    )


def _build_cancelling_action_button_updates():
    return (
        _button_update(
            value=_("Cancelling..."),
            interactive=False,
            variant="primary",
        ),
        _button_update(interactive=False, variant="stop"),
        _button_update(interactive=False, variant="secondary"),
    )


def _sanitize_user_facing_error_detail(error_details: str | None) -> str | None:
    details = (error_details or "").strip()
    if not details:
        return None
    if "traceback" in details.lower() or "\n" in details or len(details) > 180:
        return None
    return details


def _build_user_error_hint(
    error_message: str, error_details: str | None = None
) -> str | None:
    searchable_message = "\n".join(
        item for item in [error_message, error_details or ""] if item
    ).lower()

    if any(token in searchable_message for token in ("api key", "credential", "auth")):
        return _("Check the selected engine credentials and try again.")
    if any(
        token in searchable_message
        for token in (
            "connecterror",
            "operation not permitted",
            "no available endpoints",
            "chatproxy",
            "api1.pdf2zh-next.com",
            "api2.pdf2zh-next.com",
        )
    ):
        return _(
            "The default SiliconFlowFree service could not be reached. Check the network/proxy settings, retry later, or choose another translation service such as OpenAI or Ollama."
        )
    if any(
        token in searchable_message
        for token in ("timeout", "timed out", "connection reset", "network")
    ):
        return _(
            "The translation service did not respond in time. Check the network connection or lower the concurrency settings."
        )
    if any(
        token in searchable_message
        for token in ("rate limit", "429", "too many requests")
    ):
        return _(
            "The translation service is throttling requests. Lower the rate-limit settings and retry."
        )
    if (
        "not a valid pdf" in searchable_message
        or "direct pdf link" in searchable_message
    ):
        return _("Use the original PDF file or a direct PDF download link, then retry.")
    return None


def _format_user_facing_error(
    error_message: str | Exception,
    error_details: str | None = None,
) -> str:
    message = str(error_message).strip()
    safe_detail = _sanitize_user_facing_error_detail(error_details)
    hint = _build_user_error_hint(message, error_details)

    message_parts = [message]
    if safe_detail and safe_detail not in message:
        message_parts.append(safe_detail)
    if hint and hint not in message:
        message_parts.append(hint)

    return "\n".join(message_parts)


def _build_source_preview_value(
    file_type_value: str,
    file_path: str | None,
) -> str | None:
    if file_type_value != "File" or not file_path:
        return None
    return file_path


def build_live_status_html(
    title: str,
    message: str,
    *,
    progress_value: float = 0.0,
    detail: str | None = None,
    tone: str = "idle",
    meta_items: list[tuple[str, str]] | None = None,
) -> str:
    progress_percent = max(0, min(100, int(round(float(progress_value) * 100))))
    safe_tone = html.escape(tone)
    detail_html = ""
    if detail:
        detail_html = f'<p class="live-status-detail">{html.escape(str(detail))}</p>'

    meta_html = ""
    if meta_items:
        meta_html = "".join(
            f"""
            <div class="live-status-meta-item">
                <span class="live-status-meta-label">{html.escape(str(label))}</span>
                <span class="live-status-meta-value">{html.escape(str(value))}</span>
            </div>
            """
            for label, value in meta_items
            if value not in (None, "")
        )
        if meta_html:
            meta_html = f'<div class="live-status-meta">{meta_html}</div>'

    return f"""
    <section class="live-status-card live-status-{safe_tone}">
        <div class="live-status-head">
            <div>
                <p class="live-status-kicker">{html.escape(_("Live status"))}</p>
                <h3 class="live-status-title">{html.escape(str(title))}</h3>
            </div>
            <span class="live-status-percent">{progress_percent}%</span>
        </div>
        <p class="live-status-message">{html.escape(str(message))}</p>
        <div class="live-status-meter">
            <span style="width: {progress_percent}%"></span>
        </div>
        {detail_html}
        {meta_html}
    </section>
    """


def _build_route_text(lang_from_name: str, lang_to_name: str) -> str:
    return f"{lang_from_name} -> {lang_to_name}"


def _build_service_route_meta_items(
    service_name: str,
    lang_from_name: str,
    lang_to_name: str,
) -> list[tuple[str, str]]:
    return [
        (_("Engine"), service_name),
        (_("Route"), _build_route_text(lang_from_name, lang_to_name)),
    ]


def _build_output_status_meta_items(
    *,
    mono_ready: bool,
    dual_ready: bool,
    glossary_ready: bool,
) -> list[tuple[str, str]]:
    return [
        (_("Mono"), _("Ready") if mono_ready else _("Unavailable")),
        (_("Dual"), _("Ready") if dual_ready else _("Unavailable")),
        (_("Glossary"), _("Ready") if glossary_ready else _("Unavailable")),
    ]


def _downloads_heading(token_info: str = "") -> str:
    return f"## {_('Downloads')}{token_info}"


def build_hero_html() -> str:
    return f"""
        <section class="hero-card">
            <p class="hero-kicker">{html.escape(_('PDF Translation Workspace'))}</p>
            <h1 class="hero-title">{html.escape(_('PaperFlow Translate'))}</h1>
            <p class="hero-description">{html.escape(_('Translate academic PDFs while keeping layout, formulas, and reading flow intact.'))}</p>
            <div class="hero-highlights">
                <span class="hero-chip">{html.escape(_('Layout-safe output'))}</span>
                <span class="hero-chip">{html.escape(_('Live progress pinned'))}</span>
                <span class="hero-chip">{html.escape(_('Mono / Dual export'))}</span>
            </div>
            <p class="hero-caption">{html.escape(_('Upload a paper, choose the language route, and start translating. Progress stays visible on the right while you keep reading the preview.'))}</p>
        </section>
    """


def _build_translation_updates(
    *,
    mono_value=_UNCHANGED,
    preview_value=_UNCHANGED,
    dual_value=_UNCHANGED,
    glossary_value=_UNCHANGED,
    mono_visible=_UNCHANGED,
    dual_visible=_UNCHANGED,
    glossary_visible=_UNCHANGED,
    output_title_value=_UNCHANGED,
    output_title_visible=_UNCHANGED,
    result_zone_visible=_UNCHANGED,
    live_status_value=_UNCHANGED,
    action_buttons=_UNCHANGED,
):
    button_updates = (
        action_buttons
        if action_buttons is not _UNCHANGED
        else (gr.skip(), gr.skip(), gr.skip())
    )
    return (
        mono_value if mono_value is not _UNCHANGED else gr.skip(),
        preview_value if preview_value is not _UNCHANGED else gr.skip(),
        dual_value if dual_value is not _UNCHANGED else gr.skip(),
        glossary_value if glossary_value is not _UNCHANGED else gr.skip(),
        _component_update(visible=mono_visible),
        _component_update(visible=dual_visible),
        _component_update(visible=glossary_visible),
        _component_update(
            value=output_title_value,
            visible=output_title_visible,
        ),
        _component_update(visible=result_zone_visible),
        live_status_value if live_status_value is not _UNCHANGED else gr.skip(),
        *button_updates,
    )


async def _run_translation_task(
    settings: SettingsModel,
    file_path: Path,
    session_id: str,
    event_queue: asyncio.Queue,
) -> tuple[Path | None, Path | None, Path | None, dict | None]:
    """
    This function runs the translation task and handles progress updates.

    Inputs:
        - settings: The translation settings
        - file_path: The path to the input file
        - session_id: The session identifier for logging
        - event_queue: Queue used to mirror progress updates into the UI

    Returns:
        - A tuple of (mono_pdf_path, dual_pdf_path, glossary_path, token_usage)
    """
    mono_path = None
    dual_path = None
    glossary_path = None
    token_usage = None

    try:
        settings.basic.input_files = set()
        async for event in do_translate_async_stream(
            settings,
            file_path,
            raise_on_error=False,
        ):
            if event["type"] in (
                "progress_start",
                "progress_update",
                "progress_end",
            ):
                await event_queue.put(
                    {
                        "stage": event["stage"],
                        "progress_value": event["overall_progress"] / 100.0,
                        "part_index": event["part_index"],
                        "total_parts": event["total_parts"],
                        "stage_current": event["stage_current"],
                        "stage_total": event["stage_total"],
                    }
                )
            elif event["type"] == "finish":
                # Extract result paths
                result = event["translate_result"]
                mono_path = result.mono_pdf_path
                dual_path = result.dual_pdf_path
                glossary_path = result.auto_extracted_glossary_path
                token_usage = event.get("token_usage", {})
                break
            elif event["type"] == "error":
                # Handle error event
                error_msg = event.get("error", "Unknown error")
                error_details = event.get("details", "")
                raise gr.Error(_format_user_facing_error(error_msg, error_details))
    except asyncio.CancelledError:
        # Handle task cancellation - let translate_file handle the UI updates
        logger.info(f"Translation for session {session_id} was cancelled")
        raise  # Re-raise for the calling function to handle
    except TranslationError as e:
        # Handle structured translation errors
        logger.error(f"Translation error: {e}")
        raise gr.Error(_format_user_facing_error(getattr(e, "raw_message", e))) from e
    except gr.Error as e:
        # Handle Gradio errors
        logger.error(f"Gradio error: {e}")
        raise
    except Exception as e:
        # Handle other exceptions
        logger.error(f"Error in _run_translation_task: {e}", exc_info=True)
        raise gr.Error(
            _format_user_facing_error(
                _("Translation failed because of an unexpected internal error.")
            )
        ) from e

    return mono_path, dual_path, glossary_path, token_usage


def stop_translate_file(
    service_name: str,
    lang_from_name: str,
    lang_to_name: str,
) -> tuple[str, typing.Any, typing.Any, typing.Any]:
    """
    Build the immediate UI response for a cancel request.

    Inputs:
        - service_name: Current translation engine
        - lang_from_name: Current source language
        - lang_to_name: Current target language
    """
    logger.info("Cancellation requested from GUI")
    return (
        build_live_status_html(
            _("Cancelling translation"),
            _("Stop request sent. The running job is shutting down safely."),
            progress_value=0.0,
            detail=_("This usually completes within a few seconds."),
            tone="warning",
            meta_items=_build_service_route_meta_items(
                service_name,
                lang_from_name,
                lang_to_name,
            ),
        ),
        *_build_cancelling_action_button_updates(),
    )


async def translate_file(
    file_type,
    file_input,
    link_input,
    *ui_args,
    progress=_GUI_PROGRESS,
):
    """
    This function translates a PDF file from one language to another using the new architecture.

    Inputs:
        - file_type: The type of file to translate
        - file_input: The file to translate
        - link_input: The link to the file to translate
        - *ui_args: UI setting controls (see build_ui_inputs for details)
        - progress: The progress bar

    Returns:
        - The translated mono PDF file
        - The preview PDF file
        - The translated dual PDF file
        - The visibility state of the mono PDF output
        - The visibility state of the dual PDF output
        - The visibility state of the output title
    """
    # Build ui_inputs from *args
    ui_inputs = build_ui_inputs(*ui_args)
    service_name = ui_inputs["service"]
    lang_from_name = ui_inputs["lang_from"]
    lang_to_name = ui_inputs["lang_to"]

    # Initialize session and output directory
    session_id = str(uuid.uuid4())
    preview_source_value = _build_source_preview_value(file_type, file_input)

    # Track progress
    progress(0, desc=_("Starting translation..."))

    # Prepare output directory
    output_dir = Path("pdf2zh_files") / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield _build_translation_updates(
            mono_value=None,
            preview_value=preview_source_value,
            dual_value=None,
            glossary_value=None,
            mono_visible=False,
            dual_visible=False,
            glossary_visible=False,
            output_title_value=_downloads_heading(),
            output_title_visible=False,
            result_zone_visible=False,
            live_status_value=build_live_status_html(
                _("Preparing translation"),
                _("Validating source file and building the translation job."),
                progress_value=0.04,
                detail=_(
                    "This status panel stays pinned so you can watch progress without scrolling."
                ),
                tone="running",
                meta_items=_build_service_route_meta_items(
                    service_name,
                    lang_from_name,
                    lang_to_name,
                ),
            ),
            action_buttons=_build_action_button_updates(is_running=True),
        )

        # Step 1: Prepare input file
        file_path = _prepare_input_file(file_type, file_input, link_input, output_dir)
        preview_source_value = str(file_path)
        source_name = file_path.name if file_path else _("Source ready")
        yield _build_translation_updates(
            preview_value=preview_source_value,
            live_status_value=build_live_status_html(
                _("Source ready"),
                source_name,
                progress_value=0.1,
                detail=_("Initializing engine settings and preparing the first stage."),
                tone="running",
                meta_items=_build_service_route_meta_items(
                    service_name,
                    lang_from_name,
                    lang_to_name,
                ),
            ),
        )

        # Step 2: Build translation settings
        translate_settings = _build_translate_settings(
            settings.clone(), file_path, output_dir, SaveMode.follow_settings, ui_inputs
        )

        # Step 3: Create and run the translation task
        event_queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(
            _run_translation_task(
                translate_settings, file_path, session_id, event_queue
            )
        )

        while True:
            try:
                progress_event = await asyncio.wait_for(event_queue.get(), timeout=0.2)
            except TimeoutError:
                if task.done():
                    break
                continue

            progress_value = progress_event["progress_value"]
            stage_name = progress_event["stage"]
            part_index = progress_event["part_index"]
            total_parts = progress_event["total_parts"]
            stage_current = progress_event["stage_current"]
            stage_total = progress_event["stage_total"]
            desc = (
                f"{stage_name} "
                f"({part_index}/{total_parts}, {stage_current}/{stage_total})"
            )
            logger.info(f"Progress: {progress_value}, {desc}")
            progress(progress_value, desc=desc)
            yield _build_translation_updates(
                live_status_value=build_live_status_html(
                    _("Translating"),
                    stage_name,
                    progress_value=progress_value,
                    detail=_("Part {part} of {total} · Step {step} of {steps}").format(
                        part=part_index,
                        total=total_parts,
                        step=stage_current,
                        steps=stage_total,
                    ),
                    tone="running",
                    meta_items=_build_service_route_meta_items(
                        service_name,
                        lang_from_name,
                        lang_to_name,
                    ),
                )
            )

        mono_path, dual_path, glossary_path, token_usage = await task
        mono_path = _normalize_output_path(mono_path)
        dual_path = _normalize_output_path(dual_path)
        glossary_path = _normalize_output_path(glossary_path)

        token_info = ""
        if token_usage:
            token_info = "\n\n**Token Usage:**\n"  # noqa: S105, this is not a hardcoded password
            total_usage = {
                "total": 0,
                "prompt": 0,
                "cache_hit_prompt": 0,
                "completion": 0,
            }
            if "main" in token_usage:
                m = token_usage["main"]
                token_info += f"- Main: Total {m['total']} (Prompt {m['prompt']}, Cache Hit Prompt {m['cache_hit_prompt']}, Completion {m['completion']})\n"
                total_usage["total"] += m["total"]
                total_usage["prompt"] += m["prompt"]
                total_usage["cache_hit_prompt"] += m["cache_hit_prompt"]
                total_usage["completion"] += m["completion"]
            if "term" in token_usage:
                t = token_usage["term"]
                token_info += f"- Term: Total {t['total']} (Prompt {t['prompt']}, Cache Hit Prompt {t['cache_hit_prompt']}, Completion {t['completion']})\n"
                total_usage["total"] += t["total"]
                total_usage["prompt"] += t["prompt"]
                total_usage["cache_hit_prompt"] += t["cache_hit_prompt"]
                total_usage["completion"] += t["completion"]
            token_info += f"- Total: Total {total_usage['total']} (Prompt {total_usage['prompt']}, Cache Hit Prompt {total_usage['cache_hit_prompt']}, Completion {total_usage['completion']})\n"
            logger.info(f"Token usage: {token_info}")
        has_downloads = bool(mono_path or dual_path or glossary_path)
        progress(1.0, desc=_("Translation complete!"))
        yield _build_translation_updates(
            mono_value=str(mono_path) if mono_path else None,
            preview_value=(
                str(mono_path)
                if mono_path
                else (str(dual_path) if dual_path else gr.skip())
            ),
            dual_value=str(dual_path) if dual_path else None,
            glossary_value=str(glossary_path) if glossary_path else None,
            mono_visible=bool(mono_path),
            dual_visible=bool(dual_path),
            glossary_visible=bool(glossary_path),
            output_title_value=_downloads_heading(token_info),
            output_title_visible=has_downloads,
            result_zone_visible=has_downloads,
            live_status_value=build_live_status_html(
                _("Translation complete"),
                _(
                    "The translated files are ready. Downloads stay pinned here while you inspect the preview."
                ),
                progress_value=1.0,
                detail=(
                    _("Preview switched to the translated PDF.")
                    if mono_path or dual_path
                    else _("No translated PDF was returned by the backend.")
                ),
                tone="success",
                meta_items=_build_output_status_meta_items(
                    mono_ready=bool(mono_path),
                    dual_ready=bool(dual_path),
                    glossary_ready=bool(glossary_path),
                ),
            ),
            action_buttons=_build_action_button_updates(is_running=False),
        )
        return
    except asyncio.CancelledError:
        gr.Info(_("Translation cancelled"))
        yield _build_translation_updates(
            preview_value=preview_source_value,
            mono_visible=False,
            dual_visible=False,
            glossary_visible=False,
            output_title_value=_downloads_heading(),
            output_title_visible=False,
            result_zone_visible=False,
            live_status_value=build_live_status_html(
                _("Translation cancelled"),
                _("The running task was stopped before completion."),
                progress_value=0.0,
                detail=_("Adjust the settings and run it again when ready."),
                tone="warning",
                meta_items=_build_service_route_meta_items(
                    service_name,
                    lang_from_name,
                    lang_to_name,
                ),
            ),
            action_buttons=_build_action_button_updates(is_running=False),
        )
        return
    except gr.Error as e:
        yield _build_translation_updates(
            preview_value=preview_source_value,
            mono_visible=False,
            dual_visible=False,
            glossary_visible=False,
            output_title_value=_downloads_heading(),
            output_title_visible=False,
            result_zone_visible=False,
            live_status_value=build_live_status_html(
                _("Translation failed"),
                _get_gradio_error_message(e),
                progress_value=0.0,
                detail=_("Check the source file and engine settings, then retry."),
                tone="danger",
                meta_items=_build_service_route_meta_items(
                    service_name,
                    lang_from_name,
                    lang_to_name,
                ),
            ),
            action_buttons=_build_action_button_updates(is_running=False),
        )
        raise
    except Exception as e:
        logger.exception(f"Error in translate_file: {e}")
        user_message = _format_user_facing_error(
            _("Translation failed because of an unexpected internal error.")
        )
        yield _build_translation_updates(
            preview_value=preview_source_value,
            mono_visible=False,
            dual_visible=False,
            glossary_visible=False,
            output_title_value=_downloads_heading(),
            output_title_visible=False,
            result_zone_visible=False,
            live_status_value=build_live_status_html(
                _("Translation failed"),
                user_message,
                progress_value=0.0,
                detail=_("Check the source file and engine settings, then retry."),
                tone="danger",
                meta_items=_build_service_route_meta_items(
                    service_name,
                    lang_from_name,
                    lang_to_name,
                ),
            ),
            action_buttons=_build_action_button_updates(is_running=False),
        )
        raise gr.Error(user_message) from e


def save_config(
    *ui_args,
    progress=_GUI_PROGRESS,
):
    """
    This function saves the translation configuration.

    Inputs:
        - *ui_args: UI setting controls (see build_ui_inputs for details)
        - progress: The progress bar
    """
    # Build ui_inputs from *args
    ui_inputs = build_ui_inputs(*ui_args)

    # Track progress
    progress(0, desc=_("Saving configuration..."))

    # Prepare output directory
    output_dir = Path("pdf2zh_files")

    _build_translate_settings(
        settings.clone(), config_fake_pdf_path, output_dir, SaveMode.always, ui_inputs
    )

    # Show success message
    gr.Info(_("Configuration saved to: {path}").format(path=DEFAULT_CONFIG_FILE))


# Custom theme definition
custom_blue = gr.themes.Color(
    c50="#E8F3FF",
    c100="#BEDAFF",
    c200="#94BFFF",
    c300="#6AA1FF",
    c400="#4080FF",
    c500="#165DFF",  # Primary color
    c600="#0E42D2",
    c700="#0A2BA6",
    c800="#061D79",
    c900="#03114D",
    c950="#020B33",
)

custom_css = """
    :root {
        --app-bg: #edf3fa;
        --app-bg-deep: #d8e6f6;
        --app-surface: rgba(255, 255, 255, 0.88);
        --app-surface-soft: #f5f9ff;
        --app-surface-strong: #ffffff;
        --app-surface-tint: rgba(244, 249, 255, 0.92);
        --app-border: rgba(24, 48, 84, 0.11);
        --app-border-strong: rgba(24, 48, 84, 0.18);
        --app-text: #12253f;
        --app-text-muted: #61728b;
        --app-blue: #1263ff;
        --app-blue-deep: #0b47bf;
        --app-blue-soft: rgba(18, 99, 255, 0.11);
        --app-cyan: #0fa9bf;
        --app-green: #0f9f6e;
        --app-amber: #d9861b;
        --app-red: #d14343;
        --app-focus-ring: rgba(18, 99, 255, 0.16);
        --app-shadow: 0 30px 72px rgba(16, 28, 48, 0.12);
        --app-shadow-soft: 0 16px 40px rgba(16, 28, 48, 0.08);
        --app-shadow-hover: 0 26px 56px rgba(18, 99, 255, 0.12);
        --app-inset-highlight: inset 0 1px 0 rgba(255, 255, 255, 0.72);
        --app-radius: 26px;
        --app-radius-sm: 18px;
    }

    footer {
        visibility: hidden;
    }

    .gradio-container {
        background:
            radial-gradient(circle at 12% 10%, rgba(18, 99, 255, 0.12), transparent 0 28%),
            radial-gradient(circle at 86% 0%, rgba(15, 169, 191, 0.10), transparent 0 24%),
            radial-gradient(circle at 90% 85%, rgba(18, 99, 255, 0.08), transparent 0 22%),
            linear-gradient(180deg, #f7fbff 0%, var(--app-bg) 44%, #eef4fb 100%);
        color: var(--app-text);
        position: relative;
    }

    .gradio-container::before {
        content: "";
        position: fixed;
        inset: 0;
        background-image:
            linear-gradient(rgba(18, 99, 255, 0.028) 1px, transparent 1px),
            linear-gradient(90deg, rgba(18, 99, 255, 0.028) 1px, transparent 1px);
        background-size: 160px 160px;
        mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.28), transparent 78%);
        pointer-events: none;
        z-index: 0;
    }

    #app-shell,
    .gradio-container > .main {
        position: relative;
        z-index: 1;
    }

    .env-warning {
        color: #b96007 !important;
    }

    .env-success {
        color: #2e7d32 !important;
    }

    #app-shell {
        max-width: 1460px;
        margin: 0 auto;
        padding: 28px 22px 40px;
    }

    #hero-layout,
    #workspace-grid,
    .control-split {
        gap: 20px;
        align-items: flex-start;
    }

    .stacked-column,
    .preview-stack {
        gap: 20px;
    }

    .panel-card {
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(246, 250, 255, 0.92));
        border: 1px solid var(--app-border);
        border-radius: var(--app-radius);
        box-shadow: var(--app-shadow-soft);
        box-shadow:
            var(--app-inset-highlight),
            var(--app-shadow-soft);
        padding: 18px !important;
        overflow: visible !important;
        position: relative;
        backdrop-filter: blur(14px);
        transition:
            transform 0.22s ease,
            box-shadow 0.22s ease,
            border-color 0.22s ease;
    }

    .panel-card::before {
        content: "";
        position: absolute;
        inset: 0;
        border-radius: inherit;
        background:
            linear-gradient(135deg, rgba(255, 255, 255, 0.42), transparent 48%);
        pointer-events: none;
    }

    .panel-card:hover {
        transform: translateY(-2px);
        border-color: rgba(18, 99, 255, 0.16);
        box-shadow:
            var(--app-inset-highlight),
            var(--app-shadow-hover);
    }

    .panel-card-primary {
        background: linear-gradient(
            160deg,
            rgba(255, 255, 255, 0.96),
            rgba(241, 247, 255, 0.98)
        );
        border-color: rgba(18, 99, 255, 0.18);
        box-shadow: var(--app-shadow);
    }

    .panel-card-secondary {
        background: linear-gradient(180deg, #ffffff, rgba(248, 251, 255, 0.96));
    }

    .panel-card-quiet {
        background: linear-gradient(180deg, rgba(250, 252, 255, 0.96), rgba(243, 248, 255, 0.94));
        border-color: rgba(18, 99, 255, 0.08);
    }

    .language-panel::after,
    .source-panel::after,
    .setup-panel::after,
    .export-panel::after,
    .advanced-panel::after,
    .status-panel::after {
        content: "";
        position: absolute;
        inset: 0 0 auto;
        height: 4px;
        opacity: 0.92;
        pointer-events: none;
    }

    .language-panel::after {
        background: linear-gradient(90deg, rgba(15, 169, 191, 0.78), rgba(18, 99, 255, 0.42), transparent);
    }

    .source-panel::after {
        background: linear-gradient(90deg, rgba(18, 99, 255, 0.56), rgba(18, 99, 255, 0.18), transparent);
    }

    .setup-panel::after {
        background: linear-gradient(90deg, rgba(18, 99, 255, 0.9), rgba(15, 169, 191, 0.34), transparent);
    }

    .export-panel::after {
        background: linear-gradient(90deg, rgba(18, 99, 255, 0.64), rgba(129, 174, 255, 0.24), transparent);
    }

    .advanced-panel::after {
        background: linear-gradient(90deg, rgba(106, 124, 154, 0.52), rgba(199, 210, 230, 0.18), transparent);
    }

    .status-panel::after {
        background: linear-gradient(90deg, rgba(18, 99, 255, 0.88), rgba(15, 169, 191, 0.42), transparent);
    }

    .panel-card .prose {
        color: var(--app-text);
    }

    .panel-card .prose h2,
    .panel-card .prose h3,
    .panel-card .prose h4 {
        margin-top: 0;
        margin-bottom: 0.35rem;
        color: var(--app-text);
        font-family: "Avenir Next", "Segoe UI Variable Display", "Space Grotesk", "Noto Sans SC", sans-serif;
        letter-spacing: -0.03em;
        line-height: 1.02;
        text-wrap: balance;
    }

    .section-title {
        margin: 0 !important;
        padding: 0 !important;
    }

    .section-title .prose {
        margin: 0 !important;
    }

    .section-title h2,
    .section-title h3 {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 0 !important;
    }

    .section-title h2::before,
    .section-title h3::before {
        content: "";
        width: 11px;
        height: 11px;
        border-radius: 999px;
        background: linear-gradient(135deg, var(--app-blue), var(--app-cyan));
        box-shadow: 0 0 0 5px rgba(18, 99, 255, 0.10);
        flex-shrink: 0;
    }

    .panel-intro {
        margin-top: -2px;
        margin-bottom: 10px;
    }

    .panel-intro p {
        margin: 0;
        color: var(--app-text-muted);
        font-size: 0.95rem;
        line-height: 1.6;
    }

    #app-hero {
        margin: 0;
    }

    .hero-card {
        display: grid;
        gap: 18px;
        background:
            radial-gradient(circle at top right, rgba(15, 169, 191, 0.10), transparent 0 28%),
            linear-gradient(140deg, rgba(255, 255, 255, 0.96), rgba(244, 249, 255, 0.98) 48%, rgba(235, 244, 255, 0.98) 100%);
        border: 1px solid var(--app-border-strong);
        border-radius: 30px;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.9),
            0 28px 70px rgba(18, 99, 255, 0.10);
        padding: 30px 32px;
        overflow: hidden;
        position: relative;
        min-height: 250px;
        animation: workspace-fade-up 0.55s ease both;
    }

    .hero-card::before {
        content: "";
        position: absolute;
        inset: 0;
        background:
            linear-gradient(120deg, rgba(255, 255, 255, 0.34), transparent 42%),
            radial-gradient(circle at 16% 18%, rgba(18, 99, 255, 0.18), transparent 0 28%);
        pointer-events: none;
    }

    .hero-card::after {
        content: "";
        position: absolute;
        inset: auto -72px -102px auto;
        width: 248px;
        height: 248px;
        border-radius: 999px;
        background:
            radial-gradient(circle, rgba(18, 99, 255, 0.16) 0%, rgba(18, 99, 255, 0.04) 46%, transparent 74%);
        pointer-events: none;
        animation: hero-orb-drift 8s ease-in-out infinite;
    }

    .hero-kicker {
        margin: 0;
        color: var(--app-blue);
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        width: fit-content;
        padding: 0.55rem 0.82rem;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid rgba(18, 99, 255, 0.12);
        box-shadow: 0 12px 24px rgba(18, 99, 255, 0.08);
    }

    .hero-title {
        margin: 0;
        color: var(--app-text);
        font-family: "Avenir Next", "Segoe UI Variable Display", "Space Grotesk", "Noto Sans SC", sans-serif;
        font-size: clamp(2.25rem, 4.4vw, 3.35rem);
        line-height: 0.95;
        letter-spacing: -0.065em;
        max-width: 11ch;
        text-wrap: balance;
    }

    .hero-description {
        margin: 2px 0 0;
        max-width: 56ch;
        color: #4f6581;
        font-size: 1.04rem;
        line-height: 1.72;
    }

    .hero-highlights {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 4px;
    }

    .hero-chip {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 40px;
        padding: 0.6rem 0.98rem;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.76);
        border: 1px solid rgba(18, 99, 255, 0.12);
        color: #21466f;
        font-size: 0.88rem;
        font-weight: 650;
        box-shadow: 0 12px 22px rgba(18, 99, 255, 0.08);
        backdrop-filter: blur(10px);
    }

    .hero-caption {
        margin: 0;
        color: #44617f;
        font-size: 0.92rem;
        line-height: 1.62;
        max-width: 58ch;
        padding-top: 16px;
        border-top: 1px solid rgba(18, 99, 255, 0.10);
    }

    .hero-side-card {
        min-height: 100%;
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(246, 250, 255, 0.96));
        box-shadow: 0 18px 34px rgba(15, 23, 42, 0.06);
    }

    .hero-side-card .prose h2 {
        margin-bottom: 0.45rem;
    }

    .hero-side-card .section-title h2 {
        font-size: 1.18rem;
    }

    .hero-side-card .gradio-dropdown,
    .hero-side-card .gradio-textbox,
    .hero-side-card .gradio-radio {
        margin-top: 8px;
    }

    .input-file {
        border: 1.8px dashed rgba(18, 99, 255, 0.28) !important;
        border-radius: 22px !important;
        background: linear-gradient(
            180deg,
            rgba(250, 252, 255, 0.96),
            rgba(239, 245, 255, 0.98)
        ) !important;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.72),
            0 18px 32px rgba(18, 99, 255, 0.06);
        padding: 12px !important;
        transition:
            border-color 0.18s ease,
            box-shadow 0.18s ease,
            transform 0.18s ease,
            background-color 0.18s ease;
    }

    .input-file:hover {
        border-color: var(--app-blue) !important;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.88),
            0 22px 38px rgba(18, 99, 255, 0.11);
        transform: translateY(-2px);
    }

    .input-file:focus-within {
        border-color: rgba(18, 99, 255, 0.54) !important;
        box-shadow:
            0 0 0 4px var(--app-focus-ring),
            inset 0 1px 0 rgba(255, 255, 255, 0.88),
            0 22px 38px rgba(18, 99, 255, 0.12);
        transform: translateY(-1px);
    }

    .info-banner {
        padding: 13px 15px !important;
        border-radius: 18px;
        border: 1px solid rgba(18, 99, 255, 0.16);
        background:
            linear-gradient(135deg, rgba(18, 99, 255, 0.10), rgba(247, 250, 255, 0.98));
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
    }

    .info-banner p {
        margin: 0;
        color: #1f4273;
        font-size: 0.92rem;
    }

    .panel-accordion {
        margin-top: 8px;
        border: 1px solid rgba(18, 99, 255, 0.10);
        border-radius: 20px !important;
        background: rgba(247, 250, 255, 0.96);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
        overflow: visible !important;
    }

    .panel-accordion > * {
        border: none !important;
    }

    .panel-card [data-testid="block-label"] {
        color: #5e728d;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .panel-card input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]),
    .panel-card textarea {
        min-height: 48px;
        border-radius: 16px !important;
        border: 1px solid rgba(24, 48, 84, 0.10) !important;
        background:
            linear-gradient(180deg, rgba(252, 253, 255, 0.98), rgba(243, 248, 255, 0.96)) !important;
        color: var(--app-text) !important;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.84),
            0 10px 22px rgba(18, 99, 255, 0.03);
        transition:
            border-color 0.18s ease,
            box-shadow 0.18s ease,
            background-color 0.18s ease,
            transform 0.18s ease;
    }

    .panel-card textarea {
        min-height: 128px;
    }

    .panel-card input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"])::placeholder,
    .panel-card textarea::placeholder {
        color: #8a9bb1;
    }

    .panel-card input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]):hover,
    .panel-card textarea:hover {
        border-color: rgba(18, 99, 255, 0.22) !important;
        background: #ffffff !important;
    }

    .panel-card input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]):focus,
    .panel-card textarea:focus {
        border-color: rgba(18, 99, 255, 0.40) !important;
        box-shadow:
            0 0 0 4px var(--app-focus-ring),
            0 14px 28px rgba(18, 99, 255, 0.08) !important;
        background: #ffffff !important;
        transform: translateY(-1px);
    }

    .panel-card label:has(input[type="radio"]),
    .panel-card label:has(input[type="checkbox"]) {
        border: 1px solid rgba(24, 48, 84, 0.09);
        border-radius: 16px;
        background: rgba(252, 253, 255, 0.78);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
        transition:
            border-color 0.18s ease,
            box-shadow 0.18s ease,
            background-color 0.18s ease,
            transform 0.18s ease;
    }

    .panel-card label:has(input[type="radio"]):hover,
    .panel-card label:has(input[type="checkbox"]):hover {
        border-color: rgba(18, 99, 255, 0.20);
        background: #ffffff;
        transform: translateY(-1px);
    }

    .panel-card label:has(input[type="radio"]:checked),
    .panel-card label:has(input[type="checkbox"]:checked) {
        border-color: rgba(18, 99, 255, 0.24);
        background: linear-gradient(180deg, rgba(245, 249, 255, 0.98), rgba(237, 245, 255, 0.98));
        box-shadow:
            0 14px 28px rgba(18, 99, 255, 0.08),
            inset 0 1px 0 rgba(255, 255, 255, 0.86);
    }

    .action-zone {
        margin-top: 14px;
        padding: 18px;
        border-top: 1px solid rgba(18, 99, 255, 0.10);
        border-radius: 22px;
        background:
            linear-gradient(145deg, rgba(13, 56, 139, 0.06), rgba(255, 255, 255, 0.84) 48%, rgba(15, 169, 191, 0.05));
        border: 1px solid rgba(18, 99, 255, 0.10);
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.76),
            0 16px 30px rgba(18, 99, 255, 0.07);
    }

    .action-row {
        gap: 12px;
        margin-top: 12px;
        align-items: stretch;
        flex-wrap: wrap;
    }

    .action-row > * {
        flex: 1 1 160px;
        min-width: 0;
    }

    .action-row button {
        width: 100%;
        min-height: 54px;
        border-radius: 18px !important;
        font-weight: 650;
        letter-spacing: -0.01em;
        box-shadow: none !important;
        transition:
            transform 0.2s ease,
            box-shadow 0.2s ease,
            border-color 0.2s ease,
            background-color 0.2s ease,
            color 0.2s ease;
    }

    .action-row button:hover:not(:disabled) {
        transform: translateY(-2px);
    }

    .action-row button:focus-visible {
        box-shadow: 0 0 0 4px var(--app-focus-ring) !important;
    }

    .action-row button.primary {
        background: linear-gradient(135deg, var(--app-blue) 0%, var(--app-blue-deep) 100%) !important;
        border-color: rgba(11, 71, 191, 0.58) !important;
        color: #ffffff !important;
        box-shadow:
            0 18px 34px rgba(18, 99, 255, 0.22),
            inset 0 1px 0 rgba(255, 255, 255, 0.20) !important;
    }

    .action-row button.stop {
        background: linear-gradient(180deg, #f36f6f, #d14343) !important;
        border-color: rgba(209, 67, 67, 0.66) !important;
        color: #ffffff !important;
    }

    .action-row button.stop:hover:not(:disabled) {
        box-shadow: 0 16px 28px rgba(209, 67, 67, 0.22) !important;
    }

    .save-action button {
        background: rgba(255, 255, 255, 0.72) !important;
        border-color: rgba(24, 48, 84, 0.12) !important;
        color: var(--app-text) !important;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.84),
            0 14px 26px rgba(16, 28, 48, 0.07) !important;
    }

    .action-row button:disabled,
    .action-row button[aria-disabled="true"] {
        opacity: 0.6;
        transform: none !important;
        box-shadow: none !important;
    }

    .sub-accordion {
        margin-top: 10px;
    }

    .progress-bar-wrap,
    .progress-bar {
        border-radius: 999px !important;
    }

    #preview-column {
        align-self: flex-start;
        min-width: 0;
    }

    .live-status-shell {
        background: linear-gradient(
            180deg,
            rgba(255, 255, 255, 0.98),
            rgba(241, 247, 255, 0.96)
        );
        position: sticky;
        top: 20px;
        z-index: 2;
        overflow: hidden !important;
    }

    .live-status-shell::after {
        content: "";
        position: absolute;
        inset: 0 auto auto 0;
        width: 100%;
        height: 4px;
        background: linear-gradient(90deg, var(--app-blue), var(--app-cyan));
        opacity: 0.94;
    }

    .live-status-wrap {
        margin-top: 6px;
    }

    .live-status-card {
        display: grid;
        gap: 16px;
        padding: 8px 4px 4px;
    }

    .live-status-head {
        display: flex;
        justify-content: space-between;
        gap: 14px;
        align-items: flex-start;
    }

    .live-status-kicker {
        margin: 0 0 8px;
        color: #567291;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
    }

    .live-status-title {
        margin: 0;
        color: var(--app-text);
        font-size: 1.26rem;
        line-height: 1.1;
        letter-spacing: -0.04em;
        text-wrap: balance;
    }

    .live-status-percent {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 84px;
        min-height: 48px;
        padding: 0.55rem 0.9rem;
        border-radius: 999px;
        background: rgba(18, 99, 255, 0.10);
        color: var(--app-blue);
        font-size: 1.02rem;
        font-weight: 700;
        border: 1px solid rgba(18, 99, 255, 0.12);
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.84),
            0 14px 28px rgba(18, 99, 255, 0.08);
    }

    .live-status-message,
    .live-status-detail {
        margin: 0;
        color: var(--app-text-muted);
        line-height: 1.55;
    }

    .live-status-detail {
        color: #40506b;
        font-size: 0.93rem;
    }

    .live-status-meter {
        height: 14px;
        border-radius: 999px;
        overflow: hidden;
        background:
            linear-gradient(180deg, rgba(18, 99, 255, 0.06), rgba(18, 99, 255, 0.12));
        box-shadow: inset 0 1px 4px rgba(16, 28, 48, 0.08);
    }

    .live-status-meter span {
        display: block;
        height: 100%;
        border-radius: inherit;
        background: linear-gradient(90deg, #1263ff 0%, #2f78ff 44%, #0fa9bf 100%);
        background-size: 180% 100%;
        transition: width 0.22s ease;
        animation: meter-flow 3.4s linear infinite;
    }

    .live-status-meta {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
    }

    .live-status-meta-item {
        min-width: 0;
        padding: 12px 13px;
        border-radius: 18px;
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.84), rgba(245, 249, 255, 0.84));
        border: 1px solid rgba(18, 99, 255, 0.10);
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.84),
            0 12px 24px rgba(18, 99, 255, 0.05);
    }

    .live-status-meta-label {
        display: block;
        margin-bottom: 5px;
        color: #5f7390;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }

    .live-status-meta-value {
        display: block;
        color: var(--app-text);
        font-size: 0.96rem;
        font-weight: 600;
        line-height: 1.35;
        word-break: break-word;
    }

    .live-status-idle,
    .live-status-running {
        padding: 10px 10px 8px;
        border-radius: 22px;
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.74), rgba(239, 246, 255, 0.72));
        border: 1px solid rgba(18, 99, 255, 0.10);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
    }

    .live-status-success,
    .live-status-warning,
    .live-status-danger {
        padding: 10px 10px 8px;
        border-radius: 22px;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
    }

    .live-status-success {
        background:
            linear-gradient(180deg, rgba(244, 255, 250, 0.88), rgba(234, 248, 241, 0.78));
        border: 1px solid rgba(15, 159, 110, 0.16);
    }

    .live-status-warning {
        background:
            linear-gradient(180deg, rgba(255, 251, 245, 0.90), rgba(252, 242, 229, 0.80));
        border: 1px solid rgba(217, 134, 27, 0.16);
    }

    .live-status-danger {
        background:
            linear-gradient(180deg, rgba(255, 247, 247, 0.92), rgba(252, 239, 239, 0.80));
        border: 1px solid rgba(209, 67, 67, 0.16);
    }

    .live-status-success .live-status-percent {
        background: rgba(15, 159, 110, 0.12);
        color: var(--app-green);
    }

    .live-status-success .live-status-meter span {
        background: linear-gradient(90deg, #0f9f6e 0%, #38b985 100%);
    }

    .live-status-warning .live-status-percent {
        background: rgba(217, 134, 27, 0.14);
        color: var(--app-amber);
    }

    .live-status-warning .live-status-meter span {
        background: linear-gradient(90deg, #d9861b 0%, #f0a63c 100%);
    }

    .live-status-danger .live-status-percent {
        background: rgba(209, 67, 67, 0.12);
        color: var(--app-red);
    }

    .live-status-danger .live-status-meter span {
        background: linear-gradient(90deg, #d14343 0%, #eb6a6a 100%);
    }

    .preview-card {
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 250, 255, 0.96));
        overflow: hidden !important;
    }

    .preview-card::after {
        content: "";
        position: absolute;
        inset: 0 0 auto;
        height: 4px;
        background: linear-gradient(90deg, rgba(18, 99, 255, 0.72), rgba(15, 169, 191, 0.68));
    }

    .pdf-preview {
        height: min(980px, 74vh) !important;
        border-radius: 24px !important;
        overflow: hidden !important;
        border: 1px solid rgba(91, 105, 133, 0.14);
        background: linear-gradient(180deg, #f7f9fc, #eef3f9) !important;
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.78),
            0 24px 46px rgba(16, 28, 48, 0.08);
    }

    .preview-summary-panel {
        padding: 14px;
        border-radius: 20px;
        border: 1px solid rgba(18, 99, 255, 0.10);
        background:
            linear-gradient(180deg, rgba(248, 251, 255, 0.96), rgba(241, 247, 255, 0.84));
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.82),
            0 18px 30px rgba(18, 99, 255, 0.05);
    }

    .summary-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 12px;
    }

    .summary-pill {
        display: grid;
        gap: 6px;
        flex: 1 1 210px;
        min-width: 0;
        padding: 13px 15px;
        border-radius: 18px;
        background:
            linear-gradient(180deg, rgba(248, 251, 255, 0.98), rgba(239, 245, 255, 0.98));
        border: 1px solid rgba(18, 99, 255, 0.10);
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.82),
            0 14px 24px rgba(18, 99, 255, 0.06);
    }

    .summary-pill-source {
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(239, 247, 255, 0.92));
    }

    .summary-pill-route {
        background:
            linear-gradient(180deg, rgba(242, 248, 255, 0.98), rgba(233, 242, 255, 0.90));
    }

    .summary-pill-output {
        background:
            linear-gradient(180deg, rgba(250, 252, 255, 0.98), rgba(237, 244, 252, 0.88));
    }

    .summary-pill-label {
        color: #60708f;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }

    .summary-pill-value {
        color: var(--app-text);
        font-size: 0.95rem;
        font-weight: 600;
        min-width: 0;
        word-break: break-word;
    }

    .panel-card input[role="listbox"] {
        cursor: pointer;
        width: 100%;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        padding-right: 2.4rem !important;
    }

    .panel-card input[role="listbox"] + .icon-wrap,
    .panel-card input[role="listbox"] + .icon-wrap * {
        pointer-events: none !important;
    }

    .panel-card .wrap:has(input[role="listbox"]),
    .panel-card .wrap-inner:has(input[role="listbox"]),
    .panel-card .secondary-wrap:has(input[role="listbox"]) {
        min-width: 0 !important;
        overflow: visible !important;
    }

    .panel-card .secondary-wrap:has(> input[role="listbox"]) {
        min-height: 48px;
        border-radius: 16px;
        background:
            linear-gradient(180deg, rgba(252, 253, 255, 0.98), rgba(243, 248, 255, 0.96));
        border: 1px solid rgba(24, 48, 84, 0.10);
        box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.84),
            0 10px 22px rgba(18, 99, 255, 0.03);
        transition:
            border-color 0.18s ease,
            box-shadow 0.18s ease,
            background-color 0.18s ease,
            transform 0.18s ease;
    }

    .panel-card .secondary-wrap:has(> input[role="listbox"]):hover {
        border-color: rgba(18, 99, 255, 0.24);
        background: #ffffff;
    }

    .panel-card .secondary-wrap:has(> input[role="listbox"]):focus-within {
        border-color: rgba(18, 99, 255, 0.40);
        box-shadow: 0 0 0 4px var(--app-focus-ring);
        background: #fff;
        transform: translateY(-1px);
    }

    .panel-card ul[role="listbox"] {
        z-index: 2147483647 !important;
        border: 1px solid rgba(18, 99, 255, 0.12);
        border-radius: 16px;
        box-shadow: 0 22px 40px rgba(15, 23, 42, 0.16);
        background: rgba(255, 255, 255, 0.98);
        overflow-y: auto !important;
    }

    .panel-card [data-testid="dropdown-option"]:hover {
        background: rgba(18, 99, 255, 0.08) !important;
    }

    .panel-card [data-testid="dropdown-option"] {
        padding-top: 10px !important;
        padding-bottom: 10px !important;
    }

    .language-route-row {
        gap: 12px;
        flex-wrap: wrap;
    }

    .language-route-field {
        flex: 1 1 220px;
        min-width: 220px;
    }

    .preview-summary-wrap {
        margin-bottom: 10px;
    }

    .result-zone {
        margin-top: 16px;
        padding-top: 16px;
        border-top: 1px solid rgba(18, 99, 255, 0.10);
    }

    .download-zone {
        padding: 16px !important;
        border-radius: 20px;
        background:
            linear-gradient(180deg, rgba(248, 251, 255, 0.90), rgba(240, 246, 255, 0.82));
        border: 1px solid rgba(18, 99, 255, 0.10);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
    }

    .result-zone .gradio-file {
        margin-top: 10px;
    }

    .pdf-canvas canvas {
        width: 100%;
    }

    @keyframes workspace-fade-up {
        from {
            opacity: 0;
            transform: translateY(10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    @keyframes hero-orb-drift {
        0%,
        100% {
            transform: translate3d(0, 0, 0) scale(1);
        }
        50% {
            transform: translate3d(-8px, -12px, 0) scale(1.04);
        }
    }

    @keyframes meter-flow {
        from {
            background-position: 0% 50%;
        }
        to {
            background-position: 180% 50%;
        }
    }

    @media (max-width: 1240px) {
        .control-split {
            flex-direction: column;
        }

        .live-status-shell {
            position: static;
        }

        .pdf-preview {
            height: min(860px, 68vh) !important;
        }

        .summary-pill {
            flex-basis: calc(50% - 6px);
        }
    }

    @media (max-width: 960px) {
        #app-shell {
            padding: 20px 15px 30px;
        }

        .live-status-meta {
            grid-template-columns: 1fr;
        }

        .panel-card:hover {
            transform: none;
        }

        .pdf-preview {
            height: min(760px, 62vh) !important;
        }
    }

    @media (max-width: 840px) {
        #app-shell {
            padding: 16px 12px 24px;
        }

        .hero-card {
            padding: 24px 20px;
            border-radius: 24px;
        }

        .hero-title {
            font-size: 2.25rem;
        }

        .panel-card {
            border-radius: 20px;
            padding: 14px !important;
        }

        .action-zone {
            padding: 16px;
        }

        .action-row {
            flex-direction: column;
        }

        .summary-pills {
            gap: 8px;
        }

        .summary-pill {
            flex-basis: 100%;
        }

        .live-status-head {
            flex-direction: column;
            align-items: flex-start;
        }
    }

    @media (max-width: 640px) {
        .hero-kicker,
        .hero-chip,
        .live-status-percent {
            width: 100%;
            justify-content: center;
        }

        .hero-highlights {
            flex-direction: column;
        }

        .pdf-preview {
            height: min(640px, 55vh) !important;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .hero-card,
        .panel-card,
        .live-status-meter span {
            animation: none !important;
            transition: none !important;
        }
    }
    """

# Build paths to resources
current_dir = Path(__file__).parent
assets_dir = current_dir / "assets"
logo_path = assets_dir / "powered_by_siliconflow_light.png"
translation_file_path = current_dir / "gui_translation.yaml"
config_fake_pdf_path = DEFAULT_CONFIG_DIR / "config.fake.pdf"

if not config_fake_pdf_path.exists():
    with config_fake_pdf_path.open("w") as f:
        f.write("This is a fake PDF file for configuration saving.")
        f.flush()
update_current_languages(settings.gui_settings.ui_lang)
# The following code creates the GUI
with gr.Blocks(
    title="PDFMathTranslate - PDF Translation with preserved formats",
    theme=gr.themes.Default(
        primary_hue=custom_blue,
        spacing_size="md",
        radius_size="lg",
        font=("Noto Sans SC", "Noto Sans", "Helvetica Neue", "sans-serif"),
        font_mono=("IBM Plex Mono", "ui-monospace", "Consolas", "monospace"),
    ),
    css=custom_css,
) as demo:
    lang_selector = gr.Dropdown(
        choices=LANGUAGES,
        label=_("UI Language"),
        value=settings.gui_settings.ui_lang,
        render=False,
    )
    with Translate(get_translation_dic(translation_file_path), lang_selector):

        def format_output_mode(no_mono_value: bool, no_dual_value: bool) -> str:
            if no_mono_value and no_dual_value:
                return _("Disabled")
            if no_mono_value:
                return _("Dual only")
            if no_dual_value:
                return _("Mono only")
            return _("Mono + Dual")

        def summarize_source(
            file_type_value: str, file_path: str | None, link_value: str | None
        ) -> str:
            if file_type_value == "Link":
                if not link_value:
                    return "-"
                parsed = urlparse(link_value)
                return parsed.netloc or link_value
            if not file_path:
                return "-"
            return Path(file_path).name

        def build_workspace_summary(
            file_type_value: str,
            file_path: str | None,
            link_value: str | None,
            service_name: str,
            lang_from_name: str,
            lang_to_name: str,
            no_mono_value: bool,
            no_dual_value: bool,
            page_range_value: str,
            page_input_value: str | None,
            watermark_mode_value: str,
        ) -> str:
            def format_pages_value() -> str:
                if page_range_value == "First":
                    return _("First page")
                if page_range_value == "First 5 pages":
                    return _("First 5 pages")
                if page_range_value == "Range":
                    if page_input_value:
                        return _("Range: {pages}").format(pages=page_input_value)
                    return _("Custom range")
                return _("All pages")

            source_value = summarize_source(file_type_value, file_path, link_value)
            source_display = (
                source_value if source_value != "-" else _("No source selected")
            )
            pages_value = format_pages_value()
            summary_items = [
                ("source", _("Source"), source_display),
                ("route", _("Route"), _build_route_text(lang_from_name, lang_to_name)),
                ("engine", _("Engine"), service_name),
                ("pages", _("Pages"), pages_value),
                ("output", _("Output"), format_output_mode(no_mono_value, no_dual_value)),
            ]
            if watermark_mode_value == "No Watermark":
                summary_items.append(("watermark", _("Watermark"), _("Off")))
            pill_html = "".join(
                f"""
                <div class="summary-pill summary-pill-{key}">
                    <span class="summary-pill-label">{html.escape(str(label))}</span>
                    <span class="summary-pill-value">{html.escape(str(value))}</span>
                </div>
                """
                for key, label, value in summary_items
            )
            return f"""
            <div class="preview-summary-panel">
                <div class="summary-pills">{pill_html}</div>
            </div>
            """

        def get_selected_service_from_settings(current_settings) -> str:
            for metadata in TRANSLATION_ENGINE_METADATA:
                if getattr(current_settings, metadata.cli_flag_name, False):
                    return metadata.translate_engine_type
            return available_services[0]

        def build_workspace_summary_from_settings(current_settings) -> str:
            selected_service = get_selected_service_from_settings(current_settings)
            loaded_lang_from = rev_lang_map.get(
                current_settings.translation.lang_in, "English"
            )
            loaded_lang_to = next(
                (
                    display_name
                    for display_name, lang_code in lang_map.items()
                    if lang_code == current_settings.translation.lang_out
                ),
                "Simplified Chinese",
            )
            pages_setting = current_settings.pdf.pages
            page_range_value = "All" if pages_setting in (None, "") else "Range"
            page_input_value = "" if pages_setting in (None, "") else str(pages_setting)
            watermark_value = (
                "Watermarked"
                if current_settings.pdf.watermark_output_mode == "watermarked"
                else "No Watermark"
            )
            return build_workspace_summary(
                "File",
                None,
                None,
                selected_service,
                loaded_lang_from,
                loaded_lang_to,
                current_settings.pdf.no_mono,
                current_settings.pdf.no_dual,
                page_range_value,
                page_input_value,
                watermark_value,
            )

        hero_html = build_hero_html()

        translation_engine_arg_inputs = []
        require_llm_translator_inputs = []
        service_detail_groups = []
        service_detail_group_index_map = {}
        term_service_detail_groups = []
        term_service_detail_group_index_map = {}
        LLM_support_index_map.clear()
        initial_service = get_selected_service_from_settings(settings)
        initial_llm_support = TRANSLATION_ENGINE_METADATA_MAP[
            initial_service
        ].support_llm
        initial_workspace_summary = build_workspace_summary_from_settings(settings)
        initial_live_status_html = build_live_status_html(
            _("Ready to translate"),
            _(
                "Upload a PDF and start the job. Progress and downloads will stay visible here."
            ),
            progress_value=0.0,
            detail=_(
                "Use the left side to set the source, language route, and export mode."
            ),
            tone="idle",
            meta_items=_build_service_route_meta_items(
                initial_service,
                default_lang_from,
                default_lang_to,
            ),
        )

        with gr.Column(elem_id="app-shell"):
            with gr.Row(elem_id="hero-layout", equal_height=False):
                with gr.Column(scale=8, min_width=420):
                    hero_panel = gr.HTML(hero_html, elem_id="app-hero")
                with gr.Column(scale=4, min_width=300):
                    with gr.Group(
                        elem_classes=[
                            "panel-card",
                            "panel-card-secondary",
                            "hero-side-card",
                            "language-panel",
                        ]
                    ):
                        ui_language_title = gr.Markdown(
                            f"## {_('UI Language')}",
                            elem_classes=["section-title"],
                        )
                        ui_language_intro = gr.Markdown(
                            _(
                                "Switch the interface language without leaving the workspace."
                            ),
                            elem_classes=["panel-intro"],
                        )
                        lang_selector.render()

            with gr.Row(elem_id="workspace-grid", equal_height=False):
                with gr.Column(scale=6, min_width=480, elem_classes=["stacked-column"]):
                    with gr.Group(
                        elem_classes=[
                            "panel-card",
                            "panel-card-secondary",
                            "source-panel",
                            "workspace-source",
                        ]
                    ):
                        source_title = gr.Markdown(
                            f"## {_('Source & Pages')}",
                            elem_classes=["section-title"],
                        )
                        source_intro = gr.Markdown(
                            _(
                                "Choose the PDF source and limit the page scope if you only need a subset."
                            ),
                            elem_classes=["panel-intro"],
                        )
                        file_type = gr.Radio(
                            choices=[(_("File"), "File"), (_("Link"), "Link")],
                            label=_("Type"),
                            value="File",
                        )
                        file_input = gr.File(
                            label=_("File"),
                            file_count="single",
                            file_types=[".pdf", ".PDF"],
                            type="filepath",
                            elem_classes=["input-file"],
                        )
                        link_input = gr.Textbox(
                            label=_("Link"),
                            visible=False,
                            interactive=True,
                        )
                        page_range = gr.Radio(
                            choices=get_page_choices(),
                            label=_("Pages"),
                            value="All",
                        )
                        page_input = gr.Textbox(
                            label=_("Page range (e.g., 1,3,5-10,-5)"),
                            visible=False,
                            interactive=True,
                            placeholder=_("e.g., 1,3,5-10"),
                        )
                        page_range_feedback = gr.Markdown(
                            value=_build_page_range_feedback(
                                "Range" if settings.pdf.pages else "All",
                                settings.pdf.pages,
                            )["value"],
                            visible=bool(settings.pdf.pages),
                            elem_classes=["panel-intro"],
                        )
                        only_include_translated_page = gr.Checkbox(
                            label=_("Only include translated pages in the output PDF."),
                            info=_("Effective only when a page range is specified."),
                            value=settings.pdf.only_include_translated_page,
                            visible=bool(settings.pdf.pages),
                            interactive=True,
                        )

                    with gr.Row(elem_classes=["control-split"], equal_height=False):
                        with gr.Column(
                            scale=8,
                            min_width=360,
                            elem_classes=["stacked-column"],
                        ):
                            with gr.Group(
                                elem_classes=[
                                    "panel-card",
                                    "panel-card-primary",
                                    "setup-panel",
                                    "workspace-setup",
                                ]
                            ):
                                setup_title = gr.Markdown(
                                    f"## {_('Translation Setup')}",
                                    elem_classes=["section-title"],
                                )
                                setup_intro = gr.Markdown(
                                    _(
                                        "Set the language route, translation engine, and runtime controls in one place."
                                    ),
                                    elem_classes=["panel-intro"],
                                )
                                with gr.Row(
                                    elem_classes=["language-route-row"],
                                    equal_height=False,
                                ):
                                    with gr.Column(
                                        min_width=220,
                                        elem_classes=["language-route-field"],
                                    ):
                                        lang_from = gr.Dropdown(
                                            label=_("Translate from"),
                                            choices=list(lang_map.keys()),
                                            value=default_lang_from,
                                        )
                                    with gr.Column(
                                        min_width=220,
                                        elem_classes=["language-route-field"],
                                    ):
                                        lang_to = gr.Dropdown(
                                            label=_("Translate to"),
                                            choices=list(lang_map.keys()),
                                            value=default_lang_to,
                                        )

                                with gr.Group(
                                    elem_classes=["settings-stack"]
                                ) as translation_engine_settings:
                                    service = gr.Dropdown(
                                        label=_("Service"),
                                        choices=available_services,
                                        value=initial_service,
                                    )

                                    siliconflow_free_acknowledgement = gr.Markdown(
                                        _(
                                            "Free translation service provided by [SiliconFlow](https://siliconflow.cn)"
                                        ),
                                        visible=initial_service == "SiliconFlowFree",
                                        elem_classes=["info-banner"],
                                    )

                                    __gui_service_arg_names = []
                                    for service_name in available_services:
                                        metadata = TRANSLATION_ENGINE_METADATA_MAP[
                                            service_name
                                        ]
                                        LLM_support_index_map[
                                            metadata.translate_engine_type
                                        ] = metadata.support_llm
                                        if not metadata.cli_detail_field_name:
                                            continue
                                        detail_settings = getattr(
                                            settings, metadata.cli_detail_field_name
                                        )
                                        visible = (
                                            service.value
                                            == metadata.translate_engine_type
                                        )

                                        with gr.Group(
                                            visible=visible,
                                            elem_classes=["service-detail-group"],
                                        ) as service_detail:
                                            service_detail_group_index_map[
                                                metadata.translate_engine_type
                                            ] = len(service_detail_groups)
                                            service_detail_groups.append(service_detail)
                                            for (
                                                field_name,
                                                field,
                                            ) in metadata.setting_model_type.model_fields.items():
                                                if disable_gui_sensitive_input:
                                                    if (
                                                        field_name
                                                        in GUI_SENSITIVE_FIELDS
                                                    ):
                                                        continue
                                                    if (
                                                        field_name
                                                        in GUI_PASSWORD_FIELDS
                                                    ):
                                                        continue
                                                if field.default_factory:
                                                    continue

                                                if (
                                                    field_name
                                                    == "translate_engine_type"
                                                ):
                                                    continue
                                                if field_name == "support_llm":
                                                    continue
                                                type_hint = field.annotation
                                                original_type = typing.get_origin(
                                                    type_hint
                                                )
                                                type_args = typing.get_args(type_hint)
                                                value = getattr(
                                                    detail_settings, field_name
                                                )
                                                if (
                                                    type_hint is str
                                                    or str in type_args
                                                    or type_hint is int
                                                    or int in type_args
                                                ):
                                                    if (
                                                        field_name
                                                        in GUI_PASSWORD_FIELDS
                                                    ):
                                                        field_input = gr.Textbox(
                                                            label=field.description,
                                                            value=value,
                                                            interactive=True,
                                                            type="password",
                                                            visible=True,
                                                        )
                                                    else:
                                                        field_input = gr.Textbox(
                                                            label=field.description,
                                                            value=value,
                                                            interactive=True,
                                                            visible=True,
                                                        )
                                                elif (
                                                    type_hint is bool
                                                    or bool in type_args
                                                ):
                                                    field_input = gr.Checkbox(
                                                        label=field.description,
                                                        value=value,
                                                        interactive=True,
                                                        visible=True,
                                                    )
                                                else:
                                                    raise Exception(
                                                        f"Unsupported type {type_hint} for field {field_name} in gui translation engine settings"
                                                    )
                                                __gui_service_arg_names.append(
                                                    field_name
                                                )
                                                translation_engine_arg_inputs.append(
                                                    field_input
                                                )

                                with gr.Group(
                                    elem_classes=["settings-stack"]
                                ) as rate_limit_settings:
                                    rate_limit_mode = gr.Radio(
                                        choices=[
                                            (
                                                _("RPM (Requests Per Minute)"),
                                                "RPM",
                                            ),
                                            (
                                                _("Concurrent Requests"),
                                                "Concurrent Threads",
                                            ),
                                            (_("Custom"), "Custom"),
                                        ],
                                        label=_("Rate Limit Mode"),
                                        value="Custom",
                                        interactive=True,
                                        visible=False,
                                        info=_(
                                            "Select the rate limit mode that best suits your API provider. The system converts RPM or concurrent requests into QPS and pool workers when you start translation."
                                        ),
                                    )

                                    rpm_input = gr.Number(
                                        label=_("RPM (Requests Per Minute)"),
                                        value=240,
                                        precision=0,
                                        minimum=1,
                                        maximum=60000,
                                        interactive=True,
                                        visible=False,
                                        info=_(
                                            "Most API providers provide this parameter, such as OpenAI GPT-4: 500 RPM"
                                        ),
                                    )

                                    concurrent_threads_input = gr.Number(
                                        label=_("Concurrent Threads"),
                                        value=20,
                                        precision=0,
                                        minimum=1,
                                        maximum=1000,
                                        interactive=True,
                                        visible=False,
                                        info=_(
                                            "Maximum number of requests processed simultaneously"
                                        ),
                                    )

                                    custom_qps_input = gr.Number(
                                        label=_("QPS (Queries Per Second)"),
                                        value=settings.translation.qps or 4,
                                        precision=0,
                                        minimum=1,
                                        maximum=1000,
                                        interactive=True,
                                        visible=False,
                                        info=_("Number of requests sent per second"),
                                    )

                                    custom_pool_max_workers_input = gr.Number(
                                        label=_("Pool Max Workers"),
                                        value=settings.translation.pool_max_workers,
                                        precision=0,
                                        minimum=0,
                                        maximum=1000,
                                        interactive=True,
                                        visible=False,
                                        info=_(
                                            "If not set or set to 0, QPS will be used as the number of workers"
                                        ),
                                    )

                                with gr.Group(elem_classes=["action-zone"]):
                                    run_translation_title = gr.Markdown(
                                        f"### {_('Run Translation')}",
                                        elem_classes=["section-title"],
                                    )
                                    run_translation_intro = gr.Markdown(
                                        _(
                                            "Start the job here. Live progress and finished downloads stay pinned on the right."
                                        ),
                                        elem_classes=["panel-intro"],
                                    )
                                    with gr.Row(elem_classes=["action-row"]):
                                        translate_btn = gr.Button(
                                            _("Translate"),
                                            variant="primary",
                                            elem_classes=["translate-action"],
                                        )
                                        cancel_btn = gr.Button(
                                            _("Cancel"),
                                            variant="stop",
                                            interactive=False,
                                            elem_classes=["cancel-action"],
                                        )
                                        save_btn = gr.Button(
                                            _("Save Settings"),
                                            variant="secondary",
                                            elem_classes=["save-action"],
                                        )

                        with gr.Column(
                            scale=5,
                            min_width=300,
                            elem_classes=["stacked-column"],
                        ):
                            with gr.Group(
                                elem_classes=[
                                    "panel-card",
                                    "panel-card-secondary",
                                    "export-panel",
                                    "workspace-export",
                                ]
                            ):
                                export_title = gr.Markdown(
                                    f"## {_('Export Options')}",
                                    elem_classes=["section-title"],
                                )
                                export_intro = gr.Markdown(
                                    _(
                                        "Choose which output variants are generated after translation."
                                    ),
                                    elem_classes=["panel-intro"],
                                )
                                no_mono = gr.Checkbox(
                                    label=_("Disable monolingual output"),
                                    value=settings.pdf.no_mono,
                                    interactive=True,
                                )
                                no_dual = gr.Checkbox(
                                    label=_("Disable bilingual output"),
                                    value=settings.pdf.no_dual,
                                    interactive=True,
                                )
                                dual_translate_first = gr.Checkbox(
                                    label=_("Put translated pages first in dual mode"),
                                    value=settings.pdf.dual_translate_first,
                                    interactive=True,
                                )
                                use_alternating_pages_dual = gr.Checkbox(
                                    label=_("Use alternating pages for dual PDF"),
                                    value=settings.pdf.use_alternating_pages_dual,
                                    interactive=True,
                                )
                                watermark_output_mode = gr.Radio(
                                    choices=[
                                        (_("Watermarked"), "Watermarked"),
                                        (_("No Watermark"), "No Watermark"),
                                    ],
                                    label=_("Watermark mode"),
                                    value="Watermarked"
                                    if settings.pdf.watermark_output_mode
                                    == "watermarked"
                                    else "No Watermark",
                                )

                            with gr.Group(
                                elem_classes=[
                                    "panel-card",
                                    "panel-card-quiet",
                                    "advanced-panel",
                                    "workspace-advanced",
                                ]
                            ):
                                advanced_title = gr.Markdown(
                                    f"## {_('Advanced Settings')}",
                                    elem_classes=["section-title"],
                                )
                                advanced_intro = gr.Markdown(
                                    _(
                                        "Keep this collapsed unless you need glossary extraction, OCR workarounds, or BabelDOC tuning."
                                    ),
                                    elem_classes=["panel-intro"],
                                )

                                with gr.Accordion(
                                    _("Auto Term Extraction"),
                                    open=False,
                                    elem_classes=["panel-accordion"],
                                ):
                                    enable_auto_term_extraction = gr.Checkbox(
                                        label=_("Enable auto term extraction"),
                                        value=not settings.translation.no_auto_extract_glossary,
                                        interactive=True,
                                    )

                                    term_disabled_info = gr.Markdown(
                                        _(
                                            "Auto term extraction is disabled. Term extraction settings below will not take effect until it is enabled."
                                        ),
                                        visible=settings.translation.no_auto_extract_glossary,
                                        elem_classes=["info-banner"],
                                    )

                                    with gr.Group(
                                        visible=not settings.translation.no_auto_extract_glossary
                                    ) as term_settings_group:
                                        term_service = gr.Dropdown(
                                            label=_("Term extraction engine"),
                                            choices=[
                                                (
                                                    _("Follow main translation engine"),
                                                    "Follow main translation engine",
                                                )
                                            ]
                                            + [
                                                metadata.translate_engine_type
                                                for metadata in TERM_EXTRACTION_ENGINE_METADATA
                                            ],
                                            value="Follow main translation engine",
                                        )

                                        __gui_term_service_arg_names = []
                                        for (
                                            term_metadata
                                        ) in TERM_EXTRACTION_ENGINE_METADATA:
                                            if not term_metadata.cli_detail_field_name:
                                                continue
                                            term_detail_field_name = f"term_{term_metadata.cli_detail_field_name}"
                                            term_detail_settings = getattr(
                                                settings, term_detail_field_name
                                            )

                                            term_visible = (
                                                term_service.value
                                                == term_metadata.translate_engine_type
                                            )
                                            with gr.Group(
                                                visible=term_visible,
                                                elem_classes=[
                                                    "term-service-detail-group"
                                                ],
                                            ) as term_service_detail:
                                                term_service_detail_group_index_map[
                                                    term_metadata.translate_engine_type
                                                ] = len(term_service_detail_groups)
                                                term_service_detail_groups.append(
                                                    term_service_detail
                                                )
                                                for (
                                                    field_name,
                                                    field,
                                                ) in term_metadata.term_setting_model_type.model_fields.items():
                                                    if field_name in (
                                                        "translate_engine_type",
                                                        "support_llm",
                                                    ):
                                                        continue
                                                    if field.default_factory:
                                                        continue

                                                    base_field_name = field_name
                                                    if base_field_name.startswith(
                                                        "term_"
                                                    ):
                                                        base_name = base_field_name[
                                                            len("term_") :
                                                        ]
                                                    else:
                                                        base_name = base_field_name

                                                    if disable_gui_sensitive_input:
                                                        if (
                                                            base_name
                                                            in GUI_SENSITIVE_FIELDS
                                                        ):
                                                            continue
                                                        if (
                                                            base_name
                                                            in GUI_PASSWORD_FIELDS
                                                        ):
                                                            continue

                                                    type_hint = field.annotation
                                                    original_type = typing.get_origin(
                                                        type_hint
                                                    )
                                                    type_args = typing.get_args(
                                                        type_hint
                                                    )
                                                    value = getattr(
                                                        term_detail_settings,
                                                        field_name,
                                                    )

                                                    if (
                                                        type_hint is str
                                                        or str in type_args
                                                        or type_hint is int
                                                        or int in type_args
                                                    ):
                                                        if (
                                                            base_name
                                                            in GUI_PASSWORD_FIELDS
                                                        ):
                                                            field_input = gr.Textbox(
                                                                label=field.description,
                                                                value=value,
                                                                interactive=True,
                                                                type="password",
                                                                visible=True,
                                                            )
                                                        else:
                                                            field_input = gr.Textbox(
                                                                label=field.description,
                                                                value=value,
                                                                interactive=True,
                                                                visible=True,
                                                            )
                                                    elif (
                                                        type_hint is bool
                                                        or bool in type_args
                                                    ):
                                                        field_input = gr.Checkbox(
                                                            label=field.description,
                                                            value=value,
                                                            interactive=True,
                                                            visible=True,
                                                        )
                                                    else:
                                                        raise Exception(
                                                            f"Unsupported type {type_hint} for field {field_name} in gui term extraction engine settings"
                                                        )
                                                    __gui_term_service_arg_names.append(
                                                        field_name
                                                    )
                                                    translation_engine_arg_inputs.append(
                                                        field_input
                                                    )

                                        term_rate_limit_mode = gr.Radio(
                                            choices=[
                                                (
                                                    _("RPM (Requests Per Minute)"),
                                                    "RPM",
                                                ),
                                                (
                                                    _("Concurrent Requests"),
                                                    "Concurrent Threads",
                                                ),
                                                (_("Custom"), "Custom"),
                                            ],
                                            label=_("Term rate limit mode"),
                                            value="Custom",
                                            interactive=True,
                                        )

                                        term_rpm_input = gr.Number(
                                            label=_("Term RPM (Requests Per Minute)"),
                                            value=240,
                                            precision=0,
                                            minimum=1,
                                            maximum=60000,
                                            interactive=True,
                                            visible=False,
                                        )

                                        term_concurrent_threads_input = gr.Number(
                                            label=_("Term concurrent threads"),
                                            value=20,
                                            precision=0,
                                            minimum=1,
                                            maximum=1000,
                                            interactive=True,
                                            visible=False,
                                        )

                                        term_custom_qps_input = gr.Number(
                                            label=_("Term QPS (Queries Per Second)"),
                                            value=(
                                                settings.translation.term_qps
                                                or settings.translation.qps
                                                or 4
                                            ),
                                            precision=0,
                                            minimum=1,
                                            maximum=1000,
                                            interactive=True,
                                            visible=True,
                                        )

                                        term_custom_pool_max_workers_input = gr.Number(
                                            label=_("Term pool max workers"),
                                            value=settings.translation.term_pool_max_workers,
                                            precision=0,
                                            minimum=0,
                                            maximum=1000,
                                            interactive=True,
                                            visible=True,
                                        )

                                with gr.Accordion(
                                    _("Translation Controls"),
                                    open=False,
                                    elem_classes=[
                                        "panel-accordion",
                                        "sub-accordion",
                                    ],
                                ):
                                    prompt = gr.Textbox(
                                        label=_("Custom prompt for translation"),
                                        value="",
                                        visible=False,
                                        interactive=True,
                                        placeholder=_(
                                            "Custom prompt for the translator"
                                        ),
                                    )

                                    custom_system_prompt_input = gr.Textbox(
                                        label=_("Custom System Prompt"),
                                        value=settings.translation.custom_system_prompt
                                        or "",
                                        interactive=True,
                                        placeholder=_(
                                            "e.g. /no_think You are a professional zh-CN native translator who needs to fluently translate text into zh-CN."
                                        ),
                                    )

                                    min_text_length = gr.Number(
                                        label=_("Minimum text length to translate"),
                                        value=settings.translation.min_text_length,
                                        precision=0,
                                        minimum=0,
                                        interactive=True,
                                    )

                                    rpc_doclayout = gr.Textbox(
                                        label=_(
                                            "RPC service for document layout analysis (optional)"
                                        ),
                                        value=settings.translation.rpc_doclayout or "",
                                        visible=False,
                                        interactive=True,
                                        placeholder="http://host:port",
                                    )

                                    save_auto_extracted_glossary = gr.Checkbox(
                                        label=_(
                                            "save automatically extracted glossary"
                                        ),
                                        value=settings.translation.save_auto_extracted_glossary,
                                        interactive=True,
                                    )

                                    primary_font_family = gr.Dropdown(
                                        label=_(
                                            "Primary font family for translated text"
                                        ),
                                        choices=[
                                            "Auto",
                                            "serif",
                                            "sans-serif",
                                            "script",
                                        ],
                                        value="Auto"
                                        if not settings.translation.primary_font_family
                                        else settings.translation.primary_font_family,
                                        interactive=True,
                                    )

                                    glossary_file = gr.File(
                                        label=_("Glossary File"),
                                        file_count="multiple",
                                        file_types=[".csv"],
                                        type="binary",
                                        visible=initial_llm_support,
                                    )
                                    require_llm_translator_inputs.append(glossary_file)

                                    glossary_table = gr.Dataframe(
                                        headers=["source", "target"],
                                        datatype=["str", "str"],
                                        interactive=False,
                                        col_count=(2, "fixed"),
                                        visible=False,
                                    )
                                    require_llm_translator_inputs.append(glossary_table)

                                with gr.Accordion(
                                    _("PDF Processing"),
                                    open=False,
                                    elem_classes=[
                                        "panel-accordion",
                                        "sub-accordion",
                                    ],
                                ):
                                    skip_clean = gr.Checkbox(
                                        label=_(
                                            "Skip clean (maybe improve compatibility)"
                                        ),
                                        value=settings.pdf.skip_clean,
                                        interactive=True,
                                    )

                                    disable_rich_text_translate = gr.Checkbox(
                                        label=_(
                                            "Disable rich text translation (maybe improve compatibility)"
                                        ),
                                        value=settings.pdf.disable_rich_text_translate,
                                        interactive=True,
                                    )

                                    enhance_compatibility = gr.Checkbox(
                                        label=_(
                                            "Enhance compatibility (auto-enables skip_clean and disable_rich_text)"
                                        ),
                                        value=settings.pdf.enhance_compatibility,
                                        interactive=True,
                                    )

                                    split_short_lines = gr.Checkbox(
                                        label=_(
                                            "Force split short lines into different paragraphs"
                                        ),
                                        value=settings.pdf.split_short_lines,
                                        interactive=True,
                                    )

                                    short_line_split_factor = gr.Slider(
                                        label=_(
                                            "Split threshold factor for short lines"
                                        ),
                                        value=settings.pdf.short_line_split_factor,
                                        minimum=0.1,
                                        maximum=1.0,
                                        step=0.1,
                                        interactive=True,
                                        visible=settings.pdf.split_short_lines,
                                    )

                                    translate_table_text = gr.Checkbox(
                                        label=_("Translate table text (experimental)"),
                                        value=settings.pdf.translate_table_text,
                                        interactive=True,
                                    )

                                    skip_scanned_detection = gr.Checkbox(
                                        label=_("Skip scanned detection"),
                                        value=settings.pdf.skip_scanned_detection,
                                        interactive=True,
                                    )

                                    ocr_workaround = gr.Checkbox(
                                        label=_(
                                            "OCR workaround (experimental, will auto enable Skip scanned detection in backend)"
                                        ),
                                        value=settings.pdf.ocr_workaround,
                                        interactive=True,
                                    )

                                    auto_enable_ocr_workaround = gr.Checkbox(
                                        label=_(
                                            "Auto enable OCR workaround (enable automatic OCR workaround for heavily scanned documents)"
                                        ),
                                        value=settings.pdf.auto_enable_ocr_workaround,
                                        interactive=True,
                                    )

                                    max_pages_per_part = gr.Number(
                                        label=_(
                                            "Maximum pages per part (for auto-split translation, 0 means no limit)"
                                        ),
                                        value=settings.pdf.max_pages_per_part,
                                        precision=0,
                                        minimum=0,
                                        interactive=True,
                                    )

                                    formular_font_pattern = gr.Textbox(
                                        label=_(
                                            "Font pattern to identify formula text (regex, not recommended to change)"
                                        ),
                                        value=settings.pdf.formular_font_pattern or "",
                                        interactive=True,
                                        placeholder="e.g., CMMI|CMR",
                                    )

                                    formular_char_pattern = gr.Textbox(
                                        label=_(
                                            "Character pattern to identify formula text (regex, not recommended to change)"
                                        ),
                                        value=settings.pdf.formular_char_pattern or "",
                                        interactive=True,
                                        placeholder="e.g., [∫∬∭∮∯∰∇∆]",
                                    )

                                    ignore_cache = gr.Checkbox(
                                        label=_("Ignore cache"),
                                        value=settings.translation.ignore_cache,
                                        interactive=True,
                                    )

                                    with gr.Accordion(
                                        _("BabelDOC Tuning"),
                                        open=False,
                                        elem_classes=[
                                            "panel-accordion",
                                            "sub-accordion",
                                        ],
                                    ):
                                        merge_alternating_line_numbers = gr.Checkbox(
                                            label=_("Merge alternating line numbers"),
                                            info=_(
                                                "Handle alternating line numbers and text paragraphs in documents with line numbers"
                                            ),
                                            value=not settings.pdf.no_merge_alternating_line_numbers,
                                            interactive=True,
                                        )

                                        remove_non_formula_lines = gr.Checkbox(
                                            label=_("Remove non-formula lines"),
                                            info=_(
                                                "Remove non-formula lines within paragraph areas"
                                            ),
                                            value=not settings.pdf.no_remove_non_formula_lines,
                                            interactive=True,
                                        )

                                        non_formula_line_iou_threshold = gr.Slider(
                                            label=_("Non-formula line IoU threshold"),
                                            info=_(
                                                "IoU threshold for identifying non-formula lines"
                                            ),
                                            value=settings.pdf.non_formula_line_iou_threshold,
                                            minimum=0.0,
                                            maximum=1.0,
                                            step=0.05,
                                            interactive=True,
                                        )

                                        figure_table_protection_threshold = gr.Slider(
                                            label=_(
                                                "Figure/table protection threshold"
                                            ),
                                            info=_(
                                                "Protection threshold for figures and tables (lines within figures/tables will not be processed)"
                                            ),
                                            value=settings.pdf.figure_table_protection_threshold,
                                            minimum=0.0,
                                            maximum=1.0,
                                            step=0.05,
                                            interactive=True,
                                        )

                                        skip_formula_offset_calculation = gr.Checkbox(
                                            label=_("Skip formula offset calculation"),
                                            info=_(
                                                "Skip formula offset calculation during processing"
                                            ),
                                            value=settings.pdf.skip_formula_offset_calculation,
                                            interactive=True,
                                        )

                with gr.Column(
                    scale=6,
                    min_width=380,
                    elem_id="preview-column",
                    elem_classes=["preview-stack"],
                ):
                    with gr.Group(
                        elem_classes=[
                            "panel-card",
                            "panel-card-primary",
                            "live-status-shell",
                            "status-panel",
                            "workspace-status",
                        ]
                    ):
                        live_status_title = gr.Markdown(
                            f"## {_('Live Status')}",
                            elem_classes=["section-title"],
                        )
                        live_status = gr.HTML(
                            initial_live_status_html,
                            elem_classes=["live-status-wrap"],
                        )
                        with gr.Group(
                            elem_classes=["result-zone", "download-zone"],
                            visible=False,
                        ) as result_zone:
                            output_title = gr.Markdown(
                                _downloads_heading(),
                                visible=False,
                                elem_classes=["section-title"],
                            )
                            output_file_mono = gr.File(
                                label=_("Download Translation (Mono)"),
                                visible=False,
                            )
                            output_file_dual = gr.File(
                                label=_("Download Translation (Dual)"),
                                visible=False,
                            )
                            output_file_glossary = gr.File(
                                label=_("Download automatically extracted glossary"),
                                visible=False,
                            )

                    with gr.Group(
                        elem_classes=[
                            "panel-card",
                            "preview-card",
                            "workspace-preview",
                        ]
                    ):
                        preview_title = gr.Markdown(
                            _("## Preview"),
                            elem_classes=["section-title"],
                        )
                        workspace_summary = gr.HTML(
                            initial_workspace_summary,
                            elem_classes=["preview-summary-wrap"],
                        )
                        preview = PDF(
                            label=_("Document Preview"),
                            visible=True,
                            height=980,
                            elem_classes=["pdf-preview"],
                        )

        # Event handlers
        def on_select_filetype(file_type):
            """Update visibility based on selected file type"""
            return (
                gr.update(visible=file_type == "File"),
                gr.update(visible=file_type == "Link"),
            )

        def on_select_page(choice):
            """Update page input visibility based on selection"""
            return (
                gr.update(visible=choice == "Range"),
                gr.update(visible=choice != "All"),
            )

        def on_select_service(service_name):
            """Update service-specific settings visibility"""
            if not service_detail_groups:
                return
            selected_group_index = service_detail_group_index_map.get(service_name)
            llm_support = LLM_support_index_map.get(service_name, False)
            siliconflow_free_acknowledgement_visible = service_name == "SiliconFlowFree"
            siliconflow_update = [
                gr.update(visible=siliconflow_free_acknowledgement_visible)
            ]
            glossary_updates = [
                gr.update(visible=llm_support)
                for _ in range(len(require_llm_translator_inputs))
            ]
            service_group_updates = [
                gr.update(visible=(i == selected_group_index))
                for i in range(len(service_detail_groups))
            ]
            return siliconflow_update + glossary_updates + service_group_updates

        def on_enhance_compatibility_change(enhance_value):
            """Update skip_clean and disable_rich_text_translate when enhance_compatibility changes"""
            if enhance_value:
                # When enhanced compatibility is enabled, both options are auto-enabled and disabled for user modification
                return (
                    gr.update(value=True, interactive=False),
                    gr.update(value=True, interactive=False),
                )
            else:
                # When disabled, allow user to modify these settings
                return (
                    gr.update(interactive=True),
                    gr.update(interactive=True),
                )

        def on_split_short_lines_change(split_value):
            """Update short_line_split_factor visibility based on split_short_lines value"""
            return gr.update(visible=split_value)

        def on_glossary_file_change(glossary_file):
            if glossary_file is None:
                return gr.update(visible=False)

            glossary_list = []
            try:
                for file in glossary_file:
                    content = (
                        _decode_uploaded_text_file(
                            file,
                            file_label=_("glossary file"),
                        )
                        .replace("\r\n", "\n")
                        .strip()
                    )
                    with io.StringIO(content) as f:
                        csvreader = csv.reader(f, delimiter=",", doublequote=True)
                        next(csvreader, None)
                        for line in csvreader:
                            if line:
                                glossary_list.append(line)
            except gr.Error:
                raise
            except (UnicodeDecodeError, csv.Error, KeyError, ValueError) as e:
                logger.error(f"Error previewing glossary file: {e}")
                raise gr.Error(
                    _(
                        "Failed to preview glossary CSV. Check the file encoding and column format, then retry.\n{details}"
                    ).format(details=e)
                ) from e
            logger.debug("Loaded %d glossary row(s) for preview", len(glossary_list))
            if not glossary_list:
                glossary_list = [["", ""]]
            return gr.update(visible=True, value=glossary_list)

        def on_rate_limit_mode_change(mode, service_name):
            """Update rate-limit-specific-settings visibility based on rate_limit_mode value"""
            if service_name == "SiliconFlowFree":
                return [gr.update(visible=False)] * 4  # Hide all options

            rpm_visible = mode == "RPM"
            threads_visible = mode == "Concurrent Threads"
            custom_visible = mode == "Custom"

            return [
                gr.update(visible=rpm_visible),
                gr.update(visible=threads_visible),
                gr.update(visible=custom_visible),
                gr.update(visible=custom_visible),
            ]

        def on_enable_auto_term_extraction_change(enabled: bool):
            """Update term disabled info visibility based on auto term extraction toggle"""
            return _build_term_extraction_visibility_updates(enabled)

        def on_term_rate_limit_mode_change(mode: str):
            """Update term rate-limit controls visibility based on mode"""
            rpm_visible = mode == "RPM"
            threads_visible = mode == "Concurrent Threads"
            custom_visible = mode == "Custom"
            return [
                gr.update(visible=rpm_visible),
                gr.update(visible=threads_visible),
                gr.update(visible=custom_visible),
                gr.update(visible=custom_visible),
            ]

        def on_term_service_change(term_service_name: str):
            """Update term engine-specific settings visibility"""
            if not term_service_detail_groups:
                return
            selected_group_index = term_service_detail_group_index_map.get(
                term_service_name
            )
            return [
                gr.update(visible=(i == selected_group_index))
                for i in range(len(term_service_detail_groups))
            ]

        def on_service_change_with_rate_limit(mode, service_name):
            """Expand original on_select_service with rate-limit-UI updated"""
            original_updates = on_select_service(service_name)

            rate_limit_visible = service_name != "SiliconFlowFree"

            detailed_visible = [gr.update(visible=False)] * 4

            if rate_limit_visible:
                detailed_visible = on_rate_limit_mode_change(mode, service_name)

            # Add updates of rate-limit-UI
            rate_limit_updates = [
                gr.update(visible=rate_limit_visible),
            ]

            return original_updates + rate_limit_updates + detailed_visible

        def on_lang_selector_change(
            lang,
            file_type_value,
            file_input_value,
            link_input_value,
            service_name,
            lang_from_name,
            lang_to_name,
            no_mono_value,
            no_dual_value,
            page_range_value,
            page_input_value,
            watermark_mode_value,
        ):
            settings.gui_settings.ui_lang = lang
            update_current_languages(lang)
            config_manager.write_user_default_config_file(settings=settings.clone())
            return (
                gr.update(value=build_hero_html()),
                gr.update(value=f"## {_('UI Language')}"),
                gr.update(
                    value=_(
                        "Switch the interface language without leaving the workspace."
                    )
                ),
                gr.update(value=f"## {_('Source & Pages')}"),
                gr.update(
                    value=_(
                        "Choose the PDF source and limit the page scope if you only need a subset."
                    )
                ),
                gr.update(
                    label=_("Type"),
                    choices=[(_("File"), "File"), (_("Link"), "Link")],
                ),
                gr.update(label=_("Pages"), choices=get_page_choices()),
                gr.update(value=f"## {_('Translation Setup')}"),
                gr.update(
                    value=_(
                        "Set the language route, translation engine, and runtime controls in one place."
                    )
                ),
                gr.update(value=f"### {_('Run Translation')}"),
                gr.update(
                    value=_(
                        "Start the job here. Live progress and finished downloads stay pinned on the right."
                    )
                ),
                gr.update(value=f"## {_('Export Options')}"),
                gr.update(
                    value=_(
                        "Choose which output variants are generated after translation."
                    )
                ),
                gr.update(value=f"## {_('Advanced Settings')}"),
                gr.update(
                    value=_(
                        "Keep this collapsed unless you need glossary extraction, OCR workarounds, or BabelDOC tuning."
                    )
                ),
                gr.update(
                    label=_("Watermark mode"),
                    choices=[
                        (_("Watermarked"), "Watermarked"),
                        (_("No Watermark"), "No Watermark"),
                    ],
                ),
                gr.update(value=f"## {_('Live Status')}"),
                gr.update(value=_("## Preview")),
                gr.update(label=_("Document Preview")),
                build_workspace_summary(
                    file_type_value,
                    file_input_value,
                    link_input_value,
                    service_name,
                    lang_from_name,
                    lang_to_name,
                    no_mono_value,
                    no_dual_value,
                    page_range_value,
                    page_input_value,
                    watermark_mode_value,
                ),
                _build_page_range_feedback(page_range_value, page_input_value),
            )

        workspace_summary_inputs = [
            file_type,
            file_input,
            link_input,
            service,
            lang_from,
            lang_to,
            no_mono,
            no_dual,
            page_range,
            page_input,
            watermark_output_mode,
        ]

        # UI language change handler

        lang_selector.change(
            on_lang_selector_change,
            [lang_selector, *workspace_summary_inputs],
            outputs=[
                hero_panel,
                ui_language_title,
                ui_language_intro,
                source_title,
                source_intro,
                file_type,
                page_range,
                setup_title,
                setup_intro,
                run_translation_title,
                run_translation_intro,
                export_title,
                export_intro,
                advanced_title,
                advanced_intro,
                watermark_output_mode,
                live_status_title,
                preview_title,
                preview,
                workspace_summary,
                page_range_feedback,
            ],
        )

        # Default file handler
        file_input.upload(
            lambda x: x,
            inputs=file_input,
            outputs=preview,
        )

        file_input.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        file_input.change(
            _build_source_preview_value,
            inputs=[file_type, file_input],
            outputs=preview,
        )

        link_input.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        link_input.change(
            lambda _: None,
            inputs=link_input,
            outputs=preview,
        )

        # Event bindings
        file_type.select(
            on_select_filetype,
            file_type,
            [file_input, link_input],
        )

        file_type.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        file_type.change(
            _build_source_preview_value,
            inputs=[file_type, file_input],
            outputs=preview,
        )

        page_range.select(
            on_select_page,
            page_range,
            [page_input, only_include_translated_page],
        )

        page_range.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        page_range.change(
            _build_page_range_feedback,
            inputs=[page_range, page_input],
            outputs=page_range_feedback,
        )

        page_input.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        page_input.change(
            _build_page_range_feedback,
            inputs=[page_range, page_input],
            outputs=page_range_feedback,
        )

        on_select_service_outputs = (
            [siliconflow_free_acknowledgement]
            + require_llm_translator_inputs
            + service_detail_groups
        )

        service.select(
            on_service_change_with_rate_limit,
            [rate_limit_mode, service],
            outputs=(
                on_select_service_outputs
                if len(on_select_service_outputs) > 0
                else None
            )
            + [
                rate_limit_mode,
                rpm_input,
                concurrent_threads_input,
                custom_qps_input,
                custom_pool_max_workers_input,
            ],
        )

        service.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        lang_from.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        lang_to.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        no_mono.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        no_dual.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        watermark_output_mode.change(
            build_workspace_summary,
            inputs=workspace_summary_inputs,
            outputs=workspace_summary,
        )

        rate_limit_mode.change(
            on_rate_limit_mode_change,
            inputs=[rate_limit_mode, service],
            outputs=[
                rpm_input,
                concurrent_threads_input,
                custom_qps_input,
                custom_pool_max_workers_input,
            ],
        )

        glossary_file.change(
            on_glossary_file_change,
            glossary_file,
            outputs=glossary_table,
        )

        # Add event handler for enhance_compatibility
        enhance_compatibility.change(
            on_enhance_compatibility_change,
            enhance_compatibility,
            [skip_clean, disable_rich_text_translate],
        )

        # Add event handler for split_short_lines
        split_short_lines.change(
            on_split_short_lines_change,
            split_short_lines,
            short_line_split_factor,
        )

        # Auto term extraction toggle handlers
        enable_auto_term_extraction.change(
            on_enable_auto_term_extraction_change,
            enable_auto_term_extraction,
            [term_disabled_info, term_settings_group],
        )

        # Term rate limit handlers
        term_rate_limit_mode.change(
            on_term_rate_limit_mode_change,
            term_rate_limit_mode,
            [
                term_rpm_input,
                term_concurrent_threads_input,
                term_custom_qps_input,
                term_custom_pool_max_workers_input,
            ],
        )

        # Term service change handler
        term_service.change(
            on_term_service_change,
            term_service,
            outputs=(
                term_service_detail_groups
                if len(term_service_detail_groups) > 0
                else None
            ),
        )

        # UI setting controls list (shared by translate_btn and save_btn)
        ui_setting_controls = [
            service,
            lang_from,
            lang_to,
            page_range,
            page_input,
            # PDF Output Options
            no_mono,
            no_dual,
            dual_translate_first,
            use_alternating_pages_dual,
            watermark_output_mode,
            # Rate Limit Options
            rate_limit_mode,
            rpm_input,
            concurrent_threads_input,
            custom_qps_input,
            custom_pool_max_workers_input,
            # Advanced Options
            prompt,
            min_text_length,
            rpc_doclayout,
            custom_system_prompt_input,
            glossary_file,
            save_auto_extracted_glossary,
            # New advanced translation options
            enable_auto_term_extraction,
            primary_font_family,
            skip_clean,
            disable_rich_text_translate,
            enhance_compatibility,
            split_short_lines,
            short_line_split_factor,
            translate_table_text,
            skip_scanned_detection,
            max_pages_per_part,
            formular_font_pattern,
            formular_char_pattern,
            ignore_cache,
            ocr_workaround,
            auto_enable_ocr_workaround,
            only_include_translated_page,
            # BabelDOC v0.5.1 new options
            merge_alternating_line_numbers,
            remove_non_formula_lines,
            non_formula_line_iou_threshold,
            figure_table_protection_threshold,
            skip_formula_offset_calculation,
            # Term extraction engine options
            term_service,
            term_rate_limit_mode,
            term_rpm_input,
            term_concurrent_threads_input,
            term_custom_qps_input,
            term_custom_pool_max_workers_input,
            *translation_engine_arg_inputs,
            # any UI components that are used by translate/save should be listed above!
            # Extra UI components to be updated on load (not used by translate/save)
            siliconflow_free_acknowledgement,
            glossary_table,
            term_disabled_info,
        ]

        # Translation button click handler
        translate_event = translate_btn.click(
            translate_file,
            inputs=[
                file_type,
                file_input,
                link_input,
                *ui_setting_controls,
            ],
            outputs=[
                output_file_mono,  # Mono PDF file
                preview,  # Preview
                output_file_dual,  # Dual PDF file
                output_file_glossary,
                output_file_mono,  # Visibility of mono output
                output_file_dual,  # Visibility of dual output
                output_file_glossary,
                output_title,  # Visibility of output title
                result_zone,
                live_status,
                translate_btn,
                cancel_btn,
                save_btn,
            ],
            show_progress="hidden",
            concurrency_id="translation-job",
            concurrency_limit=1,
        )

        # Cancel button click handler
        cancel_btn.click(
            stop_translate_file,
            inputs=[service, lang_from, lang_to],
            outputs=[
                live_status,
                translate_btn,
                cancel_btn,
                save_btn,
            ],
            cancels=[translate_event],
            queue=False,
            show_progress="hidden",
        )

        # Save button click handler
        save_btn.click(
            save_config,
            inputs=ui_setting_controls,
        )

        def load_saved_config_to_ui():
            """Reload all settings from config and update UI components."""
            try:
                fresh_settings = settings
                update_current_languages(settings.gui_settings.ui_lang)

                updates: list = []

                # Determine selected service by cli flag
                selected_service = get_selected_service_from_settings(fresh_settings)
                llm_support = LLM_support_index_map.get(selected_service, False)

                # Follow the EXACT order of ui_setting_controls
                # service
                updates.append(gr.update(value=selected_service))
                # lang_from, lang_to
                loaded_lang_from = rev_lang_map.get(
                    fresh_settings.translation.lang_in, "English"
                )
                loaded_lang_to_code = fresh_settings.translation.lang_out
                loaded_lang_to = next(
                    (k for k, v in lang_map.items() if v == loaded_lang_to_code),
                    "Simplified Chinese",
                )
                updates.append(gr.update(value=loaded_lang_from))
                updates.append(gr.update(value=loaded_lang_to))
                # page_range, page_input
                pages_setting = fresh_settings.pdf.pages
                if pages_setting is None or pages_setting == "":
                    updates.append(gr.update(value="All"))
                    updates.append(gr.update(value="", visible=False))
                else:
                    updates.append(gr.update(value="Range"))
                    updates.append(gr.update(value=str(pages_setting), visible=True))
                # PDF Output Options
                updates.append(gr.update(value=fresh_settings.pdf.no_mono))
                updates.append(gr.update(value=fresh_settings.pdf.no_dual))
                updates.append(gr.update(value=fresh_settings.pdf.dual_translate_first))
                updates.append(
                    gr.update(value=fresh_settings.pdf.use_alternating_pages_dual)
                )
                watermark_value = (
                    "Watermarked"
                    if fresh_settings.pdf.watermark_output_mode == "watermarked"
                    else "No Watermark"
                )
                updates.append(gr.update(value=watermark_value))
                # Rate Limit Options
                rate_limit_visible = selected_service != "SiliconFlowFree"
                updates.append(gr.update(value="Custom", visible=rate_limit_visible))
                updates.append(gr.update(visible=False))  # rpm_input
                updates.append(gr.update(visible=False))  # concurrent_threads_input
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.qps or 4,
                        visible=rate_limit_visible,
                    )
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.pool_max_workers,
                        visible=rate_limit_visible,
                    )
                )
                # Advanced Options
                updates.append(gr.update(value=""))  # prompt
                updates.append(
                    gr.update(value=fresh_settings.translation.min_text_length)
                )
                updates.append(
                    gr.update(value=fresh_settings.translation.rpc_doclayout or "")
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.custom_system_prompt or ""
                    )
                )
                updates.append(
                    gr.update(visible=llm_support)
                )  # glossary_file visibility
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.save_auto_extracted_glossary
                    )
                )
                # enable_auto_term_extraction is the inverse of no_auto_extract_glossary
                updates.append(
                    gr.update(
                        value=not fresh_settings.translation.no_auto_extract_glossary
                    )
                )
                primary_font_display = (
                    "Auto"
                    if not fresh_settings.translation.primary_font_family
                    else fresh_settings.translation.primary_font_family
                )
                updates.append(gr.update(value=primary_font_display))
                updates.append(gr.update(value=fresh_settings.pdf.skip_clean))
                updates.append(
                    gr.update(value=fresh_settings.pdf.disable_rich_text_translate)
                )
                updates.append(
                    gr.update(value=fresh_settings.pdf.enhance_compatibility)
                )
                updates.append(gr.update(value=fresh_settings.pdf.split_short_lines))
                updates.append(
                    gr.update(
                        value=fresh_settings.pdf.short_line_split_factor,
                        visible=fresh_settings.pdf.split_short_lines,
                    )
                )
                updates.append(gr.update(value=fresh_settings.pdf.translate_table_text))
                updates.append(
                    gr.update(value=fresh_settings.pdf.skip_scanned_detection)
                )
                updates.append(gr.update(value=fresh_settings.pdf.max_pages_per_part))
                updates.append(
                    gr.update(value=fresh_settings.pdf.formular_font_pattern or "")
                )
                updates.append(
                    gr.update(value=fresh_settings.pdf.formular_char_pattern or "")
                )
                updates.append(gr.update(value=fresh_settings.translation.ignore_cache))
                updates.append(gr.update(value=fresh_settings.pdf.ocr_workaround))
                updates.append(
                    gr.update(value=fresh_settings.pdf.auto_enable_ocr_workaround)
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.pdf.only_include_translated_page,
                        visible=bool(pages_setting),
                    )
                )
                # BabelDOC
                updates.append(
                    gr.update(
                        value=not fresh_settings.pdf.no_merge_alternating_line_numbers
                    )
                )
                updates.append(
                    gr.update(value=not fresh_settings.pdf.no_remove_non_formula_lines)
                )
                updates.append(
                    gr.update(value=fresh_settings.pdf.non_formula_line_iou_threshold)
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.pdf.figure_table_protection_threshold
                    )
                )
                updates.append(
                    gr.update(value=fresh_settings.pdf.skip_formula_offset_calculation)
                )
                # Term extraction engine basic settings
                term_engine_enabled = (
                    not fresh_settings.translation.no_auto_extract_glossary
                )
                selected_term_service = "Follow main translation engine"
                for term_metadata in TERM_EXTRACTION_ENGINE_METADATA:
                    term_flag_name = f"term_{term_metadata.cli_flag_name}"
                    if getattr(fresh_settings, term_flag_name, False):
                        selected_term_service = term_metadata.translate_engine_type
                        break
                updates.append(gr.update(value=selected_term_service))
                # Term rate limit: use Custom mode by default
                updates.append(gr.update(value="Custom"))
                updates.append(gr.update(visible=False))  # term_rpm_input
                updates.append(
                    gr.update(visible=False)
                )  # term_concurrent_threads_input
                updates.append(
                    gr.update(
                        value=(
                            fresh_settings.translation.term_qps
                            or fresh_settings.translation.qps
                            or 4
                        ),
                        visible=True,
                    )
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.term_pool_max_workers,
                        visible=True,
                    )
                )
                # Translation engine detail fields (ordered)
                disable_sensitive_gui = (
                    fresh_settings.gui_settings.disable_gui_sensitive_input
                )
                for service_name in available_services:
                    metadata = TRANSLATION_ENGINE_METADATA_MAP[service_name]
                    if not metadata.cli_detail_field_name:
                        continue
                    detail_settings = getattr(
                        fresh_settings, metadata.cli_detail_field_name
                    )
                    for (
                        field_name,
                        field,
                    ) in metadata.setting_model_type.model_fields.items():
                        if disable_sensitive_gui:
                            if field_name in GUI_SENSITIVE_FIELDS:
                                continue
                            if field_name in GUI_PASSWORD_FIELDS:
                                continue
                        if field.default_factory:
                            continue
                        if (
                            field_name == "translate_engine_type"
                            or field_name == "support_llm"
                        ):
                            continue
                        value = getattr(detail_settings, field_name)
                        visible = metadata.translate_engine_type == selected_service
                        updates.append(gr.update(value=value, visible=visible))

                # Term extraction engine detail fields (ordered)
                for term_metadata in TERM_EXTRACTION_ENGINE_METADATA:
                    if not term_metadata.cli_detail_field_name:
                        continue
                    term_detail_field_name = (
                        f"term_{term_metadata.cli_detail_field_name}"
                    )
                    term_detail_settings = getattr(
                        fresh_settings, term_detail_field_name
                    )
                    for (
                        field_name,
                        field,
                    ) in term_metadata.term_setting_model_type.model_fields.items():
                        if field.default_factory:
                            continue
                        if field_name in ("translate_engine_type", "support_llm"):
                            continue
                        base_field_name = field_name
                        if base_field_name.startswith("term_"):
                            base_name = base_field_name[len("term_") :]
                        else:
                            base_name = base_field_name
                        if disable_sensitive_gui:
                            if base_name in GUI_SENSITIVE_FIELDS:
                                continue
                            if base_name in GUI_PASSWORD_FIELDS:
                                continue
                        value = getattr(term_detail_settings, field_name)
                        visible = (
                            term_metadata.translate_engine_type == selected_term_service
                        )
                        updates.append(gr.update(value=value, visible=visible))

                # Extra UI components at the end of ui_setting_controls
                siliconflow_free_ack_visible = selected_service == "SiliconFlowFree"
                updates.append(gr.update(visible=siliconflow_free_ack_visible))
                updates.append(
                    gr.update(visible=llm_support)
                )  # glossary_table visibility
                updates.append(
                    gr.update(
                        visible=fresh_settings.translation.no_auto_extract_glossary
                    )
                )  # term_disabled_info visibility
                updates.append(
                    gr.update(
                        visible=not fresh_settings.translation.no_auto_extract_glossary
                    )
                )  # term_settings_group visibility
                updates.append(
                    _build_page_range_feedback(
                        "Range" if pages_setting else "All", pages_setting
                    )
                )
                updates.append(build_workspace_summary_from_settings(fresh_settings))

                return updates
            except Exception as e:
                logger.warning(f"Could not reload config on page load: {e}")
                return [None] * (len(ui_setting_controls) + 3)

        page_load_outputs = ui_setting_controls + [
            term_settings_group,
            page_range_feedback,
            workspace_summary,
        ]

        demo.load(
            load_saved_config_to_ui,
            outputs=page_load_outputs,
        )


def parse_user_passwd(file_path: str, welcome_page: str) -> tuple[list, str]:
    """
    This function parses a user password file.

    Inputs:
        - file_path: The path to the file

    Returns:
        - A tuple containing the user list and HTML
    """
    content = ""
    tuple_list = None
    if welcome_page:
        try:
            path = Path(welcome_page)
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"Error: File '{welcome_page}' not found.")
    if file_path:
        try:
            path = Path(file_path)
            tuple_list = [
                tuple(line.strip().split(","))
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except FileNotFoundError:
            tuple_list = None
    return tuple_list, content


def _is_port_conflict_error(exc: Exception) -> bool:
    return isinstance(exc, OSError) and "Cannot find empty port in range" in str(exc)


def _find_available_port(start_port: int, search_window: int = 20) -> int | None:
    for port in range(start_port, start_port + search_window):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
        except PermissionError as exc:
            raise RuntimeError(
                _(
                    "Local port probing is blocked in this environment. Retry the GUI with --server-port <free-port> or set GRADIO_SERVER_PORT before launch."
                )
            ) from exc
        except OSError:
            continue
        return port
    return None


def _launch_demo_with_recovery(
    *,
    share: bool,
    auth: list[tuple[str, str]] | None,
    auth_message: str | None,
    server_port: int | None,
    inbrowser: bool,
) -> None:
    shared_kwargs = {
        "debug": True,
        "inbrowser": inbrowser,
        "auth": auth,
        "auth_message": auth_message,
        "allowed_paths": [logo_path],
    }
    attempts = [
        {
            "server_name": "0.0.0.0",
            "share": share,
            "error_message": (
                "Error launching GUI using 0.0.0.0.\n"
                "This may be caused by global mode of proxy software."
            ),
        },
        {
            "server_name": "127.0.0.1",
            "share": share,
            "error_message": (
                "Error launching GUI using 127.0.0.1.\n"
                "This may be caused by global mode of proxy software."
            ),
        },
        {
            "server_name": None,
            "share": True,
            "error_message": None,
        },
    ]

    last_error: Exception | None = None
    for attempt in attempts:
        launch_kwargs = {
            **shared_kwargs,
            "share": attempt["share"],
            "server_port": server_port,
        }
        if attempt["server_name"] is not None:
            launch_kwargs["server_name"] = attempt["server_name"]

        try:
            demo.launch(**launch_kwargs)
            return
        except Exception as exc:
            last_error = exc
            if _is_port_conflict_error(exc) and server_port is not None:
                try:
                    fallback_port = _find_available_port(server_port + 1)
                except RuntimeError as probe_exc:
                    last_error = RuntimeError(
                        _(
                            "Port {port} is unavailable and fallback port probing is blocked in this environment. Retry with --server-port <free-port> or set GRADIO_SERVER_PORT before launch."
                        ).format(port=server_port)
                    )
                    last_error.__cause__ = probe_exc
                    continue
                if fallback_port is None:
                    last_error = RuntimeError(
                        _(
                            "Port {port} is already in use and no free fallback port was found nearby. Start the GUI with --server-port <free-port>."
                        ).format(port=server_port)
                    )
                    continue
                fallback_kwargs = dict(launch_kwargs)
                fallback_kwargs["server_port"] = fallback_port
                print(
                    _(
                        "Port {port} is already in use. Retrying on port {fallback_port}."
                    ).format(port=server_port, fallback_port=fallback_port),
                    flush=True,
                )
                try:
                    demo.launch(**fallback_kwargs)
                    return
                except Exception as fallback_exc:
                    last_error = fallback_exc

            if attempt["error_message"]:
                print(attempt["error_message"], flush=True)

    if last_error is not None:
        if _is_port_conflict_error(last_error):
            raise RuntimeError(
                _(
                    "Unable to start the GUI because no local port was available. Try again with --server-port <free-port>."
                )
            ) from last_error
        raise last_error


def setup_gui(
    share: bool = False,
    auth_file: str | None = None,
    welcome_page: str | None = None,
    server_port=7860,
    inbrowser: bool = True,
) -> None:
    """
    This function sets up the GUI for the application.

    Inputs:
        - share: Whether to share the GUI
        - auth_file: The authentication file
        - server_port: The port to run the server on

    Returns:
        - None
    """

    user_list = None
    html = None

    user_list, html = parse_user_passwd(auth_file, welcome_page)
    _launch_demo_with_recovery(
        share=share,
        auth=user_list if auth_file and user_list else None,
        auth_message=html,
        server_port=server_port,
        inbrowser=inbrowser,
    )


# For auto-reloading while developing
if __name__ == "__main__":
    from rich.logging import RichHandler

    # disable httpx, openai, httpcore, http11 logs
    logging.getLogger("httpx").setLevel("CRITICAL")
    logging.getLogger("httpx").propagate = False
    logging.getLogger("openai").setLevel("CRITICAL")
    logging.getLogger("openai").propagate = False
    logging.getLogger("httpcore").setLevel("CRITICAL")
    logging.getLogger("httpcore").propagate = False
    logging.getLogger("http11").setLevel("CRITICAL")
    logging.getLogger("http11").propagate = False
    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])
    setup_gui(inbrowser=False)
