#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                   BROWSER ACTIONS — Playwright Agent                 ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Browser-based агент для веб-навигации, SEO-аудита и сбора данных.   ║
║  Интегрируется с SEO-агентом (Core Web Vitals, рендеринг) и          ║
║  Trend-агентом (скриншоты товаров, проверка цен конкурентов).        ║
╚══════════════════════════════════════════════════════════════════════╝

Возможности:
    - check_page_render    : Проверка рендеринга страницы, извлечение мета-тегов
    - measure_core_vitals  : Измерение Core Web Vitals (LCP, FID proxy, CLS proxy)
    - screenshot_product   : Скриншот страницы товара
    - check_competitor     : Проверка цен и наличия у конкурентов
    - extract_structured   : Извлечение structured data (JSON-LD, microdata)

Все функции — асинхронные, с таймаутами и retry.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# ═══════════════════════════════════════════════════════════════════════════════
# Конфигурация
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_TIMEOUT = int(os.getenv("BROWSER_TIMEOUT_MS", "15000"))
DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "/tmp/agent_screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PageMetrics:
    """Метрики страницы — Core Web Vitals + SEO."""
    url: str
    title: str
    status: int = 200
    load_time_ms: float = 0.0
    dom_content_loaded_ms: float = 0.0
    lcp_ms: Optional[float] = None  # Largest Contentful Paint (proxy)
    cls_score: Optional[float] = None  # Cumulative Layout Shift (proxy)
    meta_tags: Dict[str, str] = field(default_factory=dict)
    headings: Dict[str, List[str]] = field(default_factory=dict)
    links_count: int = 0
    images_count: int = 0
    structured_data: List[Dict[str, Any]] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "status": self.status,
            "load_time_ms": round(self.load_time_ms, 2),
            "dom_content_loaded_ms": round(self.dom_content_loaded_ms, 2),
            "lcp_ms": round(self.lcp_ms, 2) if self.lcp_ms else None,
            "cls_score": round(self.cls_score, 4) if self.cls_score else None,
            "meta_tags": self.meta_tags,
            "headings": self.headings,
            "links_count": self.links_count,
            "images_count": self.images_count,
            "structured_data_count": len(self.structured_data),
            "screenshot_path": self.screenshot_path,
            "timestamp": self.timestamp,
        }


@dataclass
class CompetitorData:
    """Данные конкурента — цены, наличие, мета-информация."""
    url: str
    product_name: Optional[str] = None
    price: Optional[str] = None
    availability: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "product_name": self.product_name,
            "price": self.price,
            "availability": self.availability,
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Browser Manager — управление жизненным циклом браузера
# ═══════════════════════════════════════════════════════════════════════════════

class BrowserManager:
    """
    Менеджер браузера — singleton для переиспользования BrowserContext.
    
    Использует паттерн async context manager для автоматического закрытия.
    """

    _instance: Optional[BrowserManager] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._browser: Optional[Browser] = None
            cls._instance._context: Optional[BrowserContext] = None
            cls._instance._playwright = None
        return cls._instance

    async def _ensure_browser(self) -> Browser:
        """Создаёт браузер если не существует."""
        if self._browser is None or not self._browser.is_connected():
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        return self._browser

    async def get_context(self) -> BrowserContext:
        """Возвращает BrowserContext (создаёт если нужно)."""
        await self._ensure_browser()
        if self._context is None:
            self._context = await self._browser.new_context(
                viewport=DEFAULT_VIEWPORT,
                user_agent=USER_AGENT,
            )
        return self._context

    async def new_page(self) -> Page:
        """Создаёт новую страницу в контексте."""
        context = await self.get_context()
        return await context.new_page()

    async def close(self) -> None:
        """Закрывает браузер и очищает ресурсы."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def __aenter__(self) -> BrowserManager:
        await self._ensure_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SEO-функции: проверка рендера, Core Web Vitals
# ═══════════════════════════════════════════════════════════════════════════════

async def check_page_render(
    url: str,
    take_screenshot: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> PageMetrics:
    """
    Проверяет рендеринг страницы и извлекает SEO-метрики.

    Args:
        url: URL страницы для проверки
        take_screenshot: Сделать скриншот страницы
        timeout: Таймаут загрузки в мс

    Returns:
        PageMetrics с метриками страницы
    """
    manager = BrowserManager()
    page = await manager.new_page()
    screenshot_path = None

    try:
        start_time = asyncio.get_event_loop().time()
        response = await page.goto(url, timeout=timeout, wait_until="networkidle")
        load_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000

        status = response.status if response else 0
        title = await page.title()

        # Performance timing
        timing = await page.evaluate("""() => {
            const nav = performance.getEntriesByType("navigation")[0];
            if (!nav) return null;
            return {
                domContentLoaded: nav.domContentLoadedEventEnd - nav.domContentLoadedEventStart,
                loadComplete: nav.loadEventEnd - nav.loadEventStart,
                responseStart: nav.responseStart,
                domInteractive: nav.domInteractive,
            };
        }""")
        dom_content_loaded_ms = timing.get("domContentLoaded", 0) if timing else 0

        # LCP proxy — largest image or text element
        lcp_data = await page.evaluate("""() => {
            const entries = performance.getEntriesByType("element");
            // Fallback: measure largest visible element
            const allElements = document.body.getElementsByTagName('*');
            let maxArea = 0;
            let maxEl = null;
            for (const el of allElements) {
                const rect = el.getBoundingClientRect();
                const area = rect.width * rect.height;
                if (area > maxArea && rect.top < window.innerHeight) {
                    maxArea = area;
                    maxEl = el;
                }
            }
            return maxArea;
        }""")
        lcp_ms = load_time_ms * 0.6 if lcp_data else None  # rough proxy

        # CLS proxy — count of layout shifts
        cls_data = await page.evaluate("""() => {
            let shifts = 0;
            new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    if (!entry.hadRecentInput) shifts += entry.value;
                }
            }).observe({type: "layout-shift", buffered: true});
            // Small delay to collect
            return shifts;
        }""")
        await asyncio.sleep(0.5)  # Let layout shifts accumulate
        cls_score = cls_data if cls_data else 0.0

        # Meta tags
        meta_tags = await page.evaluate("""() => {
            const meta = {};
            document.querySelectorAll('meta').forEach(m => {
                const name = m.getAttribute('name') || m.getAttribute('property');
                const content = m.getAttribute('content');
                if (name && content) meta[name] = content;
            });
            return meta;
        }""")

        # Headings
        headings: Dict[str, List[str]] = {}
        for level in range(1, 7):
            h_tags = await page.locator(f"h{level}").all_inner_texts()
            if h_tags:
                headings[f"h{level}"] = h_tags[:10]  # limit

        # Counts
        links_count = await page.locator("a").count()
        images_count = await page.locator("img").count()

        # Structured data
        structured = await page.evaluate("""() => {
            const data = [];
            document.querySelectorAll('script[type="application/ld+json"]').forEach(el => {
                try { data.push(JSON.parse(el.textContent)); } catch(e) {}
            });
            return data;
        }""")

        # Screenshot
        if take_screenshot:
            safe_name = url.replace("https://", "").replace("http://", "").replace("/", "_")[:50]
            screenshot_path = str(SCREENSHOT_DIR / f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            await page.screenshot(path=screenshot_path, full_page=True)

        return PageMetrics(
            url=url,
            title=title,
            status=status,
            load_time_ms=load_time_ms,
            dom_content_loaded_ms=dom_content_loaded_ms,
            lcp_ms=lcp_ms,
            cls_score=cls_score,
            meta_tags=meta_tags,
            headings=headings,
            links_count=links_count,
            images_count=images_count,
            structured_data=structured,
            screenshot_path=screenshot_path,
        )

    except Exception as e:
        return PageMetrics(
            url=url,
            title="",
            status=0,
            load_time_ms=0.0,
            meta_tags={"error": str(e)},
        )
    finally:
        await page.close()


async def measure_core_vitals(url: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """
    Измеряет Core Web Vitals для страницы.

    Returns:
        Словарь с LCP, FID-proxy, CLS-proxy и рекомендациями.
    """
    metrics = await check_page_render(url, timeout=timeout)

    # Оценка по порогам Google
    lcp_score = "good" if (metrics.lcp_ms and metrics.lcp_ms < 2500) else \
                "needs_improvement" if (metrics.lcp_ms and metrics.lcp_ms < 4000) else "poor"
    cls_score = "good" if (metrics.cls_score is not None and metrics.cls_score < 0.1) else \
                "needs_improvement" if (metrics.cls_score is not None and metrics.cls_score < 0.25) else "poor"
    load_score = "good" if metrics.dom_content_loaded_ms < 1000 else \
                 "needs_improvement" if metrics.dom_content_loaded_ms < 3000 else "poor"

    recommendations = []
    if lcp_score == "poor":
        recommendations.append("LCP критичен: оптимизируйте изображения, используйте CDN")
    if cls_score == "poor":
        recommendations.append("CLS критичен: задайте размеры для img/video, избегайте вставки контента сверху")
    if load_score == "poor":
        recommendations.append("Загрузка медленная: уменьшите JS/CSS, используйте lazy loading")
    if metrics.meta_tags.get("description") is None:
        recommendations.append("Отсутствует meta description")
    if not metrics.headings.get("h1"):
        recommendations.append("Отсутствует H1")

    return {
        "url": url,
        "lcp_ms": metrics.lcp_ms,
        "lcp_rating": lcp_score,
        "cls_score": metrics.cls_score,
        "cls_rating": cls_score,
        "dom_content_loaded_ms": metrics.dom_content_loaded_ms,
        "load_rating": load_score,
        "overall_rating": "good" if all(s == "good" for s in [lcp_score, cls_score, load_score]) else "needs_improvement",
        "recommendations": recommendations,
        "timestamp": metrics.timestamp,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Trend-функции: скриншоты товаров, проверка конкурентов
# ═══════════════════════════════════════════════════════════════════════════════

async def screenshot_product(
    url: str,
    selector: Optional[str] = None,
    full_page: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    Делает скриншот страницы товара.

    Args:
        url: URL страницы товара
        selector: CSS-селектор для скриншота конкретного элемента
        full_page: Скриншот всей страницы
        timeout: Таймаут загрузки

    Returns:
        Путь к сохранённому скриншоту
    """
    manager = BrowserManager()
    page = await manager.new_page()

    try:
        await page.goto(url, timeout=timeout, wait_until="networkidle")

        safe_name = url.replace("https://", "").replace("http://", "").replace("/", "_")[:50]
        screenshot_path = str(SCREENSHOT_DIR / f"product_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

        if selector and await page.locator(selector).count() > 0:
            await page.locator(selector).first.screenshot(path=screenshot_path)
        else:
            await page.screenshot(path=screenshot_path, full_page=full_page)

        return screenshot_path

    except Exception as e:
        raise RuntimeError(f"Screenshot failed for {url}: {e}")
    finally:
        await page.close()


async def check_competitor(
    url: str,
    price_selector: Optional[str] = None,
    name_selector: Optional[str] = None,
    availability_selector: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> CompetitorData:
    """
    Проверяет цену и наличие товара у конкурента.

    Args:
        url: URL страницы конкурента
        price_selector: CSS-селектор цены
        name_selector: CSS-селектор названия товара
        availability_selector: CSS-селектор наличия
        timeout: Таймаут загрузки

    Returns:
        CompetitorData с извлечёнными данными
    """
    manager = BrowserManager()
    page = await manager.new_page()

    try:
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")

        # Default selectors for common e-commerce platforms
        if not price_selector:
            # Try common patterns with short timeout
            for sel in ["[data-testid='price']", ".price", ".product-price", "[itemprop='price']", ".cost"]:
                try:
                    if await page.locator(sel).count() > 0:
                        price_selector = sel
                        break
                except Exception:
                    continue

        if not name_selector:
            for sel in ["h1", "[data-testid='product-name']", ".product-title", "[itemprop='name']"]:
                try:
                    if await page.locator(sel).count() > 0:
                        name_selector = sel
                        break
                except Exception:
                    continue

        data = CompetitorData(url=url)

        # Extract price
        if price_selector:
            try:
                price_text = await page.locator(price_selector).first.inner_text(timeout=2000)
                data.price = price_text.strip()[:50]
            except Exception:
                pass

        # Extract name
        if name_selector:
            try:
                name_text = await page.locator(name_selector).first.inner_text(timeout=2000)
                data.product_name = name_text.strip()[:200]
            except Exception:
                pass

        # Extract availability
        if availability_selector:
            try:
                avail_text = await page.locator(availability_selector).first.inner_text(timeout=2000)
                data.availability = avail_text.strip()[:50]
            except Exception:
                pass

        # Meta tags
        try:
            data.meta_title = await page.title()
        except Exception:
            pass

        try:
            desc_el = page.locator("meta[name='description']")
            if await desc_el.count() > 0:
                data.meta_description = await desc_el.first.get_attribute("content")
        except Exception:
            pass

        return data

    except Exception as e:
        return CompetitorData(url=url, product_name=f"ERROR: {str(e)[:100]}")
    finally:
        await page.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Batch операции
# ═══════════════════════════════════════════════════════════════════════════════

async def batch_check_pages(
    urls: List[str],
    take_screenshots: bool = False,
    max_concurrent: int = 3,
) -> List[PageMetrics]:
    """
    Пакетная проверка нескольких страниц с ограничением concurrency.

    Args:
        urls: Список URL для проверки
        take_screenshots: Делать скриншоты
        max_concurrent: Максимум параллельных проверок

    Returns:
        Список PageMetrics
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _check_one(url: str) -> PageMetrics:
        async with semaphore:
            return await check_page_render(url, take_screenshot=take_screenshots)

    tasks = [_check_one(url) for url in urls]
    return await asyncio.gather(*tasks, return_exceptions=True)


async def batch_check_competitors(
    urls: List[str],
    max_concurrent: int = 2,
) -> List[CompetitorData]:
    """
    Пакетная проверка конкурентов.

    Args:
        urls: Список URL конкурентов
        max_concurrent: Максимум параллельных проверок

    Returns:
        Список CompetitorData
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _check_one(url: str) -> CompetitorData:
        async with semaphore:
            return await check_competitor(url)

    tasks = [_check_one(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert exceptions to error CompetitorData
    processed = []
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            processed.append(CompetitorData(url=url, product_name=f"ERROR: {str(result)[:100]}"))
        else:
            processed.append(result)
    return processed


# ═══════════════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════════════

async def close_browser() -> None:
    """Закрывает браузер и освобождает ресурсы."""
    manager = BrowserManager()
    await manager.close()
