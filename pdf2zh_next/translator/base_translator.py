import contextlib
import hashlib
import json
import logging
import re
from abc import ABC
from abc import abstractmethod
from pathlib import Path

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.translator.base_rate_limiter import BaseRateLimiter
from pdf2zh_next.translator.cache import TranslationCache

logger = logging.getLogger(__name__)


def _glossary_cache_digest(glossaries: str | None) -> str | None:
    if not glossaries:
        return None

    entries = []
    for raw_value in glossaries.split(","):
        normalized = raw_value.strip()
        if not normalized:
            continue

        glossary_path = Path(normalized).expanduser()
        if not glossary_path.exists() or not glossary_path.is_file():
            entries.append({"path": normalized, "missing": True})
            continue

        try:
            content_digest = hashlib.sha256(glossary_path.read_bytes()).hexdigest()
        except OSError:
            entries.append({"path": str(glossary_path.resolve()), "unreadable": True})
            continue

        stat = glossary_path.stat()
        entries.append(
            {
                "path": str(glossary_path.resolve()),
                "sha256": content_digest,
                "size": stat.st_size,
            }
        )

    if not entries:
        return None

    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class BaseTranslator(ABC):
    # Due to cache limitations, name should be within 20 characters.
    # cache.py: translate_engine = CharField(max_length=20)
    """translator 的基类，所有的 translator 的实现都需要继承"""

    name = "base"
    lang_map = {}

    def __init__(
        self,
        settings: SettingsModel,
        rate_limiter: BaseRateLimiter,
    ):
        """
        translator class initialization
        :param settings: runtime setting and configuration
        :param rate_limiter: LLM request rate control
        :return: None
        """
        self.ignore_cache = settings.translation.ignore_cache
        lang_in = self.lang_map.get(
            settings.translation.lang_in.lower(), settings.translation.lang_in
        )
        lang_out = self.lang_map.get(
            settings.translation.lang_out.lower(), settings.translation.lang_out
        )
        self.lang_in = lang_in
        self.lang_out = lang_out
        self.rate_limiter = rate_limiter

        self.cache = TranslationCache(
            self.name,
            {
                "lang_in": lang_in,
                "lang_out": lang_out,
            },
        )
        self.add_cache_impact_parameters(
            "custom_system_prompt",
            settings.translation.custom_system_prompt or None,
        )
        self.add_cache_impact_parameters(
            "no_auto_extract_glossary",
            settings.translation.no_auto_extract_glossary,
        )
        glossary_digest = _glossary_cache_digest(settings.translation.glossaries)
        if glossary_digest is not None:
            self.add_cache_impact_parameters("glossaries", glossary_digest)

        self.translate_call_count = 0
        self.translate_cache_call_count = 0

    def __del__(self):
        with contextlib.suppress(Exception):
            logger.info(
                f"{self.name} translate call count: {self.translate_call_count}"
            )
            logger.info(
                f"{self.name} translate cache call count: {self.translate_cache_call_count}",
            )

    def add_cache_impact_parameters(self, k: str, v):
        """
        Add parameters that affect the translation quality to distinguish the translation effects under different parameters.
        :param k: key
        :param v: value
        """
        self.cache.add_params(k, v)

    def translate(self, text, ignore_cache=False, rate_limit_params: dict = None):
        """
        Translate the text, and the other part should call this method.
        :param text: text to translate
        :return: translated text
        """
        self.translate_call_count += 1
        if not (self.ignore_cache or ignore_cache):
            try:
                cache = self.cache.get(text)
                if cache is not None:
                    self.translate_cache_call_count += 1
                    return cache
            except Exception as e:
                logger.debug(f"try get cache failed, ignore it: {e}")
        self.rate_limiter.wait(rate_limit_params)
        translation = self.do_translate(text, rate_limit_params)
        if not (self.ignore_cache or ignore_cache):
            self.cache.set(text, translation)
        return translation

    def llm_translate(self, text, ignore_cache=False, rate_limit_params: dict = None):
        """
        Translate the text, and the other part should call this method.
        :param text: text to translate
        :return: translated text
        """
        self.translate_call_count += 1
        if not (self.ignore_cache or ignore_cache):
            try:
                cache = self.cache.get(text)
                if cache is not None:
                    self.translate_cache_call_count += 1
                    return cache
            except Exception as e:
                logger.debug(f"try get cache failed, ignore it: {e}")
        self.rate_limiter.wait(rate_limit_params)
        translation = self.do_llm_translate(text, rate_limit_params)
        if not (self.ignore_cache or ignore_cache):
            self.cache.set(text, translation)
        return translation

    def do_llm_translate(self, text, rate_limit_params: dict = None):
        """
        Actual translate text, override this method
        :param text: text to translate
        :return: translated text
        """
        raise NotImplementedError

    @abstractmethod
    def do_translate(self, text, rate_limit_params: dict = None):
        """
        Actual translate text, override this method
        :param text: text to translate
        :return: translated text
        """
        logger.critical(
            f"Do not call BaseTranslator.do_translate. "
            f"Translator: {self}. "
            f"Text: {text}. ",
        )
        raise NotImplementedError

    def _remove_cot_content(self, content: str) -> str:
        """Remove text content with the thought chain from the chat response

        :param content: Non-streaming text content
        :return: Text without a thought chain
        """
        return re.sub(r"^<think>.+?</think>", "", content, count=1, flags=re.DOTALL)

    def __str__(self):
        """
        get translator's info
        """
        return f"{self.name} {self.lang_in} {self.lang_out} {self.model}"

    def get_formular_placeholder(self, placeholder_id: int):
        """
        get formular placeholder
        LLM translator use placeholder to skip the formular char
        :param placeholder_id: placeholder id
        :return formated placeholder and regex placeholder
        """
        return "{v" + str(placeholder_id) + "}", f"{{\\s*v\\s*{placeholder_id}\\s*}}"

    def get_rich_text_left_placeholder(self, placeholder_id: int):
        """
        get rich text placeholder
        :param placeholder_id: placeholder id
        :return the start label of rich text and regex start label
        """
        return (
            f"<style id='{placeholder_id}'>",
            f"<\\s*style\\s*id\\s*=\\s*'\\s*{placeholder_id}\\s*'\\s*>",
        )

    def get_rich_text_right_placeholder(self, placeholder_id: int):
        """
        get rich text placeholder
        :return the end label of rich text and regex end label
        """
        return "</style>", r"<\s*\/\s*style\s*>"

    def prompt(self, text):
        """
        concatent the prompt
        :param text: input text
        :return: the whole prompt for LLM translator
        """
        return [
            {
                "role": "user",
                "content": f"You are a professional,authentic machine translation engine.\n\n;; Treat next line as plain text input and translate it into {self.lang_out}, output translation ONLY. If translation is unnecessary (e.g. proper nouns, codes, {'{{1}}, etc. '}), return the original text. NO explanations. NO notes. Input:\n\n{text}",
            },
        ]
