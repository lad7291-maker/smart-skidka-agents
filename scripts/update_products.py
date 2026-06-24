#!/usr/bin/env python3
"""Обновление товаров SmartSkidka.ru — 200 товаров на категорию, все ссылки проверяются, каждые 24ч."""

import json
import gzip
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
from urllib.parse import unquote

import requests
from lxml import etree as ET

# ── CONFIG ──────────────────────────────────────────────────────
ADMITAD_XML_URL = os.environ.get("ADMITAD_XML_URL", "")
MIN_DISCOUNT = int(os.environ.get("MIN_DISCOUNT_PERCENT", "30"))
PRODUCTS_PER_CATEGORY = int(os.environ.get("PRODUCTS_PER_CATEGORY", "200"))
# TARGET_CATEGORIES убран — категории определяются динамически из фида
# Но можно задать через env для feed-agent
TARGET_CATEGORIES_OVERRIDE = os.environ.get("TARGET_CATEGORIES", "")
MAX_TOTAL = 2000  # Максимум 2000 товаров всего (200 на категорию × 10 категорий)

BASE_DIR = Path("/var/www/dealshub-miniapp")
V2_DIR = BASE_DIR / "v2"
PUBLIC_DIR = V2_DIR / "public"
HTML_DIR = BASE_DIR / "html"
FEED_RAW = BASE_DIR / "feed_raw.xml.gz"
PRODUCTS_JSON = PUBLIC_DIR / "products.json"
PRODUCTS_JSON_PROD = HTML_DIR / "products.json"

CHECK_TIMEOUT = 10
CHECK_MAX_WORKERS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("product_updater")

# ── CATEGORY MAPPING ────────────────────────────────────────────
# Маппинг ID категорий фида → внутренние категории сайта
CATEGORY_MAP = {
    "2": "home", "3": "clothing", "5": "electronics", "6": "home",
    "7": "electronics", "13": "home", "15": "home", "18": "sport",
    "21": "home", "26": "home", "30": "electronics", "34": "auto",
    "36": "beauty", "39": "home", "44": "electronics", "66": "beauty",
    "320": "beauty", "322": "shoes", "502": "electronics", "509": "electronics",
    "200000345": "clothing", "200000343": "clothing", "200000297": "clothing",
    "200165144": "beauty", "200000532": "clothing", "200574005": "clothing",
    "201768104": "sport", "201355758": "auto", "1501": "home", "1503": "home",
    "1511": "beauty", "1524": "home", "1420": "home", "200000920": "home",
    # Additional subcategories for clothing
    "201303001": "clothing", "201303301": "clothing", "201303603": "clothing",
    "201303704": "clothing", "201330702": "clothing", "201336907": "clothing",
    "201352950": "clothing", "201357051": "clothing", "201359147": "clothing",
    "200001081": "clothing", "200001083": "clothing", "200001147": "clothing",
    "200001168": "clothing", "200001221": "clothing", "200001288": "clothing",
    "200001330": "clothing", "200001355": "clothing", "200001562": "clothing",
    # Beauty/Health subcategories
    "200001077": "beauty", "200001385": "beauty", "200001384": "beauty",
    "200001387": "beauty", "200001388": "beauty", "200001389": "beauty",
    "201396505": "beauty", "201376929": "beauty", "201359843": "beauty",
    "201445239": "beauty", "201515701": "beauty", "201516501": "beauty",
    "201531101": "beauty", "201531601": "beauty", "201610101": "beauty",
    "201902301": "beauty", "201902401": "beauty", "201377402": "beauty",
    # Auto subcategories
    "100005657": "auto", "629": "auto",
    # Jewelry subcategories
    "201768001": "jewelry", "201768002": "jewelry", "201768003": "jewelry",
    "201768004": "jewelry", "201768005": "jewelry", "201768006": "jewelry",
    "201768007": "jewelry", "201768008": "jewelry", "201768009": "jewelry",
    "201768010": "jewelry", "201768011": "jewelry", "201768012": "jewelry",
    "201768013": "jewelry", "201768014": "jewelry", "201768015": "jewelry",
    "201768016": "jewelry", "201768017": "jewelry", "201768018": "jewelry",
    "201768019": "jewelry", "201768020": "jewelry", "201768021": "jewelry",
    "201768022": "jewelry", "201768023": "jewelry", "201768024": "jewelry",
    "201768025": "jewelry", "201768026": "jewelry", "201768027": "jewelry",
    "201768028": "jewelry", "201768029": "jewelry", "201768030": "jewelry",
    "201768031": "jewelry", "201768032": "jewelry", "201768033": "jewelry",
    "201768034": "jewelry", "201768035": "jewelry", "201768036": "jewelry",
    "201768037": "jewelry", "201768038": "jewelry", "201768039": "jewelry",
    "201768040": "jewelry", "201768041": "jewelry", "201768042": "jewelry",
    "201768043": "jewelry", "201768044": "jewelry", "201768045": "jewelry",
    "201768046": "jewelry", "201768047": "jewelry", "201768048": "jewelry",
    "201768049": "jewelry", "201768050": "jewelry", "201768051": "jewelry",
    "201768052": "jewelry", "201768053": "jewelry", "201768054": "jewelry",
    "201768055": "jewelry", "201768056": "jewelry", "201768057": "jewelry",
    "201768058": "jewelry", "201768059": "jewelry", "201768060": "jewelry",
    "201768061": "jewelry", "201768062": "jewelry", "201768063": "jewelry",
    "201768064": "jewelry", "201768065": "jewelry", "201768066": "jewelry",
    "201768067": "jewelry", "201768068": "jewelry", "201768069": "jewelry",
    "201768070": "jewelry", "201768071": "jewelry", "201768072": "jewelry",
    "201768073": "jewelry", "201768074": "jewelry", "201768075": "jewelry",
    "201768076": "jewelry", "201768077": "jewelry", "201768078": "jewelry",
    "201768079": "jewelry", "201768080": "jewelry", "201768081": "jewelry",
    "201768082": "jewelry", "201768083": "jewelry", "201768084": "jewelry",
    "201768085": "jewelry", "201768086": "jewelry", "201768087": "jewelry",
    "201768088": "jewelry", "201768089": "jewelry", "201768090": "jewelry",
    "201768091": "jewelry", "201768092": "jewelry", "201768093": "jewelry",
    "201768094": "jewelry", "201768095": "jewelry", "201768096": "jewelry",
    "201768097": "jewelry", "201768098": "jewelry", "201768099": "jewelry",
    "201768100": "jewelry",
}

# ── CATEGORY METADATA (динамические названия и иконки) ──────────
# Если категория появляется в фиде, но нет здесь — используется cat_id как есть
CATEGORY_META = {
    "electronics": {"name": "Электроника", "icon": "Monitor"},
    "clothing": {"name": "Одежда", "icon": "Shirt"},
    "shoes": {"name": "Обувь", "icon": "Footprints"},
    "home": {"name": "Дом", "icon": "Home"},
    "auto": {"name": "Авто", "icon": "Car"},
    "beauty": {"name": "Красота", "icon": "Sparkles"},
    "sport": {"name": "Спорт", "icon": "Dumbbell"},
    "jewelry": {"name": "Украшения", "icon": "Gem"},
}

# ── MODELS ──────────────────────────────────────────────────────
class Product:
    def __init__(self, data: dict):
        self.id = data.get("id", "")
        self.itemId = data.get("itemId", "")
        self.title = data.get("title", "")
        self.category = data.get("category", "")
        self.price = float(data.get("price", 0))
        self.oldPrice = float(data.get("oldPrice", 0)) if data.get("oldPrice") else 0
        self.discount = int(data.get("discount", 0))
        self.rating = float(data.get("rating", 0))
        self.orders = int(data.get("orders", 0))
        self.image = data.get("image", "")
        self.aliLink = data.get("aliLink", "")
        self.tags = data.get("tags", [])
        self.specs = data.get("specs", {})
        self.shopName = data.get("shopName", "AliExpress")

    def to_v2_dict(self) -> dict:
        # Extract direct AliExpress link from rzekl.com redirect
        affiliate_link = self.aliLink
        if "rzekl.com" in self.aliLink and "ulp=" in self.aliLink:
            try:
                from urllib.parse import unquote
                decoded = unquote(self.aliLink)
                if "ulp=" in decoded:
                    parts = decoded.split("ulp=")
                    if len(parts) > 1:
                        direct_url = parts[1]
                        # Validate it's an AliExpress link
                        if "aliexpress.com" in direct_url or "s.click.aliexpress.com" in direct_url:
                            affiliate_link = direct_url
            except Exception:
                pass
        return {
            "id": self.id, "itemId": self.itemId, "title": self.title,
            "category": self.category, "price": self.price, "oldPrice": self.oldPrice,
            "discount": self.discount, "rating": self.rating, "orders": self.orders,
            "viewers": max(1, int(self.orders * 0.2)) + 5,
            "timer": f"еще {max(1, self.discount % 48 + 1)} часов",
            "image": self.image, "tags": self.tags[:4] if self.tags else [],
            "badges": self._generate_badges(), "features": self._specs_to_features(),
            "affiliateLink": affiliate_link, "aliLink": self.aliLink,
            "shipping": "Доставка по условиям AliExpress",
            "shopName": self.shopName,
        }

    def _generate_badges(self) -> List[str]:
        badges = []
        if self.discount >= 80: badges.append("flash")
        if self.rating >= 4.7 and self.orders > 100: badges.append("topRated")
        if self.orders > 500: badges.append("bestseller")
        if self.discount >= 50: badges.append("bestPrice")
        return badges

    def _specs_to_features(self) -> List[str]:
        if not self.specs: return []
        return [f"{k}: {v}" for k, v in list(self.specs.items())[:5] if k != "Комиссия"]


# ── FEED PARSER ─────────────────────────────────────────────────
class FeedParser:
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    def __init__(self, xml_url: str):
        self.xml_url = xml_url

    def download(self):
        if FEED_RAW.exists():
            age_hours = (datetime.now().timestamp() - FEED_RAW.stat().st_mtime) / 3600
            if age_hours < 24:
                size_mb = FEED_RAW.stat().st_size / 1024 / 1024
                logger.info(f"Используем существующий фид ({age_hours:.1f}ч, {size_mb:.1f} MB)")
                return self._open_feed()

        logger.info("Скачиваю фид...")
        resp = requests.get(self.xml_url, headers=self.HEADERS, timeout=300, stream=True)
        resp.raise_for_status()
        with open(FEED_RAW, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_mb = FEED_RAW.stat().st_size / 1024 / 1024
        logger.info(f"Фид сохранён: {FEED_RAW} ({size_mb:.1f} MB)")
        return self._open_feed()

    def _open_feed(self):
        with open(FEED_RAW, "rb") as f:
            magic = f.read(2)
        if magic[:2] == bytes([0x1f, 0x8b]):
            logger.info("Фид gzip")
            return gzip.open(FEED_RAW, "rb")
        else:
            logger.info("Фид plain XML")
            return open(FEED_RAW, "rb")

    def parse(self, stream) -> Dict[str, List[Product]]:
        by_category: Dict[str, List[Product]] = {}
        count = 0
        errors = 0

        try:
            context = ET.iterparse(stream, events=("end",), recover=True, huge_tree=True)
            context = iter(context)
            event, root = next(context)

            for event, elem in context:
                if elem.tag == "category":
                    elem.clear()
                    continue

                if elem.tag in ("offer", "product"):
                    count += 1
                    try:
                        p = self._parse_offer(elem)
                        if p and p.discount >= MIN_DISCOUNT:
                            cat = p.category
                            if cat not in by_category:
                                by_category[cat] = []
                            if len(by_category[cat]) < PRODUCTS_PER_CATEGORY:
                                by_category[cat].append(p)
                    except Exception as e:
                        errors += 1
                        if errors <= 5:
                            logger.warning(f"Ошибка парсинга offer #{count}: {e}")

                    elem.clear()

                    # Проверяем, все ли категории набраны
                    total_collected = sum(len(v) for v in by_category.values())
                    if total_collected >= MAX_TOTAL:
                        logger.info(f"Набрано {total_collected} товаров (max {MAX_TOTAL}), останавливаю парсинг")
                        break

                    if count % 50000 == 0:
                        totals = {k: len(v) for k, v in by_category.items()}
                        logger.info(f"Обработано {count} офферов, статус: {totals}")

        except ET.XMLSyntaxError as e:
            logger.warning(f"XML SyntaxError: {e}")
        except Exception as e:
            logger.warning(f"Parse error: {e}")

        total = sum(len(v) for v in by_category.values())
        logger.info(f"Всего обработано ~{count} офферов, отобрано {total} товаров в {len(by_category)} категориях")
        return by_category

    def _parse_offer(self, offer: ET.Element) -> Optional[Product]:
        def get_text(tag: str) -> str:
            el = offer.find(tag)
            return (el.text or "").strip() if el is not None else ""

        name = get_text("name") or get_text("title") or get_text("productName")
        if not name:
            return None

        price_raw = get_text("price") or get_text("currentPrice")
        old_price_raw = get_text("oldprice") or get_text("oldPrice") or get_text("basePrice")
        url = (get_text("url") or get_text("productUrl") or "").strip()
        image = (get_text("picture") or get_text("image") or "").strip()
        cat_id = get_text("categoryId")
        category = CATEGORY_MAP.get(cat_id, "home")

        item_id = ""
        try:
            decoded = unquote(url)
            if "item/" in decoded:
                parts = decoded.split("item/")
                if len(parts) > 1:
                    item_id = parts[1].split(".html")[0].split("?")[0]
        except Exception:
            pass

        try:
            price = float(price_raw) if price_raw else 0
            old_price = float(old_price_raw) if old_price_raw else 0
        except (ValueError, TypeError):
            return None

        if price <= 0 or old_price <= 0 or old_price <= price:
            return None

        discount = int(round((old_price - price) / old_price * 100))
        if discount < MIN_DISCOUNT:
            return None

        return Product({
            "id": offer.get("id", item_id or str(hash(url))),
            "itemId": item_id, "title": name[:120], "category": category,
            "price": price, "oldPrice": old_price, "discount": discount,
            "rating": 4.5, "orders": 100, "image": image, "aliLink": url,
            "tags": [], "specs": {},
        })


# ── ALIVE CHECKER ───────────────────────────────────────────────
def check_product_alive(product: Product) -> tuple:
    if not product.aliLink:
        return product, False
    try:
        resp = requests.head(
            product.aliLink,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "text/html"},
            timeout=CHECK_TIMEOUT,
            allow_redirects=True,
        )
        return product, resp.status_code < 400
    except Exception:
        return product, False


def filter_alive_products(products: List[Product]) -> List[Product]:
    logger.info(f"Проверяю {len(products)} товаров на доступность...")
    alive = []
    dead = []
    with ThreadPoolExecutor(max_workers=CHECK_MAX_WORKERS) as executor:
        futures = {executor.submit(check_product_alive, p): p for p in products}
        for future in as_completed(futures):
            product, is_alive = future.result()
            if is_alive:
                alive.append(product)
            else:
                dead.append(product)
    logger.info(f"Живых: {len(alive)}, мёртвых/распродано: {len(dead)}")
    return alive


# ── BALANCER ────────────────────────────────────────────────────
def balance_and_limit(by_category: Dict[str, List[Product]], per_cat: int, total_max: int) -> List[Product]:
    result = []
    # Сортируем категории по количеству товаров (убывание) — приоритет у категорий с больше товарами
    sorted_cats = sorted(by_category.keys(), key=lambda c: len(by_category.get(c, [])), reverse=True)
    for cat in sorted_cats:
        items = by_category.get(cat, [])
        items.sort(key=lambda x: x.discount, reverse=True)
        result.extend(items[:per_cat])
    if len(result) > total_max:
        result = result[:total_max]
    logger.info(f"Итого {len(result)} товаров после балансировки из {len(sorted_cats)} категорий")
    return result


# ── GENERATOR ───────────────────────────────────────────────────
def generate_v2_json(products: List[Product]) -> dict:
    items = [p.to_v2_dict() for p in products]
    for i, item in enumerate(items, 1):
        item["id"] = i
    return items


def generate_categories_json(products: List[Product]) -> list:
    # Динамически определяем категории из реальных товаров
    present_cats = sorted(set(p.category for p in products))
    
    result = [{"id": "all", "name": "Все", "icon": "LayoutGrid"}]
    for cat_id in present_cats:
        meta = CATEGORY_META.get(cat_id, {"name": cat_id.capitalize(), "icon": "Package"})
        result.append({"id": cat_id, "name": meta["name"], "icon": meta["icon"]})
    
    logger.info(f"Сгенерировано {len(result)} категорий: {[c['id'] for c in result]}")
    return result


# ── MAIN ────────────────────────────────────────────────────────
def main():
    logger.info("=== SmartSkidka Product Updater ===")
    logger.info(f"Время: {datetime.now().isoformat()}")
    logger.info(f"Параметры: MIN_DISCOUNT={MIN_DISCOUNT}, PRODUCTS_PER_CATEGORY={PRODUCTS_PER_CATEGORY}")
    if TARGET_CATEGORIES_OVERRIDE:
        logger.info(f"Переопределение категорий: {TARGET_CATEGORIES_OVERRIDE}")
    logger.info(f"Цель: ~{PRODUCTS_PER_CATEGORY} товаров на категорию, max {MAX_TOTAL} всего")

    if not ADMITAD_XML_URL:
        logger.error("ADMITAD_XML_URL не указан в окружении")
        sys.exit(1)

    parser = FeedParser(ADMITAD_XML_URL)
    stream = parser.download()
    by_category = parser.parse(stream)

    # Если feed-agent задал конкретные категории — фильтруем
    if TARGET_CATEGORIES_OVERRIDE:
        allowed = set(TARGET_CATEGORIES_OVERRIDE.split(","))
        by_category = {k: v for k, v in by_category.items() if k in allowed}
        logger.info(f"Фильтр категорий от feed-agent: {allowed}")

    # Собираем все товары из всех найденных категорий (динамически!)
    all_products = []
    for cat, items in by_category.items():
        all_products.extend(items)
        logger.info(f"  Категория '{cat}': {len(items)} товаров")

    if not all_products:
        logger.error("Не найдено товаров в фиде")
        sys.exit(1)

    logger.info(f"Собрано {len(all_products)} товаров из {len(by_category)} категорий до проверки")

    all_products = filter_alive_products(all_products)

    # Группируем живые товары по категориям (динамически!)
    by_category_alive: Dict[str, List[Product]] = {}
    for p in all_products:
        cat = p.category
        if cat not in by_category_alive:
            by_category_alive[cat] = []
        by_category_alive[cat].append(p)

    products = balance_and_limit(by_category_alive, PRODUCTS_PER_CATEGORY, MAX_TOTAL)

    if not products:
        logger.error("Нет живых товаров после проверки")
        sys.exit(1)

    v2_products = generate_v2_json(products)
    categories = generate_categories_json(products)

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    with open(PRODUCTS_JSON, "w", encoding="utf-8") as f:
        json.dump(v2_products, f, ensure_ascii=False, indent=2)
    logger.info(f"Сохранено {len(v2_products)} товаров в {PRODUCTS_JSON}")

    with open(PUBLIC_DIR / "categories.json", "w", encoding="utf-8") as f:
        json.dump(categories, f, ensure_ascii=False, indent=2)

    # Копируем в v2/public (для сайта) и в корень (для агентов)
    shutil.copy2(PRODUCTS_JSON, PRODUCTS_JSON_PROD)
    shutil.copy2(PUBLIC_DIR / "categories.json", HTML_DIR / "categories.json")
    # Also update root for agents and v2 build
    root_products = BASE_DIR / "products.json"
    root_categories = BASE_DIR / "categories.json"
    shutil.copy2(PRODUCTS_JSON, root_products)
    shutil.copy2(PUBLIC_DIR / "categories.json", root_categories)
    logger.info(f"Скопировано: {HTML_DIR}, {root_products}, {root_categories}")

    by_cat = {}
    for p in products:
        by_cat[p.category] = by_cat.get(p.category, 0) + 1
    logger.info("Распределение по категориям:")
    for cat, count in sorted(by_cat.items()):
        logger.info(f"  {cat}: {count}")

    logger.info("✅ Обновление завершено")


if __name__ == "__main__":
    main()
