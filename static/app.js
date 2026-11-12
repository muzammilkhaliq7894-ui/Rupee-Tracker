const currencies = {
  PKR: { symbol: "₨", name: "PKR" },
  USD: { symbol: "$", name: "USD" },
  AED: { symbol: "د.إ", name: "AED" },
  SAR: { symbol: "﷼", name: "SAR" }
};
const $ = (id) => document.getElementById(id);
const amountInput = $("amount"), fromInput = $("from-currency"), toInput = $("to-currency"), feeInput = $("fee");
let rates = null;

function format(value, currency) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: currency === "PKR" ? 0 : 2 }).format(value);
}
function timeAgo(value) {
  if (!value) return "a while";
  const parsed = Date.parse(value.replace(" UTC", " GMT"));
  if (Number.isNaN(parsed)) return "recently";
  const minutes = Math.max(1, Math.floor((Date.now() - parsed) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} hr` : `${Math.floor(hours / 24)} day`;
}
const smallNumbers = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
function numberToWords(value) {
  if (value < 20) return smallNumbers[value];
  if (value < 100) return `${tens[Math.floor(value / 10)]}${value % 10 ? `-${smallNumbers[value % 10]}` : ""}`;
  if (value < 1000) return `${smallNumbers[Math.floor(value / 100)]} hundred${value % 100 ? ` ${numberToWords(value % 100)}` : ""}`;
  if (value < 1000000) return `${numberToWords(Math.floor(value / 1000))} thousand${value % 1000 ? ` ${numberToWords(value % 1000)}` : ""}`;
  if (value < 1000000000) return `${numberToWords(Math.floor(value / 1000000))} million${value % 1000000 ? ` ${numberToWords(value % 1000000)}` : ""}`;
  return `${numberToWords(Math.floor(value / 1000000000))} billion${value % 1000000000 ? ` ${numberToWords(value % 1000000000)}` : ""}`;
}
function amountInWords(value, currency) {
  const units = { PKR: ["rupee", "rupees", "paisa", "paise"], USD: ["dollar", "dollars", "cent", "cents"], AED: ["dirham", "dirhams", "fils", "fils"], SAR: ["riyal", "riyals", "halala", "halalas"] }[currency];
  const rounded = Math.round(Math.max(0, value) * 100) / 100;
  const major = Math.floor(rounded), minor = Math.round((rounded - major) * 100);
  const majorText = `${numberToWords(major)} ${major === 1 ? units[0] : units[1]}`;
  return minor ? `${majorText} and ${numberToWords(minor)} ${minor === 1 ? units[2] : units[3]}` : majorText;
}
function animateResult(value, currency) {
  const element = $("result"), start = Number(element.dataset.value || 0), duration = 300, started = performance.now();
  element.classList.remove("skeleton"); element.dataset.value = value;
  function frame(now) {
    const progress = Math.min((now - started) / duration, 1);
    element.textContent = format(start + (value - start) * (1 - Math.pow(1 - progress, 3)), currency);
    if (progress < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
function updateResult() {
  if (!rates) return;
  const amount = Math.max(0, Number(amountInput.value) || 0), from = fromInput.value, to = toInput.value;
  const gross = amount / rates[from] * rates[to], fee = Math.min(100, Math.max(0, Number(feeInput.value) || 0)), net = gross * (1 - fee / 100);
  $("amount-symbol").textContent = currencies[from].symbol;
  animateResult(net, to);
  $("result-words").textContent = amountInWords(net, to);
  $("fee-result").textContent = fee ? `${format(amount, from)} → ${format(net, to)} after ${fee}% fee` : `Before fees · ${format(gross, to)}`;
  $("rate-line").textContent = `1 ${from} = ${format(rates[to] / rates[from], to)}`;
}
function drawSparkline(history) {
  const values = history.map((item) => item[toInput.value]).filter((value) => Number.isFinite(value));
  if (values.length < 2) { $("sparkline-wrap").hidden = true; return; }
  const min = Math.min(...values), max = Math.max(...values), range = max - min || 1;
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 320},${55 - ((value - min) / range) * 45}`).join(" ");
  $("sparkline").innerHTML = `<polyline points="${points}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
  $("trend-value").textContent = `${format(values[values.length - 1] / rates.PKR, toInput.value)} / PKR`;
  $("sparkline-wrap").hidden = false;
}
async function loadData() {
  const cached = localStorage.getItem("rupee-tracker-rates");
  if (cached) { try { rates = JSON.parse(cached); updateResult(); } catch { localStorage.removeItem("rupee-tracker-rates"); } }
  try {
    const [ratesResponse, historyResponse] = await Promise.all([fetch("/api/rates"), fetch("/api/history")]);
    if (!ratesResponse.ok) throw new Error("Rates request failed");
    const data = await ratesResponse.json(); rates = data.rates; localStorage.setItem("rupee-tracker-rates", JSON.stringify(rates)); updateResult();
    $("status").textContent = `Daily rate, updated ${timeAgo(data.updated)} ago${data.stale ? " · rates may be outdated" : ""}`;
    $("status").classList.toggle("stale", data.stale); $("error").hidden = !data.stale;
    if (historyResponse.ok) drawSparkline(await historyResponse.json());
  } catch {
    $("error").hidden = false; $("status").textContent = rates ? "Using your saved rate" : "Live rates are temporarily unavailable";
    if (!rates) { $("result").classList.remove("skeleton"); $("result").textContent = "Unavailable"; }
  }
}
[amountInput, fromInput, toInput, feeInput].forEach((input) => input.addEventListener("input", updateResult));
$("swap").addEventListener("click", () => { const from = fromInput.value; fromInput.value = toInput.value; toInput.value = from; $("swap").classList.remove("rotate"); void $("swap").offsetWidth; $("swap").classList.add("rotate"); updateResult(); });
document.querySelectorAll("[data-amount]").forEach((button) => button.addEventListener("click", () => { amountInput.value = button.dataset.amount; updateResult(); }));
$("theme-toggle").addEventListener("click", () => { const light = document.documentElement.classList.toggle("light"); $("theme-toggle").textContent = light ? "☾" : "☼"; $("theme-toggle").setAttribute("aria-label", light ? "Switch to dark theme" : "Switch to light theme"); localStorage.setItem("rupee-tracker-theme", light ? "light" : "dark"); });
if (localStorage.getItem("rupee-tracker-theme") === "light") $("theme-toggle").click();
loadData();
