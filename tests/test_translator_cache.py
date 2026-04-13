from __future__ import annotations

import json
from unittest.mock import Mock

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.translator.translator_impl.google import GoogleTranslator


def _google_settings(
    *, translation: dict | None = None, google_detail: dict | None = None
):
    return CLIEnvSettingsModel(
        google=True,
        translation=translation or {},
        google_detail=google_detail or {},
    ).to_settings_model()


def test_google_cache_key_includes_global_semantic_inputs(tmp_path):
    glossary_path = tmp_path / "terms.csv"
    glossary_path.write_text("source,target\naccuracy,准确度\n", encoding="utf-8")

    baseline = GoogleTranslator(
        _google_settings(
            translation={
                "custom_system_prompt": "Prompt A",
                "glossaries": str(glossary_path),
            }
        ),
        Mock(),
    )
    changed_prompt = GoogleTranslator(
        _google_settings(
            translation={
                "custom_system_prompt": "Prompt B",
                "glossaries": str(glossary_path),
            }
        ),
        Mock(),
    )

    baseline_params = json.loads(baseline.cache.translate_engine_params)
    changed_prompt_params = json.loads(changed_prompt.cache.translate_engine_params)

    assert baseline_params["custom_system_prompt"] == "Prompt A"
    assert "glossaries" in baseline_params
    assert changed_prompt_params["custom_system_prompt"] == "Prompt B"
    assert (
        baseline.cache.translate_engine_params
        != changed_prompt.cache.translate_engine_params
    )


def test_google_cache_key_ignores_timeout_but_tracks_glossary_content(tmp_path):
    first_glossary = tmp_path / "terms-a.csv"
    first_glossary.write_text("source,target\naccuracy,准确度\n", encoding="utf-8")
    second_glossary = tmp_path / "terms-b.csv"
    second_glossary.write_text("source,target\naccuracy,精度\n", encoding="utf-8")

    first = GoogleTranslator(
        _google_settings(
            translation={"glossaries": str(first_glossary)},
            google_detail={"google_timeout": "20"},
        ),
        Mock(),
    )
    second = GoogleTranslator(
        _google_settings(
            translation={"glossaries": str(first_glossary)},
            google_detail={"google_timeout": "45"},
        ),
        Mock(),
    )
    changed_glossary = GoogleTranslator(
        _google_settings(
            translation={"glossaries": str(second_glossary)},
            google_detail={"google_timeout": "20"},
        ),
        Mock(),
    )

    assert first.cache.translate_engine_params == second.cache.translate_engine_params
    assert (
        first.cache.translate_engine_params
        != changed_glossary.cache.translate_engine_params
    )
