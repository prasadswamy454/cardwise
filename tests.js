import { cards, categories, defaultState, validState, validCatalog, rankCards } from "./rewards.js";

export function runTests() {
  const results = [];
  const demoWallet = ["everyday", "voyager", "double"];
  const purchase = { amount: 100, category: "groceries", channel: "in-person", pointValue: 1, foreign: false };
  function test(name, fn) {
    try { fn(); results.push({ name, passed: true }); }
    catch (error) { results.push({ name, passed: false, error: error.message }); }
  }
  function equal(actual, expected) {
    if (actual !== expected) throw new Error(`Expected ${expected}, received ${actual}`);
  }
  function rejects(fn) {
    let threw = false;
    try { fn(); } catch { threw = true; }
    equal(threw, true);
  }
  test("Default wallet is valid", () => equal(validState(defaultState()), true));
  test("Loaded API catalog is valid", () => equal(validCatalog({ cards, categories, defaultWallet: defaultState().wallet }), true));
  test("Malformed API catalogs rejected", () => {
    const catalog = { cards, categories, defaultWallet: defaultState().wallet };
    [null, {}, { ...catalog, cards: [] }, { ...catalog, categories: [] },
      { ...catalog, defaultWallet: ["missing"] }, { ...catalog, cards: [cards[0], cards[0]] },
      { ...catalog, cards: [{ ...cards[0], base: "1" }] },
      { ...catalog, cards: [{ ...cards[0], style: 'jade" onclick="alert(1)' }] },
      { ...catalog, cards: [{ ...cards[0], rules: [{ categories: ["missing"], rate: 3, capped: false, description: "Invalid" }] }] },
    ].forEach(value => equal(validCatalog(value), false));
  });
  test("Default wallets do not share mutable selections", () => {
    const state = defaultState();
    const originalLength = state.wallet.length;
    state.wallet.push("market");
    equal(defaultState().wallet.length, originalLength);
  });
  test("Grocery recommendation and exact cash value", () => {
    const ranked = rankCards(demoWallet, purchase);
    equal(ranked[0].card.id, "everyday"); equal(ranked[0].net, 3); equal(ranked[1].net, 2);
  });
  test("Dining points beat flat cash", () => equal(rankCards(demoWallet, { ...purchase, category: "dining" })[0].card.id, "voyager"));
  test("Point valuation changes the recommendation", () => equal(rankCards(demoWallet, { ...purchase, category: "dining", pointValue: 0.5 })[0].card.id, "double"));
  test("Exact tie is preserved", () => {
    const results = rankCards(["double", "voyager"], { ...purchase, category: "travel" });
    equal(results[0].netCents, results[1].netCents);
  });
  test("Partial spending cap splits bonus and base", () => equal(rankCards(["market"], purchase, { market: { spent: 5950, activated: false } })[0].net, 3.5));
  test("Exhausted cap earns base rate", () => equal(rankCards(["market"], purchase, { market: { spent: 6000, activated: false } })[0].net, 1));
  test("Over-cap tracked spending earns base", () => equal(rankCards(["market"], purchase, { market: { spent: 7000, activated: false } })[0].net, 1));
  test("Cap does not apply to other categories", () => equal(rankCards(["market"], { ...purchase, category: "dining" })[0].net, 1));
  test("Inactive rotating category earns base", () => equal(rankCards(["flex"], purchase)[0].net, 1));
  test("Activated rotating category earns bonus", () => equal(rankCards(["flex"], purchase, { flex: { spent: 0, activated: true } })[0].net, 5));
  test("Quarterly cap splits the purchase", () => equal(rankCards(["flex"], purchase, { flex: { spent: 1490, activated: true } })[0].net, 1.4));
  test("Foreign fee changes the winner", () => {
    const result = rankCards(demoWallet, { ...purchase, foreign: true });
    equal(result[0].card.id, "voyager"); equal(result.find(item => item.card.id === "double").net, -1);
  });
  test("Portal rule requires portal channel", () => {
    equal(rankCards(["portal"], { ...purchase, category: "travel" })[0].net, 1);
    equal(rankCards(["portal"], { ...purchase, category: "travel", channel: "portal" })[0].net, 5);
  });
  test("Online rule requires online shopping", () => {
    equal(rankCards(["portal"], { ...purchase, category: "shopping", channel: "online" })[0].net, 3);
    equal(rankCards(["portal"], { ...purchase, category: "shopping" })[0].net, 1);
  });
  test("Small purchases round to currency precision", () => equal(rankCards(["double"], { ...purchase, amount: 0.25 })[0].net, 0.01));
  test("Empty wallet is supported", () => equal(rankCards([], purchase).length, 0));
  test("Invalid amounts rejected", () => [0, -1, NaN, Infinity, 1e10].forEach(amount => rejects(() => rankCards(["double"], { ...purchase, amount }))));
  test("Unknown category and payment channel rejected", () => {
    rejects(() => rankCards(["double"], { ...purchase, category: "unknown" }));
    rejects(() => rankCards(["double"], { ...purchase, channel: "unknown" }));
  });
  test("Invalid point values rejected", () => [0, NaN, 11].forEach(pointValue => rejects(() => rankCards(["double"], { ...purchase, pointValue }))));
  test("Unknown or duplicate cards rejected", () => {
    rejects(() => rankCards(["unknown"], purchase));
    rejects(() => rankCards(["double", "double"], purchase));
  });
  test("Invalid tracked spend rejected", () => rejects(() => rankCards(["market"], purchase, { market: { spent: -1, activated: false } })));
  test("Corrupt persisted state rejected", () => {
    [null, {}, { ...defaultState(), wallet: ["unknown"] }, { ...defaultState(), wallet: ["double", "double"] },
      { ...defaultState(), pointValue: "1" }, { ...defaultState(), settings: { market: { spent: -1, activated: false } } },
      { ...defaultState(), settings: [] }].forEach(state => equal(validState(state), false));
  });
  test("Comparisons never mutate cap spending", () => {
    const settings = { market: { spent: 5950, activated: false } };
    rankCards(["market"], purchase, settings); equal(settings.market.spent, 5950);
  });
  test("Real catalog covers the requested issuers with HTTPS sources", () => {
    const real = cards.filter(card => card.sourceUrl);
    ["Citi", "Chase", "Capital One", "American Express", "Bank of America", "Wells Fargo", "PNC", "U.S. Bank", "Bilt"]
      .forEach(issuer => equal(real.some(card => card.issuer === issuer), true));
    equal(real.every(card => card.sourceUrl.startsWith("https://") && card.limitations), true);
    equal(defaultState().wallet.every(id => real.some(card => card.id === id)), true);
  });
  test("Real grocery cap splits bonus and base", () => equal(rankCards(["amex-blue-cash-preferred"], purchase,
    { "amex-blue-cash-preferred": { spent: 5950, activated: false } })[0].net, 3.5));
  test("Amex gas bonus never applies to EV charging", () => {
    equal(rankCards(["amex-blue-cash-preferred"], { ...purchase, category: "gas" })[0].net, 3);
    equal(rankCards(["amex-blue-cash-preferred"], { ...purchase, category: "ev" })[0].net, 1);
  });
  test("Amex catalog includes 24 personal and business directory products", () => {
    equal(cards.filter(card => card.issuer === "American Express").length, 24);
    equal(cards.filter(card => card.issuer === "American Express" && card.unit === "unmodeled").length, 3);
  });
  test("Amex Everyday models only its supermarket cap rather than sharing independent caps", () => {
    equal(rankCards(["amex-blue-cash-everyday"], purchase)[0].gross, 3);
    equal(rankCards(["amex-blue-cash-everyday"], purchase,
      { "amex-blue-cash-everyday": { spent: 5950, activated: false } })[0].gross, 2);
    for (const category of ["gas", "ev", "shopping"]) {
      equal(rankCards(["amex-blue-cash-everyday"], { ...purchase, category, channel: "online" })[0].gross, 1);
    }
  });
  test("Amex Blue Business cards share one purchase allowance across all categories", () => {
    for (const id of ["amex-blue-business-cash", "amex-blue-business-plus"]) {
      for (const category of categories.map(category => category.id)) {
        equal(rankCards([id], { ...purchase, category })[0].gross, 2);
        equal(rankCards([id], { ...purchase, category }, { [id]: { spent: 49950, activated: false } })[0].gross, 1.5);
        equal(rankCards([id], { ...purchase, category }, { [id]: { spent: 50000, activated: false } })[0].gross, 1);
      }
    }
  });
  test("Amex Bevy dining and supermarket bonuses respect their combined cap", () => {
    for (const category of ["dining", "groceries"]) {
      equal(rankCards(["amex-marriott-bevy"], { ...purchase, category })[0].gross, 4);
      equal(rankCards(["amex-marriott-bevy"], { ...purchase, category },
        { "amex-marriott-bevy": { spent: 49950, activated: false } })[0].gross, 3);
      equal(rankCards(["amex-marriott-bevy"], { ...purchase, category },
        { "amex-marriott-bevy": { spent: 50000, activated: false } })[0].gross, 2);
    }
  });
  test("Amex Hilton Business splits its annual allowance and preserves point valuation", () => {
    equal(rankCards(["amex-hilton-business"], purchase)[0].gross, 5);
    equal(rankCards(["amex-hilton-business"], purchase,
      { "amex-hilton-business": { spent: 99950, activated: false } })[0].gross, 4);
    equal(rankCards(["amex-hilton-business"], { ...purchase, pointValue: 0.5 },
      { "amex-hilton-business": { spent: 100000, activated: false } })[0].gross, 1.5);
  });
  test("Amex hotel gas bonuses do not leak into EV charging", () => {
    for (const [id, gas, base] of [["amex-hilton", 5, 3], ["amex-hilton-surpass", 6, 3], ["amex-marriott-business", 4, 2]]) {
      equal(rankCards([id], { ...purchase, category: "gas" })[0].gross, gas);
      equal(rankCards([id], { ...purchase, category: "ev" })[0].gross, base);
    }
  });
  test("Amex merchant and travel-subtype bonuses do not apply to generic portal travel", () => {
    for (const [id, base] of [["amex-platinum", 1], ["amex-business-platinum", 1], ["amex-business-green", 1],
      ["amex-delta-gold", 1], ["amex-delta-reserve-business", 1], ["amex-hilton-surpass", 3], ["amex-marriott-brilliant", 2]]) {
      equal(rankCards([id], { ...purchase, category: "travel", channel: "portal" })[0].gross, base);
    }
  });
  test("Amex unsupported Gold and unverified Graphite terms never produce zero-reward estimates", () => {
    const wallet = ["amex-gold", "amex-business-gold", "amex-graphite-business"];
    equal(validState({ ...defaultState(), wallet }), true);
    equal(rankCards(wallet, purchase).length, 0);
    equal(rankCards([...wallet, "amex-blue-business-cash"], purchase).length, 1);
  });
  test("Chase online grocery bonus respects channel", () => {
    equal(rankCards(["chase-sapphire-preferred"], purchase)[0].gross, 1);
    equal(rankCards(["chase-sapphire-preferred"], { ...purchase, channel: "online" })[0].gross, 3);
  });
  test("U.S. Bank quarterly gas and EV cap uses tracked combined spending", () => {
    for (const category of ["gas", "ev"]) equal(rankCards(["usbank-altitude-connect"], { ...purchase, category },
      { "usbank-altitude-connect": { spent: 950, activated: false } })[0].gross, 2.5);
  });
  test("Discover catalog includes all eleven directory products", () => {
    equal(cards.filter(card => card.issuer === "Discover").length, 11);
    ["discover-it-cash-back", "discover-it-student-cash-back", "discover-it-secured",
      "discover-it-balance-transfer", "discover-it-chrome", "discover-it-student-chrome",
      "discover-it-miles", "discover-it-nhl", "discover-it-cash-back-good-credit",
      "discover-it-miles-good-credit", "discover-it-chrome-good-credit"]
      .forEach(id => equal(cards.some(card => card.id === id), true));
  });
  test("Discover Chrome variants share one quarterly gas and dining allowance", () => {
    for (const id of ["discover-it-chrome", "discover-it-student-chrome", "discover-it-chrome-good-credit"]) {
      for (const category of ["gas", "dining"]) {
        equal(rankCards([id], { ...purchase, category })[0].gross, 2);
        equal(rankCards([id], { ...purchase, category }, { [id]: { spent: 950, activated: false } })[0].gross, 1.5);
        equal(rankCards([id], { ...purchase, category }, { [id]: { spent: 1000, activated: false } })[0].gross, 1);
      }
    }
  });
  test("Discover Chrome bonuses do not leak into groceries shopping or unidentified EV stations", () => {
    for (const id of ["discover-it-chrome", "discover-it-student-chrome", "discover-it-chrome-good-credit"]) {
      for (const category of ["groceries", "shopping", "ev", "travel"]) {
        equal(rankCards([id], { ...purchase, category })[0].gross, 1);
      }
    }
  });
  test("Discover rotating-category products use only base rewards without an invented calendar", () => {
    for (const id of ["discover-it-cash-back", "discover-it-student-cash-back", "discover-it-secured",
      "discover-it-balance-transfer", "discover-it-nhl", "discover-it-cash-back-good-credit"]) {
      for (const category of categories.map(category => category.id)) {
        equal(rankCards([id], { ...purchase, category }, { [id]: { spent: 0, activated: true } })[0].gross, 1);
      }
    }
  });
  test("Discover Miles variants preserve fractional earnings without a first-year match or portal bonus", () => {
    for (const id of ["discover-it-miles", "discover-it-miles-good-credit"]) {
      equal(rankCards([id], purchase)[0].gross, 1.5);
      equal(rankCards([id], { ...purchase, category: "travel", channel: "portal" })[0].gross, 1.5);
      equal(rankCards([id], { ...purchase, pointValue: 0.5 })[0].gross, 0.75);
    }
  });
  test("Discover secured references do not inherit Chrome gas and dining rates", () => {
    for (const category of ["gas", "dining"]) {
      equal(rankCards(["discover-it-secured"], { ...purchase, category })[0].gross, 1);
    }
  });
  test("Discover cards remain valid wallet selections and use their modeled foreign fees", () => {
    const wallet = cards.filter(card => card.issuer === "Discover").map(card => card.id);
    equal(validState({ ...defaultState(), wallet }), true);
    equal(rankCards(wallet, purchase).length, 11);
    for (const id of wallet) {
      equal(rankCards([id], { ...purchase, foreign: true })[0].net, rankCards([id], purchase)[0].net);
    }
  });
  test("PNC catalog includes eight current and availability-unverified references", () => {
    equal(cards.filter(card => card.issuer === "PNC").length, 8);
    equal(cards.filter(card => card.issuer === "PNC" && card.unit === "unmodeled").length, 4);
  });
  test("PNC Cash Rewards categories share the anniversary-year allowance", () => {
    for (const [category, rate, partial] of [["gas", 4, 2.5], ["dining", 3, 2], ["groceries", 2, 1.5]]) {
      equal(rankCards(["pnc-cash-rewards"], { ...purchase, category })[0].gross, rate);
      equal(rankCards(["pnc-cash-rewards"], { ...purchase, category },
        { "pnc-cash-rewards": { spent: 7950, activated: false } })[0].gross, partial);
      equal(rankCards(["pnc-cash-rewards"], { ...purchase, category },
        { "pnc-cash-rewards": { spent: 8000, activated: false } })[0].gross, 1);
    }
    equal(rankCards(["pnc-cash-rewards"], { ...purchase, category: "ev" })[0].gross, 1);
    equal(rankCards(["pnc-cash-rewards"], { ...purchase, category: "travel", channel: "portal" })[0].gross, 1);
  });
  test("PNC flat business cash and financing-only models remain distinct", () => {
    equal(rankCards(["pnc-business-cash-rewards"], purchase)[0].gross, 1.5);
    equal(rankCards(["pnc-business-cash-rewards"], { ...purchase, foreign: true })[0].net, -1.5);
    equal(rankCards(["pnc-spend-wise"], purchase)[0].gross, 0);
  });
  test("Bilt catalog includes all three current card tiers", () => {
    equal(cards.filter(card => card.issuer === "Bilt").length, 3);
    ["bilt-blue", "bilt-obsidian", "bilt-palladium"].forEach(id => equal(cards.some(card => card.id === id), true));
  });
  test("Bilt Obsidian does not assume a selected dining or grocery category", () => {
    for (const category of ["dining", "groceries", "other"]) {
      equal(rankCards(["bilt-obsidian"], { ...purchase, category })[0].gross, 1);
    }
    equal(rankCards(["bilt-obsidian"], { ...purchase, category: "travel" })[0].gross, 2);
    equal(rankCards(["bilt-obsidian"], { ...purchase, category: "travel", channel: "portal" })[0].gross, 2);
    equal(rankCards(["bilt-obsidian"], { ...purchase, category: "travel", pointValue: 0.5, foreign: true })[0].net, 1);
  });
  test("U.S. Bank catalog includes fourteen personal business and reference products", () => {
    equal(cards.filter(card => card.issuer === "U.S. Bank").length, 14);
    equal(cards.filter(card => card.issuer === "U.S. Bank" && card.unit === "unmodeled").length, 6);
  });
  test("U.S. Bank Altitude Go variants cap dining without capping grocery or fuel bonuses", () => {
    for (const id of ["usbank-altitude-go", "usbank-altitude-go-secured"]) {
      equal(rankCards([id], { ...purchase, category: "dining" })[0].gross, 4);
      equal(rankCards([id], { ...purchase, category: "dining" },
        { [id]: { spent: 1950, activated: false } })[0].gross, 2.5);
      equal(rankCards([id], { ...purchase, category: "dining" },
        { [id]: { spent: 2000, activated: false } })[0].gross, 1);
      for (const category of ["groceries", "gas", "ev"]) {
        equal(rankCards([id], { ...purchase, category }, { [id]: { spent: 2000, activated: false } })[0].gross, 2);
      }
      equal(rankCards([id], { ...purchase, category: "travel", channel: "portal" })[0].gross, 1);
    }
  });
  test("U.S. Bank Business Connect uses one annual travel and fuel allowance", () => {
    for (const category of ["travel", "gas", "ev"]) {
      equal(rankCards(["usbank-business-altitude-connect"], { ...purchase, category })[0].gross, 4);
      equal(rankCards(["usbank-business-altitude-connect"], { ...purchase, category },
        { "usbank-business-altitude-connect": { spent: 149950, activated: false } })[0].gross, 2.5);
      equal(rankCards(["usbank-business-altitude-connect"], { ...purchase, category },
        { "usbank-business-altitude-connect": { spent: 150000, activated: false } })[0].gross, 1);
    }
    equal(rankCards(["usbank-business-altitude-connect"], { ...purchase, category: "dining" },
      { "usbank-business-altitude-connect": { spent: 150000, activated: false } })[0].gross, 2);
  });
  test("U.S. Bank models omit relationship boosts and unsupported fuel transaction bonuses", () => {
    equal(rankCards(["usbank-smartly"], purchase)[0].gross, 2);
    equal(rankCards(["usbank-smartly"], { ...purchase, foreign: true })[0].net, -1);
    equal(rankCards(["usbank-triple-cash-business"], { ...purchase, category: "dining" })[0].gross, 3);
    for (const category of ["gas", "ev"]) {
      equal(rankCards(["usbank-triple-cash-business"], { ...purchase, category })[0].gross, 1);
      equal(rankCards(["usbank-triple-cash-business"], { ...purchase, category, amount: 250 })[0].gross, 2.5);
    }
    for (const id of ["usbank-shield", "usbank-secured"]) {
      equal(rankCards([id], purchase)[0].gross, 0);
    }
  });
  test("PNC and U.S. Bank catalog-only entries remain saveable without reward estimates", () => {
    const wallet = cards.filter(card => ["PNC", "U.S. Bank"].includes(card.issuer) && card.unit === "unmodeled").map(card => card.id);
    equal(wallet.length, 10);
    equal(validState({ ...defaultState(), wallet }), true);
    equal(rankCards(wallet, purchase).length, 0);
    equal(rankCards([...wallet, "pnc-cash-unlimited"], purchase).length, 1);
  });
  test("Bilt everyday base rates do not invent housing or portal bonuses", () => {
    equal(rankCards(["bilt-blue"], purchase)[0].gross, 1);
    equal(rankCards(["bilt-palladium"], { ...purchase, category: "travel", channel: "portal" })[0].gross, 2);
  });
  test("Unsafe and incomplete real-card sources are rejected", () => {
    const catalog = { cards, categories, defaultWallet: defaultState().wallet };
    const real = cards.find(card => card.sourceUrl);
    for (const sourceUrl of ["javascript:alert(1)", "http://example.com", "https://user:password@example.com"]) {
      equal(validCatalog({ ...catalog, cards: [{ ...real, sourceUrl }] }), false);
    }
    equal(validCatalog({ ...catalog, cards: [{ ...real, limitations: "" }] }), false);
  });
  test("Chase directory includes all 43 listed personal and business products", () => {
    equal(cards.filter(card => card.issuer === "Chase").length, 43);
    ["chase-freedom-flex", "chase-sapphire-reserve", "chase-prime-visa", "chase-united-club-business",
      "chase-ihg-premier-select", "chase-hyatt-business"].forEach(id => equal(cards.some(card => card.id === id), true));
  });
  test("Citi directory includes all 25 listed product families", () => {
    equal(cards.filter(card => card.issuer === "Citi").length, 25);
    ["citi-strata-elite", "citi-strata-premier", "citi-strata", "citi-costco-anywhere",
      "citi-aadvantage-globe", "citi-home-depot"].forEach(id => equal(cards.some(card => card.id === id), true));
  });
  test("Capital One catalog includes 20 personal and business reference entries", () => {
    equal(cards.filter(card => card.issuer === "Capital One").length, 20);
    ["capitalone-venture-x", "capitalone-ventureone", "capitalone-quicksilver",
      "capitalone-quicksilver-secured", "capitalone-savor-student", "capitalone-venture-x-business",
      "capitalone-spark-cash-plus"].forEach(id => equal(cards.some(card => card.id === id), true));
  });
  test("Capital One fixed-rate reference models preserve fractional mile values", () => {
    equal(rankCards(["capitalone-venture-x"], purchase)[0].gross, 2);
    equal(rankCards(["capitalone-ventureone"], purchase)[0].gross, 1.25);
    equal(rankCards(["capitalone-quicksilver"], purchase)[0].gross, 1.5);
    equal(rankCards(["capitalone-quicksilver-secured"], purchase)[0].gross, 1.5);
  });
  test("Capital One Savor variants apply only the modeled categories", () => {
    for (const id of ["capitalone-savor", "capitalone-savor-student", "capitalone-savor-good-credit"]) {
      equal(rankCards([id], purchase)[0].gross, 3);
      equal(rankCards([id], { ...purchase, category: "dining" })[0].gross, 3);
      equal(rankCards([id], { ...purchase, category: "shopping", channel: "online" })[0].gross, 1);
    }
  });
  test("Capital One generic portal travel never receives an unsupported hotel-only bonus", () => {
    equal(rankCards(["capitalone-venture-x"], { ...purchase, category: "travel", channel: "portal" })[0].gross, 2);
    equal(rankCards(["capitalone-venture-x-business"], { ...purchase, category: "travel", channel: "portal" })[0].gross, 2);
  });
  test("Capital One Platinum earns no modeled purchase rewards", () => {
    equal(rankCards(["capitalone-platinum"], purchase)[0].gross, 0);
    equal(rankCards(["capitalone-platinum-secured"], purchase)[0].gross, 0);
  });
  test("Capital One uncertain legacy business variants are excluded rather than ranked at zero", () => {
    equal(rankCards(["capitalone-spark-cash", "capitalone-spark-miles-select"], purchase).length, 0);
    const ranked = rankCards(["capitalone-spark-cash", "capitalone-spark-cash-plus"], purchase);
    equal(ranked.length, 1);
    equal(ranked[0].gross, 2);
  });
  test("Wells Fargo catalog covers 10 core and availability-unverified references", () => {
    equal(cards.filter(card => card.issuer === "Wells Fargo").length, 10);
    equal(cards.filter(card => card.issuer === "Wells Fargo" && card.unit === "unmodeled").length, 3);
  });
  test("Wells Fargo Journey does not inherit Autograph gas or EV bonuses", () => {
    for (const category of ["dining", "travel"]) {
      equal(rankCards(["wells-autograph-journey"], { ...purchase, category })[0].gross, 3);
    }
    for (const category of ["gas", "ev"]) {
      equal(rankCards(["wells-autograph-journey"], { ...purchase, category })[0].gross, 1);
    }
  });
  test("Wells Fargo Choice bonuses exclude EV and generic hotel travel", () => {
    for (const [id, base] of [["wells-choice-privileges", 1], ["wells-choice-privileges-select", 2]]) {
      for (const category of ["groceries", "gas"]) {
        equal(rankCards([id], { ...purchase, category })[0].gross, 5);
      }
      for (const category of ["ev", "travel", "shopping"]) {
        equal(rankCards([id], { ...purchase, category, channel: "portal" })[0].gross, base);
      }
    }
  });
  test("Wells Fargo flat cash and non-rewards references stay distinct", () => {
    equal(rankCards(["wells-signify-business-cash"], purchase)[0].gross, 2);
    equal(rankCards(["wells-reflect"], purchase)[0].gross, 0);
    equal(rankCards(["wells-signify-business-cash"], { ...purchase, foreign: true })[0].net, -1);
  });
  test("Wells Fargo restricted or uncertain references are excluded from estimates", () => {
    const wallet = ["wells-attune", "wells-one-key", "wells-one-key-plus"];
    equal(validState({ ...defaultState(), wallet }), true);
    equal(rankCards(wallet, purchase).length, 0);
  });
  test("Bank of America catalog covers 22 personal and business references", () => {
    equal(cards.filter(card => card.issuer === "Bank of America").length, 22);
    equal(cards.filter(card => card.issuer === "Bank of America" && card.unit === "unmodeled").length, 9);
  });
  test("Bank of America student secured and business cash variants use ongoing rates", () => {
    for (const id of ["boa-unlimited-cash", "boa-unlimited-student", "boa-unlimited-secured", "boa-business-unlimited"]) {
      equal(rankCards([id], purchase)[0].gross, 1.5);
      equal(rankCards([id], { ...purchase, foreign: true })[0].net, -1.5);
    }
  });
  test("Bank of America travel variants preserve fractional points without portal bonuses", () => {
    for (const id of ["boa-travel-rewards", "boa-travel-student", "boa-travel-secured", "boa-business-travel"]) {
      equal(rankCards([id], { ...purchase, category: "travel", channel: "portal", pointValue: 0.5, foreign: true })[0].net, 0.75);
    }
  });
  test("Bank of America Premium variants model travel and dining without relationship boosts", () => {
    for (const id of ["boa-premium-rewards", "boa-premium-rewards-elite"]) {
      equal(rankCards([id], purchase)[0].gross, 1.5);
      for (const category of ["travel", "dining"]) {
        equal(rankCards([id], { ...purchase, category })[0].gross, 2);
      }
    }
  });
  test("Bank of America non-rewards and catalog-only cards remain distinct", () => {
    for (const id of ["boa-bankamericard", "boa-bankamericard-student", "boa-bankamericard-secured"]) {
      equal(rankCards([id], purchase)[0].gross, 0);
    }
    const wallet = cards.filter(card => card.issuer === "Bank of America" && card.unit === "unmodeled").map(card => card.id);
    equal(validState({ ...defaultState(), wallet }), true);
    equal(rankCards(wallet, purchase).length, 0);
    equal(rankCards([...wallet, "boa-unlimited-cash"], purchase).length, 1);
  });
  test("Citi Strata Premier models eligible categories without inventing generic travel bonuses", () => {
    for (const category of ["groceries", "dining", "gas", "ev"]) {
      equal(rankCards(["citi-strata-premier"], { ...purchase, category })[0].gross, 3);
    }
    equal(rankCards(["citi-strata-premier"], { ...purchase, category: "travel", channel: "portal" })[0].gross, 1);
  });
  test("Citi Strata Elite uses ordinary dining rather than assuming Citi Nights eligibility", () => {
    equal(rankCards(["citi-strata-elite"], { ...purchase, category: "dining" })[0].gross, 3);
    equal(rankCards(["citi-strata-elite"], purchase)[0].gross, 1.5);
  });
  test("Citi retail catalog entries remain selectable but are never ranked as zero-reward cards", () => {
    equal(validState({ ...defaultState(), wallet: ["citi-home-depot"] }), true);
    equal(rankCards(["citi-home-depot"], purchase).length, 0);
    equal(rankCards(["citi-home-depot", "citi-strata-premier"], purchase).length, 1);
  });
  test("Catalog-only entries are validated and excluded rather than ranked at zero", () => {
    const reference = { ...cards.find(card => card.id === "bilt-blue"), id: "catalog-only-test", unit: "unmodeled", base: 0, foreignFee: 0, rules: [] };
    equal(validCatalog({ cards: [reference], categories, defaultWallet: [] }), true);
    equal(validCatalog({ cards: [{ ...reference, base: 1 }], categories, defaultWallet: [] }), false);
    cards.push(reference);
    try {
      equal(rankCards([reference.id], purchase).length, 0);
      equal(rankCards([reference.id, "citi-double-cash"], purchase).length, 1);
      equal(rankCards([reference.id, "citi-double-cash"], purchase)[0].card.id, "citi-double-cash");
    } finally {
      cards.pop();
    }
  });
  test("Freedom Flex fixed dining does not require rotating-category activation", () => {
    equal(rankCards(["chase-freedom-flex"], { ...purchase, category: "dining" })[0].gross, 3);
    equal(rankCards(["chase-freedom-flex"], purchase)[0].gross, 1);
  });
  test("Sapphire Reserve portal rewards never apply to generic direct travel", () => {
    equal(rankCards(["chase-sapphire-reserve"], { ...purchase, category: "travel", channel: "portal" })[0].gross, 8);
    equal(rankCards(["chase-sapphire-reserve"], { ...purchase, category: "travel" })[0].gross, 1);
    equal(rankCards(["chase-sapphire-reserve"], { ...purchase, category: "dining" })[0].gross, 3);
  });
  test("Prime Visa never treats all shopping or groceries as Amazon or Whole Foods", () => {
    equal(rankCards(["chase-prime-visa"], { ...purchase, category: "shopping", channel: "online" })[0].gross, 1);
    equal(rankCards(["chase-prime-visa"], purchase)[0].gross, 1);
    equal(rankCards(["chase-prime-visa"], { ...purchase, category: "travel", channel: "portal" })[0].gross, 5);
  });
  test("Marriott combined-category caps split bonus and base points", () => {
    equal(rankCards(["chase-marriott-boundless"], purchase,
      { "chase-marriott-boundless": { spent: 5950, activated: false } })[0].gross, 2.5);
    equal(rankCards(["chase-marriott-bountiful"], purchase,
      { "chase-marriott-bountiful": { spent: 14950, activated: false } })[0].gross, 3);
  });
  test("Ink business caps use combined manually tracked spending", () => {
    equal(rankCards(["chase-ink-business-cash"], { ...purchase, category: "gas" },
      { "chase-ink-business-cash": { spent: 24950, activated: false } })[0].gross, 1.5);
    equal(rankCards(["chase-ink-business-preferred"], { ...purchase, category: "travel" },
      { "chase-ink-business-preferred": { spent: 149950, activated: false } })[0].gross, 2);
  });
  test("Southwest combined gas and grocery cap splits at the anniversary-year boundary", () => {
    for (const category of ["gas", "groceries"]) equal(rankCards(["chase-southwest-plus"], { ...purchase, category },
      { "chase-southwest-plus": { spent: 4950, activated: false } })[0].gross, 1.5);
  });
  test("New IHG cards use their own base and dining point rates", () => {
    equal(rankCards(["chase-ihg-premier-select"], { ...purchase, category: "other" })[0].gross, 3);
    equal(rankCards(["chase-ihg-premier-select"], { ...purchase, category: "dining" })[0].gross, 6);
    equal(rankCards(["chase-ihg-premier"], purchase)[0].gross, 5);
  });
  test("Unsupported merchant and top-spend bonuses stay at the disclosed base rate", () => {
    equal(rankCards(["chase-british-airways"], { ...purchase, category: "travel" })[0].gross, 1);
    equal(rankCards(["chase-hyatt-business"], { ...purchase, category: "dining" })[0].gross, 1);
    equal(rankCards(["chase-ink-business-premier"], { ...purchase, amount: 5000 })[0].gross, 100);
    equal(rankCards(["chase-slate"], purchase)[0].gross, 0);
  });
  return results;
}
