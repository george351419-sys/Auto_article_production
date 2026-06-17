"""Unit tests for the final_package shape validator (P3)."""
from __future__ import annotations

import pytest

import final_package_validator as v

pytestmark = pytest.mark.M2


def _valid_pkg() -> dict:
    return {
        "platforms": [
            {
                "platform": "wechat",
                "titles": ["A great title"],
                "formattedArticle": "# Headline\n\nBody copy.",
                "summary": "summary",
                "tags": ["ai"],
            },
        ],
        "createdAt": "2026-06-17T00:00:00Z",
    }


def test_valid_package_returns_no_issues():
    assert v.validate_final_package(_valid_pkg()) == []


def test_non_dict_root_is_rejected():
    issues = v.validate_final_package("not a dict")  # type: ignore[arg-type]
    assert issues and "expected dict" in issues[0]


def test_missing_platforms_is_rejected():
    pkg = _valid_pkg()
    del pkg["platforms"]
    issues = v.validate_final_package(pkg)
    assert issues == ["final_package.platforms: missing or empty"]


def test_empty_platforms_list_is_rejected():
    issues = v.validate_final_package({"platforms": []})
    assert issues == ["final_package.platforms: missing or empty"]


def test_platform_without_platform_field_is_flagged():
    pkg = {"platforms": [{"titles": ["t"], "formattedArticle": "body"}]}
    issues = v.validate_final_package(pkg)
    assert any("platform: missing" in i for i in issues)


def test_platform_without_title_is_flagged():
    pkg = _valid_pkg()
    pkg["platforms"][0]["titles"] = []
    issues = v.validate_final_package(pkg)
    assert any("no usable title" in i for i in issues)


def test_platform_with_string_title_is_accepted():
    pkg = _valid_pkg()
    pkg["platforms"][0]["titles"] = "A single title string"
    assert v.validate_final_package(pkg) == []


def test_platform_without_body_is_flagged():
    pkg = _valid_pkg()
    pkg["platforms"][0]["formattedArticle"] = ""
    issues = v.validate_final_package(pkg)
    assert any("empty body" in i for i in issues)


def test_snake_case_body_alias_accepted():
    pkg = _valid_pkg()
    pkg["platforms"][0].pop("formattedArticle")
    pkg["platforms"][0]["formatted_article"] = "snake-cased body"
    assert v.validate_final_package(pkg) == []


def test_unrecognised_only_platforms_is_flagged():
    pkg = {
        "platforms": [
            {"platform": "douyin", "titles": ["t"], "formattedArticle": "body"}
        ]
    }
    issues = v.validate_final_package(pkg)
    assert any("none of the platforms match" in i for i in issues)
