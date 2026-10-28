import csv
import json
import shutil
import tempfile
import threading
import unittest
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from server import ROOT, CardwiseHandler, CatalogError, load_catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        shutil.copytree(ROOT / "data", self.data)

    def edit_row(self, filename, index, **changes):
        path = self.data / filename
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            columns = reader.fieldnames
            rows = list(reader)
        rows[index].update(changes)
        with path.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def test_seed_catalog_shape_and_types(self):
        catalog = load_catalog(self.data)
        self.assertEqual(len(catalog["cards"]), 60)
        self.assertEqual(len(catalog["categories"]), 7)
        self.assertEqual(catalog["defaultWallet"], ["chase-freedom-unlimited", "capitalone-savor", "wells-active-cash"])
        self.assertEqual(sum(len(card["rules"]) for card in catalog["cards"]), 60)
        market = next(card for card in catalog["cards"] if card["id"] == "market")
        self.assertEqual(market["cap"], 6000)
        self.assertEqual(market["capPeriod"], "annual")
        self.assertIs(market["rules"][0]["capped"], True)
        self.assertNotIn("cap", catalog["cards"][0])
        self.assertIsInstance(catalog["cards"][0]["base"], float)

    def test_csv_quotes_commas_unicode_and_newlines(self):
        name = 'Example "Rewards", cafe \u00e9\nPreferred'
        self.edit_row("cards.csv", 0, name=name)
        self.assertEqual(load_catalog(self.data)["cards"][0]["name"], name)

    def test_utf8_bom_is_supported(self):
        path = self.data / "cards.csv"
        path.write_text("\ufeff" + path.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(len(load_catalog(self.data)["cards"]), 60)

    def test_real_card_sources_and_review_status(self):
        real = [card for card in load_catalog(self.data)["cards"] if "sourceUrl" in card]
        self.assertEqual(len(real), 54)
        self.assertEqual({card["issuer"] for card in real},
                         {"Citi", "Chase", "Capital One", "American Express", "Bank of America",
                          "Wells Fargo", "PNC", "U.S. Bank", "Bilt"})
        self.assertTrue(all(card["limitations"] for card in real))
        bilt = next(card for card in real if card["id"] == "bilt-blue")
        self.assertEqual(bilt["reviewedOn"], "2026-10-26")
        savor = next(card for card in real if card["id"] == "capitalone-savor")
        self.assertNotIn("reviewedOn", savor)

    def test_chase_directory_coverage(self):
        chase = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "Chase"]
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
                self.edit_row("cards.csv", 0, source_url=value, limitations="Reference only")
                with self.assertRaisesRegex(CatalogError, "public HTTPS URL"):
                    load_catalog(self.data)

    def test_citi_directory_coverage(self):
        citi = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "Citi"]
        self.assertGreaterEqual(len(citi), 25)
        identifiers = {card["id"] for card in citi}
        self.assertTrue({"citi-strata-elite", "citi-strata-premier", "citi-strata",
                         "citi-costco-anywhere", "citi-aadvantage-executive",
                         "citi-aadvantage-business", "citi-home-depot"}.issubset(identifiers))

    def test_capitalone_card_family_coverage(self):
        capitalone = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "Capital One"]
        identifiers = {card["id"] for card in capitalone}
        self.assertTrue({"capitalone-venture-x", "capitalone-venture", "capitalone-ventureone",
                         "capitalone-savor", "capitalone-quicksilver", "capitalone-platinum",
                         "capitalone-platinum-secured", "capitalone-quicksilver-secured",
                         "capitalone-savor-student", "capitalone-quicksilver-student",
                         "capitalone-venture-x-business", "capitalone-spark-cash-plus"}.issubset(identifiers))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.capitalone.com/")
                            for card in capitalone))

    def test_wells_fargo_card_family_coverage(self):
        wells = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "Wells Fargo"]
        identifiers = {card["id"] for card in wells}
        self.assertTrue({"wells-active-cash", "wells-autograph", "wells-autograph-journey",
                         "wells-reflect", "wells-attune", "wells-signify-business-cash"}.issubset(identifiers))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://") for card in wells))

    def test_bank_of_america_card_family_coverage(self):
        boa = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "Bank of America"]
        identifiers = {card["id"] for card in boa}
        self.assertTrue({"boa-unlimited-cash", "boa-customized-cash", "boa-travel-rewards",
                         "boa-premium-rewards", "boa-premium-rewards-elite", "boa-bankamericard",
                         "boa-unlimited-student", "boa-unlimited-secured", "boa-atmos-ascent",
                         "boa-business-unlimited"}.issubset(identifiers))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.bankofamerica.com/")
                            for card in boa))

    def test_discover_card_family_coverage(self):
        discover = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "Discover"]
        self.assertEqual({card["id"] for card in discover}, {
            "discover-it-cash-back", "discover-it-student-cash-back", "discover-it-secured",
            "discover-it-balance-transfer", "discover-it-chrome", "discover-it-student-chrome",
            "discover-it-miles", "discover-it-nhl", "discover-it-cash-back-good-credit",
            "discover-it-miles-good-credit", "discover-it-chrome-good-credit",
        })
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.discover.com/")
                            for card in discover))

    def test_pnc_card_family_coverage(self):
        pnc = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "PNC"]
        self.assertTrue({"pnc-cash-unlimited", "pnc-cash-rewards", "pnc-points", "pnc-core",
                         "pnc-secured"}.issubset({card["id"] for card in pnc}))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.pnc.com/") for card in pnc))

    def test_bilt_card_family_coverage(self):
        bilt = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "Bilt"]
        self.assertEqual({card["id"] for card in bilt}, {"bilt-blue", "bilt-obsidian", "bilt-palladium"})
        self.assertTrue(all(card.get("sourceUrl") == "https://www.bilt.com/card" for card in bilt))

    def test_usbank_card_family_coverage(self):
        usbank = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "U.S. Bank"]
        self.assertTrue({"usbank-altitude-connect", "usbank-altitude-go", "usbank-smartly",
                         "usbank-cash-plus", "usbank-shopper-cash", "usbank-shield"}
                        .issubset({card["id"] for card in usbank}))
        self.assertTrue(all(card.get("sourceUrl", "").startswith("https://www.usbank.com/")
                            for card in usbank))

    def test_catalog_only_entries_have_no_modeled_rates(self):
        self.edit_row("cards.csv", 59, unit="unmodeled", base="0", foreign_fee="0")
        self.assertEqual(load_catalog(self.data)["cards"][59]["unit"], "unmodeled")
        self.edit_row("cards.csv", 59, base="1")
        with self.assertRaisesRegex(CatalogError, "no modeled rewards or fees"):
            load_catalog(self.data)

    def test_amex_card_family_coverage(self):
        amex = [card for card in load_catalog(self.data)["cards"] if card["issuer"] == "American Express"]
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
        self.edit_row("cards.csv", 0, reviewed_on="2026-10-26")
        with self.assertRaisesRegex(CatalogError, "requires a source URL"):
            load_catalog(self.data)

    def test_invalid_source_review_date_rejected(self):
        self.edit_row("cards.csv", 0, source_url="https://www.citi.com/", reviewed_on="yesterday",
                      limitations="Reference only")
        with self.assertRaisesRegex(CatalogError, "YYYY-MM-DD"):
            load_catalog(self.data)

    def test_multiple_categories_per_rule(self):
        self.edit_row("reward_rules.csv", 0, category_ids="groceries|shopping")
        self.assertEqual(load_catalog(self.data)["cards"][0]["rules"][0]["categories"], ["groceries", "shopping"])

    def test_bad_numeric_values_rejected(self):
        path = self.data / "cards.csv"
        original = path.read_text(encoding="utf-8")
        for value in ("NaN", "Infinity", "-1", "abc", ""):
            with self.subTest(value=value):
                path.write_text(original, encoding="utf-8")
                self.edit_row("cards.csv", 0, base=value)
                with self.assertRaises(CatalogError):
                    load_catalog(self.data)

    def test_unknown_card_rule_rejected(self):
        self.edit_row("reward_rules.csv", 0, card_id="unknown")
        with self.assertRaisesRegex(CatalogError, "unknown card"):
            load_catalog(self.data)

    def test_unknown_category_rule_rejected(self):
        self.edit_row("reward_rules.csv", 0, category_ids="unknown")
        with self.assertRaisesRegex(CatalogError, "unknown or repeated category"):
            load_catalog(self.data)

    def test_duplicate_cards_rejected(self):
        self.edit_row("cards.csv", 1, id="everyday")
        with self.assertRaisesRegex(CatalogError, "Duplicate card"):
            load_catalog(self.data)

    def test_duplicate_categories_rejected(self):
        self.edit_row("categories.csv", 1, id="groceries")
        with self.assertRaisesRegex(CatalogError, "Duplicate category"):
            load_catalog(self.data)

    def test_duplicate_rules_rejected(self):
        self.edit_row("reward_rules.csv", 1, category_ids="groceries")
        with self.assertRaisesRegex(CatalogError, "duplicate rule"):
            load_catalog(self.data)

    def test_invalid_boolean_rejected(self):
        self.edit_row("cards.csv", 0, activation="yes")
        with self.assertRaisesRegex(CatalogError, "expected true or false"):
            load_catalog(self.data)

    def test_invalid_style_rejected(self):
        self.edit_row("cards.csv", 0, style='jade" onclick="alert(1)')
        with self.assertRaisesRegex(CatalogError, "unsupported style"):
            load_catalog(self.data)

    def test_unsafe_identifier_rejected(self):
        self.edit_row("cards.csv", 0, id='card"]')
        with self.assertRaisesRegex(CatalogError, "identifier"):
            load_catalog(self.data)

    def test_invalid_channel_rejected(self):
        self.edit_row("reward_rules.csv", 0, channel="wire")
        with self.assertRaisesRegex(CatalogError, "unsupported payment channel"):
            load_catalog(self.data)

    def test_cap_requires_period(self):
        self.edit_row("cards.csv", 3, cap_period="")
        with self.assertRaisesRegex(CatalogError, "cap must be positive"):
            load_catalog(self.data)

    def test_capped_rule_requires_card_cap(self):
        self.edit_row("reward_rules.csv", 0, capped="true")
        with self.assertRaisesRegex(CatalogError, "requires a card spending cap"):
            load_catalog(self.data)

    def test_cap_requires_capped_rule(self):
        self.edit_row("reward_rules.csv", 4, capped="false")
        with self.assertRaisesRegex(CatalogError, "requires a capped reward rule"):
            load_catalog(self.data)

    def test_bonus_below_base_rejected(self):
        self.edit_row("reward_rules.csv", 0, rate="0.5")
        with self.assertRaisesRegex(CatalogError, "below the base rate"):
            load_catalog(self.data)

    def test_missing_file_is_explicit(self):
        (self.data / "cards.csv").unlink()
        with self.assertRaises(FileNotFoundError):
            load_catalog(self.data)

    def test_wrong_headers_rejected(self):
        (self.data / "cards.csv").write_text("wrong,headers\n1,2\n", encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "expected columns"):
            load_catalog(self.data)

    def test_wrong_column_count_rejected(self):
        with (self.data / "cards.csv").open("a", encoding="utf-8") as target:
            target.write("too,few,columns\n")
        with self.assertRaisesRegex(CatalogError, "wrong column count"):
            load_catalog(self.data)

    def test_empty_catalog_rejected(self):
        path = self.data / "cards.csv"
        path.write_text(path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "At least one card"):
            load_catalog(self.data)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.temp.name) / "data"
        shutil.copytree(ROOT / "data", cls.data)
        cls.original_cards = (cls.data / "cards.csv").read_text(encoding="utf-8")
        handler = partial(CardwiseHandler, directory=str(ROOT), data_dir=cls.data)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def setUp(self):
        (self.data / "cards.csv").write_text(self.original_cards, encoding="utf-8")
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

    def test_csv_edits_are_read_without_restart(self):
        self.request("/api/catalog")
        path = self.data / "cards.csv"
        path.write_text(self.original_cards.replace("Everyday Cash", "Edited CSV Card"), encoding="utf-8")
        status, _, body = self.request("/api/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["cards"][0]["name"], "Edited CSV Card")

    def test_invalid_csv_returns_json_error_and_logs(self):
        (self.data / "cards.csv").write_text("bad,header\n", encoding="utf-8")
        with self.assertLogs(level="ERROR") as logged:
            status, _, body = self.request("/api/catalog")
        self.assertEqual(status, 500)
        self.assertIn("error", json.loads(body))
        self.assertNotIn("cards", json.loads(body))
        self.assertIn("CatalogError", logged.output[0])

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

    def test_backend_data_and_sources_are_not_public(self):
        for path in ("/data/cards.csv", "/server.py", "/test_server.py", "/../server.py", "/%2e%2e/server.py"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)


if __name__ == "__main__":
    unittest.main()
