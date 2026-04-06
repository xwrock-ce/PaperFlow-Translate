from __future__ import annotations

from typing import Literal

import langcodes

from pdf2zh_next.ui_options import TRANSLATION_LANGUAGE_MAP

UiLocale = Literal["en", "zh"]
LocalizedText = dict[UiLocale, str]

SUPPORTED_UI_LOCALES: tuple[UiLocale, ...] = ("en", "zh")

_LANGUAGE_ZH_OVERRIDES = {
    "zh-CN": "简体中文",
    "zh-HK": "繁体中文（香港）",
    "zh-TW": "繁体中文（台湾）",
    "pt-BR": "巴西葡萄牙语",
}

_LANGUAGE_ZH_FALLBACKS_WHEN_UNLOCALIZED = {
    # `langcodes` returns "English" for zh labels when `language_data` is missing.
    "en": "英语",
}

_GENERAL_FIELD_LABELS: dict[str, LocalizedText] = {
    "min_text_length": {"en": "Minimum Text Length", "zh": "最短翻译文本长度"},
    "rpc_doclayout": {"en": "Layout RPC Address", "zh": "版面分析 RPC 地址"},
    "qps": {"en": "QPS Limit", "zh": "QPS 限制"},
    "ignore_cache": {"en": "Ignore Cache", "zh": "忽略缓存"},
    "custom_system_prompt": {"en": "Custom System Prompt", "zh": "自定义系统提示词"},
    "save_auto_extracted_glossary": {
        "en": "Save Auto-Extracted Glossary",
        "zh": "保存自动提取术语表",
    },
    "pool_max_workers": {"en": "Max Worker Count", "zh": "最大工作线程数"},
    "term_qps": {"en": "Term Extraction QPS", "zh": "术语提取 QPS"},
    "term_pool_max_workers": {
        "en": "Term Extraction Max Workers",
        "zh": "术语提取最大工作线程数",
    },
    "no_auto_extract_glossary": {
        "en": "Disable Auto Term Extraction",
        "zh": "关闭自动术语提取",
    },
    "primary_font_family": {"en": "Preferred Font Family", "zh": "首选字体族"},
    "pages": {"en": "Page Range", "zh": "页码范围"},
    "no_dual": {"en": "Disable Bilingual PDF", "zh": "禁用双语 PDF"},
    "no_mono": {"en": "Disable Monolingual PDF", "zh": "禁用单语 PDF"},
    "formular_font_pattern": {"en": "Formula Font Pattern", "zh": "公式字体模式"},
    "formular_char_pattern": {"en": "Formula Character Pattern", "zh": "公式字符模式"},
    "split_short_lines": {"en": "Split Short Lines", "zh": "拆分短行"},
    "short_line_split_factor": {
        "en": "Short-Line Split Factor",
        "zh": "短行拆分系数",
    },
    "skip_clean": {"en": "Skip PDF Cleanup", "zh": "跳过 PDF 清理"},
    "dual_translate_first": {
        "en": "Translated Pages First",
        "zh": "双语 PDF 译文在前",
    },
    "disable_rich_text_translate": {
        "en": "Disable Rich Text Translation",
        "zh": "禁用富文本翻译",
    },
    "enhance_compatibility": {"en": "Enhance Compatibility", "zh": "增强兼容性"},
    "use_alternating_pages_dual": {
        "en": "Alternate Pages In Bilingual PDF",
        "zh": "双语 PDF 交替分页",
    },
    "watermark_output_mode": {"en": "Watermark Output", "zh": "水印输出模式"},
    "max_pages_per_part": {"en": "Max Pages Per Part", "zh": "每分片最大页数"},
    "translate_table_text": {"en": "Translate Table Text", "zh": "翻译表格文本"},
    "skip_scanned_detection": {"en": "Skip Scan Detection", "zh": "跳过扫描版检测"},
    "ocr_workaround": {"en": "OCR Workaround", "zh": "OCR 兼容模式"},
    "auto_enable_ocr_workaround": {
        "en": "Auto-Enable OCR Workaround",
        "zh": "自动开启 OCR 兼容模式",
    },
    "only_include_translated_page": {
        "en": "Only Include Translated Pages",
        "zh": "仅输出已翻译页",
    },
    "no_merge_alternating_line_numbers": {
        "en": "Keep Alternating Line Numbers",
        "zh": "不合并交替行号",
    },
    "no_remove_non_formula_lines": {
        "en": "Keep Non-Formula Lines",
        "zh": "不移除非公式行",
    },
    "non_formula_line_iou_threshold": {
        "en": "Non-Formula Line IoU Threshold",
        "zh": "非公式行 IoU 阈值",
    },
    "figure_table_protection_threshold": {
        "en": "Figure/Table Protection Threshold",
        "zh": "图表保护阈值",
    },
    "skip_formula_offset_calculation": {
        "en": "Skip Formula Offset Calculation",
        "zh": "跳过公式偏移计算",
    },
    "ali_domains": {"en": "Aliyun Domains", "zh": "阿里云域名列表"},
    "num_predict": {"en": "Max Prediction Tokens", "zh": "最大生成 Token"},
}

_ENGINE_PREFIXES = {
    "aliyun_dashscope": "Aliyun DashScope",
    "anythingllm": "AnythingLLM",
    "azure": "Azure",
    "azure_openai": "Azure OpenAI",
    "claude_code": "Claude Code",
    "deepl": "DeepL",
    "deepseek": "DeepSeek",
    "dify": "Dify",
    "gemini": "Gemini",
    "grok": "Grok",
    "groq": "Groq",
    "modelscope": "ModelScope",
    "ollama": "Ollama",
    "openai": "OpenAI",
    "openai_compatible": "OpenAI-Compatible",
    "qwenmt": "Qwen MT",
    "siliconflow": "SiliconFlow",
    "siliconflow_free": "SiliconFlow Free",
    "tencentcloud": "Tencent Cloud",
    "xinference": "Xinference",
    "zhipu": "Zhipu",
}

_ENGINE_FIELD_SUFFIXES: dict[str, LocalizedText] = {
    "api_key": {"en": "API Key", "zh": "API 密钥"},
    "apikey": {"en": "API Key", "zh": "API 密钥"},
    "auth_key": {"en": "Auth Key", "zh": "认证密钥"},
    "base_url": {"en": "Base URL", "zh": "基础 URL"},
    "url": {"en": "URL", "zh": "URL"},
    "host": {"en": "Host", "zh": "主机地址"},
    "endpoint": {"en": "Endpoint", "zh": "服务端点"},
    "model": {"en": "Model", "zh": "模型"},
    "timeout": {"en": "Timeout", "zh": "超时时间"},
    "temperature": {"en": "Temperature", "zh": "温度"},
    "send_temperature": {"en": "Send Temperature", "zh": "发送温度参数"},
    "send_temprature": {"en": "Send Temperature", "zh": "发送温度参数"},
    "reasoning_effort": {"en": "Reasoning Effort", "zh": "推理强度"},
    "send_reasoning_effort": {
        "en": "Send Reasoning Effort",
        "zh": "发送推理强度参数",
    },
    "enable_json_mode": {"en": "JSON Mode", "zh": "JSON 模式"},
    "api_version": {"en": "API Version", "zh": "API 版本"},
    "secret_id": {"en": "Secret ID", "zh": "密钥 ID"},
    "secret_key": {"en": "Secret Key", "zh": "密钥"},
    "enable_thinking": {"en": "Enable Thinking", "zh": "启用思考模式"},
    "send_enable_thinking_param": {
        "en": "Send Thinking Parameter",
        "zh": "发送思考参数",
    },
    "domains": {"en": "Domains", "zh": "域名列表"},
    "path": {"en": "Executable Path", "zh": "可执行文件路径"},
}

_FIELD_OPTIONS: dict[str, list[tuple[str, LocalizedText]]] = {
    "primary_font_family": [
        ("Auto", {"en": "Auto", "zh": "自动"}),
        ("serif", {"en": "Serif", "zh": "衬线"}),
        ("sans-serif", {"en": "Sans-serif", "zh": "无衬线"}),
        ("script", {"en": "Script", "zh": "手写/斜体"}),
    ],
    "watermark_output_mode": [
        ("watermarked", {"en": "Watermarked", "zh": "带水印"}),
        ("no_watermark", {"en": "No Watermark", "zh": "无水印"}),
        ("both", {"en": "Both", "zh": "两者都输出"}),
    ],
    "openai_reasoning_effort": [
        ("minimal", {"en": "Minimal", "zh": "极低"}),
        ("low", {"en": "Low", "zh": "低"}),
        ("medium", {"en": "Medium", "zh": "中"}),
        ("high", {"en": "High", "zh": "高"}),
    ],
    "openai_compatible_reasoning_effort": [
        ("minimal", {"en": "Minimal", "zh": "极低"}),
        ("low", {"en": "Low", "zh": "低"}),
        ("medium", {"en": "Medium", "zh": "中"}),
        ("high", {"en": "High", "zh": "高"}),
    ],
}


def normalize_ui_locale(locale: str | None) -> UiLocale:
    return "zh" if locale == "zh" else "en"


def localized(en: str, zh: str) -> LocalizedText:
    return {"en": en, "zh": zh}


def _normalized_label_text(value: str | None, fallback: str) -> str:
    normalized = (value or "").strip()
    return normalized or fallback


def _localized_language_name(english_label: str, code: str) -> LocalizedText:
    fallback_en = _normalized_label_text(english_label, code)
    zh_label = _LANGUAGE_ZH_OVERRIDES.get(code)
    if zh_label is None:
        try:
            zh_label = langcodes.Language.get(code).display_name("zh")
        except Exception:
            zh_label = _LANGUAGE_ZH_FALLBACKS_WHEN_UNLOCALIZED.get(code, "")
        normalized_zh_label = (zh_label or "").strip()
        if (
            normalized_zh_label
            and normalized_zh_label.casefold() == fallback_en.casefold()
        ):
            zh_label = _LANGUAGE_ZH_FALLBACKS_WHEN_UNLOCALIZED.get(code, zh_label)
    return localized(fallback_en, _normalized_label_text(zh_label, fallback_en))


def build_translation_language_options() -> list[dict[str, str | LocalizedText]]:
    options: list[dict[str, str | LocalizedText]] = []
    for english_label, code in TRANSLATION_LANGUAGE_MAP.items():
        options.append(
            {"label": _localized_language_name(english_label, code), "value": code}
        )
    return options


def localize_field_label(field_name: str) -> LocalizedText:
    normalized_field_name = (
        field_name.removeprefix("term_")
        if field_name.startswith("term_")
        else field_name
    )

    if normalized_field_name in _GENERAL_FIELD_LABELS:
        return _GENERAL_FIELD_LABELS[normalized_field_name]

    for suffix, suffix_label in sorted(
        _ENGINE_FIELD_SUFFIXES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        marker = f"_{suffix}"
        if not normalized_field_name.endswith(marker):
            continue

        prefix = normalized_field_name[: -len(marker)]
        if prefix not in _ENGINE_PREFIXES:
            continue

        engine_name = _ENGINE_PREFIXES[prefix]
        return localized(
            f"{engine_name} {suffix_label['en']}",
            f"{engine_name} {suffix_label['zh']}",
        )

    raise KeyError(f"Missing WebUI localization for field: {field_name}")


def localize_field_description(field_name: str) -> LocalizedText:
    return localize_field_label(field_name)


def field_options(field_name: str) -> list[dict[str, str | LocalizedText]]:
    options = _FIELD_OPTIONS.get(field_name, [])
    return [{"label": label, "value": value} for value, label in options]
