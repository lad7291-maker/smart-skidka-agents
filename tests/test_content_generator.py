#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для content_generator.py.
Мокают LLM вызовы, тестируют data-классы, парсинг, fallback.
"""

import json
import sys
from datetime import datetime
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.content_generator import (
    BlogArticle,
    Comparison,
    ContentGenerator,
    Guide,
    ProductDescription,
    SEOPage,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════


class TestSEOPage:
    def test_defaults(self):
        page = SEOPage(title="T", meta_description="D", h1="H", content="C", keywords=["k"])
        assert page.title == "T"
        assert page.canonical_url == ""
        assert page.og_tags == {}
        assert page.structured_data == {}


class TestProductDescription:
    def test_defaults(self):
        pd = ProductDescription(title="T", description="D", features=["f"], pros=["p"], cons=["c"])
        assert pd.price_info == ""
        assert pd.where_to_buy == []


class TestComparison:
    def test_defaults(self):
        c = Comparison(title="T", product_a_name="A", product_b_name="B", verdict="V", comparison_table={})
        assert c.winner == ""
        assert c.recommendation == ""


class TestGuide:
    def test_defaults(self):
        g = Guide(title="T", introduction="I", steps=[{"s": "1"}], conclusion="C")
        assert g.tags == []
        assert g.reading_time_min == 0


class TestBlogArticle:
    def test_defaults(self):
        ba = BlogArticle(
            title="T",
            subtitle="S",
            introduction="I",
            sections=[{"h": "H", "b": "B"}],
            conclusion="C",
        )
        assert ba.tags == []
        assert ba.reading_time_min == 0
        assert ba.product_mentions == []
        assert ba.cta_text == ""
        assert ba.featured_image_prompt == ""

    def test_full(self):
        ba = BlogArticle(
            title="Как я купил наушники",
            subtitle="И не пожалел",
            introduction="Всем привет!",
            sections=[{"heading": "Шаг 1", "body": "Выбрал"}],
            conclusion="Рекомендую",
            tags=["наушники", "aliexpress"],
            reading_time_min=5,
            product_mentions=["Беспроводные наушники XY"],
            cta_text="Купи тоже!",
            featured_image_prompt="Наушники на столе",
        )
        assert ba.reading_time_min == 5
        assert ba.cta_text == "Купи тоже!"


# ═══════════════════════════════════════════════════════════════════════════════
# ContentGenerator — парсинг и fallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseJsonResponse:
    def test_plain_json(self):
        gen = ContentGenerator(api_key="test")
        result = gen._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_markdown(self):
        gen = ContentGenerator(api_key="test")
        result = gen._parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_json_embedded_in_text(self):
        gen = ContentGenerator(api_key="test")
        result = gen._parse_json_response('Some text before {"key": "value"} and after')
        assert result == {"key": "value"}

    def test_invalid_json(self):
        gen = ContentGenerator(api_key="test")
        result = gen._parse_json_response("not json at all")
        assert result["parse_error"] is True
        assert "raw_text" in result

    def test_empty_string(self):
        gen = ContentGenerator(api_key="test")
        result = gen._parse_json_response("")
        assert result["parse_error"] is True


class TestFallbackMethods:
    def test_fallback_seo_page(self):
        gen = ContentGenerator(api_key="test")
        result = gen._fallback_seo_page("Смартфоны", ["смартфоны со скидкой"])
        assert result["title"] == "Смартфоны со скидкой до 70% — smart-skidka.ru 2024"
        assert "smart-skidka.ru" in result["meta_description"]
        assert result["_metadata"]["fallback"] is True
        assert "generated_at" in result["_metadata"]

    def test_fallback_product_description(self):
        gen = ContentGenerator(api_key="test")
        product = {"name": "Phone X", "brand": "Brand", "category": "phones", "price": "1000"}
        result = gen._fallback_product_description(product)
        assert result["title"] == "Phone X — обзор и лучшие цены"
        assert "Brand" in result["description"]
        assert result["_metadata"]["fallback"] is True

    def test_fallback_comparison(self):
        gen = ContentGenerator(api_key="test")
        product_a = {"name": "Phone A", "specs": {"price": "100"}}
        product_b = {"name": "Phone B", "specs": {"price": "200"}}
        result = gen._fallback_comparison(product_a, product_b, ["price"])
        assert result["product_a_name"] == "Phone A"
        assert result["product_b_name"] == "Phone B"
        assert result["_metadata"]["fallback"] is True
        assert "comparison_table" in result

    def test_fallback_guide(self):
        gen = ContentGenerator(api_key="test")
        result = gen._fallback_guide("Как выбрать телефон", ["Step 1", "Step 2"])
        assert "Как выбрать телефон" in result["title"]
        assert len(result["steps"]) == 2
        assert result["_metadata"]["fallback"] is True

    def test_fallback_blog_article(self):
        gen = ContentGenerator(api_key="test")
        product = {
            "title": "Беспроводные наушники",
            "category": "электроника",
            "price": 1500,
            "original_price": 3000,
            "discount": 50,
        }
        result = gen._fallback_blog_article(product, angle="story")
        assert result["title"] == "Как я купил Беспроводные наушники и не пожалел"
        assert "smart-skidka.ru" in result["introduction"]
        assert len(result["sections"]) == 4
        assert result["_metadata"]["fallback"] is True
        assert result["_metadata"]["content_type"] == "blog_article"

    def test_fallback_blog_article_minimal(self):
        gen = ContentGenerator(api_key="test")
        result = gen._fallback_blog_article({"title": "X"}, angle="review")
        assert result["product_mentions"] == ["X"]
        assert result["reading_time_min"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# ContentGenerator — async с моком LLM
# ═══════════════════════════════════════════════════════════════════════════════


import pytest


class TestGenerateSEOPage:
    @pytest.mark.asyncio
    async def test_success(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {
            "content": json.dumps(
                {
                    "title": "Best Phones",
                    "meta_description": "Great phones",
                    "h1": "Phones",
                    "content": "Buy phones",
                    "keywords": ["phones"],
                    "canonical_url": "https://example.com/phones",
                    "og_tags": {"og:title": "Phones"},
                }
            )
        }
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            result = await gen.generate_seo_page("Phones", ["phones"])
        assert result["title"] == "Best Phones"
        assert "_metadata" in result
        assert result["_metadata"]["content_type"] == "seo_page"

    @pytest.mark.asyncio
    async def test_llm_error_uses_fallback(self):
        gen = ContentGenerator(api_key="test")
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value={"error": "timeout"}):
            result = await gen.generate_seo_page("Phones", ["phones"])
        assert result["_metadata"]["fallback"] is True

    @pytest.mark.asyncio
    async def test_parse_error_uses_fallback(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {"content": "not valid json"}
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            result = await gen.generate_seo_page("Phones", ["phones"])
        assert result["_metadata"]["fallback"] is True


class TestGenerateProductDescription:
    @pytest.mark.asyncio
    async def test_success(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {
            "content": json.dumps(
                {
                    "title": "Phone X",
                    "description": "Great phone",
                    "features": ["Fast"],
                    "pros": ["Good"],
                    "cons": ["Expensive"],
                }
            )
        }
        product = {"name": "Phone X", "brand": "X", "category": "phones"}
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            result = await gen.generate_product_description(product)
        assert result["title"] == "Phone X"

    @pytest.mark.asyncio
    async def test_fallback(self):
        gen = ContentGenerator(api_key="test")
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value={"error": "fail"}):
            result = await gen.generate_product_description({"name": "X"})
        assert result["_metadata"]["fallback"] is True


class TestGenerateComparison:
    @pytest.mark.asyncio
    async def test_success(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {
            "content": json.dumps(
                {
                    "title": "A vs B",
                    "product_a_name": "A",
                    "product_b_name": "B",
                    "verdict": "A wins",
                    "comparison_table": {"price": {"A": "100", "B": "200"}},
                }
            )
        }
        product_a = {"name": "A"}
        product_b = {"name": "B"}
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            result = await gen.generate_comparison(product_a, product_b, ["price"])
        assert result["verdict"] == "A wins"

    @pytest.mark.asyncio
    async def test_fallback(self):
        gen = ContentGenerator(api_key="test")
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value={"error": "fail"}):
            result = await gen.generate_comparison({"name": "A"}, {"name": "B"}, ["price"])
        assert result["_metadata"]["fallback"] is True


class TestGenerateGuide:
    @pytest.mark.asyncio
    async def test_success(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {
            "content": json.dumps(
                {
                    "title": "Guide",
                    "introduction": "Intro",
                    "steps": [{"title": "Step 1", "content": "Do this"}],
                    "conclusion": "Done",
                    "tags": ["tag"],
                    "reading_time_min": 5,
                }
            )
        }
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            result = await gen.generate_guide("How to", "phones")
        assert result["title"] == "Guide"
        assert result["reading_time_min"] >= 1

    @pytest.mark.asyncio
    async def test_fallback(self):
        gen = ContentGenerator(api_key="test")
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value={"error": "fail"}):
            result = await gen.generate_guide("How to", "phones")
        assert result["_metadata"]["fallback"] is True


class TestGenerateBlogArticle:
    @pytest.mark.asyncio
    async def test_success(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {
            "content": json.dumps(
                {
                    "title": "Как я купил наушники",
                    "subtitle": "И не пожалел",
                    "introduction": "Всем привет!",
                    "sections": [{"heading": "Шаг 1", "body": "Выбрал"}],
                    "conclusion": "Рекомендую",
                    "tags": ["наушники"],
                    "product_mentions": ["Наушники XY"],
                    "cta_text": "Купи!",
                    "featured_image_prompt": "Фото наушников",
                }
            )
        }
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            product = {"title": "Наушники XY", "category": "электроника", "price": 1000}
            result = await gen.generate_blog_article(product, angle="story", tone="friendly")
        assert result["title"] == "Как я купил наушники"
        assert result["_metadata"]["content_type"] == "blog_article"
        assert result["reading_time_min"] >= 1

    @pytest.mark.asyncio
    async def test_llm_error_uses_fallback(self):
        gen = ContentGenerator(api_key="test")
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value={"error": "timeout"}):
            product = {"title": "Тест", "category": "тест"}
            result = await gen.generate_blog_article(product)
        assert result["_metadata"]["fallback"] is True

    @pytest.mark.asyncio
    async def test_invalid_json_uses_fallback(self):
        gen = ContentGenerator(api_key="test")
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value={"content": "not json"}):
            product = {"title": "Тест", "category": "тест"}
            result = await gen.generate_blog_article(product)
        assert result["_metadata"]["fallback"] is True

    @pytest.mark.asyncio
    async def test_different_angles(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {
            "content": json.dumps(
                {
                    "title": "T",
                    "subtitle": "S",
                    "introduction": "I",
                    "sections": [{"heading": "H", "body": "B"}],
                    "conclusion": "C",
                    "tags": ["t"],
                    "product_mentions": ["P"],
                    "cta_text": "CTA",
                    "featured_image_prompt": "IMG",
                }
            )
        }
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            product = {"title": "P", "category": "c"}
            for angle in ["story", "review", "howto", "comparison"]:
                result = await gen.generate_blog_article(product, angle=angle, tone="expert")
                assert result["_metadata"]["angle"] == angle

    @pytest.mark.asyncio
    async def test_different_tones(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {
            "content": json.dumps(
                {
                    "title": "T",
                    "subtitle": "S",
                    "introduction": "I",
                    "sections": [{"heading": "H", "body": "B"}],
                    "conclusion": "C",
                    "tags": ["t"],
                    "product_mentions": ["P"],
                    "cta_text": "CTA",
                    "featured_image_prompt": "IMG",
                }
            )
        }
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            product = {"title": "P", "category": "c"}
            for tone in ["friendly", "expert", "humorous"]:
                result = await gen.generate_blog_article(product, tone=tone)
                assert result["_metadata"]["tone"] == tone


class TestBatchGenerate:
    @pytest.mark.asyncio
    async def test_batch_generate(self):
        gen = ContentGenerator(api_key="test")
        mock_response = {
            "content": json.dumps(
                {
                    "title": "Phone",
                    "description": "Desc",
                    "features": ["F"],
                    "pros": ["P"],
                    "cons": ["C"],
                }
            )
        }
        with patch.object(gen, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            results = await gen.batch_generate(
                count=2,
                content_type="product_description",
                params={"items": [{"name": "A"}, {"name": "B"}]},
            )
        assert len(results) == 2
        assert all("_metadata" in r for r in results)

    @pytest.mark.asyncio
    async def test_batch_generate_empty(self):
        gen = ContentGenerator(api_key="test")
        results = await gen.batch_generate(count=0, content_type="product_description")
        assert results == []


class TestInit:
    def test_api_key_from_env(self):
        with patch.dict("os.environ", {"LLM_API_KEY": "env-key"}, clear=False):
            gen = ContentGenerator()
            assert gen.api_key == "env-key"

    def test_api_key_from_arg(self):
        gen = ContentGenerator(api_key="arg-key")
        assert gen.api_key == "arg-key"

    def test_model_rrouter(self):
        gen = ContentGenerator(api_key="test", model="rrouter/test")
        assert "rrouter" in gen.base_url

    def test_model_anthropic(self):
        gen = ContentGenerator(api_key="test", model="anthropic/claude")
        assert "rrouter" in gen.base_url

    def test_model_deepseek(self):
        gen = ContentGenerator(api_key="test", model="deepseek-chat")
        assert "deepseek" in gen.base_url

    def test_no_api_key_warning(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("scripts.content_generator.logger") as mock_logger:
                gen = ContentGenerator()
                mock_logger.warning.assert_called_once()
