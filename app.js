import { cards, categories, defaultState, validState, rankCards, loadCatalog } from "./rewards.js";

const $ = selector => document.querySelector(selector);
const money = value => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
const escape = value => String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const storageKey = "cardwise.wallet.v1";
let state;
let catalogReady = false;

function notice(message) {
  $("#storage-notice").textContent = message;
  $("#storage-notice").hidden = false;
}

function restoreWallet() {
  state = defaultState();
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved !== null) {
      const parsed = JSON.parse(saved);
      if (validState(parsed)) state = parsed;
      else notice("Your saved wallet is invalid or references cards no longer in the catalog. The catalog’s default wallet is shown instead. Edit your wallet to save a new copy.");
    }
  } catch (error) {
    console.error("Could not load Cardwise wallet:", error);
    notice("Your saved wallet could not be loaded. Default cards are shown; changes may not persist in this browser.");
  }
}

function save() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(state));
  } catch (error) {
    console.error("Could not save Cardwise wallet:", error);
    notice("Your changes work for this session, but could not be saved. Check your browser storage permissions.");
  }
}

function cardArt(card, small = false) {
  return `<div class="credit-card ${card.style} ${small ? "mini-card" : ""}" aria-hidden="true"><div class="card-top"><span>${escape(card.issuer)}</span><span class="contactless">)))</span></div><div class="chip"></div><div class="card-bottom"><span>${escape(card.name)}</span><span class="card-symbol">◒◒</span></div></div>`;
}

function cardTerms(card) {
  if (!card.sourceUrl) return `<p class="catalog-source">Fictional example, not an issuer product.</p>`;
  return `${card.unit === "unmodeled" ? `<p class="reference-note">Catalog only. Excluded from reward estimates.</p>` : ""}<div class="catalog-source"><a href="${escape(card.sourceUrl)}" target="_blank" rel="noopener noreferrer">Official issuer terms ↗</a><span>${card.reviewedOn ? `Source page reviewed ${escape(card.reviewedOn)}` : "Reference rates · not independently verified"}</span></div><details class="card-terms"><summary>Eligibility & exclusions</summary><p>${escape(card.limitations)}</p></details>`;
}

function renderCatalog() {
  const query = $("#catalog-search").value.trim().toLowerCase();
  const issuer = $("#catalog-issuer").value;
  const matches = cards.filter(card => (!issuer || card.issuer === issuer) &&
    `${card.name} ${card.issuer} ${card.summary}`.toLowerCase().includes(query))
    .sort((first, second) => Number(Boolean(second.sourceUrl)) - Number(Boolean(first.sourceUrl)) ||
      first.issuer.localeCompare(second.issuer) || first.name.localeCompare(second.name));
  $("#catalog-count").textContent = `${matches.length} card${matches.length === 1 ? "" : "s"}`;
  $("#catalog-list").innerHTML = matches.map(card => `<div class="catalog-entry"><label class="catalog-card"><input type="checkbox" data-card="${card.id}" ${state.wallet.includes(card.id) ? "checked" : ""}><span class="catalog-swatch ${card.style}" aria-hidden="true"></span><span><strong>${escape(card.name)}${card.sourceUrl ? "" : " (Demo)"}</strong><span>${escape(card.issuer)} · ${escape(card.summary)}</span></span></label>${cardTerms(card)}</div>`).join("") || `<p class="input-help">No matching cards.</p>`;
}

function renderWallet() {
  $("#wallet-count").textContent = state.wallet.length;
  $("#wallet-total").textContent = `(${state.wallet.length})`;
  $("#wallet-cards").innerHTML = state.wallet.length ? state.wallet.map(id => {
    const card = cards.find(item => item.id === id);
    const setting = state.settings[id] ?? { spent: 0, activated: false };
    return `<article class="wallet-card">${cardArt(card)}<div class="wallet-card-info"><h3>${escape(card.name)}${card.sourceUrl ? "" : " (Demo)"}</h3><p>${escape(card.summary)}</p>${cardTerms(card)}${card.cap ? `<label class="cap-label" for="spent-${id}">Bonus-category spend this ${card.capPeriod === "annual" ? "year" : "quarter"} ($)</label><input id="spent-${id}" class="spend-input" data-spent="${id}" type="number" min="0" max="1000000000" step="0.01" value="${setting.spent}" required><p class="input-help">Assumed $0 until you update it. Does not auto-reset.</p>` : ""}${card.activation ? `<label class="checkbox-label activation"><input data-activation="${id}" type="checkbox" ${setting.activated ? "checked" : ""}> Demo bonus activated</label>` : ""}</div></article>`;
  }).join("") : `<div class="empty-wallet"><h3>A fresh start.</h3><p>Add a card to start comparing rewards.</p><button class="button secondary" id="add-first">Add your first card</button></div>`;
  $("#add-first")?.addEventListener("click", openWallet);
  renderCatalog();
}

function compare() {
  if (!catalogReady) return;
  const form = $("#purchase-form");
  const invalidSpend = [...document.querySelectorAll("[data-spent]")].find(input => !input.validity.valid);
  if (!form.checkValidity() || invalidSpend) {
    $("#input-error").textContent = invalidSpend ? "Enter valid tracked spending between $0 and $1,000,000,000 in your wallet." : "Enter an amount from $0.01 to $1,000,000,000 and a point value from 0.1 to 10¢.";
    $("#input-error").hidden = false;
    $("#results").innerHTML = `<div class="empty-results"><h2 id="results-heading">Check your details</h2><p>Correct the highlighted purchase or wallet inputs to see a reliable estimate.</p></div>`;
    return;
  }
  $("#input-error").hidden = true;
  const purchase = { amount: Number($("#amount").value), category: document.querySelector('[name="category"]:checked').value,
    channel: $("#channel").value, pointValue: Number($("#point-value").value), foreign: $("#foreign").checked };
  const ranked = rankCards(state.wallet, purchase, state.settings);
  const excluded = state.wallet.map(id => cards.find(card => card.id === id)).filter(card => card.unit === "unmodeled");
  const excludedNotice = excluded.length ? `<p class="reference-note" role="status">Excluded from estimates (catalog only): ${excluded.map(card => escape(card.name)).join(", ")}. Rewards, fees and eligibility are not modeled.</p>` : "";
  if (state.pointValue !== purchase.pointValue) {
    state.pointValue = purchase.pointValue;
    save();
  }
  if (!ranked.length) {
    $("#results").innerHTML = `<div class="empty-results"><span class="empty-symbol">▱</span><h2 id="results-heading">${excluded.length ? "No modeled rewards in this wallet" : "Your next best move starts here."}</h2><p>Add a card with modeled rewards to compare estimates.</p>${excludedNotice}<button class="button primary" id="add-result">Manage wallet</button></div>`;
    $("#add-result").addEventListener("click", openWallet);
    return;
  }
  const best = ranked[0];
  const tied = ranked.filter(result => result.netCents === best.netCents);
  const next = ranked[1];
  const category = categories.find(item => item.id === purchase.category);
  const allNegative = best.netCents < 0;
  const headline = allNegative ? "Lowest estimated cost" : tied.length > 1 ? `${tied.length} cards, equally rewarding` : "Meet your best card.";
  $("#results").innerHTML = `
    ${excludedNotice}
    <article class="winner">
      <div class="winner-top"><span class="winner-tag"><span aria-hidden="true">✦</span> ${allNegative ? "LOWEST NET LOSS" : tied.length > 1 ? "TIED FOR BEST" : "YOUR TOP PICK"}</span><span>${escape(category.name)} · ${money(purchase.amount)}</span></div>
      <h2 id="results-heading">${headline}</h2>
      ${best.card.sourceUrl ? `<p class="reference-note">${best.card.reviewedOn ? "Reference estimate; rewards and fees are subject to change." : "Unverified reference rates; confirm current issuer terms."} Some benefits and bonuses are excluded.</p>` : `<p class="reference-note">Fictional example card, not a real issuer offer.</p>`}
      <div class="winner-body"><div class="winner-card-name"><p>${escape(best.card.issuer)}</p><h3>${escape(best.card.name)}</h3><span>${escape(best.explanation)}</span></div><div class="reward-total"><span>${money(best.net)}</span><p>estimated net rewards</p></div></div>
      <div class="winner-stats"><div><strong>${best.effectiveRate.toFixed(2)}%</strong><span>reward value before fees</span></div><div><strong>${money(best.fee)}</strong><span>transaction fees</span></div></div>
      <div class="winner-insight"><span aria-hidden="true">↗</span><p>${allNegative ? "Fees outweigh rewards on every card in this wallet. Consider a fee-free payment method." : tied.length > 1 ? `Equal estimated value with ${tied.slice(1).map(result => escape(result.card.name)).join(", ")}. Choose based on your other benefits.` : next ? `<strong>${money(best.net - next.net)} more</strong> than your next-best card on this purchase.` : "Add another card to compare this estimate with alternatives."}</p></div>
    </article>
    <div class="comparison-header"><h3>The full picture</h3><span>${ranked.length} card${ranked.length === 1 ? "" : "s"} compared</span></div>
    <div class="comparison-list">${ranked.map((result, index) => `<div class="comparison-row"><span class="rank">${String(index + 1).padStart(2, "0")}</span><span class="tiny-card ${result.card.style}" aria-hidden="true"></span><div class="comparison-name"><strong>${escape(result.card.name)}</strong><span>${result.effectiveRate.toFixed(2)}% value${result.fee ? ` · ${money(result.fee)} fee` : ""}</span></div><strong class="comparison-value">${money(result.net)}${result.netCents === best.netCents ? `<span class="best-label">${tied.length > 1 ? "TIED BEST" : "BEST"}</span>` : ""}</strong></div>`).join("")}</div>
    <details class="assumptions"><summary>Behind the numbers <span aria-hidden="true">＋</span></summary><p>Category eligibility is assumed. Superstores and warehouse clubs may not qualify as supermarkets. Check each issuer’s terms.</p>${ranked.map(result => `<div><strong>${escape(result.card.name)}</strong><p>${escape(result.explanation)}. Gross rewards: ${money(result.gross)}; fees: ${money(result.fee)}.</p>${result.notes.length ? `<ul>${result.notes.map(note => `<li>${escape(note)}</li>`).join("")}</ul>` : ""}</div>`).join("")}<p>Annual fees, interest, welcome offers, and price differences between booking channels are not included. Demo rules are not current issuer offers.</p></details>`;
}

function openWallet() {
  $("#wallet-dialog").showModal();
}

$("#purchase-form").addEventListener("submit", event => { event.preventDefault(); compare(); });
$("#purchase-form").addEventListener("input", compare);
$("#purchase-form").addEventListener("change", compare);
$("#manage-top").addEventListener("click", openWallet);
$("#manage-wallet").addEventListener("click", openWallet);
$("#close-wallet").addEventListener("click", () => $("#wallet-dialog").close());
$("#done-wallet").addEventListener("click", () => $("#wallet-dialog").close());
$("#catalog-search").addEventListener("input", renderCatalog);
$("#catalog-issuer").addEventListener("change", renderCatalog);
$("#how-button").addEventListener("click", () => $("#how-dialog").showModal());
$("#close-how").addEventListener("click", () => $("#how-dialog").close());
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      event.preventDefault();
      dialog.close();
    }
  });
}
$("#catalog-list").addEventListener("change", event => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.dataset.card) return;
  state.wallet = input.checked ? [...state.wallet, input.dataset.card] : state.wallet.filter(id => id !== input.dataset.card);
  save();
  renderWallet();
  compare();
  document.querySelector(`[data-card="${input.dataset.card}"]`)?.focus();
});
$("#wallet-cards").addEventListener("input", event => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;
  const id = input.dataset.spent ?? input.dataset.activation;
  if (!id) return;
  if (!input.checkValidity()) { compare(); return; }
  const setting = state.settings[id] ?? { spent: 0, activated: false };
  state.settings[id] = { ...setting, ...(input.dataset.spent ? { spent: Number(input.value) } : { activated: input.checked }) };
  save();
  compare();
});
$("#reset-button").addEventListener("click", () => {
  if (!confirm("Reset your wallet, tracked spending, point valuation, and purchase details to the demo defaults?")) return;
  state = defaultState();
  $("#purchase-form").reset();
  $("#point-value").value = state.pointValue;
  save();
  renderWallet();
  compare();
});

async function initialize() {
  $("#retry-catalog").disabled = true;
  $("#catalog-notice").hidden = true;
  $("#results").innerHTML = `<div class="empty-results"><h2 id="results-heading">Loading card catalog…</h2><p>Getting card details and reward rules from the backend.</p></div>`;
  try {
    await loadCatalog();
  } catch (error) {
    console.error("Could not load Cardwise catalog:", error);
    $("#catalog-error").textContent = "Card details could not be loaded. Start the backend with python server.py, check the database connection, then retry.";
    $("#catalog-notice").hidden = false;
    $("#retry-catalog").disabled = false;
    $("#results").innerHTML = `<div class="empty-results"><h2 id="results-heading">Card catalog unavailable</h2><p>Comparisons are disabled until valid catalog data can be loaded. No sample fallback is used.</p></div>`;
    return;
  }
  restoreWallet();
  $("#catalog-issuer").innerHTML = `<option value="">All issuers</option>` + [...new Set(cards.map(card => card.issuer))].sort().map(issuer => `<option value="${escape(issuer)}">${escape(issuer)}</option>`).join("");
  $("#categories").innerHTML = categories.map((category, index) => `<label class="category-option"><input type="radio" name="category" value="${category.id}" ${index === 0 ? "checked" : ""}><span><span class="category-icon" aria-hidden="true">${escape(category.icon)}</span>${escape(category.name)}</span></label>`).join("");
  $("#point-value").value = state.pointValue;
  catalogReady = true;
  $("#purchase-controls").disabled = false;
  for (const selector of ["#manage-top", "#manage-wallet", "#reset-button"]) $(selector).disabled = false;
  renderWallet();
  compare();
}

$("#retry-catalog").addEventListener("click", initialize);
initialize();
