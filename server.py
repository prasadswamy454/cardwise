"""Serve Cardwise and a validated, CSV-backed catalog. No external dependencies."""

import argparse
import csv
import json
import logging
import math
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NotRequired, TypedDict
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
STYLES = {"jade", "midnight", "sand", "plum", "blue", "copper"}
CHANNELS = {"in-person", "online", "portal"}
PUBLIC_FILES = {"/", "/index.html", "/styles.css", "/app.js", "/rewards.js", "/tests.html", "/tests.js"}
IDENTIFIER = re.compile(r"[a-z][a-z0-9-]*")


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


class Catalog(TypedDict):
    cards: list[Card]
    categories: list[Category]
    defaultWallet: list[str]


def read_rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source, strict=True)
        if reader.fieldnames != list(columns):
            raise CatalogError(f"{path.name}: expected columns {', '.join(columns)}")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise CatalogError(f"{path.name}, line {reader.line_num}: wrong column count")
            rows.append({key: value.strip() for key, value in row.items()})
        return rows


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


def load_catalog(data_dir: Path) -> Catalog:
    categories: list[Category] = []
    category_ids: set[str] = set()
    for row in read_rows(data_dir / "categories.csv", ("id", "name", "icon")):
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
    columns = ("id", "name", "issuer", "style", "unit", "base", "foreign_fee", "summary",
               "cap", "cap_period", "activation", "default_wallet", "source_url", "reviewed_on", "limitations")
    for row in read_rows(data_dir / "cards.csv", columns):
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
        cards[card_id] = card
        if boolean(row["default_wallet"], card_id + " default wallet"):
            default_wallet.append(card_id)
    if not cards:
        raise CatalogError("At least one card is required")

    rule_keys: set[tuple[str, str, str]] = set()
    for row in read_rows(data_dir / "reward_rules.csv",
                         ("card_id", "category_ids", "channel", "rate", "capped", "description")):
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


class CardwiseHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, data_dir: Path = ROOT / "data", **kwargs):
        self.data_dir = data_dir
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
                catalog = load_catalog(self.data_dir)
            except (OSError, UnicodeError, csv.Error, CatalogError):
                logging.exception("Could not load the CSV card catalog")
                self.send_json(500, {"error": "Card catalog could not be loaded. Check the server logs and CSV files."}, head_only)
                return
            self.send_json(200, catalog, head_only)
        elif path.startswith("/api/"):
            self.send_json(404, {"error": "API endpoint not found."}, head_only)
        elif path in PUBLIC_FILES:
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    handler = partial(CardwiseHandler, directory=str(ROOT))
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        logging.info("Cardwise running at http://%s:%s", args.host, args.port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logging.info("Stopping Cardwise")


if __name__ == "__main__":
    main()
