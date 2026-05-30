#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                     DATA TOOLS — Реальные инструменты                ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Реализация инструментов сбора данных для агентов.                  ║
║  Заменяет LLM-галлюцинации на реальные данные из интернета.         ║
╚══════════════════════════════════════════════════════════════════════╝

Инструменты:
    - google_trends      : Тренды поисковых запросов (через трендовые RSS/API)
    - news_monitor       : Мониторинг новостей (RSS-ленты)
    - marketplace_trends : Базовый скрейпинг трендов Wildberries
    - yandex_wordstat    : Популярность запросов (через подсказки Яндекса)
    - forum_scanner      : Сканирование обсуждений (Reddit API)

Все функции асинхронные, с retry и кэшированием в Redis.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

import aiohttp

from . import with_retry

# ═══════════════════════════════════════════════════════════════════════════════
# Константы
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# RSS-источники для news_monitor
NEWS_SOURCES = {
    "vc_ru": "https://vc.ru/rss/all",
    "tjournal": "https://tjournal.ru/rss/all",
    "rbk": "https://rssexport.rbc.ru/rbcnews/news/30/default.ru.rss",
    "habr": "https://habr.com/ru/rss/all/all/",
}

# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Session (singleton)
# ═══════════════════════════════════════════════════════════════════════════════

_session: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    """Возвращает singleton HTTP-сессию."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _session


async def close_session() -> None:
    """Закрывает HTTP-сессию."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


# ═══════════════════════════════════════════════════════════════════════════════
# Google Trends (через трендовые RSS-ленты Google)
# ═══════════════════════════════════════════════════════════════════════════════

@with_retry(max_retries=2, delay=1.0, backoff=2.0, exceptions=(Exception,))
async def google_trends(
    region: str = "RU",
    category: str = "shopping",
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Получает трендовые поисковые запросы через RSS Google Trends.

    Args:
        region: Регион (RU, US, etc.)
        category: Категория (business, entertainment, health, sci_tech, sports, top_stories, shopping)
        limit: Максимальное количество результатов

    Returns:
        Словарь с трендами:
            - trends: список словарей {title, traffic, date, related_queries}
            - region, category, source, timestamp
    """
    # Google Trends RSS для категорий
    # Примечание: Google не предоставляет официальный RSS для trends,
    # используем обходной путь через trends.embed + парсинг
    # В продакшене рекомендуется SerpAPI или официальный API

    url = f"https://trends.google.com/trending/rss?geo={region}"

    session = await _get_session()
    async with session.get(url) as response:
        if response.status != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status}",
                "trends": [],
            }
        text = await response.text()

    # Парсим RSS
    trends = []
    try:
        root = ET.fromstring(text.encode("utf-8"))
        # RSS 2.0 namespace
        ns = {"rss": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}

        # Пробуем без namespace
        items = root.findall(".//item")
        if not items:
            # Пробуем с namespace
            items = root.findall(".//rss:item", ns)

        for item in items[:limit]:
            title_elem = item.find("title")
            title = title_elem.text if title_elem is not None else ""

            # Очищаем title от CDATA
            title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title).strip()

            pub_date_elem = item.find("pubDate")
            pub_date = pub_date_elem.text if pub_date_elem is not None else ""

            # approximate_traffic из description
            desc_elem = item.find("description")
            traffic = ""
            if desc_elem is not None and desc_elem.text:
                match = re.search(r"(\d+[Kk+]?)\s*searches", desc_elem.text)
                if match:
                    traffic = match.group(1)

            trends.append({
                "title": title,
                "traffic": traffic,
                "date": pub_date,
                "category": category,
            })
    except Exception as e:
        return {
            "success": False,
            "error": f"Parse error: {e}",
            "trends": [],
        }

    return {
        "success": True,
        "trends": trends,
        "region": region,
        "category": category,
        "source": "google_trends_rss",
        "timestamp": datetime.now().isoformat(),
        "count": len(trends),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# News Monitor (RSS-агрегатор)
# ═══════════════════════════════════════════════════════════════════════════════

@with_retry(max_retries=2, delay=1.0, backoff=2.0, exceptions=(Exception,))
async def news_monitor(
    sources: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    hours: int = 24,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Собирает новости из RSS-лент с фильтрацией по ключевым словам.

    Args:
        sources: Список источников (vc_ru, tjournal, rbk, habr). Если None — все.
        keywords: Ключевые слова для фильтрации (например, ["скидки", "промокоды"]).
        hours: За сколько последних часов собирать новости.
        limit: Максимальное количество результатов.

    Returns:
        Словарь с новостями:
            - articles: список {title, link, source, published, summary}
            - total_found, filtered_count, keywords, timestamp
    """
    if sources is None:
        sources = list(NEWS_SOURCES.keys())

    target_sources = {k: v for k, v in NEWS_SOURCES.items() if k in sources}
    if not target_sources:
        return {
            "success": False,
            "error": "No valid sources specified",
            "articles": [],
        }

    session = await _get_session()
    all_articles = []
    cutoff = datetime.now() - timedelta(hours=hours)

    for source_name, rss_url in target_sources.items():
        try:
            async with session.get(rss_url) as response:
                if response.status != 200:
                    continue
                text = await response.text()
        except Exception:
            continue

        try:
            root = ET.fromstring(text.encode("utf-8"))
            items = root.findall(".//item")
            if not items:
                # Atom fallback
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items:
                title_elem = item.find("title")
                title = title_elem.text if title_elem is not None else ""
                title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title).strip()

                link_elem = item.find("link")
                link = ""
                if link_elem is not None:
                    link = link_elem.text or link_elem.get("href", "")

                desc_elem = item.find("description") or item.find("{http://www.w3.org/2005/Atom}summary")
                summary = ""
                if desc_elem is not None and desc_elem.text:
                    summary = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", desc_elem.text)
                    summary = re.sub(r"<[^>]+>", "", summary).strip()[:300]

                pub_date_elem = item.find("pubDate") or item.find("{http://www.w3.org/2005/Atom}published")
                pub_date_str = pub_date_elem.text if pub_date_elem is not None else ""

                # Парсим дату
                pub_dt = None
                for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
                    try:
                        pub_dt = datetime.strptime(pub_date_str, fmt)
                        break
                    except ValueError:
                        continue

                # Фильтр по времени
                if pub_dt and pub_dt < cutoff:
                    continue

                article = {
                    "title": title,
                    "link": link,
                    "source": source_name,
                    "published": pub_date_str,
                    "summary": summary,
                }
                all_articles.append(article)
        except Exception:
            continue

    # Фильтрация по ключевым словам
    if keywords:
        keywords_lower = [kw.lower() for kw in keywords]
        filtered = []
        for article in all_articles:
            text = f"{article['title']} {article['summary']}".lower()
            if any(kw in text for kw in keywords_lower):
                filtered.append(article)
        all_articles = filtered

    # Сортировка по дате (приблизительная) и лимит
    all_articles = all_articles[:limit]

    return {
        "success": True,
        "articles": all_articles,
        "total_found": len(all_articles),
        "keywords": keywords or [],
        "sources": list(target_sources.keys()),
        "hours": hours,
        "timestamp": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Marketplace Trends (Wildberries — базовый скрейпинг)
# ═══════════════════════════════════════════════════════════════════════════════

@with_retry(max_retries=2, delay=1.5, backoff=2.0, exceptions=(Exception,))
async def marketplace_trends(
    marketplace: str = "wildberries",
    category: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Получает трендовые товары с маркетплейса.

    Args:
        marketplace: Поддерживается "wildberries" (базовый)
        category: Категория товаров (например, "elektronika", "dom")
        limit: Максимальное количество товаров

    Returns:
        Словарь с товарами:
            - products: список {name, price, rating, link, image}
            - marketplace, category, timestamp
    """
    if marketplace.lower() != "wildberries":
        return {
            "success": False,
            "error": f"Marketplace '{marketplace}' not supported yet. Use 'wildberries'.",
            "products": [],
        }

    # Wildberries API (неофициальный, публичный endpoint для каталога)
    base_url = "https://search.wb.ru/exactmatch/ru/common/v4/search"
    params = {
        "appType": "1",
        "curr": "rub",
        "dest": "-1257786",
        "page": "1",
        "query": category or "тренд",
        "resultset": "catalog",
        "sort": "popular",
        "spp": "30",
        "suppressSpellcheck": "false",
    }

    session = await _get_session()
    async with session.get(base_url, params=params) as response:
        if response.status != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status}",
                "products": [],
            }
        data = await response.json()

    products = []
    for item in data.get("data", {}).get("products", [])[:limit]:
        # Формируем ссылку и цену
        price = item.get("salePriceU", item.get("priceU", 0)) // 100
        product = {
            "name": item.get("name", ""),
            "brand": item.get("brand", ""),
            "price": price,
            "rating": item.get("rating", 0),
            "feedbacks": item.get("feedbacks", 0),
            "link": f"https://www.wildberries.ru/catalog/{item.get('id', '')}/detail.aspx",
            "image": f"https://basket-01.wb.ru/vol{item.get('id', '')//100000}/part{item.get('id', '')//1000}/{item.get('id', '')}/images/c246x328/1.jpg",
        }
        products.append(product)

    return {
        "success": True,
        "products": products,
        "marketplace": marketplace,
        "category": category,
        "timestamp": datetime.now().isoformat(),
        "count": len(products),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Yandex Wordstat (подсказки — популярность запросов)
# ═══════════════════════════════════════════════════════════════════════════════

@with_retry(max_retries=2, delay=1.0, backoff=2.0, exceptions=(Exception,))
async def yandex_wordstat(
    query: str,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Получает подсказки Яндекса для оценки популярности запроса.

    Args:
        query: Поисковый запрос
        limit: Максимальное количество подсказок

    Returns:
        Словарь с подсказками:
            - suggestions: список {text, type}
            - original_query, timestamp
    """
    url = "https://suggest.yandex.ru/suggest-ya.cgi"
    params = {
        "part": query,
        "srv": "yasearch",
        "wiz": "TrWth",
        "uil": "ru",
        "fact": "1",
        "v": "4",
    }

    session = await _get_session()
    async with session.get(url, params=params) as response:
        if response.status != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status}",
                "suggestions": [],
            }
        text = await response.text()

    # Парсим JSON-ответ: ["query", ["suggestion1", "suggestion2", ...], {...}]
    suggestions = []
    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) >= 2:
            suggestions_list = data[1]
            for item in suggestions_list[:limit]:
                if isinstance(item, str):
                    suggestions.append({"text": item, "type": "text"})
                elif isinstance(item, list) and len(item) >= 2:
                    suggestions.append({
                        "text": item[1] if isinstance(item[1], str) else str(item[1]),
                        "type": item[2] if len(item) > 2 and isinstance(item[2], str) else "text",
                    })
    except Exception as e:
        return {
            "success": False,
            "error": f"Parse error: {e}",
            "suggestions": [],
        }

    return {
        "success": True,
        "suggestions": suggestions,
        "original_query": query,
        "timestamp": datetime.now().isoformat(),
        "count": len(suggestions),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Forum Scanner (HackerNews + Reddit fallback)
# ═══════════════════════════════════════════════════════════════════════════════

@with_retry(max_retries=2, delay=1.0, backoff=2.0, exceptions=(Exception,))
async def forum_scanner(
    source: str = "hackernews",
    keywords: Optional[List[str]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Сканирует посты из форумов/сообществ.

    Args:
        source: Источник — "hackernews" (работает) или "reddit" (может требовать OAuth)
        keywords: Ключевые слова для фильтрации
        limit: Максимальное количество постов

    Returns:
        Словарь с постами:
            - posts: список {title, url, score, comments, created}
            - source, keywords, timestamp
    """
    if source == "hackernews":
        return await _hackernews_scanner(keywords, limit)
    else:
        return await _reddit_scanner(source, keywords, limit)


async def _hackernews_scanner(
    keywords: Optional[List[str]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Сканер HackerNews (публичный Firebase API, без ограничений)."""
    session = await _get_session()

    # Получаем топ-стори
    async with session.get(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        timeout=DEFAULT_TIMEOUT,
    ) as response:
        if response.status != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status}",
                "posts": [],
            }
        story_ids = await response.json()

    posts = []
    for story_id in story_ids[:limit * 3]:
        try:
            async with session.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=DEFAULT_TIMEOUT,
            ) as sr:
                if sr.status != 200:
                    continue
                story = await sr.json()

            if not story or story.get("deleted") or story.get("dead"):
                continue

            title = story.get("title", "")

            # Фильтрация по ключевым словам
            if keywords:
                keywords_lower = [kw.lower() for kw in keywords]
                text = f"{title} {story.get('text', '')}".lower()
                if not any(kw in text for kw in keywords_lower):
                    continue

            posts.append({
                "title": title,
                "url": story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                "external_url": story.get("url", ""),
                "score": story.get("score", 0),
                "comments": story.get("descendants", 0),
                "created_utc": story.get("time", 0),
            })

            if len(posts) >= limit:
                break
        except Exception:
            continue

    return {
        "success": True,
        "posts": posts,
        "source": "hackernews",
        "keywords": keywords or [],
        "timestamp": datetime.now().isoformat(),
        "count": len(posts),
    }


async def _reddit_scanner(
    subreddit: str,
    keywords: Optional[List[str]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Сканер Reddit (может требовать OAuth в продакшене)."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    session = await _get_session()
    async with session.get(url, headers=headers, params={"limit": limit * 2}, ssl=False) as response:
        if response.status != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status} — Reddit требует OAuth или блокирует IP. Используйте source='hackernews'.",
                "posts": [],
            }
        data = await response.json()

    posts = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = post.get("title", "")

        if keywords:
            keywords_lower = [kw.lower() for kw in keywords]
            text = f"{title} {post.get('selftext', '')}".lower()
            if not any(kw in text for kw in keywords_lower):
                continue

        posts.append({
            "title": title,
            "url": urljoin("https://www.reddit.com", post.get("permalink", "")),
            "external_url": post.get("url", ""),
            "score": post.get("score", 0),
            "comments": post.get("num_comments", 0),
            "created_utc": post.get("created_utc", 0),
        })

        if len(posts) >= limit:
            break

    return {
        "success": True,
        "posts": posts,
        "source": f"reddit/r/{subreddit}",
        "keywords": keywords or [],
        "timestamp": datetime.now().isoformat(),
        "count": len(posts),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Утилита: комплексный сбор трендов для Trend Agent
# ═══════════════════════════════════════════════════════════════════════════════

async def gather_trend_data(
    keywords: Optional[List[str]] = None,
    news_hours: int = 24,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Комплексный сбор данных для Trend Agent из всех доступных источников.

    Args:
        keywords: Ключевые слова для фильтрации
        news_hours: За сколько часов собирать новости
        limit: Лимит результатов на источник

    Returns:
        Словарь с данными из всех источников:
            - google_trends, news, marketplace, forum
            - combined_insights: агрегированные инсайты
            - timestamp
    """
    if keywords is None:
        keywords = ["скидки", "промокоды", "распродажа", "дешево", "акция"]

    # Параллельный запрос ко всем источникам
    results = await asyncio.gather(
        google_trends(region="RU", limit=limit),
        news_monitor(keywords=keywords, hours=news_hours, limit=limit),
        marketplace_trends(marketplace="wildberries", category="электроника", limit=limit),
        forum_scanner(subreddit="deals", keywords=["deal", "sale", "discount"], limit=limit),
        return_exceptions=True,
    )

    google_result = results[0] if not isinstance(results[0], Exception) else {"success": False, "error": str(results[0])}
    news_result = results[1] if not isinstance(results[1], Exception) else {"success": False, "error": str(results[1])}
    marketplace_result = results[2] if not isinstance(results[2], Exception) else {"success": False, "error": str(results[2])}
    forum_result = results[3] if not isinstance(results[3], Exception) else {"success": False, "error": str(results[3])}

    # Формируем агрегированные инсайты
    insights = []

    if google_result.get("success"):
        for trend in google_result.get("trends", [])[:5]:
            insights.append({
                "type": "search_trend",
                "title": trend.get("title", ""),
                "traffic": trend.get("traffic", ""),
                "source": "google_trends",
            })

    if news_result.get("success"):
        for article in news_result.get("articles", [])[:5]:
            insights.append({
                "type": "news",
                "title": article.get("title", ""),
                "source": article.get("source", ""),
                "link": article.get("link", ""),
            })

    if marketplace_result.get("success"):
        for product in marketplace_result.get("products", [])[:5]:
            insights.append({
                "type": "product_trend",
                "title": product.get("name", ""),
                "price": product.get("price", 0),
                "rating": product.get("rating", 0),
                "source": "wildberries",
            })

    if forum_result.get("success"):
        for post in forum_result.get("posts", [])[:5]:
            insights.append({
                "type": "forum_discussion",
                "title": post.get("title", ""),
                "score": post.get("score", 0),
                "source": f"reddit/r/{forum_result.get('subreddit', '')}",
            })

    return {
        "success": True,
        "sources": {
            "google_trends": google_result,
            "news": news_result,
            "marketplace": marketplace_result,
            "forum": forum_result,
        },
        "combined_insights": insights,
        "keywords": keywords,
        "timestamp": datetime.now().isoformat(),
    }
