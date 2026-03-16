/* script-v2.js - Logique dédiée à la vue Win Probability (pre-match + live). */

const CONFIG = {
  FACEIT_NICKNAME: "",
  REFRESH_INTERVAL_MS: 60000,
  PROXY_BASE_URL:
    typeof window !== "undefined" && window.location?.hostname
      ? `${window.location.protocol}//${window.location.hostname}:8787`
      : "http://127.0.0.1:8787",
  FETCH_TIMEOUT_MS: 12000,
  WINPROB_MATCH_ID: "",
  WINPROB_FETCH_TIMEOUT_MS: 45000,
  LIVE_WINPROB_FETCH_TIMEOUT_MS: 45000,
  LIVE_SCORE_CHECK_INTERVAL_MS: 7000
};

applyRuntimeOverridesFromQuery(CONFIG);

const ACTIVE_MATCH_STATUSES = new Set([
  "ongoing",
  "in_progress",
  "started",
  "ready",
  "configuring",
  "live",
  "voting",
  "captains_picking"
]);

const DOM = {
  winprobSection: document.getElementById("winprob-section"),
  winprobLoader: document.getElementById("winprob-loader"),
  winprobError: document.getElementById("winprob-error"),
  winprobBadge: document.getElementById("winprob-badge"),
  winprobValue: document.getElementById("winprob-value"),
  winprobMeta: document.getElementById("winprob-meta"),
  liveWinprobBadge: document.getElementById("live-winprob-badge"),
  liveWinprobValue: document.getElementById("live-winprob-value"),
  liveWinprobMeta: document.getElementById("live-winprob-meta")
};

const RUNTIME = {
  resolvedMatchId: "",
  lastLiveWinprobPct: Number.NaN,
  lastObservedLiveScoreKey: "",
  lastObservedLiveScoreMatchId: ""
};

let refreshTimer = null;
let liveScoreTimer = null;
let isRefreshing = false;
let isLiveWinprobRefreshing = false;
let isLiveScorePolling = false;

document.addEventListener("DOMContentLoaded", () => {
  void initWidget();
});

window.addEventListener("beforeunload", () => {
  stopAutoRefresh();
  stopLiveScoreWatcher();
});

async function initWidget() {
  renderWinProbability(null);
  renderLiveWinProbability(null);
  setSectionError("");

  try {
    await loadAllData();
  } finally {
    startAutoRefresh();
    startLiveScoreWatcher();
  }
}

async function loadAllData() {
  if (isRefreshing) {
    return;
  }

  isRefreshing = true;
  setSectionLoading(true);
  setSectionError("");

  try {
    const preMatchResult = await fetchWinProbability();

    renderWinProbability(preMatchResult);

    if (preMatchResult?.no_active_match === true) {
      renderLiveWinProbability({ no_active_match: true });
    } else {
      // Même logique que l'index principal:
      // on ne recalcule pas le live à chaque refresh global.
      // Le refresh live + delta est déclenché uniquement au changement de score.
      if (!Number.isFinite(asFiniteNumber(RUNTIME.lastLiveWinprobPct))) {
        await refreshLiveWinProbability({ withLoader: false, clearError: false });
      }
    }
  } catch (error) {
    renderWinProbability(null);
    renderLiveWinProbability(null);
    setSectionError(toFriendlyError(error));
  } finally {
    setSectionLoading(false);
    isRefreshing = false;
  }
}

async function fetchWinProbability() {
  const nickname = String(CONFIG.FACEIT_NICKNAME || "").trim();
  if (!nickname) {
    throw new Error("FACEIT_NICKNAME manquant pour la win probability.");
  }

  const proxyBase = String(CONFIG.PROXY_BASE_URL || "").trim();
  if (!proxyBase) {
    throw new Error("PROXY_BASE_URL requis pour récupérer la win probability locale.");
  }

  const url = new URL("win-probability", ensureTrailingSlash(proxyBase));
  url.searchParams.set("nickname", nickname);
  const matchId = getEffectiveMatchId();
  if (matchId) {
    url.searchParams.set("match_id", matchId);
  }

  let payload;
  try {
    payload = await fetchJson(
      url,
      { Accept: "application/json" },
      asFiniteNumber(CONFIG.WINPROB_FETCH_TIMEOUT_MS)
    );
  } catch (error) {
    if (isNoActiveMatchError(error)) {
      return {
        ok: true,
        no_active_match: true,
        win_probability: null
      };
    }
    throw error;
  }

  if (!isPlainObject(payload)) {
    throw new Error("Réponse win probability invalide.");
  }

  if (payload.ok === false) {
    if (isNoActiveMatchPayload(payload)) {
      return {
        ...payload,
        no_active_match: true,
        win_probability: null
      };
    }
    throw new Error(String(payload.error || "Calcul win probability impossible."));
  }

  const returnedMatchId = String(payload.match_id || payload.matchId || "").trim();
  if (!String(CONFIG.WINPROB_MATCH_ID || "").trim() && returnedMatchId) {
    setResolvedMatchId(returnedMatchId);
  }

  return payload;
}

async function fetchLiveWinProbability() {
  const nickname = String(CONFIG.FACEIT_NICKNAME || "").trim();
  if (!nickname) {
    throw new Error("FACEIT_NICKNAME manquant pour la live win probability.");
  }

  const proxyBase = String(CONFIG.PROXY_BASE_URL || "").trim();
  if (!proxyBase) {
    throw new Error("PROXY_BASE_URL requis pour récupérer la live win probability locale.");
  }

  const url = new URL("live-win-probability", ensureTrailingSlash(proxyBase));
  url.searchParams.set("nickname", nickname);
  const matchId = getEffectiveMatchId();
  if (matchId) {
    url.searchParams.set("match_id", matchId);
  }

  let payload;
  try {
    payload = await fetchJson(
      url,
      { Accept: "application/json" },
      asFiniteNumber(CONFIG.LIVE_WINPROB_FETCH_TIMEOUT_MS)
    );
  } catch (error) {
    if (isNoActiveMatchError(error)) {
      return {
        ok: true,
        no_active_match: true,
        dynamic_win_probability: null
      };
    }
    throw error;
  }

  if (!isPlainObject(payload)) {
    throw new Error("Réponse live win probability invalide.");
  }

  if (payload.ok === false) {
    if (isNoActiveMatchPayload(payload)) {
      return {
        ...payload,
        no_active_match: true,
        dynamic_win_probability: null
      };
    }
    throw new Error(String(payload.error || "Calcul live win probability impossible."));
  }

  const returnedMatchId = String(payload.match_id || payload.matchId || "").trim();
  if (!String(CONFIG.WINPROB_MATCH_ID || "").trim() && returnedMatchId) {
    setResolvedMatchId(returnedMatchId);
  }

  return payload;
}

async function refreshLiveWinProbability(options = {}) {
  if (isLiveWinprobRefreshing) {
    return;
  }

  const withLoader = Boolean(options.withLoader);
  const clearError = options.clearError !== false;
  isLiveWinprobRefreshing = true;

  if (withLoader) {
    setSectionLoading(true);
  }
  if (clearError) {
    setSectionError("");
  }

  try {
    const payload = await fetchLiveWinProbability();
    syncScoreWatcherFromLivePayload(payload);
    renderLiveWinProbability(payload);
  } catch (error) {
    if (isNoActiveMatchError(error)) {
      renderLiveWinProbability({ no_active_match: true });
      return;
    }
    renderLiveWinProbability(null);
    setSectionError(toFriendlyError(error));
  } finally {
    if (withLoader) {
      setSectionLoading(false);
    }
    isLiveWinprobRefreshing = false;
  }
}

async function checkLiveScoreAndRefresh(options = {}) {
  if (isLiveScorePolling) {
    return;
  }

  const clearError = options.clearError !== false;
  isLiveScorePolling = true;

  try {
    const snapshot = await fetchLiveScoreSnapshot();
    if (snapshot?.no_active_match === true) {
      renderLiveWinProbability({ no_active_match: true });
      return;
    }

    const scoreKey = String(snapshot?.scoreKey || "").trim();
    const matchId = String(snapshot?.matchId || "").trim();
    if (!scoreKey || !matchId) {
      return;
    }

    if (
      !RUNTIME.lastObservedLiveScoreKey ||
      !RUNTIME.lastObservedLiveScoreMatchId ||
      RUNTIME.lastObservedLiveScoreMatchId !== matchId
    ) {
      RUNTIME.lastObservedLiveScoreMatchId = matchId;
      RUNTIME.lastObservedLiveScoreKey = scoreKey;
      return;
    }

    if (RUNTIME.lastObservedLiveScoreKey !== scoreKey) {
      RUNTIME.lastObservedLiveScoreKey = scoreKey;
      await refreshLiveWinProbability({ withLoader: false, clearError });
    }
  } catch (error) {
    if (clearError) {
      setSectionError(toFriendlyError(error));
    }
  } finally {
    isLiveScorePolling = false;
  }
}

async function fetchLiveScoreSnapshot() {
  const matchId = getEffectiveMatchId();
  if (!matchId) {
    return { ok: true, no_active_match: true };
  }

  let payload;
  try {
    payload = await apiFetch("faceit", `matches/${encodeURIComponent(matchId)}`);
  } catch (error) {
    if (isHttp404Like(error) || isNoActiveMatchError(error)) {
      return { ok: true, no_active_match: true, matchId };
    }
    throw error;
  }

  const status = String(payload?.status || payload?.match_status || payload?.state || "").trim().toLowerCase();
  const hasFinishedAt = Boolean(payload?.finished_at || payload?.finishedAt);
  if ((status && !ACTIVE_MATCH_STATUSES.has(status)) || hasFinishedAt) {
    return { ok: true, no_active_match: true, matchId };
  }

  const parsedScore = extractScoreFromMatchPayload(payload);
  return {
    ok: true,
    no_active_match: false,
    matchId,
    scoreA: parsedScore?.scoreA ?? Number.NaN,
    scoreB: parsedScore?.scoreB ?? Number.NaN,
    scoreKey: parsedScore?.scoreKey || ""
  };
}

function extractScoreFromMatchPayload(payload) {
  if (!isPlainObject(payload)) {
    return null;
  }

  const results = isPlainObject(payload.results) ? payload.results : {};
  const scoreMap = isPlainObject(results.score) ? results.score : {};

  const faction1 = toScoreInteger(scoreMap.faction1);
  const faction2 = toScoreInteger(scoreMap.faction2);
  if (Number.isFinite(faction1) || Number.isFinite(faction2)) {
    const scoreA = Number.isFinite(faction1) ? faction1 : 0;
    const scoreB = Number.isFinite(faction2) ? faction2 : 0;
    return { scoreA, scoreB, scoreKey: buildScoreWatchKey(scoreA, scoreB) };
  }

  const teams = isPlainObject(payload.teams) ? payload.teams : {};
  const teamFaction1 = toScoreInteger(teams?.faction1?.score);
  const teamFaction2 = toScoreInteger(teams?.faction2?.score);
  if (Number.isFinite(teamFaction1) || Number.isFinite(teamFaction2)) {
    const scoreA = Number.isFinite(teamFaction1) ? teamFaction1 : 0;
    const scoreB = Number.isFinite(teamFaction2) ? teamFaction2 : 0;
    return { scoreA, scoreB, scoreKey: buildScoreWatchKey(scoreA, scoreB) };
  }

  const scoreCandidates = Object.values(scoreMap)
    .map((value) => toScoreInteger(value))
    .filter((value) => Number.isFinite(value));
  if (scoreCandidates.length >= 2) {
    const scoreA = scoreCandidates[0];
    const scoreB = scoreCandidates[1];
    return { scoreA, scoreB, scoreKey: buildScoreWatchKey(scoreA, scoreB) };
  }

  return null;
}

function syncScoreWatcherFromLivePayload(payload) {
  const matchId = String(payload?.match_id || payload?.matchId || getEffectiveMatchId() || "").trim();
  if (!matchId) {
    return;
  }

  const scoreOur = toScoreInteger(payload?.score_our ?? payload?.scoreOur);
  const scoreEnemy = toScoreInteger(payload?.score_enemy ?? payload?.scoreEnemy);
  if (!Number.isFinite(scoreOur) || !Number.isFinite(scoreEnemy)) {
    return;
  }

  RUNTIME.lastObservedLiveScoreMatchId = matchId;
  RUNTIME.lastObservedLiveScoreKey = buildScoreWatchKey(scoreOur, scoreEnemy);
}

function renderWinProbability(payload) {
  if (!DOM.winprobBadge || !DOM.winprobValue || !DOM.winprobMeta) {
    return;
  }

  if (payload?.no_active_match === true) {
    DOM.winprobBadge.style.setProperty("--winprob-accent", "#888888");
    DOM.winprobValue.textContent = "--%";
    DOM.winprobMeta.textContent = "Aucune partie en cours";
    return;
  }

  let probability = firstFiniteNumber(
    payload?.win_probability,
    payload?.winProbability,
    payload?.probability,
    payload?.win_probability_pct,
    payload?.winProbabilityPct
  );

  if (Number.isFinite(probability) && probability > 1 && probability <= 100) {
    probability /= 100;
  }

  if (!Number.isFinite(probability)) {
    DOM.winprobBadge.style.setProperty("--winprob-accent", "#888888");
    DOM.winprobValue.textContent = "--%";
    DOM.winprobMeta.textContent = "Aucune partie en cours";
    return;
  }

  const clamped = Math.max(0, Math.min(1, probability));
  const pct = clamped * 100;
  const accent = getWinprobColor(pct);

  DOM.winprobBadge.style.setProperty("--winprob-accent", accent);
  DOM.winprobValue.textContent = `${pct.toFixed(1).replace(".", ",")}%`;
  DOM.winprobMeta.textContent = "";
}

function renderLiveWinProbability(payload) {
  if (!DOM.liveWinprobBadge || !DOM.liveWinprobValue || !DOM.liveWinprobMeta) {
    return;
  }

  if (payload?.no_active_match === true) {
    DOM.liveWinprobBadge.style.setProperty("--winprob-accent", "#888888");
    DOM.liveWinprobValue.textContent = "--%";
    DOM.liveWinprobMeta.textContent = "Aucune partie en cours";
    clearLiveWinprobDelta();
    RUNTIME.lastLiveWinprobPct = Number.NaN;
    resetLiveScoreWatcherState();
    return;
  }

  let probability = firstFiniteNumber(
    payload?.dynamic_win_probability,
    payload?.dynamicWinProbability,
    payload?.dynamic_win_probability_pct,
    payload?.dynamicWinProbabilityPct
  );

  if (Number.isFinite(probability) && probability > 1 && probability <= 100) {
    probability /= 100;
  }

  if (!Number.isFinite(probability)) {
    DOM.liveWinprobBadge.style.setProperty("--winprob-accent", "#888888");
    DOM.liveWinprobValue.textContent = "--%";
    DOM.liveWinprobMeta.textContent = "Live indisponible";
    clearLiveWinprobDelta();
    RUNTIME.lastLiveWinprobPct = Number.NaN;
    return;
  }

  const clamped = Math.max(0, Math.min(1, probability));
  const pct = clamped * 100;
  const accent = getWinprobColor(pct);
  const previousPct = asFiniteNumber(RUNTIME.lastLiveWinprobPct);
  const hasPrevious = Number.isFinite(previousPct);
  const deltaPct = hasPrevious ? pct - previousPct : Number.NaN;

  DOM.liveWinprobBadge.style.setProperty("--winprob-accent", accent);
  DOM.liveWinprobValue.textContent = `${pct.toFixed(1).replace(".", ",")}%`;
  applyLiveWinprobDelta(deltaPct, hasPrevious);
  DOM.liveWinprobMeta.textContent = "";

  RUNTIME.lastLiveWinprobPct = pct;
}

function applyLiveWinprobDelta(deltaPct, hasPrevious) {
  if (!DOM.liveWinprobValue || !hasPrevious || !Number.isFinite(deltaPct)) {
    clearLiveWinprobDelta();
    return;
  }

  const absValue = Math.abs(deltaPct);
  const formatted = absValue.toFixed(1).replace(".", ",");
  let direction = "flat";
  let indicator = `•${formatted}`;

  if (deltaPct > 0.05) {
    direction = "up";
    indicator = `▲${formatted}`;
  } else if (deltaPct < -0.05) {
    direction = "down";
    indicator = `▼${formatted}`;
  }

  DOM.liveWinprobValue.dataset.delta = indicator;
  DOM.liveWinprobValue.dataset.deltaDir = direction;
  DOM.liveWinprobValue.classList.add("has-delta");
}

function clearLiveWinprobDelta() {
  if (!DOM.liveWinprobValue) {
    return;
  }

  DOM.liveWinprobValue.classList.remove("has-delta");
  DOM.liveWinprobValue.removeAttribute("data-delta");
  DOM.liveWinprobValue.removeAttribute("data-delta-dir");
}

function startAutoRefresh() {
  stopAutoRefresh();
  const interval = asFiniteNumber(CONFIG.REFRESH_INTERVAL_MS);
  if (!Number.isFinite(interval) || interval <= 0) {
    return;
  }

  refreshTimer = setInterval(() => {
    void loadAllData();
  }, interval);
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

function startLiveScoreWatcher() {
  stopLiveScoreWatcher();
  const interval = asFiniteNumber(CONFIG.LIVE_SCORE_CHECK_INTERVAL_MS);
  if (!Number.isFinite(interval) || interval <= 0) {
    return;
  }

  void checkLiveScoreAndRefresh({ clearError: false });
  liveScoreTimer = setInterval(() => {
    void checkLiveScoreAndRefresh({ clearError: false });
  }, interval);
}

function stopLiveScoreWatcher() {
  if (liveScoreTimer) {
    clearInterval(liveScoreTimer);
    liveScoreTimer = null;
  }
}

function setResolvedMatchId(matchId) {
  const next = String(matchId || "").trim();
  const prev = String(RUNTIME.resolvedMatchId || "").trim();
  if (next === prev) {
    return;
  }

  RUNTIME.resolvedMatchId = next;
  resetLiveScoreWatcherState();
}

function resetLiveScoreWatcherState() {
  RUNTIME.lastObservedLiveScoreKey = "";
  RUNTIME.lastObservedLiveScoreMatchId = "";
}

function getEffectiveMatchId() {
  return String(CONFIG.WINPROB_MATCH_ID || RUNTIME.resolvedMatchId || "").trim();
}

async function apiFetch(service, path, query = {}, extraHeaders = {}) {
  const proxyBase = String(CONFIG.PROXY_BASE_URL || "").trim();
  if (!proxyBase) {
    throw new Error("PROXY_BASE_URL manquant. Le widget fonctionne en proxy-only.");
  }

  const targetUrl = buildProxyUrl(service, path, query);
  const headers = {
    Accept: "application/json",
    ...extraHeaders
  };

  try {
    return await fetchJson(targetUrl, headers);
  } catch (error) {
    const reason = toFriendlyError(error);
    throw new Error(`Requête ${service} via proxy impossible (${reason}).`);
  }
}

function buildProxyUrl(service, path, query = {}) {
  const proxyRoot = ensureTrailingSlash(CONFIG.PROXY_BASE_URL);
  const url = new URL("proxy", proxyRoot);
  url.searchParams.set("service", service);
  url.searchParams.set("path", `/${normalizePath(path)}`);

  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && String(value) !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  return url;
}

async function fetchJson(url, headers, timeoutOverrideMs) {
  const configuredTimeout = Number.isFinite(timeoutOverrideMs)
    ? timeoutOverrideMs
    : asFiniteNumber(CONFIG.FETCH_TIMEOUT_MS);
  const timeoutMs = Number.isFinite(configuredTimeout) && configuredTimeout > 0 ? configuredTimeout : 12000;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(url.toString(), {
      method: "GET",
      headers,
      signal: controller.signal
    });

    if (!response.ok) {
      const errorText = (await response.text()).trim();
      const suffix = errorText ? ` - ${errorText.slice(0, 180)}` : "";
      throw new Error(`HTTP ${response.status}${suffix}`);
    }

    return await response.json();
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error(`Timeout dépassé (${timeoutMs} ms)`);
    }
    if (error instanceof TypeError) {
      const rawMessage = String(error.message || "").trim();
      const suffix = rawMessage ? ` (${rawMessage})` : "";
      throw new Error(`Échec réseau/CORS${suffix}`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

function setSectionLoading(isLoading) {
  if (DOM.winprobLoader) {
    DOM.winprobLoader.hidden = !isLoading;
  }
  if (DOM.winprobSection) {
    DOM.winprobSection.setAttribute("aria-busy", String(Boolean(isLoading)));
  }
}

function setSectionError(message) {
  if (!DOM.winprobError) {
    return;
  }
  if (!message) {
    DOM.winprobError.hidden = true;
    DOM.winprobError.textContent = "";
    return;
  }

  DOM.winprobError.hidden = false;
  DOM.winprobError.textContent = message;
}

function getWinprobColor(pctValue) {
  const pct = asFiniteNumber(pctValue);
  if (!Number.isFinite(pct)) {
    return "#888888";
  }
  if (pct >= 60) {
    return "#4CAF50";
  }
  if (pct >= 45) {
    return "#F4C430";
  }
  return "#F44336";
}

function toScoreInteger(value) {
  const numeric = parseMetricNumber(value);
  if (!Number.isFinite(numeric)) {
    return Number.NaN;
  }
  return Math.max(0, Math.trunc(numeric));
}

function buildScoreWatchKey(scoreA, scoreB) {
  const first = toScoreInteger(scoreA);
  const second = toScoreInteger(scoreB);
  if (!Number.isFinite(first) || !Number.isFinite(second)) {
    return "";
  }

  const low = Math.min(first, second);
  const high = Math.max(first, second);
  return `${low}-${high}`;
}

function normalizePath(path) {
  return String(path || "").replace(/^\/+/, "");
}

function ensureTrailingSlash(url) {
  const value = String(url || "").trim();
  return value.endsWith("/") ? value : `${value}/`;
}

function parseMetricNumber(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : Number.NaN;
  }

  const raw = String(value || "").trim();
  if (!raw) {
    return Number.NaN;
  }

  let cleaned = raw.replace(/%/g, "").replace(/\s+/g, "");
  if (!cleaned) {
    return Number.NaN;
  }

  const hasComma = cleaned.includes(",");
  const hasDot = cleaned.includes(".");

  if (hasComma && hasDot) {
    const lastComma = cleaned.lastIndexOf(",");
    const lastDot = cleaned.lastIndexOf(".");
    const decimalSep = lastComma > lastDot ? "," : ".";
    const thousandsSepRegex = decimalSep === "," ? /\./g : /,/g;
    cleaned = cleaned.replace(thousandsSepRegex, "");
    cleaned = cleaned.replace(decimalSep, ".");
  } else if (hasComma) {
    const decimalDigits = cleaned.length - cleaned.lastIndexOf(",") - 1;
    cleaned = decimalDigits === 3 ? cleaned.replace(/,/g, "") : cleaned.replace(",", ".");
  } else if (hasDot) {
    const decimalDigits = cleaned.length - cleaned.lastIndexOf(".") - 1;
    if (decimalDigits === 3) {
      cleaned = cleaned.replace(/\./g, "");
    }
  }

  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function firstFiniteNumber(...values) {
  for (const value of values) {
    const parsed = asFiniteNumber(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return Number.NaN;
}

function asFiniteNumber(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : Number.NaN;
  }

  if (typeof value === "string") {
    const parsed = Number(value.replace(/,/g, "."));
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }

  return Number.NaN;
}

function isHttp404Like(error) {
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
      ? error.message
      : String(error || "");
  return /(^|[^0-9])404([^0-9]|$)/.test(message) || /not found/i.test(message);
}

function isNoActiveMatchPayload(payload) {
  if (!isPlainObject(payload)) {
    return false;
  }

  if (matchesNoActiveMatchText(payload.error) || matchesNoActiveMatchText(payload.message)) {
    return true;
  }

  const detail = payload.detail;
  if (isPlainObject(detail)) {
    return matchesNoActiveMatchText(detail.error) || matchesNoActiveMatchText(detail.message);
  }

  if (typeof detail === "string") {
    return matchesNoActiveMatchText(detail);
  }

  return false;
}

function isNoActiveMatchError(error) {
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
      ? error.message
      : String(error || "");
  return matchesNoActiveMatchText(message);
}

function matchesNoActiveMatchText(value) {
  const text = String(value || "").toLowerCase();
  if (!text) {
    return false;
  }
  return (
    text.includes("aucune partie en cours") ||
    text.includes("no ongoing match") ||
    text.includes("no match in progress")
  );
}

function toFriendlyError(error) {
  if (!error) {
    return "Erreur inconnue.";
  }

  const message =
    typeof error === "string"
      ? error
      : error instanceof Error && error.message
      ? error.message
      : "Erreur API.";

  if (matchesNoActiveMatchText(message)) {
    return "Aucune partie en cours";
  }

  if (/failed to fetch|load failed|networkerror|echec reseau|échec réseau|cors/i.test(message)) {
    return "Échec réseau/CORS. Utilisez un proxy local (PROXY_BASE_URL).";
  }

  return message || "Erreur API.";
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function applyRuntimeOverridesFromQuery(config) {
  if (typeof window === "undefined" || !window.location || !window.location.search) {
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const overrides = {
    FACEIT_NICKNAME: pickFirstQueryValue(params, ["nickname", "faceit_nickname"]),
    WINPROB_MATCH_ID: pickFirstQueryValue(params, ["match_id", "matchid"])
  };

  for (const [key, value] of Object.entries(overrides)) {
    if (value) {
      config[key] = value;
    }
  }
}

function pickFirstQueryValue(params, keys) {
  for (const key of keys) {
    const value = String(params.get(key) || "").trim();
    if (value) {
      return value;
    }
  }
  return "";
}
