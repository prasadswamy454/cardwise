export let categories = [];
export let cards = [];
let defaultWallet = [];

const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);
const isText = value => typeof value === "string" && value.trim().length > 0;
const isId = value => typeof value === "string" && /^[a-z][a-z0-9-]*$/.test(value);
const inRange = (value, max) => Number.isFinite(value) && value >= 0 && value <= max;

function validSource(value) {
  if (value.sourceUrl === undefined) return value.reviewedOn === undefined && value.limitations === undefined;
  try {
    const url = new URL(value.sourceUrl);
    return url.protocol === "https:" && !url.username && !url.password && isText(value.limitations) &&
      (value.reviewedOn === undefined || /^\d{4}-\d{2}-\d{2}$/.test(value.reviewedOn));
  } catch {
    return false;
  }
}

export function validCatalog(value) {
  if (!isRecord(value) || !Array.isArray(value.categories) || !value.categories.length ||
    !Array.isArray(value.cards) || !value.cards.length || !Array.isArray(value.defaultWallet)) return false;
  if (!value.categories.every(category => isRecord(category) && isId(category.id) &&
    isText(category.name) && isText(category.icon))) return false;
  const categoryIds = new Set(value.categories.map(category => category.id));
  if (categoryIds.size !== value.categories.length) return false;
  if (!value.cards.every(card => isRecord(card) && isId(card.id) &&
    isText(card.name) && isText(card.issuer) && isText(card.summary) && validSource(card) &&
    ["jade", "midnight", "sand", "plum", "blue", "copper"].includes(card.style) &&
    ["cash", "points", "unmodeled"].includes(card.unit) && inRange(card.base, 1000) && inRange(card.foreignFee, 100) &&
    typeof card.activation === "boolean" &&
    (card.cap === undefined ? card.capPeriod === undefined : inRange(card.cap, 1e9) && card.cap > 0 &&
      ["annual", "quarterly"].includes(card.capPeriod)) &&
    Array.isArray(card.rules) && card.rules.every(rule => isRecord(rule) &&
      Array.isArray(rule.categories) && rule.categories.length > 0 &&
      new Set(rule.categories).size === rule.categories.length &&
      rule.categories.every(id => categoryIds.has(id)) &&
      (rule.channel === undefined || ["in-person", "online", "portal"].includes(rule.channel)) &&
      inRange(rule.rate, 1000) && rule.rate >= card.base && isText(rule.description) &&
      typeof rule.capped === "boolean" && (!rule.capped || card.cap !== undefined)) &&
    (card.cap === undefined || card.rules.some(rule => rule.capped)) &&
    (!card.activation || card.rules.length > 0) &&
    (card.unit !== "unmodeled" || (card.base === 0 && card.foreignFee === 0 && !card.activation &&
      card.cap === undefined && card.rules.length === 0 && card.sourceUrl !== undefined)))) return false;
  const cardIds = new Set(value.cards.map(card => card.id));
  return cardIds.size === value.cards.length && new Set(value.defaultWallet).size === value.defaultWallet.length &&
    value.defaultWallet.every(id => cardIds.has(id));
}

export async function loadCatalog() {
  const response = await fetch("/api/catalog", { cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error(`Catalog request failed (HTTP ${response.status}).`);
  const catalog = await response.json();
  if (!validCatalog(catalog)) throw new Error("The server returned an invalid card catalog.");
  categories = catalog.categories;
  cards = catalog.cards;
  defaultWallet = catalog.defaultWallet;
}

export function defaultState() {
  return { version: 1, wallet: [...defaultWallet], settings: {}, pointValue: 1 };
}

export function validState(value) {
  return value !== null && typeof value === "object" && value.version === 1 &&
    Array.isArray(value.wallet) && value.wallet.every(id => cards.some(card => card.id === id)) &&
    new Set(value.wallet).size === value.wallet.length &&
    Number.isFinite(value.pointValue) && value.pointValue >= 0.1 && value.pointValue <= 10 &&
    value.settings !== null && typeof value.settings === "object" && !Array.isArray(value.settings) &&
    Object.entries(value.settings).every(([id, setting]) =>
      cards.some(card => card.id === id) && setting !== null && typeof setting === "object" &&
      Number.isFinite(setting.spent) && setting.spent >= 0 && setting.spent <= 1e9 &&
      typeof setting.activated === "boolean");
}

export function rankCards(wallet, purchase, settings = {}) {
  if (!Array.isArray(wallet) || new Set(wallet).size !== wallet.length ||
    wallet.some(id => !cards.some(card => card.id === id))) throw new Error("Choose valid, unique cards.");
  if (!Number.isFinite(purchase.amount) || purchase.amount <= 0 || purchase.amount > 1e9 ||
    !categories.some(category => category.id === purchase.category) ||
    !["in-person", "online", "portal"].includes(purchase.channel) ||
    !Number.isFinite(purchase.pointValue) || purchase.pointValue < 0.1 || purchase.pointValue > 10 ||
    typeof purchase.foreign !== "boolean") throw new Error("Enter valid purchase details.");

  return wallet.filter(id => cards.find(card => card.id === id).unit !== "unmodeled").map(id => {
    const card = cards.find(item => item.id === id);
    const setting = settings[id] ?? { spent: 0, activated: false };
    if (!Number.isFinite(setting.spent) || setting.spent < 0 || setting.spent > 1e9 ||
      typeof setting.activated !== "boolean") throw new Error("Enter valid card spending and activation settings.");
    const eligible = card.rules.filter(rule => rule.categories.includes(purchase.category) &&
      (!rule.channel || rule.channel === purchase.channel) && (!card.activation || setting.activated));
    const rule = eligible.sort((a, b) => b.rate - a.rate)[0];
    const rate = rule?.rate ?? card.base;
    const remaining = card.cap === undefined ? null : Math.max(0, card.cap - setting.spent);
    const bonusAmount = rule?.capped ? Math.min(purchase.amount, remaining) : purchase.amount;
    const units = (bonusAmount * rate + (purchase.amount - bonusAmount) * card.base) / (card.unit === "cash" ? 100 : 1);
    const gross = card.unit === "cash" ? units : units * purchase.pointValue / 100;
    const fee = purchase.foreign ? purchase.amount * card.foreignFee / 100 : 0;
    // Rank at displayed currency precision so visually equal rewards are true ties.
    const netCents = Math.round((gross - fee + Number.EPSILON) * 100);
    const notes = [];
    if (card.limitations) notes.push(card.limitations);
    if (card.sourceUrl && !card.reviewedOn) notes.push("Unverified reference rates. Confirm current issuer rewards and fees before relying on this estimate.");
    if (card.cap) notes.push(`${remaining.toLocaleString("en-US")} USD of ${card.capPeriod} bonus allowance remains, based on manually tracked spending.`);
    if (rule?.capped && bonusAmount < purchase.amount) notes.push("This purchase crosses or exceeds the bonus cap; the remainder earns the base rate.");
    if (card.activation && !setting.activated) notes.push("Bonus is not activated. Base rewards apply.");
    if (card.unit === "points") notes.push(`Points valued at ${purchase.pointValue}¢ each, using your estimate.`);
    if (purchase.foreign) notes.push(card.foreignFee ? `${card.foreignFee}% foreign transaction fee deducted.` : "No foreign transaction fee in this demo.");
    if (purchase.channel === "portal") notes.push("Portal bonuses apply only through the issuing card’s own portal; compare booking prices separately.");
    return { card, rate, gross, fee, netCents, net: netCents / 100, effectiveRate: gross / purchase.amount * 100,
      explanation: rule?.description ?? `${card.base}${card.unit === "cash" ? "% cash back" : " point per dollar"} base rewards`,
      notes };
  }).sort((a, b) => b.netCents - a.netCents || a.card.name.localeCompare(b.card.name));
}
