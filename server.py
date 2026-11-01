"""Serve Cardwise and a validated, PostgreSQL-backed catalog."""

import argparse
import json
import logging
import math
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from functools import partial
from http.client import HTTPException
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NotRequired, TypedDict
from urllib.parse import urlencode, urlsplit

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parent
# libpq connection string; the password comes from pgpass.conf (or PGPASSWORD), never from source.
DEFAULT_DATABASE = "host=localhost port=5432 dbname=cardwise user=cardwise_app"
DEFAULT_SCHEMA = "prod"
TABLES = {
    "categories": ("id", "name", "icon"),
    "cards": ("id", "name", "issuer", "style", "unit", "base", "foreign_fee", "summary",
              "cap", "cap_period", "activation", "default_wallet", "source_url", "reviewed_on", "limitations",
              "image_url"),
    "reward_rules": ("card_id", "category_ids", "channel", "rate", "capped", "description"),
}
ORDER_BY = {"categories": ("sort_order",), "cards": ("id",), "reward_rules": ("card_id", "category_ids", "channel")}
OVERPASS_URL = os.environ.get("CARDWISE_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
MAX_STORES = 10
MAX_BODY_BYTES = 1024
# OpenStreetMap tags mapped to catalog category IDs. Issuers decide the real category from merchant codes.
AMENITY_CATEGORIES = {"restaurant": "dining", "fast_food": "dining", "cafe": "dining", "bar": "dining", "pub": "dining",
                      "food_court": "dining", "ice_cream": "dining", "fuel": "gas", "charging_station": "ev",
                      "car_rental": "travel", "pharmacy": "other"}
TOURISM_CATEGORIES = {"hotel": "travel", "motel": "travel", "hostel": "travel", "guest_house": "travel"}
SHOP_CATEGORIES = {"supermarket": "groceries", "grocery": "groceries", "greengrocer": "groceries",
                   "bakery": "dining", "convenience": "other", "chemist": "other"}
SHOP_DEFAULT_CATEGORY = "shopping"
GOOGLE_PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
# These four fields keep each lookup on the Nearby Search Pro SKU; adding others can raise the price.
GOOGLE_FIELD_MASK = "places.displayName,places.location,places.primaryType,places.types"
GOOGLE_CATEGORIES = {
    "supermarket": "groceries", "grocery_store": "groceries",
    "restaurant": "dining", "fast_food_restaurant": "dining", "cafe": "dining", "coffee_shop": "dining",
    "bar": "dining", "pub": "dining", "bakery": "dining", "ice_cream_shop": "dining",
    "gas_station": "gas", "electric_vehicle_charging_station": "ev",
    "hotel": "travel", "motel": "travel", "lodging": "travel", "hostel": "travel", "car_rental": "travel",
    "shopping_mall": "shopping", "department_store": "shopping", "clothing_store": "shopping",
    "electronics_store": "shopping", "home_goods_store": "shopping", "hardware_store": "shopping",
    "furniture_store": "shopping", "shoe_store": "shopping", "book_store": "shopping",
    "sporting_goods_store": "shopping", "jewelry_store": "shopping", "warehouse_store": "shopping",
    "discount_store": "shopping", "pet_store": "shopping", "store": "shopping",
    "convenience_store": "other", "pharmacy": "other", "drugstore": "other",
}
STYLES = {"jade", "midnight", "sand", "plum", "blue", "copper"}
CHANNELS = {"in-person", "online", "portal"}
PUBLIC_FILES = {"/", "/index.html", "/styles.css", "/app.js", "/rewards.js", "/tests.html", "/tests.js"}
IDENTIFIER = re.compile(r"[a-z][a-z0-9-]*")
CARD_IMAGE = re.compile(r"images/[a-z0-9][a-z0-9-]*\.(png|jpg|jpeg|webp)")


class CatalogError(ValueError):
    """The catalog cannot be used safely for reward calculations."""


class Category(TypedDict):
    id: str
    name: str
    icon: str


class Rule(TypedDict):
    categories: list[str]
    rate: float
    description: str
    capped: bool
    channel: NotRequired[str]


class Card(TypedDict):
    id: str
    name: str
    issuer: str
    style: str
    unit: str
    base: float
    foreignFee: float
    summary: str
    activation: bool
    rules: list[Rule]
    cap: NotRequired[float]
    capPeriod: NotRequired[str]
    sourceUrl: NotRequired[str]
    reviewedOn: NotRequired[str]
    limitations: NotRequired[str]
    imageUrl: NotRequired[str]


class Catalog(TypedDict):
    cards: list[Card]
    categories: list[Category]
    defaultWallet: list[str]


Tables = dict[str, list[dict[str, str]]]


def text(value: object) -> str:
    """Normalize a database value to the text form the validators expect (NULL becomes empty)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def fetch_tables(database: str, schema: str) -> Tables:
    tables: Tables = {}
    with psycopg.connect(database, connect_timeout=5) as connection:
        connection.read_only = True
        for table, columns in TABLES.items():
            query = sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.Identifier(schema, table),
                sql.SQL(", ").join(map(sql.Identifier, ORDER_BY[table])))
            rows = connection.execute(query).fetchall()
            tables[table] = [{column: text(value) for column, value in zip(columns, row)} for row in rows]
    return tables


def number(value: str, field: str, maximum: float = 1000) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise CatalogError(f"{field}: expected a number") from error
    if not math.isfinite(parsed) or not 0 <= parsed <= maximum:
        raise CatalogError(f"{field}: expected a finite number from 0 to {maximum}")
    return parsed


def boolean(value: str, field: str) -> bool:
    if value not in {"true", "false"}:
        raise CatalogError(f"{field}: expected true or false")
    return value == "true"


def identifier(value: str, field: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise CatalogError(f"{field}: expected a lowercase identifier with optional digits or hyphens")
    return value


def required(value: str, field: str) -> str:
    if not value:
        raise CatalogError(f"{field}: must not be empty")
    return value


def build_catalog(tables: Tables) -> Catalog:
    categories: list[Category] = []
    category_ids: set[str] = set()
    for row in tables["categories"]:
        category_id = identifier(row["id"], "category id")
        if category_id in category_ids:
            raise CatalogError(f"Duplicate category: {category_id}")
        category_ids.add(category_id)
        categories.append(Category(id=category_id, name=required(row["name"], category_id + " name"),
                                   icon=required(row["icon"], category_id + " icon")))
    if not categories:
        raise CatalogError("At least one category is required")

    cards: dict[str, Card] = {}
    default_wallet: list[str] = []
    for row in tables["cards"]:
        card_id = identifier(row["id"], "card id")
        if card_id in cards:
            raise CatalogError(f"Duplicate card: {card_id}")
        if row["style"] not in STYLES or row["unit"] not in {"cash", "points", "unmodeled"}:
            raise CatalogError(f"{card_id}: unsupported style or reward unit")
        card = Card(id=card_id, name=required(row["name"], card_id + " name"),
                    issuer=required(row["issuer"], card_id + " issuer"), style=row["style"],
                    unit=row["unit"], base=number(row["base"], card_id + " base"),
                    foreignFee=number(row["foreign_fee"], card_id + " foreign fee", 100),
                    summary=required(row["summary"], card_id + " summary"),
                    activation=boolean(row["activation"], card_id + " activation"), rules=[])
        if row["source_url"]:
            source = urlsplit(row["source_url"])
            if source.scheme != "https" or not source.hostname or source.username or source.password:
                raise CatalogError(f"{card_id}: source must be a public HTTPS URL")
            if row["reviewed_on"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["reviewed_on"]):
                raise CatalogError(f"{card_id}: source review date must use YYYY-MM-DD")
            card["sourceUrl"] = row["source_url"]
            if row["reviewed_on"]:
                card["reviewedOn"] = row["reviewed_on"]
            card["limitations"] = required(row["limitations"], card_id + " limitations")
        elif row["reviewed_on"] or row["limitations"]:
            raise CatalogError(f"{card_id}: source metadata requires a source URL")
        if row["cap"]:
            cap = number(row["cap"], card_id + " cap", 1e9)
            if cap == 0 or row["cap_period"] not in {"annual", "quarterly"}:
                raise CatalogError(f"{card_id}: cap must be positive with an annual or quarterly period")
            card["cap"] = cap
            card["capPeriod"] = row["cap_period"]
        elif row["cap_period"]:
            raise CatalogError(f"{card_id}: cap period requires a cap")
        if row["image_url"]:
            if not CARD_IMAGE.fullmatch(row["image_url"]):
                raise CatalogError(f"{card_id}: image must be a png, jpg, or webp file in images/")
            card["imageUrl"] = row["image_url"]
        cards[card_id] = card
        if boolean(row["default_wallet"], card_id + " default wallet"):
            default_wallet.append(card_id)
    if not cards:
        raise CatalogError("At least one card is required")

    rule_keys: set[tuple[str, str, str]] = set()
    for row in tables["reward_rules"]:
        card_id = row["card_id"]
        if card_id not in cards:
            raise CatalogError(f"Reward rule refers to unknown card: {card_id}")
        rule_categories = [value.strip() for value in row["category_ids"].split("|")]
        if len(set(rule_categories)) != len(rule_categories) or any(value not in category_ids for value in rule_categories):
            raise CatalogError(f"{card_id}: unknown or repeated category in reward rule")
        if row["channel"] and row["channel"] not in CHANNELS:
            raise CatalogError(f"{card_id}: unsupported payment channel")
        for category_id in rule_categories:
            key = (card_id, category_id, row["channel"])
            if key in rule_keys:
                raise CatalogError(f"{card_id}: duplicate rule for category and channel")
            rule_keys.add(key)
        rule = Rule(categories=rule_categories, rate=number(row["rate"], card_id + " reward rate"),
                    capped=boolean(row["capped"], card_id + " capped"),
                    description=required(row["description"], card_id + " rule description"))
        if rule["rate"] < cards[card_id]["base"]:
            raise CatalogError(f"{card_id}: bonus rate must not be below the base rate")
        if rule["capped"] and "cap" not in cards[card_id]:
            raise CatalogError(f"{card_id}: capped rule requires a card spending cap")
        if row["channel"]:
            rule["channel"] = row["channel"]
        cards[card_id]["rules"].append(rule)
    for card in cards.values():
        if card["unit"] == "unmodeled" and (card["base"] != 0 or card["foreignFee"] != 0 or
                            card["rules"] or "cap" in card or card["activation"] or
                            "sourceUrl" not in card):
            raise CatalogError(f"{card['id']}: catalog-only entries require a source and no modeled rewards or fees")
        if "cap" in card and not any(rule["capped"] for rule in card["rules"]):
            raise CatalogError(f"{card['id']}: spending cap requires a capped reward rule")
        if card["activation"] and not card["rules"]:
            raise CatalogError(f"{card['id']}: activation requires a reward rule")
    return Catalog(cards=list(cards.values()), categories=categories, defaultWallet=default_wallet)


def load_catalog(database: str = DEFAULT_DATABASE, schema: str = DEFAULT_SCHEMA) -> Catalog:
    return build_catalog(fetch_tables(database, schema))


class StoreLookupError(RuntimeError):
    """The nearby-store service could not answer."""


class Store(TypedDict):
    name: str
    category: str
    distance: int


class StoreResults(TypedDict):
    stores: list[Store]
    source: str


def store_category(tags: dict[str, str]) -> str | None:
    if tags.get("amenity") in AMENITY_CATEGORIES:
        return AMENITY_CATEGORIES[tags["amenity"]]
    if tags.get("tourism") in TOURISM_CATEGORIES:
        return TOURISM_CATEGORIES[tags["tourism"]]
    if "shop" in tags:
        return SHOP_CATEGORIES.get(tags["shop"], SHOP_DEFAULT_CATEGORY)
    return None


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    half_phi = (phi2 - phi1) / 2
    half_lambda = math.radians(lon2 - lon1) / 2
    return 2 * 6371000 * math.asin(math.sqrt(math.sin(half_phi) ** 2 +
                                             math.cos(phi1) * math.cos(phi2) * math.sin(half_lambda) ** 2))


def closest_stores(candidates: Iterable[Store]) -> list[Store]:
    """Keep the closest entry per named store and category, nearest first."""
    closest: dict[tuple[str, str], Store] = {}
    for store in candidates:
        key = (store["name"].casefold(), store["category"])
        if key not in closest or store["distance"] < closest[key]["distance"]:
            closest[key] = store
    return sorted(closest.values(), key=lambda store: (store["distance"], store["name"]))[:MAX_STORES]


def parse_overpass(payload: dict, latitude: float, longitude: float) -> list[Store]:
    candidates = []
    for element in payload["elements"]:
        tags = element.get("tags", {})
        name = tags.get("name", "").strip()[:120]
        category = store_category(tags)
        point = element.get("center", element)
        if name and category and "lat" in point and "lon" in point:
            candidates.append(Store(name=name, category=category, distance=round(
                distance_meters(latitude, longitude, point["lat"], point["lon"]))))
    return closest_stores(candidates)


def parse_google(payload: dict, latitude: float, longitude: float) -> list[Store]:
    candidates = []
    for place in payload.get("places", []):
        name = place.get("displayName", {}).get("text", "").strip()[:120]
        types = [place.get("primaryType"), *place.get("types", [])]
        category = next((GOOGLE_CATEGORIES[value] for value in types if value in GOOGLE_CATEGORIES), None)
        point = place.get("location", {})
        if name and category and "latitude" in point and "longitude" in point:
            candidates.append(Store(name=name, category=category, distance=round(
                distance_meters(latitude, longitude, point["latitude"], point["longitude"]))))
    return closest_stores(candidates)


def fetch_stores(request: urllib.request.Request, parse: Callable[[dict, float, float], list[Store]],
                 latitude: float, longitude: float) -> list[Store]:
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return parse(json.load(response), latitude, longitude)
    except urllib.error.HTTPError as error:
        raise StoreLookupError(f"HTTP {error.code}") from None
    except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError) as error:
        # Report only the error type: messages could echo the request, and coordinates must stay out of logs.
        raise StoreLookupError(type(error).__name__) from None


def overpass_stores(latitude: float, longitude: float, radius: float) -> list[Store]:
    around = f"(around:{radius:.0f},{latitude:.6f},{longitude:.6f})"
    amenities = "|".join(AMENITY_CATEGORIES)
    tourism = "|".join(TOURISM_CATEGORIES)
    query = (f'[out:json][timeout:10];(nwr{around}["shop"]["name"];'
             f'nwr{around}["amenity"~"^({amenities})$"]["name"];'
             f'nwr{around}["tourism"~"^({tourism})$"]["name"];);out center tags 100;')
    request = urllib.request.Request(OVERPASS_URL, data=urlencode({"data": query}).encode("ascii"),
                                     headers={"User-Agent": "Cardwise/1.0 (local rewards calculator)"})
    return fetch_stores(request, parse_overpass, latitude, longitude)


def google_stores(latitude: float, longitude: float, radius: float, key: str) -> list[Store]:
    body = {"includedTypes": list(GOOGLE_CATEGORIES), "maxResultCount": 20, "rankPreference": "DISTANCE",
            "locationRestriction": {"circle": {"center": {"latitude": latitude, "longitude": longitude},
                                               "radius": radius}}}
    request = urllib.request.Request(GOOGLE_PLACES_URL, data=json.dumps(body).encode("utf-8"), headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": GOOGLE_FIELD_MASK})
    return fetch_stores(request, parse_google, latitude, longitude)


def nearby_stores(latitude: float, longitude: float, radius: float) -> StoreResults:
    """Use Google Places when a key is set. Its daily quota or any failure falls back to OpenStreetMap."""
    key = os.environ.get("CARDWISE_GOOGLE_PLACES_KEY", "").strip()
    if key:
        try:
            return StoreResults(stores=google_stores(latitude, longitude, radius, key), source="google")
        except StoreLookupError as error:
            logging.warning("Google Places unavailable (%s); using OpenStreetMap", error)
    return StoreResults(stores=overpass_stores(latitude, longitude, radius), source="openstreetmap")


def coordinate(value: object, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not -maximum <= value <= maximum:
        raise ValueError
    return float(value)


class CardwiseServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a busy port while the first keeps answering.
    allow_reuse_address = os.name != "nt"


class CardwiseHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, load: Callable[[], Catalog] = load_catalog,
                 find_stores: Callable[[float, float, float], StoreResults] = nearby_stores, **kwargs):
        self.load = load
        self.find_stores = find_stores
        super().__init__(*args, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_json(self, status: int, payload: object, head_only: bool) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def serve(self, head_only: bool = False) -> None:
        path = urlsplit(self.path).path
        if path == "/api/catalog":
            try:
                catalog = self.load()
            except (psycopg.Error, CatalogError):
                logging.exception("Could not load the card catalog from PostgreSQL")
                self.send_json(500, {"error": "Card catalog could not be loaded. Check the server logs and database."}, head_only)
                return
            self.send_json(200, catalog, head_only)
        elif path.startswith("/api/"):
            self.send_json(404, {"error": "API endpoint not found."}, head_only)
        elif path in PUBLIC_FILES or CARD_IMAGE.fullmatch(path.removeprefix("/")):
            if head_only:
                super().do_HEAD()
            else:
                super().do_GET()
        else:
            self.send_error(404, "Not found")

    def do_GET(self) -> None:
        self.serve()

    def do_HEAD(self) -> None:
        self.serve(head_only=True)

    def do_POST(self) -> None:
        # Coordinates travel in the body so they never appear in URLs or request logs.
        if urlsplit(self.path).path != "/api/nearby-stores":
            self.send_json(404, {"error": "API endpoint not found."}, False)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "Send a JSON request."}, False)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            latitude = coordinate(body["latitude"], 90)
            longitude = coordinate(body["longitude"], 180)
            radius = coordinate(body["radius"], 1000)
            if radius < 50:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            self.send_json(400, {"error": "Send a valid latitude, longitude, and radius from 50 to 1000 meters."}, False)
            return
        try:
            results = self.find_stores(latitude, longitude, radius)
        except StoreLookupError as error:
            logging.error("Nearby store lookup failed (%s)", error)
            self.send_json(502, {"error": "Nearby stores could not be loaded. Choose a category instead."}, False)
            return
        self.send_json(200, results, False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--database", default=os.environ.get("CARDWISE_DATABASE", DEFAULT_DATABASE),
                        help="libpq connection string (default: $CARDWISE_DATABASE or %(default)s)")
    parser.add_argument("--schema", default=os.environ.get("CARDWISE_SCHEMA", DEFAULT_SCHEMA))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    handler = partial(CardwiseHandler, directory=str(ROOT), load=partial(load_catalog, args.database, args.schema))
    try:
        server = CardwiseServer((args.host, args.port), handler)
    except OSError as error:
        parser.exit(1, f"Cannot listen on {args.host}:{args.port} ({error}). Is another Cardwise server already running?\n")
    with server:
        logging.info("Cardwise running at http://%s:%s", args.host, args.port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logging.info("Stopping Cardwise")


if __name__ == "__main__":
    main()
