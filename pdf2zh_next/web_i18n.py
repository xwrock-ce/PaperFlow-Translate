from __future__ import annotations

from typing import Any

import langcodes

from pdf2zh_next.ui_options import TRANSLATION_LANGUAGE_MAP

LocalizedText = dict[str, str]


def localized_text(en: str, zh: str) -> LocalizedText:
    return {"en": en, "zh": zh}


_FIELD_TRANSLATIONS = {
    "translation": {
        "min_text_length": {
            "label": localized_text("Minimum text length", "最小文本长度"),
            "description": localized_text(
                "Ignore text blocks shorter than this length during translation.",
                "翻译时忽略短于该长度的文本块。",
            ),
        },
        "rpc_doclayout": {
            "label": localized_text("Layout RPC host", "版面分析 RPC 主机"),
            "description": localized_text(
                "RPC host used for document layout analysis.",
                "用于文档版面分析的 RPC 主机地址。",
            ),
        },
        "qps": {
            "label": localized_text("QPS limit", "QPS 限制"),
            "description": localized_text(
                "Maximum queries per second for the main translation service.",
                "主翻译服务的每秒最大请求数。",
            ),
        },
        "ignore_cache": {
            "label": localized_text("Ignore cache", "忽略缓存"),
            "description": localized_text(
                "Skip cached results and force fresh translation requests.",
                "跳过缓存结果并强制重新发起翻译请求。",
            ),
        },
        "custom_system_prompt": {
            "label": localized_text("Custom system prompt", "自定义系统提示词"),
            "description": localized_text(
                "Extra system prompt appended to the translation request.",
                "附加到翻译请求中的额外系统提示词。",
            ),
        },
        "save_auto_extracted_glossary": {
            "label": localized_text("Save extracted glossary", "保存自动提取术语表"),
            "description": localized_text(
                "Save the glossary generated automatically during translation.",
                "保存翻译过程中自动提取的术语表。",
            ),
        },
        "pool_max_workers": {
            "label": localized_text("Worker pool size", "工作线程池大小"),
            "description": localized_text(
                "Maximum worker count for the main translation pool.",
                "主翻译线程池的最大工作线程数量。",
            ),
        },
        "term_qps": {
            "label": localized_text("Term extraction QPS", "术语提取 QPS"),
            "description": localized_text(
                "Maximum queries per second for automatic term extraction.",
                "自动术语提取服务的每秒最大请求数。",
            ),
        },
        "term_pool_max_workers": {
            "label": localized_text("Term extraction workers", "术语提取线程数"),
            "description": localized_text(
                "Maximum worker count for the term extraction pool.",
                "术语提取线程池的最大工作线程数量。",
            ),
        },
        "no_auto_extract_glossary": {
            "label": localized_text(
                "Disable auto glossary extraction",
                "禁用自动术语提取",
            ),
            "description": localized_text(
                "Turn off automatic glossary extraction during translation.",
                "在翻译过程中关闭自动术语提取。",
            ),
        },
        "primary_font_family": {
            "label": localized_text("Primary font family", "主字体族"),
            "description": localized_text(
                "Override the main translated font family.",
                "覆盖译文使用的主要字体族。",
            ),
        },
    },
    "pdf": {
        "pages": {
            "label": localized_text("Pages", "页码范围"),
            "description": localized_text(
                "Pages to translate, for example 1,3,5-7.",
                "需要翻译的页码范围，例如 1,3,5-7。",
            ),
        },
        "no_dual": {
            "label": localized_text("Disable bilingual PDF", "关闭双语 PDF"),
            "description": localized_text(
                "Do not generate the bilingual PDF output.",
                "不生成双语 PDF 输出。",
            ),
        },
        "no_mono": {
            "label": localized_text("Disable monolingual PDF", "关闭单语 PDF"),
            "description": localized_text(
                "Do not generate the monolingual translated PDF output.",
                "不生成单语译文 PDF 输出。",
            ),
        },
        "formular_font_pattern": {
            "label": localized_text("Formula font pattern", "公式字体模式"),
            "description": localized_text(
                "Font pattern used to identify formula text.",
                "用于识别公式文本的字体模式。",
            ),
        },
        "formular_char_pattern": {
            "label": localized_text("Formula character pattern", "公式字符模式"),
            "description": localized_text(
                "Character pattern used to identify formula text.",
                "用于识别公式文本的字符模式。",
            ),
        },
        "split_short_lines": {
            "label": localized_text("Split short lines", "拆分短行"),
            "description": localized_text(
                "Force short lines into separate paragraphs.",
                "强制将短行拆分为独立段落。",
            ),
        },
        "short_line_split_factor": {
            "label": localized_text("Short-line split factor", "短行拆分阈值"),
            "description": localized_text(
                "Threshold factor used when splitting short lines.",
                "拆分短行时使用的阈值系数。",
            ),
        },
        "skip_clean": {
            "label": localized_text("Skip PDF cleaning", "跳过 PDF 清理"),
            "description": localized_text(
                "Skip the PDF cleanup step before translation.",
                "在翻译前跳过 PDF 清理步骤。",
            ),
        },
        "dual_translate_first": {
            "label": localized_text(
                "Put translated pages first",
                "双语 PDF 优先显示译文页",
            ),
            "description": localized_text(
                "Place translated pages before original pages in dual mode.",
                "在双语模式中将译文页排在原文页之前。",
            ),
        },
        "disable_rich_text_translate": {
            "label": localized_text(
                "Disable rich-text translation",
                "禁用富文本翻译",
            ),
            "description": localized_text(
                "Turn off rich-text translation handling.",
                "关闭富文本翻译处理。",
            ),
        },
        "enhance_compatibility": {
            "label": localized_text("Enhance compatibility", "增强兼容模式"),
            "description": localized_text(
                "Enable the broader PDF compatibility safeguards.",
                "启用更强的 PDF 兼容性保护选项。",
            ),
        },
        "use_alternating_pages_dual": {
            "label": localized_text(
                "Use alternating dual pages",
                "双语 PDF 使用交替页",
            ),
            "description": localized_text(
                "Arrange dual PDF output in alternating original and translated pages.",
                "让双语 PDF 以原文页和译文页交替排列。",
            ),
        },
        "watermark_output_mode": {
            "label": localized_text("Watermark output", "水印输出模式"),
            "description": localized_text(
                "Choose whether to export watermarked, clean, or both PDF variants.",
                "选择输出带水印、无水印或两种 PDF 版本。",
            ),
        },
        "max_pages_per_part": {
            "label": localized_text("Max pages per part", "每段最大页数"),
            "description": localized_text(
                "Split large documents into parts with at most this many pages.",
                "将大文档拆分为每段不超过该页数的部分。",
            ),
        },
        "translate_table_text": {
            "label": localized_text("Translate table text", "翻译表格文本"),
            "description": localized_text(
                "Try to translate text detected inside tables.",
                "尝试翻译表格中的文本。",
            ),
        },
        "skip_scanned_detection": {
            "label": localized_text("Skip scan detection", "跳过扫描检测"),
            "description": localized_text(
                "Skip scanned-PDF detection before processing.",
                "在处理前跳过扫描版 PDF 检测。",
            ),
        },
        "ocr_workaround": {
            "label": localized_text("Force OCR workaround", "强制启用 OCR 兼容方案"),
            "description": localized_text(
                "Force the OCR compatibility workaround for scanned pages.",
                "为扫描页强制启用 OCR 兼容方案。",
            ),
        },
        "auto_enable_ocr_workaround": {
            "label": localized_text("Auto OCR workaround", "自动启用 OCR 兼容方案"),
            "description": localized_text(
                "Enable the OCR workaround automatically for heavily scanned documents.",
                "对重度扫描文档自动启用 OCR 兼容方案。",
            ),
        },
        "only_include_translated_page": {
            "label": localized_text("Only translated pages", "仅输出翻译页"),
            "description": localized_text(
                "Only keep translated pages in the output when a page range is used.",
                "使用页码范围时，仅在输出中保留翻译后的页面。",
            ),
        },
        "no_merge_alternating_line_numbers": {
            "label": localized_text(
                "Do not merge alternating line numbers",
                "不要合并交替行号",
            ),
            "description": localized_text(
                "Keep alternating line numbers separate from paragraph text.",
                "让交替行号与段落文本保持分离。",
            ),
        },
        "no_remove_non_formula_lines": {
            "label": localized_text(
                "Do not remove non-formula lines",
                "不要移除非公式行",
            ),
            "description": localized_text(
                "Keep non-formula lines inside formula-heavy areas.",
                "保留公式密集区域中的非公式文本行。",
            ),
        },
        "non_formula_line_iou_threshold": {
            "label": localized_text(
                "Non-formula line IoU",
                "非公式行 IoU 阈值",
            ),
            "description": localized_text(
                "IoU threshold used to identify non-formula lines.",
                "用于识别非公式行的 IoU 阈值。",
            ),
        },
        "figure_table_protection_threshold": {
            "label": localized_text(
                "Figure/table protection",
                "图表保护阈值",
            ),
            "description": localized_text(
                "Protection threshold for figures and tables during processing.",
                "处理图表内容时使用的保护阈值。",
            ),
        },
        "skip_formula_offset_calculation": {
            "label": localized_text(
                "Skip formula offset calculation",
                "跳过公式偏移计算",
            ),
            "description": localized_text(
                "Skip formula offset calculation during PDF processing.",
                "在 PDF 处理中跳过公式偏移计算。",
            ),
        },
    },
}

_SERVICE_FIELD_TEXT = {
    "model": {
        "label": localized_text("Model", "模型"),
        "description": localized_text(
            "Model name used by the selected translation service.",
            "所选翻译服务使用的模型名称。",
        ),
    },
    "base_url": {
        "label": localized_text("Base URL", "基础 URL"),
        "description": localized_text(
            "Custom base URL for the selected translation service.",
            "所选翻译服务的自定义基础 URL。",
        ),
    },
    "api_key": {
        "label": localized_text("API key", "API Key"),
        "description": localized_text(
            "Credential used to authenticate the selected translation service.",
            "用于访问所选翻译服务的凭证。",
        ),
    },
    "timeout": {
        "label": localized_text("Timeout (seconds)", "超时时间（秒）"),
        "description": localized_text(
            "Request timeout for the selected translation service.",
            "所选翻译服务的请求超时时间。",
        ),
    },
    "temperature": {
        "label": localized_text("Temperature", "采样温度"),
        "description": localized_text(
            "Sampling temperature used by the selected translation service.",
            "所选翻译服务使用的采样温度。",
        ),
    },
    "reasoning_effort": {
        "label": localized_text("Reasoning effort", "推理强度"),
        "description": localized_text(
            "Reasoning effort level for the selected translation service.",
            "所选翻译服务的推理强度级别。",
        ),
    },
    "enable_json_mode": {
        "label": localized_text("Enable JSON mode", "启用 JSON 模式"),
        "description": localized_text(
            "Ask the selected translation service to respond in JSON mode.",
            "要求所选翻译服务以 JSON 模式响应。",
        ),
    },
    "send_temperature": {
        "label": localized_text("Send temperature", "发送 Temperature 参数"),
        "description": localized_text(
            "Forward the temperature parameter to the selected translation service.",
            "将 Temperature 参数发送给所选翻译服务。",
        ),
    },
    "send_reasoning_effort": {
        "label": localized_text("Send reasoning effort", "发送推理强度参数"),
        "description": localized_text(
            "Forward the reasoning effort parameter to the selected translation service.",
            "将推理强度参数发送给所选翻译服务。",
        ),
    },
    "enable_thinking": {
        "label": localized_text("Enable thinking", "启用思考模式"),
        "description": localized_text(
            "Enable the thinking mode supported by the selected translation service.",
            "启用所选翻译服务支持的思考模式。",
        ),
    },
    "send_enable_thinking_param": {
        "label": localized_text("Send thinking parameter", "发送思考模式参数"),
        "description": localized_text(
            "Forward the thinking-mode parameter to the selected translation service.",
            "将思考模式参数发送给所选翻译服务。",
        ),
    },
    "host": {
        "label": localized_text("Host", "主机地址"),
        "description": localized_text(
            "Host address for the selected translation service.",
            "所选翻译服务的主机地址。",
        ),
    },
    "endpoint": {
        "label": localized_text("Endpoint", "服务终端"),
        "description": localized_text(
            "Endpoint used by the selected translation service.",
            "所选翻译服务使用的终端地址。",
        ),
    },
    "api_version": {
        "label": localized_text("API version", "API 版本"),
        "description": localized_text(
            "API version used for the selected translation service.",
            "所选翻译服务使用的 API 版本。",
        ),
    },
    "auth_key": {
        "label": localized_text("Auth key", "认证密钥"),
        "description": localized_text(
            "Authentication key for the selected translation service.",
            "所选翻译服务的认证密钥。",
        ),
    },
    "secret_id": {
        "label": localized_text("Secret ID", "Secret ID"),
        "description": localized_text(
            "Secret ID for the selected translation service.",
            "所选翻译服务使用的 Secret ID。",
        ),
    },
    "secret_key": {
        "label": localized_text("Secret key", "Secret Key"),
        "description": localized_text(
            "Secret key for the selected translation service.",
            "所选翻译服务使用的 Secret Key。",
        ),
    },
    "url": {
        "label": localized_text("URL", "URL 地址"),
        "description": localized_text(
            "Service URL for the selected translation service.",
            "所选翻译服务的 URL 地址。",
        ),
    },
    "max_predicted_tokens": {
        "label": localized_text("Max predicted tokens", "最大预测 Token 数"),
        "description": localized_text(
            "Maximum number of tokens to predict per request.",
            "每次请求允许预测的最大 Token 数量。",
        ),
    },
    "target_domain": {
        "label": localized_text("Target domain", "目标领域"),
        "description": localized_text(
            "Target domain used to guide the translation style.",
            "用于引导翻译风格的目标领域。",
        ),
    },
    "path": {
        "label": localized_text("CLI path", "CLI 路径"),
        "description": localized_text(
            "Executable path for the selected translation CLI.",
            "所选翻译 CLI 的可执行文件路径。",
        ),
    },
}

_SERVICE_FIELD_NAME_MAP = {
    "num_predict": "max_predicted_tokens",
    "ali_domains": "target_domain",
    "claude_code_path": "path",
}

_SERVICE_FIELD_SUFFIX_MAP = [
    ("_send_enable_thinking_param", "send_enable_thinking_param"),
    ("_send_reasoning_effort", "send_reasoning_effort"),
    ("_send_temperature", "send_temperature"),
    ("_send_temprature", "send_temperature"),
    ("_enable_json_mode", "enable_json_mode"),
    ("_reasoning_effort", "reasoning_effort"),
    ("_enable_thinking", "enable_thinking"),
    ("_base_url", "base_url"),
    ("_api_version", "api_version"),
    ("_api_key", "api_key"),
    ("_apikey", "api_key"),
    ("_auth_key", "auth_key"),
    ("_secret_id", "secret_id"),
    ("_secret_key", "secret_key"),
    ("_timeout", "timeout"),
    ("_temperature", "temperature"),
    ("_endpoint", "endpoint"),
    ("_model", "model"),
    ("_host", "host"),
    ("_url", "url"),
]

_CHOICE_TEXT = {
    "Auto": localized_text("Auto", "自动"),
    "serif": localized_text("Serif", "衬线"),
    "sans-serif": localized_text("Sans-serif", "无衬线"),
    "script": localized_text("Script", "手写 / 斜体"),
    "watermarked": localized_text("Watermarked", "带水印"),
    "no_watermark": localized_text("No watermark", "无水印"),
    "both": localized_text("Both", "同时输出"),
    "minimal": localized_text("Minimal", "最少"),
    "low": localized_text("Low", "低"),
    "medium": localized_text("Medium", "中"),
    "high": localized_text("High", "高"),
}

_LANGUAGE_OVERRIDES = {
    "en": localized_text("English", "英语"),
    "zh-CN": localized_text("Simplified Chinese", "简体中文"),
    "zh-HK": localized_text("Traditional Chinese (Hong Kong)", "繁体中文（香港）"),
    "zh-TW": localized_text("Traditional Chinese (Taiwan)", "繁体中文（台湾）"),
    "pt-BR": localized_text("Brazilian Portuguese", "巴西葡萄牙语"),
    "sr": localized_text("Serbian (Cyrillic)", "塞尔维亚语（西里尔文）"),
    "kk": localized_text("Kazakh (Latin)", "哈萨克语（拉丁文）"),
}


def _language_name_for_code(code: str, en_label: str) -> LocalizedText:
    if code in _LANGUAGE_OVERRIDES:
        return _LANGUAGE_OVERRIDES[code]

    language = langcodes.Language.get(code)
    zh_label = language.display_name("zh")
    return localized_text(en_label, zh_label)


def build_translation_language_options() -> list[dict[str, Any]]:
    return [
        {
            "value": code,
            "label": _language_name_for_code(code, en_label),
        }
        for en_label, code in TRANSLATION_LANGUAGE_MAP.items()
    ]


def localize_field_text(
    section: str,
    field_name: str,
) -> dict[str, LocalizedText]:
    if section in _FIELD_TRANSLATIONS and field_name in _FIELD_TRANSLATIONS[section]:
        return _FIELD_TRANSLATIONS[section][field_name]
    if section != "service":
        raise ValueError(
            f"Missing WebUI translation for {section} field `{field_name}`."
        )

    field_key = _SERVICE_FIELD_NAME_MAP.get(field_name)
    if field_key is None:
        for suffix, candidate_key in _SERVICE_FIELD_SUFFIX_MAP:
            if field_name.endswith(suffix):
                field_key = candidate_key
                break
    if field_key is None or field_key not in _SERVICE_FIELD_TEXT:
        raise ValueError(f"Missing WebUI translation for service field `{field_name}`.")
    return _SERVICE_FIELD_TEXT[field_key]


def localize_choice(value: str) -> LocalizedText:
    if value not in _CHOICE_TEXT:
        raise ValueError(f"Missing WebUI translation for choice `{value}`.")
    return _CHOICE_TEXT[value]
