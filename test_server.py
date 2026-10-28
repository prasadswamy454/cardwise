import copy
import json
import threading
import unittest
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import psycopg

from server import (DEFAULT_DATABASE, DEFAULT_SCHEMA, ROOT, CardwiseHandler, CatalogError, build_catalog,
                    fetch_tables, text)


def database_tables():
    """Read the live catalog once. Tests edit deep copies in memory and never write to the database."""
    try:
        return fetch_tables(DEFAULT_DATABASE, DEFAULT_SCHEMA)
    except psycopg.OperationalError as error:
        raise unittest.SkipTest(f"PostgreSQL is not reachable: {error}") from error


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = database_tables()

    def setUp(self):
        self.tables = copy.deepcopy(self.source)

    def row(self, table, **match):
        return next(row for row in self.tables[table] if all(row[key] == value for key, value in match.items()))

    def card(self, card_id):
        return next(card for card in build_catalog(self.tables)["cards"] if card["id"] == card_id)

    def test_database_catalog_shape_and_types(self):
        catalog = build_catalog(self.tables)
        self.assertEqual(len(catalog["cards"]), 180)
        self.assertEqual([category["id"] for category in catalog["categories"]],
                         ["groceries", "dining", "gas", "ev", "travel", "shopping", "other"])
        self.assertEqual(catalog["defaultWallet"], ["capitalone-savor", "chase-freedom-unlimited", "wells-active-cash"])
        self.assertEqual(sum(len(card["rules"]) for card in catalog["cards"]), 88)
        everyday = self.card("amex-blue-cash-everyday")
        self.assertEqual(everyday["cap"], 6000)
        self.assertEqual(everyday["capPeriod"], "annual")
        self.assertIs(everyday["rules"][0]["capped"], True)
        self.assertNotIn("cap", self.card("citi-double-cash"))
        self.assertIsInstance(catalog["cards"][0]["base"], float)

    def test_database_values_are_normalized_to_text(self):
        self.assertEqual(text(None), "")
        self.assertEqual(text(True), "true")
        self.assertEqual(text(False), "false")
        self.assertEqual(text(6000), "6000")
        self.assertEqual(text(1.5), "1.5")
        self.assertEqual(text("  padded  "), "padded")

    def test_quotes_commas_unicode_and_newlines_survive(self):
        name = 'Example "Rewards", cafe é\nPreferred'
        self.row("cards", id="citi-double-cash")["name"] = name
        self.assertEqual(self.card("citi-double-cash")["name"], name)

    def test_real_card_sources_and_review_status(self):
        real = [card for card in build_catalog(self.tables)["cards"] if "sourceUrl" in card]
        self.assertEqual(len(real), 180)
        self.assertEqual({card["issuer"] for card in real},
                         {"Citi", "Chase", "Capital One", "American Express", "Bank of America",
                          "Wells Fargo", "PNC", "U.S. Bank", "Bilt", "Discover"})
        self.assertTrue(all(card["limitations"] for card in real))
        self.assertEqual(self.card("bilt-blue")["reviewedOn"], "2026-10-26")
        self.assertNotIn("reviewedOn", self.card("capitalone-savor"))

    def test_chase_directory_coverage(self):
        chase = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "Chase"]
        self.assertEqual(len(chase), 43)
        identifiers = {card["id"] for card in chase}
        self.assertTrue({"chase-freedom-flex", "chase-freedom-rise", "chase-sapphire-reserve",
                         "chase-ink-business-cash", "chase-prime-visa", "chase-united-explorer",
                         "chase-hyatt-business", "chase-ihg-premier-select"}.issubset(identifiers))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://creditcards.chase.com/")
                            for card in chase))

    def test_unsafe_source_url_rejected(self):
        for value in ("javascript:alert(1)", "http://example.com", "https://user:password@example.com"):
            with self.subTest(value=value):
                self.row("cards", id="citi-double-cash")["source_url"] = value
                with self.assertRaisesRegex(CatalogError, "public HTTPS URL"):
                    build_catalog(self.tables)

    def test_citi_directory_coverage(self):
        citi = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "Citi"]
        self.assertGreaterEqual(len(citi), 25)
        identifiers = {card["id"] for card in citi}
        self.assertTrue({"citi-strata-elite", "citi-strata-premier", "citi-strata",
                         "citi-costco-anywhere", "citi-aadvantage-executive",
                         "citi-aadvantage-business", "citi-home-depot"}.issubset(identifiers))

    def test_capitalone_card_family_coverage(self):
        capitalone = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "Capital One"]
        identifiers = {card["id"] for card in capitalone}
        self.assertTrue({"capitalone-venture-x", "capitalone-venture", "capitalone-ventureone",
                         "capitalone-savor", "capitalone-quicksilver", "capitalone-platinum",
                         "capitalone-platinum-secured", "capitalone-quicksilver-secured",
                         "capitalone-savor-student", "capitalone-quicksilver-student",
                         "capitalone-venture-x-business", "capitalone-spark-cash-plus"}.issubset(identifiers))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.capitalone.com/")
                            for card in capitalone))

    def test_wells_fargo_card_family_coverage(self):
        wells = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "Wells Fargo"]
        identifiers = {card["id"] for card in wells}
        self.assertTrue({"wells-active-cash", "wells-autograph", "wells-autograph-journey",
                         "wells-reflect", "wells-attune", "wells-signify-business-cash"}.issubset(identifiers))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://") for card in wells))

    def test_bank_of_america_card_family_coverage(self):
        boa = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "Bank of America"]
        identifiers = {card["id"] for card in boa}
        self.assertTrue({"boa-unlimited-cash", "boa-customized-cash", "boa-travel-rewards",
                         "boa-premium-rewards", "boa-premium-rewards-elite", "boa-bankamericard",
                         "boa-unlimited-student", "boa-unlimited-secured", "boa-atmos-ascent",
                         "boa-business-unlimited"}.issubset(identifiers))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.bankofamerica.com/")
                            for card in boa))

    def test_discover_card_family_coverage(self):
        discover = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "Discover"]
        self.assertEqual({card["id"] for card in discover}, {
            "discover-it-cash-back", "discover-it-student-cash-back", "discover-it-secured",
            "discover-it-balance-transfer", "discover-it-chrome", "discover-it-student-chrome",
            "discover-it-miles", "discover-it-nhl", "discover-it-cash-back-good-credit",
            "discover-it-miles-good-credit", "discover-it-chrome-good-credit",
        })
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.discover.com/")
                            for card in discover))

    def test_pnc_card_family_coverage(self):
        pnc = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "PNC"]
        self.assertTrue({"pnc-cash-unlimited", "pnc-cash-rewards", "pnc-points", "pnc-core",
                         "pnc-secured"}.issubset({card["id"] for card in pnc}))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.pnc.com/") for card in pnc))

    def test_bilt_card_family_coverage(self):
        bilt = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "Bilt"]
        self.assertEqual({card["id"] for card in bilt}, {"bilt-blue", "bilt-obsidian", "bilt-palladium"})
        self.assertTrue(all(card.get("sourceUrl") == "https://www.bilt.com/card" for card in bilt))

    def test_usbank_card_family_coverage(self):
        usbank = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "U.S. Bank"]
        self.assertTrue({"usbank-altitude-connect", "usbank-altitude-go", "usbank-smartly",
                         "usbank-cash-plus", "usbank-shopper-cash", "usbank-shield"}
                        .issubset({card["id"] for card in usbank}))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.usbank.com/")
                            for card in usbank))

    def test_catalog_only_entries_have_no_modeled_rates(self):
        unmodeled = next(row for row in self.tables["cards"] if row["unit"] == "unmodeled")
        self.assertEqual(self.card(unmodeled["id"])["unit"], "unmodeled")
        unmodeled["base"] = "1"
        with self.assertRaisesRegex(CatalogError, "no modeled rewards or fees"):
            build_catalog(self.tables)

    def test_amex_card_family_coverage(self):
        amex = [card for card in build_catalog(self.tables)["cards"] if card["issuer"] == "American Express"]
        self.assertEqual(len(amex), 24)
        identifiers = {card["id"] for card in amex}
        self.assertTrue({"amex-platinum", "amex-gold", "amex-blue-cash-everyday",
                         "amex-business-platinum", "amex-business-gold",
                         "amex-delta-gold", "amex-hilton-surpass", "amex-graphite-business",
                         "amex-blue-business-plus", "amex-blue-business-cash", "amex-business-green",
                         "amex-delta-reserve-business", "amex-hilton-business",
                         "amex-marriott-business"}.issubset(identifiers))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.americanexpress.com/")
                            for card in amex))

    def test_source_metadata_requires_a_source(self):
        self.row("cards", id="bilt-blue")["source_url"] = ""
        with self.assertRaisesRegex(CatalogError, "requires a source URL"):
            build_catalog(self.tables)

    def test_invalid_source_review_date_rejected(self):
        self.row("cards", id="bilt-blue")["reviewed_on"] = "yesterday"
        with self.assertRaisesRegex(CatalogError, "YYYY-MM-DD"):
            build_catalog(self.tables)

    def test_multiple_categories_per_rule(self):
        self.row("reward_rules", card_id="amex-blue-cash-everyday")["category_ids"] = "groceries|shopping"
        self.assertEqual(self.card("amex-blue-cash-everyday")["rules"][0]["categories"], ["groceries", "shopping"])

    def test_bad_numeric_values_rejected(self):
        for value in ("NaN", "Infinity", "-1", "abc", ""):
            with self.subTest(value=value):
                self.row("cards", id="citi-double-cash")["base"] = value
                with self.assertRaises(CatalogError):
                    build_catalog(self.tables)

    def test_empty_required_value_rejected(self):
        self.row("cards", id="citi-double-cash")["name"] = text(None)
        with self.assertRaisesRegex(CatalogError, "must not be empty"):
            build_catalog(self.tables)

    def test_unknown_card_rule_rejected(self):
        self.tables["reward_rules"][0]["card_id"] = "unknown"
        with self.assertRaisesRegex(CatalogError, "unknown card"):
            build_catalog(self.tables)

    def test_unknown_category_rule_rejected(self):
        self.tables["reward_rules"][0]["category_ids"] = "unknown"
        with self.assertRaisesRegex(CatalogError, "unknown or repeated category"):
            build_catalog(self.tables)

    def test_duplicate_cards_rejected(self):
        self.tables["cards"][1]["id"] = self.tables["cards"][0]["id"]
        with self.assertRaisesRegex(CatalogError, "Duplicate card"):
            build_catalog(self.tables)

    def test_duplicate_categories_rejected(self):
        self.tables["categories"][1]["id"] = "groceries"
        with self.assertRaisesRegex(CatalogError, "Duplicate category"):
            build_catalog(self.tables)

    def test_duplicate_rules_rejected(self):
        self.tables["reward_rules"].append(dict(self.tables["reward_rules"][0]))
        with self.assertRaisesRegex(CatalogError, "duplicate rule"):
            build_catalog(self.tables)

    def test_invalid_boolean_rejected(self):
        self.row("cards", id="citi-double-cash")["activation"] = "yes"
        with self.assertRaisesRegex(CatalogError, "expected true or false"):
            build_catalog(self.tables)

    def test_invalid_style_rejected(self):
        self.row("cards", id="citi-double-cash")["style"] = 'jade" onclick="alert(1)'
        with self.assertRaisesRegex(CatalogError, "unsupported style"):
            build_catalog(self.tables)

    def test_unsafe_identifier_rejected(self):
        self.row("cards", id="citi-double-cash")["id"] = 'card"]'
        with self.assertRaisesRegex(CatalogError, "identifier"):
            build_catalog(self.tables)

    def test_invalid_channel_rejected(self):
        self.tables["reward_rules"][0]["channel"] = "wire"
        with self.assertRaisesRegex(CatalogError, "unsupported payment channel"):
            build_catalog(self.tables)

    def test_cap_requires_period(self):
        self.row("cards", id="amex-blue-cash-everyday")["cap_period"] = ""
        with self.assertRaisesRegex(CatalogError, "cap must be positive"):
            build_catalog(self.tables)

    def test_capped_rule_requires_card_cap(self):
        uncapped = {row["id"] for row in self.tables["cards"] if not row["cap"]}
        next(row for row in self.tables["reward_rules"] if row["card_id"] in uncapped)["capped"] = "true"
        with self.assertRaisesRegex(CatalogError, "requires a card spending cap"):
            build_catalog(self.tables)

    def test_cap_requires_capped_rule(self):
        for row in self.tables["reward_rules"]:
            if row["card_id"] == "amex-blue-cash-everyday":
                row["capped"] = "false"
        with self.assertRaisesRegex(CatalogError, "requires a capped reward rule"):
            build_catalog(self.tables)

    def test_bonus_below_base_rejected(self):
        self.row("reward_rules", card_id="amex-blue-cash-everyday")["rate"] = "0.5"
        with self.assertRaisesRegex(CatalogError, "below the base rate"):
            build_catalog(self.tables)

    def test_missing_table_is_explicit(self):
        with self.assertRaises(psycopg.errors.UndefinedTable):
            fetch_tables(DEFAULT_DATABASE, "missing_schema")

    def test_empty_catalog_rejected(self):
        self.tables["cards"] = []
        self.tables["reward_rules"] = []
        with self.assertRaisesRegex(CatalogError, "At least one card"):
            build_catalog(self.tables)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = database_tables()
        handler = partial(CardwiseHandler, directory=str(ROOT), load=lambda: cls.load())
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.tables = copy.deepcopy(self.source)
        type(self).load = staticmethod(lambda: build_catalog(self.tables))
        self.connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(self.connection.close)

    def request(self, path, method="GET"):
        self.connection.request(method, path)
        response = self.connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_catalog_json_contract(self):
        status, headers, body = self.request("/api/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertEqual(set(json.loads(body)), {"cards", "categories", "defaultWallet"})

    def test_database_edits_are_read_without_restart(self):
        self.request("/api/catalog")
        self.tables["cards"][0]["name"] = "Edited Database Card"
        status, _, body = self.request("/api/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["cards"][0]["name"], "Edited Database Card")

    def test_invalid_data_returns_json_error_and_logs(self):
        self.tables["cards"][0]["style"] = "unknown"
        with self.assertLogs(level="ERROR") as logged:
            status, _, body = self.request("/api/catalog")
        self.assertEqual(status, 500)
        self.assertIn("error", json.loads(body))
        self.assertNotIn("cards", json.loads(body))
        self.assertIn("CatalogError", logged.output[0])

    def test_database_failure_returns_json_error_and_logs(self):
        def unreachable():
            raise psycopg.OperationalError("connection refused")
        type(self).load = staticmethod(unreachable)
        with self.assertLogs(level="ERROR") as logged:
            status, _, body = self.request("/api/catalog")
        self.assertEqual(status, 500)
        self.assertIn("database", json.loads(body)["error"])
        self.assertIn("OperationalError", logged.output[0])

    def test_head_matches_get_without_body(self):
        status, headers, body = self.request("/api/catalog", "HEAD")
        self.assertEqual(status, 200)
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertEqual(body, b"")

    def test_unknown_api_returns_json_404(self):
        status, _, body = self.request("/api/missing")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))

    def test_app_is_served(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Cardwise", body)

    def test_backend_sources_are_not_public(self):
        for path in ("/db/001_category_sort_order.sql", "/requirements.txt", "/server.py", "/test_server.py",
                     "/../server.py", "/%2e%2e/server.py"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)


if __name__ == "__main__":
    unittest.main()
