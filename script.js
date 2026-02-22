/* script.js - Logique de récupération, rendu et rafraîchissement du widget CS2 Stats. */

const CONFIG = {
  STEAM_ID_64: "",
  FACEIT_NICKNAME: "",
  REFRESH_INTERVAL_MS: 60000,
  PROXY_BASE_URL: "http://127.0.0.1:8787", // Le widget fonctionne en proxy-only pour ne jamais exposer les clés API.
  FETCH_TIMEOUT_MS: 12000,
  WINPROB_ENABLED: true,
  LIVE_WINPROB_ENABLED: true,
  WINPROB_MATCH_ID: "",
  WINPROB_FETCH_TIMEOUT_MS: 45000,
  LIVE_WINPROB_FETCH_TIMEOUT_MS: 45000,
  LIVE_WINPROB_INTERVAL_MS: 20000,
  AUTO_RESOLVE_IDS: true
};

applyRuntimeOverridesFromQuery(CONFIG);

/*
  Important CORS/Sécurité:
  - Le front est volontairement en proxy-only.
  - Aucune clé API ne doit exister dans ce fichier.
  - Le proxy local/backend injecte l'auth côté serveur via .env.
*/

const FACEIT_KD_KEYS = [
  "Average K/D Ratio",
  "Average K/D",
  "Average KDR",
  "K/D Ratio",
  "K/D",
  "KD Ratio"
];

const FACEIT_AVG_KEYS = [
  "Average Kills",
  "Average Kills per Match",
  "Avg Kills",
  "Kills per Match",
  "ADR",
  "Average Damage per Round"
];

const FACEIT_HS_KEYS = [
  "Average Headshots %",
  "Average HS %",
  "Headshots %",
  "HS %",
  "HS"
];

const FACEIT_KR_KEYS = [
  "Average K/R Ratio",
  "Average K/R",
  "K/R Ratio",
  "K/R"
];

const FACEIT_TOTAL_KILLS_KEYS = [
  "Total Kills with extended stats",
  "Kills with extended stats",
  "Total Kills",
  "Kills"
];

const FACEIT_TOTAL_ROUNDS_KEYS = [
  "Total Rounds with extended stats",
  "Rounds with extended stats",
  "Total Rounds",
  "Rounds"
];

const DEFAULT_AVATAR =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'><rect width='120' height='120' fill='%23222222'/><circle cx='60' cy='46' r='22' fill='%23383838'/><rect x='22' y='76' width='76' height='28' rx='14' fill='%23383838'/></svg>"
  );

const DOM = {
  premierLoader: document.getElementById("premier-loader"),
  premierError: document.getElementById("premier-error"),
  premierMiniSlot: document.getElementById("premier-mini-slot"),

  faceitSection: document.getElementById("faceit-section"),
  faceitPanel: document.getElementById("faceit-panel"),
  faceitLoader: document.getElementById("faceit-loader"),
  faceitError: document.getElementById("faceit-error"),
  faceitAvatar: document.getElementById("faceit-avatar"),
  faceitNickname: document.getElementById("faceit-nickname"),
  faceitCountry: document.getElementById("faceit-country"),
  faceitLevelBadge: document.getElementById("faceit-level-badge"),
  faceitElo: document.getElementById("faceit-elo"),
  faceitAvg: document.getElementById("faceit-avg"),
  faceitHs: document.getElementById("faceit-hs"),
  faceitKd: document.getElementById("faceit-kd"),
  faceitKr: document.getElementById("faceit-kr"),
  faceitLastMatches: document.getElementById("faceit-last-matches"),

  winprobSection: document.getElementById("winprob-section"),
  winprobLoader: document.getElementById("winprob-loader"),
  winprobError: document.getElementById("winprob-error"),
  winprobBadge: document.getElementById("winprob-badge"),
  winprobValue: document.getElementById("winprob-value"),
  winprobMeta: document.getElementById("winprob-meta"),
  liveWinprobBadge: document.getElementById("live-winprob-badge"),
  liveWinprobValue: document.getElementById("live-winprob-value"),
  liveWinprobMeta: document.getElementById("live-winprob-meta"),

  lastUpdated: document.getElementById("last-updated")
};

const RUNTIME = {
  resolvedPlayerId: "",
  resolvedSteamId64: "",
  resolvedMatchId: "",
  bootstrapAt: 0,
  lastLiveWinprobPct: Number.NaN
};

let refreshTimer = null;
let liveWinprobTimer = null;
let isRefreshing = false;
let isLiveWinprobRefreshing = false;
let premierSvgCounter = 0;

document.addEventListener("DOMContentLoaded", () => {
  void initWidget();
});

window.addEventListener("beforeunload", () => {
  stopAutoRefresh();
  stopLiveWinprobRefresh();
});

async function initWidget() {
  renderBadgePremier(Number.NaN);
  renderFaceitProfile(null);
  renderWinProbability(null);
  renderLiveWinProbability(null);

  if (!shouldShowWinprob() && DOM.winprobSection) {
    DOM.winprobSection.hidden = true;
  } else if (DOM.winprobSection) {
    DOM.winprobSection.hidden = false;
  }

  try {
    await loadAllData();
  } finally {
    startAutoRefresh();
    startLiveWinprobRefresh();
  }
}

async function loadAllData() {
  if (isRefreshing) {
    return;
  }

  const showWinprob = shouldShowWinprob();

  isRefreshing = true;
  setSectionLoading("premier", true);
  setSectionLoading("faceit", true);
  if (showWinprob) {
    setSectionLoading("winprob", true);
  }
  setSectionError("premier", "");
  setSectionError("faceit", "");
  setSectionError("winprob", "");

  try {
    await bootstrapWidgetIdentity();

    const [leetifyResult, faceitResult, winprobResult] = await Promise.allSettled([
      fetchLeetify(),
      fetchFaceit(),
      showWinprob ? fetchWinProbability() : Promise.resolve(null)
    ]);

    if (leetifyResult.status === "fulfilled") {
      const premierElo = leetifyResult.value.premierElo;
      const isUnranked = Boolean(leetifyResult.value.isUnranked);
      try {
        renderBadgePremier(premierElo, { unranked: isUnranked });
      } catch (error) {
        renderBadgePremierFallback(isUnranked ? "UNRANKED" : "N/A");
        setSectionError("premier", `Rendu badge Premier impossible (${toFriendlyError(error)}).`);
      }

      if (!Number.isFinite(premierElo) && !isUnranked) {
        setSectionError("premier", "ELO Premier indisponible (profil privé, non classé, ou non lié).");
      }
    } else {
      renderBadgePremier(Number.NaN, { unranked: false });
      setSectionError("premier", toFriendlyError(leetifyResult.reason));
    }

    if (faceitResult.status === "fulfilled") {
      renderFaceitProfile(faceitResult.value);
    } else {
      renderFaceitProfile(null);
      setSectionError("faceit", toFriendlyError(faceitResult.reason));
    }

    if (showWinprob) {
      if (winprobResult.status === "fulfilled") {
        renderWinProbability(winprobResult.value);
        if (winprobResult.value?.no_active_match === true) {
          renderLiveWinProbability({ no_active_match: true });
        } else {
          void refreshLiveWinProbability({ withLoader: false, clearError: false });
        }
      } else {
        renderWinProbability(null);
        renderLiveWinProbability(null);
        setSectionError("winprob", toFriendlyError(winprobResult.reason));
      }
    }
  } catch (error) {
    setSectionError("premier", toFriendlyError(error));
  } finally {
    setSectionLoading("premier", false);
    setSectionLoading("faceit", false);
    if (showWinprob) {
      setSectionLoading("winprob", false);
    }
    updateLastUpdated();
    isRefreshing = false;
  }
}

async function fetchLeetify() {
  const steamId64 = await resolveSteamId64ForLeetify();
  if (!steamId64) {
    throw new Error("STEAM_ID_64 manquant après résolution via Faceit.");
  }

  let profile;
  try {
    profile = await apiFetch("leetify", "v3/profile", {
      steam64_id: steamId64
    });
  } catch (error) {
    const reason = toFriendlyError(error);
    if (reason.includes("HTTP 404")) {
      return {
        premierElo: Number.NaN,
        premierSource: "unranked",
        isUnranked: true
      };
    }
    throw error;
  }

  // Source stricte demandée: ProfileResponse.ranks.premier
  const profileData = isPlainObject(profile?.data) ? profile.data : profile;
  const premierElo = asFiniteNumber(profileData?.ranks?.premier);
  const isUnranked = !Number.isFinite(premierElo);

  return {
    premierElo,
    premierSource: "ranks.premier",
    isUnranked
  };
}

async function resolveSteamId64ForLeetify() {
  const current = getEffectiveSteamId64();
  if (current) {
    return current;
  }

  const nickname = String(CONFIG.FACEIT_NICKNAME || "").trim();
  if (!nickname) {
    return "";
  }

  // Résolution explicite via Faceit players pour garantir le flux:
  // nickname -> player profile -> steam_id_64 -> Leetify profile.
  const playerLookup = await apiFetch("faceit", "players", {
    nickname,
    game: "cs2"
  });
  syncRuntimeFromFaceitLookup(playerLookup);

  return getEffectiveSteamId64();
}

async function fetchFaceit() {
  if (!CONFIG.FACEIT_NICKNAME) {
    throw new Error("FACEIT_NICKNAME manquant.");
  }

  const playerLookup = await apiFetch("faceit", "players", {
    nickname: CONFIG.FACEIT_NICKNAME,
    game: "cs2"
  });
  syncRuntimeFromFaceitLookup(playerLookup);

  const playerId =
    playerLookup?.player_id ||
    playerLookup?.items?.[0]?.player_id ||
    playerLookup?.payload?.items?.[0]?.player_id;

  if (!playerId) {
    throw new Error("Impossible de résoudre le player_id Faceit.");
  }

  const [profile, statsPayload, historyPayload] = await Promise.all([
    apiFetch("faceit", `players/${encodeURIComponent(playerId)}`),
    apiFetch("faceit", `players/${encodeURIComponent(playerId)}/stats/cs2`),
    apiFetch("faceit", `players/${encodeURIComponent(playerId)}/history`, {
      game: "cs2",
      offset: 0,
      limit: 5
    })
  ]);

  const lifetime = isPlainObject(statsPayload?.lifetime) ? statsPayload.lifetime : {};
  const computedKr = computeKrFromLifetime(lifetime, { decimals: 2 });
  const fallbackKr = getLifetimeMetric(lifetime, FACEIT_KR_KEYS, { decimals: 2 });

  return {
    playerId,
    nickname: profile?.nickname || playerLookup?.nickname || CONFIG.FACEIT_NICKNAME,
    country: profile?.country || playerLookup?.country || "",
    avatar: profile?.avatar || playerLookup?.avatar || "",
    level: asFiniteNumber(profile?.games?.cs2?.skill_level),
    elo: asFiniteNumber(profile?.games?.cs2?.faceit_elo),
    avg: getLifetimeMetric(lifetime, FACEIT_AVG_KEYS, { decimals: 1 }),
    hs: getLifetimeMetric(lifetime, FACEIT_HS_KEYS, {
      decimals: 0,
      percent: true
    }),
    kd: getLifetimeMetric(lifetime, FACEIT_KD_KEYS, { decimals: 2 }),
    // K/R fiable: calcul explicite sur stats agrégées FACEIT (Kills / Rounds).
    kr: computedKr !== "--" ? computedKr : fallbackKr,
    matches: parseFaceitRecentMatches(historyPayload?.items, playerId)
  };
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
    RUNTIME.resolvedMatchId = returnedMatchId;
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
    RUNTIME.resolvedMatchId = returnedMatchId;
  }

  return payload;
}

async function bootstrapWidgetIdentity() {
  if (!CONFIG.AUTO_RESOLVE_IDS) {
    return;
  }

  const nickname = String(CONFIG.FACEIT_NICKNAME || "").trim();
  if (!nickname) {
    return;
  }

  const steamAlreadyAvailable = Boolean(getEffectiveSteamId64());
  const matchAlreadyAvailable = Boolean(getEffectiveMatchId());
  if (steamAlreadyAvailable && matchAlreadyAvailable) {
    return;
  }

  const now = Date.now();
  if (RUNTIME.bootstrapAt && now - RUNTIME.bootstrapAt < 5000) {
    return;
  }
  RUNTIME.bootstrapAt = now;

  const proxyPayload = await resolveIdsFromProxy(nickname);
  if (isPlainObject(proxyPayload)) {
    syncRuntimeFromFaceitLookup(proxyPayload);

    const resolvedMatchId = String(proxyPayload.match_id || proxyPayload.matchId || "").trim();
    if (!String(CONFIG.WINPROB_MATCH_ID || "").trim() && resolvedMatchId) {
      RUNTIME.resolvedMatchId = resolvedMatchId;
    }
  }

  if (getEffectiveSteamId64()) {
    return;
  }

  try {
    const playerLookup = await apiFetch("faceit", "players", {
      nickname,
      game: "cs2"
    });
    syncRuntimeFromFaceitLookup(playerLookup);
  } catch {
    // Tolérant: Faceit section affichera sa propre erreur si nécessaire.
  }
}

async function resolveIdsFromProxy(nickname) {
  const proxyBase = String(CONFIG.PROXY_BASE_URL || "").trim();
  if (!proxyBase) {
    return null;
  }

  const url = new URL("resolve-live-match", ensureTrailingSlash(proxyBase));
  url.searchParams.set("nickname", nickname);

  try {
    const payload = await fetchJson(url, { Accept: "application/json" }, asFiniteNumber(CONFIG.FETCH_TIMEOUT_MS));
    return isPlainObject(payload) ? payload : null;
  } catch {
    return null;
  }
}

function syncRuntimeFromFaceitLookup(payload) {
  if (!isPlainObject(payload)) {
    return;
  }

  const resolvedPlayerId = String(payload.player_id || payload.playerId || "").trim();
  if (resolvedPlayerId) {
    RUNTIME.resolvedPlayerId = resolvedPlayerId;
  }

  const steamId64 = extractSteamId64FromPayload(payload);
  if (!String(CONFIG.STEAM_ID_64 || "").trim() && steamId64) {
    RUNTIME.resolvedSteamId64 = steamId64;
  }
}

function extractSteamId64FromPayload(payload) {
  const platforms = isPlainObject(payload?.platforms) ? payload.platforms : {};
  return String(payload?.steam_id_64 || platforms.steam || payload?.new_steam_id || "").trim();
}

function getEffectiveSteamId64() {
  return String(CONFIG.STEAM_ID_64 || RUNTIME.resolvedSteamId64 || "").trim();
}

function getEffectiveMatchId() {
  return String(CONFIG.WINPROB_MATCH_ID || RUNTIME.resolvedMatchId || "").trim();
}

function renderBadgePremier(eloValue, options = {}) {
  const isUnranked = Boolean(options.unranked);
  const safeElo = asFiniteNumber(eloValue);
  if (!DOM.premierMiniSlot) {
    return;
  }

  if (isUnranked) {
    const color = "#A0A0A0";
    DOM.premierMiniSlot.dataset.premierState = "unranked";
    DOM.premierMiniSlot.dataset.premierValue = "";
    try {
      DOM.premierMiniSlot.innerHTML = `
        <div class="premier-mini-badge" style="--premier-glow:${toRgba(color, 0.52)};">
          ${buildPremierBadgeSvg("UNRANKED", color)}
        </div>
      `;
    } catch {
      renderBadgePremierFallback("UNRANKED");
    }
    return;
  }

  if (Number.isFinite(safeElo)) {
    const color = getEloColor(safeElo);
    const eloLabel = formatIntFr(Math.round(safeElo));
    DOM.premierMiniSlot.dataset.premierState = "ranked";
    DOM.premierMiniSlot.dataset.premierValue = String(Math.round(safeElo));

    try {
      DOM.premierMiniSlot.innerHTML = `
        <div class="premier-mini-badge" style="--premier-glow:${toRgba(color, 0.6)};">
          ${buildPremierBadgeSvg(eloLabel, color)}
        </div>
      `;
    } catch {
      renderBadgePremierFallback(eloLabel, color);
    }
    return;
  }

  DOM.premierMiniSlot.dataset.premierState = "na";
  DOM.premierMiniSlot.dataset.premierValue = "";
  renderBadgePremierFallback("N/A");
}

function renderBadgePremierFallback(label, color = "#A0A0A0") {
  if (!DOM.premierMiniSlot) {
    return;
  }
  const safeLabel = escapeHtml(label);
  DOM.premierMiniSlot.innerHTML = `
    <span class="premier-mini-value" style="color:${color};text-shadow:0 0 10px ${toRgba(color, 0.75)};">
      ${safeLabel}
    </span>
  `;
}

function renderFaceitProfile(data) {
  const profile = data || {
    nickname: "--",
    country: "",
    avatar: "",
    level: Number.NaN,
    elo: Number.NaN,
    avg: "--",
    hs: "--",
    kd: "--",
    kr: "--",
    matches: []
  };

  DOM.faceitAvatar.src = profile.avatar || DEFAULT_AVATAR;
  DOM.faceitAvatar.alt = `Avatar ${profile.nickname || "joueur"}`;
  if (DOM.faceitPanel) {
    DOM.faceitPanel.style.setProperty(
      "--faceit-bg-image",
      `url("${escapeCssUrl(profile.avatar || DEFAULT_AVATAR)}")`
    );
  }

  DOM.faceitNickname.textContent = profile.nickname || "--";

  const countryText = profile.country
    ? `${countryCodeToFlag(profile.country)} ${String(profile.country).toUpperCase()}`
    : "--";
  DOM.faceitCountry.textContent = countryText;

  const hasLevel = Number.isFinite(profile.level) && profile.level >= 1 && profile.level <= 10;
  if (hasLevel) {
    DOM.faceitLevelBadge.src = `./images/faceit_elo/${Math.round(profile.level)}.png`;
    DOM.faceitLevelBadge.hidden = false;
    DOM.faceitLevelBadge.alt = `Niveau Faceit ${Math.round(profile.level)}`;
  } else {
    DOM.faceitLevelBadge.hidden = true;
    DOM.faceitLevelBadge.removeAttribute("src");
  }

  const eloText = Number.isFinite(profile.elo)
    ? Math.round(profile.elo).toLocaleString("fr-FR")
    : "--";
  DOM.faceitElo.textContent = eloText;

  DOM.faceitAvg.textContent = profile.avg || "--";
  DOM.faceitHs.textContent = profile.hs || "--";
  DOM.faceitKd.textContent = profile.kd || "--";
  DOM.faceitKr.textContent = profile.kr || "--";

  renderRecentMatchPills(Array.isArray(profile.matches) ? profile.matches : []);
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

function clearLiveWinprobDelta() {
  if (!DOM.liveWinprobValue) {
    return;
  }

  DOM.liveWinprobValue.classList.remove("has-delta");
  DOM.liveWinprobValue.removeAttribute("data-delta");
  DOM.liveWinprobValue.removeAttribute("data-delta-dir");
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

async function refreshLiveWinProbability(options = {}) {
  if (!shouldShowWinprob() || !shouldShowLiveWinprob()) {
    return;
  }
  if (isLiveWinprobRefreshing) {
    return;
  }

  const withLoader = Boolean(options.withLoader);
  const clearError = options.clearError !== false;

  isLiveWinprobRefreshing = true;
  if (withLoader) {
    setSectionLoading("winprob", true);
  }
  if (clearError) {
    setSectionError("winprob", "");
  }

  try {
    const payload = await fetchLiveWinProbability();
    renderLiveWinProbability(payload);
  } catch (error) {
    if (isNoActiveMatchError(error)) {
      renderLiveWinProbability({ no_active_match: true });
      return;
    }
    renderLiveWinProbability(null);
    setSectionError("winprob", toFriendlyError(error));
  } finally {
    if (withLoader) {
      setSectionLoading("winprob", false);
    }
    isLiveWinprobRefreshing = false;
  }
}

function getEloColor(eloValue) {
  const elo = asFiniteNumber(eloValue);

  if (!Number.isFinite(elo)) {
    return "#A0A0A0";
  }
  if (elo >= 30000) {
    return "#FFD700";
  }
  if (elo >= 25000) {
    return "#FF0000";
  }
  if (elo >= 20000) {
    return "#FF69B4";
  }
  if (elo >= 15000) {
    return "#9370DB";
  }
  if (elo >= 10000) {
    return "#4169E1";
  }
  if (elo >= 5000) {
    return "#87CEEB";
  }

  return "#A0A0A0";
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

function buildPremierBadgeSvg(eloLabel, baseHexColor) {
  const uid = `premier_${Date.now()}_${premierSvgCounter++}`;
  const accentMain = baseHexColor;
  const accentDark = shiftHexColor(baseHexColor, -92);
  const accentMid = shiftHexColor(baseHexColor, -40);
  const textColor = shiftHexColor(baseHexColor, 130);
  const escapedElo = escapeHtml(eloLabel);
  const labelLength = String(eloLabel || "").length;
  const isUnrankedLabel = String(eloLabel || "").toUpperCase() === "UNRANKED";
  const textSize = isUnrankedLabel ? 24 : labelLength >= 8 ? 24 : labelLength >= 6 ? 30 : 40;
  const textLetterSpacing = isUnrankedLabel ? 0.45 : labelLength >= 8 ? 0.7 : 1.05;

  return `
    <svg class="premier-badge-svg" width="178" height="64" viewBox="0 0 178 64" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="CS2 Premier ELO ${escapedElo}">
      <g clip-path="url(#clip0_${uid})">
        <path d="M25 0H21L9 64H13L25 0Z" fill="${accentMid}"/>
        <path d="M178 0H33.9996L22 64H166L178 0Z" fill="url(#paint0_${uid})"/>
        <path d="M176.25 1.5H33.24L21.6562 62.5H164.666L176.25 1.5Z" fill="url(#paint1_${uid})"/>
        <path opacity="0.38" d="M46.1141 4L54 4L40.8859 61H33L46.1141 4Z" fill="${accentDark}"/>
        <path d="M36.7301 4L42 4L30.2699 61H25L36.7301 4Z" fill="${accentDark}"/>
        <path opacity="0.38" d="M56.8737 4L72 4L59.1263 61H44L56.8737 4Z" fill="${accentDark}"/>
        <path opacity="0.38" d="M75.7813 4L110 4L97.2187 61H63L75.7813 4Z" fill="${accentDark}"/>
        <path d="M18 0H27L18 64H3.25L18 0Z" fill="${accentDark}"/>
        <path d="M12 0H21L9 64H0L12 0Z" fill="#F5F8FF"/>
        <path d="M24.9997 0H33.9997L22 64H13L24.9997 0Z" fill="#F5F8FF"/>
        <path d="M25 0H33L21 64H13L25 0Z" fill="url(#paint2_${uid})"/>
        <path d="M12 0H20L8 64H0L12 0Z" fill="url(#paint4_${uid})"/>
        <text
          x="104"
          y="45"
          text-anchor="middle"
          fill="${textColor}"
          font-size="${textSize}"
          font-family="Stratum2Bold, Rajdhani, sans-serif"
          font-style="italic"
          letter-spacing="${textLetterSpacing}"
          filter="url(#textGlow_${uid})"
        >${escapedElo}</text>
      </g>
      <defs>
        <linearGradient id="paint0_${uid}" x1="187.49" y1="48.7288" x2="30.4973" y2="20.5012" gradientUnits="userSpaceOnUse">
          <stop offset="0.06" stop-color="${accentDark}"/>
          <stop offset="0.62" stop-color="${accentMain}"/>
          <stop offset="1" stop-color="${accentMid}"/>
        </linearGradient>
        <linearGradient id="paint1_${uid}" x1="185.411" y1="47.9446" x2="26.5628" y2="33.7951" gradientUnits="userSpaceOnUse">
          <stop offset="0.862691" stop-color="${shiftHexColor(baseHexColor, -120)}" stop-opacity="0.48"/>
          <stop offset="1" stop-color="${shiftHexColor(baseHexColor, -136)}"/>
        </linearGradient>
        <linearGradient id="paint2_${uid}" x1="23.4998" y1="1" x2="23.4998" y2="63" gradientUnits="userSpaceOnUse">
          <stop stop-color="#E6E6E6"/>
          <stop offset="1" stop-color="#DEDEDE"/>
        </linearGradient>
        <linearGradient id="paint4_${uid}" x1="10.4998" y1="1" x2="10.4998" y2="63" gradientUnits="userSpaceOnUse">
          <stop stop-color="#E6E6E6"/>
          <stop offset="1" stop-color="#DEDEDE"/>
        </linearGradient>
        <filter id="textGlow_${uid}" x="-30%" y="-50%" width="160%" height="220%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="1.35" result="blur"/>
          <feMerge>
            <feMergeNode in="blur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>
    </svg>
  `;
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

function startLiveWinprobRefresh() {
  stopLiveWinprobRefresh();

  if (!shouldShowWinprob() || !shouldShowLiveWinprob()) {
    return;
  }

  const interval = asFiniteNumber(CONFIG.LIVE_WINPROB_INTERVAL_MS);
  if (!Number.isFinite(interval) || interval <= 0) {
    return;
  }

  liveWinprobTimer = setInterval(() => {
    void refreshLiveWinProbability({ withLoader: false, clearError: false });
  }, interval);
}

function stopLiveWinprobRefresh() {
  if (liveWinprobTimer) {
    clearInterval(liveWinprobTimer);
    liveWinprobTimer = null;
  }
}

async function apiFetch(service, path, query = {}, extraHeaders = {}) {
  const proxyBase = String(CONFIG.PROXY_BASE_URL || "").trim();
  if (!proxyBase) {
    throw new Error("PROXY_BASE_URL manquant. Le widget fonctionne en proxy-only pour la sécurité des clés API.");
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
    throw new Error(`Requête ${service} via proxy impossible (${reason}). Vérifiez que proxy-server.mjs est lancé.`);
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

function getLifetimeMetric(lifetime, candidateKeys, options = {}) {
  const rawValue = pickLifetimeValue(lifetime, candidateKeys);

  if (rawValue === null) {
    return "--";
  }

  return formatMetric(rawValue, options);
}

function computeKrFromLifetime(lifetime, options = {}) {
  const kills = pickLifetimeNumber(lifetime, FACEIT_TOTAL_KILLS_KEYS);
  const rounds = pickLifetimeNumber(lifetime, FACEIT_TOTAL_ROUNDS_KEYS);

  if (!Number.isFinite(kills) || !Number.isFinite(rounds) || rounds <= 0) {
    return "--";
  }

  const decimals = Number.isInteger(options.decimals) ? options.decimals : 2;
  return finalizeMetricNumber(kills / rounds, decimals, false);
}

function pickLifetimeValue(lifetime, candidateKeys) {
  const lookup = new Map();

  for (const [key, value] of Object.entries(lifetime)) {
    lookup.set(normalizeMetricKey(key), value);
  }

  for (const key of candidateKeys) {
    const foundValue = lookup.get(normalizeMetricKey(key));
    if (foundValue !== undefined && foundValue !== null && String(foundValue).trim() !== "") {
      return foundValue;
    }
  }

  return null;
}

function pickLifetimeNumber(lifetime, candidateKeys) {
  const rawValue = pickLifetimeValue(lifetime, candidateKeys);
  if (rawValue === null) {
    return Number.NaN;
  }
  return parseMetricNumber(rawValue);
}

function formatMetric(value, options = {}) {
  const decimals = Number.isInteger(options.decimals) ? options.decimals : 0;
  const asPercent = Boolean(options.percent);

  if (typeof value === "number" && Number.isFinite(value)) {
    return finalizeMetricNumber(value, decimals, asPercent);
  }

  const raw = String(value).trim();
  if (!raw) {
    return "--";
  }

  const numeric = parseMetricNumber(raw);
  if (Number.isFinite(numeric)) {
    return finalizeMetricNumber(numeric, decimals, asPercent);
  }

  if (asPercent && !raw.includes("%")) {
    return `${raw}%`;
  }

  return raw;
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

function finalizeMetricNumber(numberValue, decimals, asPercent) {
  const rounded = decimals > 0 ? Number(numberValue.toFixed(decimals)) : Math.round(numberValue);
  const text =
    decimals > 0
      ? rounded.toLocaleString("fr-FR", {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals
        })
      : rounded.toLocaleString("fr-FR");

  return asPercent ? `${text}%` : text;
}

function parseFaceitRecentMatches(items, playerId) {
  if (!Array.isArray(items)) {
    return [];
  }

  return items.slice(0, 5).map((match) => ({
    result: resolveFaceitMatchOutcome(match, playerId)
  }));
}

function resolveFaceitMatchOutcome(match, playerId) {
  const teams = match?.teams;
  if (!teams || typeof teams !== "object") {
    return "?";
  }

  const playerTeamCandidates = new Set();

  for (const [teamKey, teamValue] of Object.entries(teams)) {
    const players = Array.isArray(teamValue?.players) ? teamValue.players : [];
    const isPlayerInTeam = players.some((entry) => String(entry?.player_id || "") === String(playerId));

    if (!isPlayerInTeam) {
      continue;
    }

    playerTeamCandidates.add(String(teamKey));

    if (teamValue?.faction_id !== undefined && teamValue?.faction_id !== null) {
      playerTeamCandidates.add(String(teamValue.faction_id));
    }

    if (teamValue?.team_id !== undefined && teamValue?.team_id !== null) {
      playerTeamCandidates.add(String(teamValue.team_id));
    }
  }

  if (playerTeamCandidates.size === 0) {
    return "?";
  }

  const winner = match?.results?.winner;
  if (winner === undefined || winner === null) {
    return "?";
  }

  return playerTeamCandidates.has(String(winner)) ? "W" : "L";
}

function renderRecentMatchPills(matches) {
  DOM.faceitLastMatches.innerHTML = "";

  if (matches.length === 0) {
    const placeholder = document.createElement("span");
    placeholder.className = "muted-text";
    placeholder.textContent = "Aucun résultat récent";
    DOM.faceitLastMatches.appendChild(placeholder);
    return;
  }

  for (const match of matches) {
    const value = match?.result === "W" || match?.result === "L" ? match.result : "?";
    const pill = document.createElement("span");

    pill.className =
      value === "W"
        ? "match-pill match-pill--win"
        : value === "L"
        ? "match-pill match-pill--loss"
        : "match-pill match-pill--unknown";

    pill.textContent = value;
    DOM.faceitLastMatches.appendChild(pill);
  }
}

function setSectionLoading(section, isLoading) {
  if (section === "premier") {
    if (DOM.premierLoader) {
      DOM.premierLoader.hidden = !isLoading;
      DOM.premierLoader.style.display = isLoading ? "block" : "none";
    }
    return;
  }

  if (section === "faceit") {
    DOM.faceitLoader.hidden = !isLoading;
    DOM.faceitSection.setAttribute("aria-busy", String(isLoading));
    return;
  }

  if (section === "winprob" && DOM.winprobLoader && DOM.winprobSection) {
    DOM.winprobLoader.hidden = !isLoading;
    DOM.winprobSection.setAttribute("aria-busy", String(isLoading));
  }
}

function setSectionError(section, message) {
  let target = null;
  if (section === "premier") {
    target = DOM.premierError;
  } else if (section === "faceit") {
    target = DOM.faceitError;
  } else if (section === "winprob") {
    target = DOM.winprobError;
  }

  if (!target) {
    return;
  }
  if (!message) {
    target.hidden = true;
    target.textContent = "";
    return;
  }

  target.textContent = message;
  target.hidden = false;
}

function updateLastUpdated() {
  const now = new Date();
  DOM.lastUpdated.textContent = `Dernière mise à jour: ${now.toLocaleTimeString("fr-FR")}`;
}

function countryCodeToFlag(countryCode) {
  const code = String(countryCode || "").trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(code)) {
    return code || "--";
  }

  return String.fromCodePoint(...[...code].map((char) => char.charCodeAt(0) + 127397));
}

function normalizeMetricKey(input) {
  return String(input || "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function shouldShowWinprob() {
  return Boolean(CONFIG.WINPROB_ENABLED);
}

function shouldShowLiveWinprob() {
  return Boolean(CONFIG.LIVE_WINPROB_ENABLED);
}

function escapeCssUrl(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"');
}

function applyRuntimeOverridesFromQuery(config) {
  if (typeof window === "undefined" || !window.location || !window.location.search) {
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const overrides = {
    STEAM_ID_64: pickFirstQueryValue(params, ["steamid64", "steam_id_64", "steam64"]),
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

function normalizePath(path) {
  return String(path || "").replace(/^\/+/, "");
}

function ensureTrailingSlash(url) {
  const value = String(url || "").trim();
  return value.endsWith("/") ? value : `${value}/`;
}

function shiftHexColor(hex, amount) {
  const rgb = hexToRgb(hex);
  if (!rgb) {
    return hex;
  }

  const clamp = (value) => Math.max(0, Math.min(255, value));
  const r = clamp(rgb.r + amount);
  const g = clamp(rgb.g + amount);
  const b = clamp(rgb.b + amount);

  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

function toRgba(hex, alpha = 1) {
  const rgb = hexToRgb(hex);
  if (!rgb) {
    return `rgba(160,160,160,${alpha})`;
  }

  const safeAlpha = Math.max(0, Math.min(1, alpha));
  return `rgba(${rgb.r},${rgb.g},${rgb.b},${safeAlpha})`;
}

function hexToRgb(hex) {
  const value = String(hex || "").trim().replace(/^#/, "");
  if (!/^[A-Fa-f0-9]{6}$/.test(value)) {
    return null;
  }

  return {
    r: Number.parseInt(value.slice(0, 2), 16),
    g: Number.parseInt(value.slice(2, 4), 16),
    b: Number.parseInt(value.slice(4, 6), 16)
  };
}

function toHex(value) {
  return Number(value).toString(16).padStart(2, "0");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatIntFr(value) {
  const number = asFiniteNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }

  try {
    return Math.round(number).toLocaleString("fr-FR");
  } catch {
    return String(Math.round(number));
  }
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

function firstFiniteNumber(...values) {
  for (const value of values) {
    const parsed = asFiniteNumber(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return Number.NaN;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
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

  if (typeof error === "string") {
    return error;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Erreur API.";
}
