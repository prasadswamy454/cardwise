# Cardwise

A responsive credit-card rewards MVP. Native HTML, CSS, and JavaScript frontend with a Python backend and a PostgreSQL-backed catalog. No build step, bank linking, or external services.

## Run

Requires Python 3.11 or newer and a local PostgreSQL database. From this directory:

```sh
python3 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python server.py
```

Open <http://127.0.0.1:5173>. This one process serves both the app and its API. A plain `http.server` is no longer sufficient. Stop with Ctrl+C. Optionally select a different local port with `server.py --port 8000`. This is a local development server, not a production deployment server.

### Database connection

By default the server connects with `host=localhost port=5432 dbname=cardwise user=cardwise_app` and reads schema `prod`. Override with `--database "<libpq connection string>"` / `--schema <name>`, or the `CARDWISE_DATABASE` / `CARDWISE_SCHEMA` environment variables.

Never put the password in source or the connection string. Store it in a [pgpass file](https://www.postgresql.org/docs/current/libpq-pgpass.html) (`%APPDATA%\postgresql\pgpass.conf` on Windows, `~/.pgpass` elsewhere) as `localhost:5432:cardwise:cardwise_app:<password>`. The `cardwise_app` role only needs `CONNECT` on the database, `USAGE` on `prod`, and `SELECT` on its tables; the server opens read-only transactions.

One-time schema change: run [db/001_category_sort_order.sql](./db/001_category_sort_order.sql) as the table owner (for example `postgres` in pgAdmin). It adds `prod.categories.sort_order`, which sets the category display order; the first category is preselected.

## Database catalog and API

The backend queries these tables on every `GET /api/catalog` request:

- `prod.cards`: identity, issuer, appearance, reward unit, base rate, foreign transaction fee, cap, activation requirement, summary, default-wallet selection, issuer source URL, optional source-page review date, and calculation limitations.
- `prod.reward_rules`: bonus rates linked to cards and categories, channel restrictions, cap applicability, and descriptions.
- `prod.categories`: available spending categories, display icons, and `sort_order`.

**Change a row and refresh the browser to see the change; no server restart or JavaScript edits are needed.** The app fetches the catalog once at startup, before restoring saved wallet selections. Existing wallets override the default-wallet flags. Reset demo to apply changed defaults.

`GET /api/catalog` returns:

```json
{
  "cards": [
    {
      "id": "example",
      "name": "Example Card",
      "issuer": "Example Bank",
      "style": "jade",
      "unit": "cash",
      "base": 1,
      "foreignFee": 0,
      "summary": "3% on groceries",
      "activation": false,
      "rules": [
        {
          "categories": ["groceries"],
          "rate": 3,
          "capped": false,
          "description": "3% on eligible supermarkets"
        }
      ]
    }
  ],
  "categories": [{"id": "groceries", "name": "Groceries", "icon": "G"}],
  "defaultWallet": ["example"]
}
```

### Editing conventions

- Keep the existing column names. Empty text and `NULL` are treated the same.
- In the current schema `reward_rules.rate` and `cards.cap` are `integer` columns, so a fractional bonus rate (for example `1.5`) needs `rate` changed to `numeric` first. `cards.base` and `cards.foreign_fee` already accept decimals.
- IDs must begin with a lowercase letter and contain only lowercase letters, digits, or hyphens. Keep IDs stable so saved wallets continue to work.
- Use `cash` or `points` for `unit`. Cash rates and fees are percentages (enter `3`, not `0.03`); point rates are points per dollar.
- Boolean columns must be `true` or `false`, not `NULL`. `default_wallet` seeds new/reset wallets only.
- Valid styles: `jade`, `midnight`, `sand`, `plum`, `blue`, `copper`.
- Leave `cap` and `cap_period` blank for uncapped cards. Otherwise set a positive bonus-category spending cap and `annual` or `quarterly`. Mark applicable reward rules `capped=true`. Capped rules on a card share its spending allowance.
- For reward rules, separate multiple category IDs with `|`. Leave `channel` blank for all channels, or use `in-person`, `online`, or `portal`. Channel-specific rules take priority by rate among eligible rules. A bonus rate must be at least the card's base rate.
- `activation=true` requires manual activation for all of that card's bonus rules; base rewards remain available.
- Update display summaries/descriptions when changing numeric reward rules; calculations use numeric fields, not display text.
- Real-card entries require an HTTPS `source_url` and nonempty `limitations`. Set `reviewed_on` to the date the source page was actually inspected (`YYYY-MM-DD`); leave it blank for unverified reference entries. A page review is not certification that every pricing/rewards term was verified. Leave all three fields blank only for fictional examples.

The backend validates identifiers, duplicates, references, numeric ranges, booleans, caps, units, and channels before returning data; the tables have no constraints of their own, so this validation is the safety net. Invalid data, a missing table or column, or an unreachable database return HTTP 500 with a JSON error and server-side logs; unknown API routes return JSON 404. The client also validates the response, disables comparison until loading succeeds, and offers a retry on failure. There is no hardcoded-card fallback. Backend source and SQL files are not served as public assets.

## Features

- Search and filter 54 real-card reference entries from nine issuers, plus six clearly labeled fictional examples. Wallet selections persist in browser local storage.
- Compare grocery, dining, gas stations, EV charging, travel, shopping, and other purchases.
- See official issuer links, source-page review status, and card-specific eligibility/exclusions in the catalog and wallet.
- Account for online/direct/issuer-portal channels, manual points valuations, foreign transaction fees, activation, and partial spending caps.
- See exact reward estimates, alternatives, ties, negative net rewards, and calculation assumptions.
- Track bonus-category spending manually. Comparing a purchase never increments spending; quarterly/annual balances do not reset automatically.
- Responsive layout, keyboard-accessible dialogs and controls, and explicit input/storage errors.
- Reset demo restores wallet, tracked spending, point value, and purchase inputs after confirmation.

## Data limitations

### Capital One catalog

Twenty core personal/business reference entries cover Venture X, Venture, VentureOne (including a good-credit variant), Savor (standard/student/good-credit), Quicksilver (standard/good-credit/One/secured/student), Platinum/Platinum Secured, Venture X Business, Spark Cash Plus/Select, Spark Miles, and two legacy business references (Spark Cash and Spark Miles Select). This is not a verified exhaustive list of every Capital One partner/store card. The issuer pages did not expose product details during this update, so all these entries are visibly marked as unverified, with no claimed review date. Product naming, current availability, rates, fees, and eligibility must be checked with Capital One.

Eighteen entries have simple reference earning models; the two uncertain legacy business references are **catalog only** and excluded from estimates. Portal/merchant-specific multipliers, entertainment/streaming rewards, annual fees, credits, deposits, and financing benefits are not included. Miles use the shared manual cents-per-point input. Open **Manage wallet**, select **Capital One**, and clear the search to see all 20 entries. Existing wallet selections are not automatically expanded.

### Citi catalog

The catalog includes all 25 product-family listings in Citi's US [card directory](https://www.citi.com/credit-cards/view-all-credit-cards), checked October 27, 2026. Double Cash, Strata Premier, and Strata Elite have modeled rates. The other 22 entries are explicitly **catalog only**: they can be selected in a wallet but are excluded from reward estimates, not ranked as zero-reward or fee-free cards. Retail listings may cover multiple card variants; they are not claims of individually verified coverage for every variant. Each entry links to its official product page.

Strata Premier models eligible groceries, dining, gas, and EV charging at 3x, with a 1x base. Strata Elite models ordinary dining at 3x and a 1.5x base. Time-specific Citi Nights offers, travel-subtype and merchant-specific multipliers, selectable categories, and retail financing/restricted rewards are not guessed. Confirm issuer terms before using any estimate. In **Manage wallet**, select **Citi** and clear the search field to view the full listing.

**This is a reference calculator, not a verified live issuer feed or financial advice.** Real-card entries cover Citi Double Cash; 43 Chase personal and business products; Capital One Savor and Venture Rewards; Amex Blue Cash Preferred; Bank of America Unlimited Cash Rewards; Wells Fargo Active Cash and Autograph; PNC Cash Unlimited; U.S. Bank Altitude Connect; and Bilt Blue and Palladium. Official sources are linked on every real-card entry. Many entries have not been independently verified and are visibly marked as such. Always confirm current rewards, product availability, foreign fees, and eligibility with the issuer before relying on an estimate.

Chase coverage matches its [all-credit-cards directory](https://creditcards.chase.com/all-credit-cards) inspected on October 27, 2026: Freedom Flex/Unlimited/Rise; Sapphire Preferred/Reserve; Slate/Slate Edge; United Explorer/Quest/Gateway/Club; Southwest Plus/Priority/Premier; Marriott Boundless/Bountiful/Bold; IHG Premier Select/Premier/One Rewards; World of Hyatt; Disney Inspire/Premier/Visa; Prime Visa/Amazon Visa; Aeroplan; British Airways/Aer Lingus/Iberia; DoorDash; Instacart; Ink Unlimited/Cash/Preferred/Premier; Sapphire Reserve for Business; United Business/Club Business; Southwest Performance Business/Premier Business; IHG Business; and Hyatt Business. This is the currently listed directory, not every discontinued or invitation-only Chase card. Open **Manage wallet**, select **Chase**, and clear any search text to see all 43. Existing saved wallets do not automatically add new catalog entries.

The six fictional examples remain for regression tests and are labeled Demo. New/reset wallets use real reference cards; existing saved wallets are preserved. Dollar amounts use USD. Merchant classification is not inferred. Default cap spending is assumed zero until edited. The rotating-category demo remains a fixed fictional grocery offer, not a current quarterly category.

The model deliberately omits unsupported terms rather than applying a bonus too broadly. These include some hotel/car-only portal bonuses, streaming/entertainment/transit/drugstore bonuses, relationship boosts, first-year promotional rates, and Bilt housing/partner rewards. Omitted bonuses can understate a card's return and change the recommendation. Citi Double Cash assumes both purchasing and paying. Amex bonus merchants must be eligible US merchants; gas and EV are separate categories. U.S. Bank gas/EV use one combined quarterly spending cap. Housing payments are not supported purchase inputs.

Chase-specific exclusions are visible per card: Freedom Flex rotating categories are not guessed; Amazon/Whole Foods/DoorDash/Instacart/Disney and airline/hotel merchant bonuses are not applied to generic categories; direct-flight/hotel bonuses are not applied to all travel; Hyatt Business top-spend categories and Ink Premier large-purchase bonuses are omitted. Ink and Southwest anniversary-year allowances require manual tracking/reset on the card anniversary, not January 1. Some entries deliberately use only a base rate and are labeled accordingly. Disney Rewards Dollars are valued at face value for eligible restricted redemptions, not represented as unrestricted cash. Loyalty-program/status earnings are not added to co-branded card earnings. One shared point-value input cannot accurately value all airline and hotel currencies at once.

Point values are user estimates, not guaranteed cash redemption values. One shared cents-per-point input applies to every points card; it is not a card-specific redemption quote. Annual fees, interest, welcome bonuses, targeted offers, statement credits, redemption constraints, and booking-price differences are excluded. Compare only purchases you would otherwise make; rewards do not offset the costs of carrying debt.

Card details come from the backend PostgreSQL catalog; reward calculations still run in the browser. There is no account sync, bank connection, analytics, or live issuer-data feed. Wallet selections, point valuation, and manually tracked spending stay in the current browser profile and are not sent to the backend or encrypted. Do not enter sensitive card information.

### Discover Catalog

Discover has 11 reference entries matching its [credit-card directory](https://www.discover.com/credit-cards/): it Cash Back, Student Cash Back, Secured Cash Back, Balance Transfer, Chrome Gas & Restaurants, Student Chrome, Miles, NHL Discover it, and Cash Back/Miles/Chrome for Good Credit. NHL team designs are one reward-product family, not separate cards. Existing saved wallets are unchanged; filter **Discover** in **Manage wallet** to view the listing.

The three Chrome variants model 2% at eligible standalone US gas stations/restaurants on the first $1,000 combined purchases each calendar quarter, then 1%. Track/reset the shared allowance manually. Grocery/wholesale/supercenter fuel may be excluded. Only some public EV stations qualify, so the EV bonus is conservatively omitted rather than applied to all charging. Miles variants model 1.5 miles per dollar; use the redemption value for your Discover account, not an airline-mile valuation. The app's point-value control is shared across all points cards.

The six rotating-category products model only 1% base earnings. Current 5% categories, activation, merchant eligibility, and quarterly limits are not guessed; estimates may substantially understate earnings. In particular, the inspected current Secured Cash Back listing advertises rotating categories; it is not assigned the gas/dining rewards of older secured accounts or Chrome. Confirm your exact account agreement.

First-year Cashback Match/Discover Match, welcome bonuses, balance transfers, interest, deposits, introductory APR, and borrowing costs are excluded from purchase estimates. Rates and fees are unverified references with blank review dates; a directory listing does not verify every financial term. The Discover brand remains a separate issuer filter even though its current pages link Capital One applications. This is the inspected directory, not every discontinued or account-specific product.

### PNC, Bilt, and U.S. Bank Catalogs

PNC has eight reference entries: Cash Unlimited, Cash Rewards, Spend Wise, Secured, points, Core, Business Cash Rewards, and BusinessOptions. Four have models: Cash Unlimited (2%), Cash Rewards (4% gas/3% dining/2% groceries within a shared $8,000 allowance), Spend Wise (no standard purchase rewards), and Business Cash Rewards (1.5%). Cash Rewards resets on the rewards enrollment anniversary, not January 1; manually track/reset combined eligible spend. EV charging does not receive its gas bonus. Secured and BusinessOptions are catalog-only because full account terms are unverified. points and Core were absent from the inspected current personal directory and are availability-unverified, catalog-only references.

Bilt includes all three current tiers: Blue, Obsidian, and Palladium. Obsidian models 2x eligible other travel and a 1x base; its optional 3x dining OR groceries is omitted because the calculator has no category selector. It does not award 3x to both categories. Housing rewards, Bilt Cash, partner/Lyft earnings, specialized Bilt Travel hotel/flight bonuses, annual fees, and credits remain excluded. Do not enter rent or mortgage as an everyday purchase.

U.S. Bank has 14 reference entries: Smartly, Shield, Cash+, Altitude Connect, Altitude Go, Altitude Go Secured, Cash+ Secured, Secured Visa, Shopper Cash Rewards, Business Essentials, Business Essentials Plus, Business Shield, Triple Cash Rewards Business, and Business Altitude Connect. Eight have conservative models; six are catalog-only. Cash+ variants require quarterly selections; Shopper Cash Rewards has retailer selections and independent caps and was absent from the inspected core directory. Business Essentials/Plus and Business Shield are catalog-only pending full pricing verification. This is core coverage, not an exhaustive affinity, commercial, or legacy-card listing.

Smartly models only the standard 2%, not balance-based boosts. Altitude Go variants use the shared $2,000 quarterly dining allowance; their modeled grocery/gas/EV earnings are outside that allowance. Business Altitude Connect uses a shared $150,000 calendar-year travel/gas/EV allowance. Triple Cash models dining but omits fuel/EV bonuses because of unsupported per-purchase eligibility restrictions; office-supply, cell-service, and portal bonuses are also omitted. Shield and standard Secured Visa model no standard purchase rewards. Estimates can understate actual returns.

Sources: [PNC personal](https://www.pnc.com/en/personal-banking/banking/credit-cards.html), [PNC business](https://www.pnc.com/en/small-business/borrowing/business-credit-cards.html), [Bilt](https://www.bilt.com/card), [U.S. Bank personal](https://www.usbank.com/credit-cards.html), and [U.S. Bank business](https://www.usbank.com/business-banking/business-credit-cards.html). Directory presence is not verification of financial terms. New PNC/U.S. Bank rates and fees are unverified references with blank review dates. Obsidian's modeled base/travel rates and no foreign fee were checked against its official listing on October 27, 2026. Merchant eligibility and redemption requirements still apply. Catalog-only cards can be saved but never ranked. In **Manage wallet**, filter by issuer and clear search to see all entries; existing saved wallets are unchanged.

### American Express Catalog

Amex coverage includes the 13 personal and 11 business products listed in its official directories: Platinum, Gold, Blue Cash Preferred/Everyday; Delta Blue/Gold/Platinum/Reserve; Hilton Honors/Surpass/Aspire; Marriott Bevy/Brilliant; Business Platinum/Gold/Green; Graphite Business Cash Unlimited; Blue Business Cash/Plus; Delta Gold/Platinum/Reserve Business; Marriott Business; and Hilton Business. This is directory coverage, not an exhaustive list of legacy, corporate, invitation-only, or co-branded variants.

Twenty-one entries have conservative reward models. Personal Gold is catalog-only because its dining and supermarket bonuses have independent annual caps. Business Gold is catalog-only because monthly top-two category selection cannot be inferred. Graphite is catalog-only because full pricing, including foreign fees, has not been verified. Catalog-only entries can be saved but are excluded from comparisons, not assigned zero rewards.

Blue Cash Everyday models only the US supermarket allowance; its separate gas and online-retail allowances are omitted. Blue Business Cash/Plus apply one shared $50,000 annual allowance across eligible purchases. Bevy uses a shared $50,000 dining/supermarket allowance. Hilton Business models the $100,000 allowance for eligible non-Hilton purchases; Hilton bookings should not be entered as generic travel for this model. Track the relevant annual spend manually. Specialized flight/hotel, selected merchant, large-purchase, and status bonuses are not guessed. Some cards deliberately use base-only models and may substantially understate earnings.

Sources: [Amex personal cards](https://www.americanexpress.com/us/credit-cards/) and [Amex business cards](https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/). Directory presence is not verification of financial terms. Review dates remain blank and rates/fees are explicitly unverified references. US merchant restrictions and grocery exclusions apply where noted. Membership Rewards, SkyMiles, Hilton, and Bonvoy need different redemption values; the shared point-value control cannot value them independently. Annual fees, credits, interest, welcome offers, and benefits are excluded. Filter **American Express** in **Manage wallet** to see all 24 entries; saved wallets are unchanged.

### Wells Fargo and Bank of America Catalogs

Wells Fargo has 10 reference entries: Active Cash, Reflect, Autograph, Autograph Journey, Signify Business Cash, Choice Privileges, Choice Privileges Select, Attune, One Key, and One Key+. The first seven have conservative reward models. One Key uses restricted OneKeyCash and is catalog-only. Attune and One Key+ were absent from the inspected core directory and are explicitly availability-unverified, catalog-only references, not claims that new applications are open.

Bank of America has 22 reference entries: six core personal families; eight student/secured variants; Atmos Ascent and Summit; Susan G. Komen Customized Cash; Allways Rewards; Norwegian Cruise Line; and Business Advantage Unlimited Cash, Travel, and Customized Cash. Thirteen have modeled rewards, including three non-rewards BankAmericard variants. Nine are catalog-only because selectable categories/shared caps or partner rewards are not supported. This is core coverage, not an exhaustive affinity, legacy, or commercial-card directory.

Official directories: [Wells Fargo](https://creditcards.wellsfargo.com/), [Bank of America personal](https://www.bankofamerica.com/credit-cards/), and [Bank of America business](https://www.bankofamerica.com/smallbusiness/credit-cards/). Directory presence is not verification of financial terms. Review dates remain blank for these entries; rates and fees are unverified references. First-year promotions, relationship boosts, annual fees, credits, and unsupported merchant/portal bonuses are excluded. Choice hotel points and Bank of America travel points require an appropriate user-supplied redemption value; the shared point-value control cannot value different currencies independently.

In **Manage wallet**, filter by either issuer and clear the search field to see its complete listing. Existing saved wallets are unchanged. Catalog-only cards may be saved but never receive reward estimates.

## Tests

Run backend parsing and HTTP integration tests:

```sh
.venv/Scripts/python -m unittest -v test_server.py
```

The tests read the live `prod` tables once and make every edit on in-memory copies; they never write to the database. They are skipped if PostgreSQL is unreachable.

With the backend running, open <http://127.0.0.1:5173/tests.html>. The browser suite loads the database-backed catalog, then checks reward calculations, cap boundaries, activation, channel restrictions, point valuation, fees, ties, invalid inputs, saved-state validation, API/source validation, real-issuer coverage, and non-mutation. Fictional fixtures isolate the original engine tests from the real-card defaults. Real-card tests cover gas versus EV, grocery caps, online channels, combined quarterly caps, and Bilt base rates. Tests prove the modeled calculations, not the accuracy of issuer terms.

## Structure

- [index.html](./index.html): application shell and dialogs
- [styles.css](./styles.css): responsive interface
- [app.js](./app.js): wallet persistence, interactions, and rendering
- [rewards.js](./rewards.js): API loading, catalog/state validation, and deterministic calculation engine
- [server.py](./server.py): PostgreSQL reads, catalog validation, JSON API, and static asset serving
- [db/](./db/): one-time SQL changes to run against the database
- [requirements.txt](./requirements.txt): the PostgreSQL driver (`psycopg`)
- [test_server.py](./test_server.py): catalog validation and HTTP API tests
- [tests.js](./tests.js) and [tests.html](./tests.html): browser-executable tests

## Production next steps

Verify every reference entry against authorized issuer rewards and pricing terms, record effective dates, and establish an ongoing review process. Add merchant classification, card-specific point valuations, omitted benefit categories, selectable-category rules, and offer/cap-period lifecycle handling before claiming complete real-world recommendations. Add primary keys, foreign keys, `NOT NULL`, and check constraints to the `prod` tables so the database rejects bad rows itself, and give `reward_rules` an explicit order column. Add authentication and wallet storage only if users need cross-device sync; keep sensitive payment data out of this application.
