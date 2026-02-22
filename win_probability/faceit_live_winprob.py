#!/usr/bin/env python3
"""
faceit_live_winprob.py
──────────────────────────────────────────────────────────────────
Win Probability DYNAMIQUE pour un match FACEIT CS2 en cours.

Usage:
  python faceit_live_winprob.py <nickname>          # auto-détecte le match en cours
  python faceit_live_winprob.py <nickname> --json   # sortie machine-readable
  python faceit_live_winprob.py <nickname> -m <match_id>  # force le match_id

Algorithme:
  1. Résout le player_id et le match_id via FACEIT Data API + Web API interne
  2. Collecte les stats (30 derniers matchs) des 10 joueurs → base_prob
  3. Boucle de polling : récupère le score live toutes les POLL_INTERVAL secondes
  4. Combine base_prob (qualité des joueurs) + score_prob (état du match)
     via un poids croissant à mesure que le match avance
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import ssl
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from colorama import Fore, Style, init
from curl_cffi import requests as cfrequests
from dotenv import load_dotenv

try:
    import certifi
except Exception:
    certifi = None

# ─── ENV ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
load_dotenv(dotenv_path=ROOT_DIR / ".env", override=False)
load_dotenv(dotenv_path=SCRIPT_DIR / ".env", override=False)
init(autoreset=True)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
GAME_ID              = "cs2"
BASE_URL             = "https://open.faceit.com/data/v4"
FACEIT_WEB_BASE      = "https://www.faceit.com"
STATS_LIMIT          = 30        # matchs analysés par joueur (base_prob)
ROUNDS_TO_WIN        = 13        # premier à 13 manches
POLL_INTERVAL        = 115        # secondes entre chaque poll du score
SCORE_BLEND_POWER    = 0.35      # plus bas = le score prend le dessus plus tôt
SCORE_MIN_WEIGHT     = 0.25      # poids minimum accordé au score (même en début de match)
SCORE_GAP_WEIGHT     = 0.55      # bonus de poids du score selon l'écart de rounds
ROUND_WIN_BASE_INFLUENCE = 0.55  # réduit l'extrême de base_prob pour le calcul round-by-round
ACTIVE_LOOKBACK_SEC  = 24 * 3600
JSON_MARKER          = "__LIVEWINPROB_JSON__"

WEIGHTS = {
    "elo":          0.30,
    "kd":           0.20,
    "winrate":      0.20,
    "map_winrate":  0.20,
    "hs_pct":       0.05,
    "avg_kills":    0.05,
}

NORM = {
    "elo":        {"min": 500,  "max": 4000},
    "kd":         {"min": 0.4,  "max": 2.5},
    "winrate":    {"min": 0.2,  "max": 0.9},
    "map_winrate":{"min": 0.1,  "max": 1.0},
    "hs_pct":     {"min": 0.0,  "max": 0.70},
    "avg_kills":  {"min": 5,    "max": 30},
}

ACTIVE_MATCH_STATUSES = {
    "ongoing", "in_progress", "started", "ready",
    "configuring", "live", "voting", "captains_picking",
}

STATE_PRIORITY = [
    "ONGOING", "READY", "CONFIGURING", "VOTING",
    "LIVE", "STARTED", "IN_PROGRESS",
]

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))

def normalize(value: float, key: str) -> float:
    lo, hi = NORM[key]["min"], NORM[key]["max"]
    return clamp((value - lo) / (hi - lo))

def read_bool_env(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() not in {"0", "false", "no", "off"}

def is_active_status(status) -> bool:
    return str(status or "").strip().lower() in ACTIVE_MATCH_STATUSES

def is_plausible_match_id(value) -> bool:
    text = str(value or "").strip()
    return bool(re.match(r"^(?:[0-9]+-)?[0-9a-fA-F-]{20,}$", text)) if text else False

def build_ssl_option():
    if not read_bool_env("FACEIT_SSL_VERIFY", default=True):
        return False
    try:
        if certifi:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()
    except Exception:
        return True

def resolve_curl_verify() -> bool:
    return read_bool_env("FACEIT_SSL_VERIFY", default=True)

def emit_json(payload: dict) -> None:
    print(JSON_MARKER + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

def elo_to_level_label(elo: int) -> str:
    thresholds = [500, 750, 900, 1050, 1200, 1350, 1530, 1750, 2000, 2250]
    for i, t in enumerate(thresholds):
        if elo < t:
            return f"Level {i+1}"
    return "Level 10"

def color_kd(kd: float) -> str:
    if kd >= 1.15:
        return f"{Fore.GREEN}{kd:.2f}{Style.RESET_ALL}"
    elif kd >= 0.9:
        return f"{Fore.YELLOW}{kd:.2f}{Style.RESET_ALL}"
    else:
        return f"{Fore.RED}{kd:.2f}{Style.RESET_ALL}"

# ─── SCORE PROBABILITY ────────────────────────────────────────────────────────

def compute_score_probability(
    our_rounds: int,
    enemy_rounds: int,
    p_round_win: float,
    target: int = ROUNDS_TO_WIN,
) -> float:
    """
    Probabilité analytique que notre équipe gagne la partie depuis le score actuel.

    Utilise la programmation dynamique : P[a][b] = probabilité de gagner
    sachant qu'il faut encore 'a' rounds à notre équipe et 'b' à l'adversaire.

    p_round_win : probabilité de gagner un round individuel
                  (= base_prob du script statique, bornée pour rester robuste)
    """
    p = clamp(p_round_win, 0.05, 0.95)

    # Rounds encore nécessaires
    need_us    = target - our_rounds
    need_enemy = target - enemy_rounds

    if need_us <= 0:
        return 1.0
    if need_enemy <= 0:
        return 0.0

    # Tableau DP : dp[a][b] = P(gagner | need a rounds, enemy needs b rounds)
    # Dimensions max: need_us x need_enemy
    dp: list[list[float]] = [[0.0] * (need_enemy + 1) for _ in range(need_us + 1)]

    # Conditions aux bords
    for b in range(1, need_enemy + 1):
        dp[0][b] = 1.0   # nous avons déjà gagné
    for a in range(1, need_us + 1):
        dp[a][0] = 0.0   # l'adversaire a déjà gagné

    for a in range(1, need_us + 1):
        for b in range(1, need_enemy + 1):
            dp[a][b] = p * dp[a - 1][b] + (1 - p) * dp[a][b - 1]

    return dp[need_us][need_enemy]


def blend_probabilities(
    base_prob: float,
    score_prob: float,
    our_rounds: int,
    enemy_rounds: int,
    target: int = ROUNDS_TO_WIN,
) -> float:
    """
    Combine la probabilité statique (stats des joueurs) et la probabilité
    dynamique (score actuel) via un poids qui croît avec le nombre de rounds joués.

    Au début (0-0) : 100% basé sur les stats.
    À mi-match      : ~50/50.
    En fin de match : presque 100% basé sur le score.
    """
    rounds_played = our_rounds + enemy_rounds
    max_rounds_before_win = max(1, 2 * (target - 1))  # 24 si target=13
    progress = clamp(rounds_played / max_rounds_before_win)

    # Plus le match avance, plus on fait confiance au score en direct.
    weight_progress = progress ** SCORE_BLEND_POWER

    # Renforce encore l'influence du score quand l'écart de rounds se creuse.
    round_gap = abs(our_rounds - enemy_rounds)
    gap_boost = clamp(round_gap / max(1, target - 1)) * SCORE_GAP_WEIGHT

    weight = clamp(max(weight_progress, SCORE_MIN_WEIGHT) + gap_boost, SCORE_MIN_WEIGHT, 0.97)

    return clamp(base_prob * (1 - weight) + score_prob * weight, 0.02, 0.98)


# ─── API CLIENT ───────────────────────────────────────────────────────────────

class FaceitClient:
    def __init__(self, api_key: str, session: aiohttp.ClientSession):
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        self.session = session

    async def _get(self, path: str, params: dict = None) -> Optional[dict]:
        url = f"{BASE_URL}{path}"
        try:
            async with self.session.get(url, headers=self.headers, params=params) as resp:
                if resp.status == 404:
                    return None
                if resp.status == 429:
                    await asyncio.sleep(2)
                    return await self._get(path, params)
                resp.raise_for_status()
                return await resp.json()
        except Exception:
            return None

    async def get_player_by_nickname(self, nickname: str) -> Optional[dict]:
        return await self._get("/players", {"nickname": nickname, "game": GAME_ID})

    async def get_player(self, player_id: str) -> Optional[dict]:
        return await self._get(f"/players/{player_id}")

    async def get_player_stats_matches(self, player_id: str, limit: int = 30) -> Optional[dict]:
        return await self._get(f"/players/{player_id}/games/{GAME_ID}/stats",
                               {"limit": limit, "offset": 0})

    async def get_player_history(self, player_id: str, limit: int = 30,
                                  game: str = GAME_ID, from_ts: int = None,
                                  to_ts: int = None) -> Optional[dict]:
        params: dict = {"offset": 0, "limit": limit}
        if game:     params["game"] = game
        if from_ts:  params["from"] = int(from_ts)
        if to_ts:    params["to"]   = int(to_ts)
        return await self._get(f"/players/{player_id}/history", params)

    async def get_match(self, match_id: str) -> Optional[dict]:
        return await self._get(f"/matches/{match_id}")


# ─── SCORE FETCHER (multi-source) ─────────────────────────────────────────────

async def fetch_live_score(
    client: FaceitClient,
    match_id: str,
    our_faction: str,
    enemy_faction: str,
) -> Tuple[int, int, str, str, str]:
    """
    Récupère le score en temps réel depuis plusieurs sources par ordre de fiabilité.
    Retourne (our_score, enemy_score, source_name, our_side, enemy_side).

    Sources essayées :
      1. FACEIT Data API v4  /matches/{match_id}  → results.score
      2. FACEIT Web API interne  /api/match/v2/match/{match_id}
      3. FACEIT Web API interne  /api/match/v1/matches/{match_id}
    """
    # ── Source 1 : Data API v4 ─────────────────────────────────────────────────
    match_data = await client.get_match(match_id)
    if match_data:
        score = _extract_score_from_data_api(match_data, our_faction, enemy_faction)
        if score is not None:
            teams = match_data.get("teams") or {}
            our_side = _extract_side_from_team_obj(teams.get(our_faction) or {})
            enemy_side = _extract_side_from_team_obj(teams.get(enemy_faction) or {})
            return score[0], score[1], "data_api_v4", our_side, enemy_side

    # ── Source 2 : Web API v2 ──────────────────────────────────────────────────
    try:
        resp = cfrequests.get(
            f"{FACEIT_WEB_BASE}/api/match/v2/match/{match_id}",
            impersonate="chrome",
            timeout=12,
            verify=resolve_curl_verify(),
        )
        if resp.status_code == 200:
            payload = resp.json().get("payload", {}) or {}
            score = _extract_score_from_web_v2(payload, our_faction, enemy_faction)
            if score is not None:
                teams = payload.get("teams") or {}
                our_team = teams.get(our_faction) or teams.get("faction1") or {}
                enemy_team = teams.get(enemy_faction) or teams.get("faction2") or {}
                our_side = _extract_side_from_team_obj(our_team)
                enemy_side = _extract_side_from_team_obj(enemy_team)
                return score[0], score[1], "web_api_v2", our_side, enemy_side
    except Exception:
        pass

    # ── Source 3 : Web API v1 ──────────────────────────────────────────────────
    try:
        resp = cfrequests.get(
            f"{FACEIT_WEB_BASE}/api/match/v1/matches/{match_id}",
            impersonate="chrome",
            timeout=12,
            verify=resolve_curl_verify(),
        )
        if resp.status_code == 200:
            payload = resp.json().get("payload", {}) or {}
            score = _extract_score_from_web_v1(payload, our_faction, enemy_faction)
            if score is not None:
                teams = payload.get("teams") or {}
                our_team = teams.get(our_faction) or teams.get("faction1") or {}
                enemy_team = teams.get(enemy_faction) or teams.get("faction2") or {}
                our_side = _extract_side_from_team_obj(our_team)
                enemy_side = _extract_side_from_team_obj(enemy_team)
                return score[0], score[1], "web_api_v1", our_side, enemy_side
    except Exception:
        pass

    return 0, 0, "unavailable", "", ""


def _normalize_side_label(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text in {"CT", "COUNTER_TERRORIST", "COUNTER-TERRORIST", "COUNTER TERRORIST", "COUNTERTERRORISTS"}:
        return "CT"
    if text in {"T", "TERRORIST", "TERRORISTS"}:
        return "T"
    return ""


def _extract_side_from_team_obj(team_obj: dict) -> str:
    if not isinstance(team_obj, dict):
        return ""

    stats = team_obj.get("stats") or {}
    for key in ("side", "current_side", "currentSide", "team_side", "teamSide", "starting_side", "startingSide"):
        candidate = team_obj.get(key)
        normalized = _normalize_side_label(candidate)
        if normalized:
            return normalized

        if isinstance(stats, dict):
            candidate_stats = stats.get(key)
            normalized_stats = _normalize_side_label(candidate_stats)
            if normalized_stats:
                return normalized_stats

    return ""


def _extract_score_from_data_api(
    match: dict,
    our_faction: str,
    enemy_faction: str,
) -> Optional[Tuple[int, int]]:
    """
    Cherche le score dans la réponse de /matches/{match_id} (Data API v4).
    Le champ 'results' peut être présent pendant le match ou seulement après.
    Également disponible sous 'score' dans 'teams' parfois.
    """
    results = match.get("results") or {}

    # Format : results = {"score": {"faction1": 7, "faction2": 4}, "winner": "faction1"}
    score_map = results.get("score") or {}
    if isinstance(score_map, dict) and score_map:
        our   = int(score_map.get(our_faction,    score_map.get("faction1", 0)) or 0)
        enemy = int(score_map.get(enemy_faction, score_map.get("faction2", 0)) or 0)
        if our > 0 or enemy > 0:
            return our, enemy

    # Certains matchs exposent le score différemment selon la version de l'API
    # Exemple: match["teams"]["faction1"]["score"]
    teams = match.get("teams") or {}
    our_score_t   = (teams.get(our_faction)    or {}).get("score")
    enemy_score_t = (teams.get(enemy_faction) or {}).get("score")
    if our_score_t is not None or enemy_score_t is not None:
        return int(our_score_t or 0), int(enemy_score_t or 0)

    return None


def _extract_score_from_web_v2(
    payload: dict,
    our_faction: str,
    enemy_faction: str,
) -> Optional[Tuple[int, int]]:
    """Extrait le score depuis la Web API v2 (payload interne)."""
    # Format courant : payload.voting.map + payload.teams.faction1.stats.score
    teams = payload.get("teams") or {}
    our_data   = teams.get(our_faction)    or teams.get("faction1") or {}
    enemy_data = teams.get(enemy_faction) or teams.get("faction2") or {}

    # Cherche dans stats
    our_score   = (our_data.get("stats")   or {}).get("score") \
               or our_data.get("score")
    enemy_score = (enemy_data.get("stats") or {}).get("score") \
               or enemy_data.get("score")

    if our_score is not None or enemy_score is not None:
        return int(our_score or 0), int(enemy_score or 0)

    # Format alternatif : payload.score = {"faction1": 5, "faction2": 3}
    score_obj = payload.get("score") or {}
    if isinstance(score_obj, dict) and score_obj:
        return (
            int(score_obj.get(our_faction, score_obj.get("faction1", 0)) or 0),
            int(score_obj.get(enemy_faction, score_obj.get("faction2", 0)) or 0),
        )

    return None


def _extract_score_from_web_v1(
    payload: dict,
    our_faction: str,
    enemy_faction: str,
) -> Optional[Tuple[int, int]]:
    """Extrait le score depuis la Web API v1."""
    # Format: payload.results.score ou payload.score
    results = payload.get("results") or {}
    score_map = results.get("score") or payload.get("score") or {}
    if isinstance(score_map, dict) and score_map:
        our   = int(score_map.get(our_faction,    score_map.get("faction1", 0)) or 0)
        enemy = int(score_map.get(enemy_faction, score_map.get("faction2", 0)) or 0)
        if our > 0 or enemy > 0:
            return our, enemy

    return None


# ─── MATCH RESOLVER ───────────────────────────────────────────────────────────

def _find_match_id_deep(data, depth=0, max_depth=5) -> str:
    if depth > max_depth:
        return ""
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in {"active_match_id", "ongoing_match_id",
                                    "current_match_id", "match_id", "faceit_match_id"}:
                if is_plausible_match_id(value):
                    return str(value).strip()
            nested = _find_match_id_deep(value, depth + 1, max_depth)
            if nested:
                return nested
    if isinstance(data, list):
        for item in data:
            nested = _find_match_id_deep(item, depth + 1, max_depth)
            if nested:
                return nested
    return ""


def _extract_active_match_id(player_data: dict) -> str:
    games = (player_data.get("games") or {})
    game_data = games.get(GAME_ID, {}) if isinstance(games, dict) else {}
    candidates = [
        player_data.get("active_match_id"),
        player_data.get("ongoing_match_id"),
        player_data.get("match_id"),
        (game_data or {}).get("active_match_id"),
        (game_data or {}).get("match_id"),
    ]
    for c in candidates:
        v = str(c or "").strip()
        if is_plausible_match_id(v):
            return v
    return _find_match_id_deep(player_data)


def _normalize_nickname(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().casefold()


def _extract_player_id_from_member(member: dict) -> str:
    if not isinstance(member, dict):
        return ""
    for key in ("player_id", "playerId", "id", "user_id", "userId", "faceit_id", "faceitId"):
        value = str(member.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_player_nickname_from_member(member: dict) -> str:
    if not isinstance(member, dict):
        return ""
    for key in ("nickname", "nick", "name", "game_player_name", "gamePlayerName"):
        value = str(member.get(key) or "").strip()
        if value:
            return value
    return ""


def _iter_team_members(team_data: dict):
    if not isinstance(team_data, dict):
        return

    containers = [
        team_data.get("roster"),
        team_data.get("players"),
        team_data.get("members"),
        team_data.get("lineup"),
        team_data.get("line_up"),
    ]

    for container in containers:
        if isinstance(container, list):
            for item in container:
                if isinstance(item, dict):
                    yield item
        elif isinstance(container, dict):
            for key, value in container.items():
                if isinstance(value, dict):
                    candidate = dict(value)
                    if not _extract_player_id_from_member(candidate):
                        candidate["player_id"] = str(key)
                    yield candidate

    captain = team_data.get("captain")
    if isinstance(captain, dict):
        yield captain
    elif captain is not None:
        yield {"player_id": str(captain)}


def _resolve_player_faction(teams: dict, player_id: str, nickname_candidates: List[str]) -> str:
    target_id = str(player_id or "").strip()
    normalized_nicks = {_normalize_nickname(n) for n in nickname_candidates}
    normalized_nicks.discard("")

    for faction_key, faction_data in (teams or {}).items():
        for member in _iter_team_members(faction_data):
            member_id = _extract_player_id_from_member(member)
            if target_id and member_id and member_id == target_id:
                return faction_key

            member_nick = _normalize_nickname(_extract_player_nickname_from_member(member))
            if member_nick and member_nick in normalized_nicks:
                return faction_key

    return ""


def _team_member_debug_preview(team_data: dict, limit: int = 5) -> str:
    previews: List[str] = []
    for member in _iter_team_members(team_data):
        member_nick = _extract_player_nickname_from_member(member)
        member_id = _extract_player_id_from_member(member)
        label = member_nick or member_id
        if label and label not in previews:
            previews.append(label)
        if len(previews) >= limit:
            break
    return ", ".join(previews)


async def resolve_match_via_web_api(player_id: str) -> str:
    """Utilise l'API web interne FACEIT pour trouver le match en cours (groupByState)."""
    try:
        resp = cfrequests.get(
            f"{FACEIT_WEB_BASE}/api/match/v1/matches/groupByState",
            params={"userId": player_id},
            impersonate="chrome",
            timeout=18,
            verify=resolve_curl_verify(),
        )
        if resp.status_code != 200:
            return ""
        payload = resp.json().get("payload", {}) or {}
        if not isinstance(payload, dict):
            return ""
        for state in STATE_PRIORITY:
            items = payload.get(state)
            if isinstance(items, list) and items:
                first = items[0] if isinstance(items[0], dict) else {}
                mid = str(first.get("id") or first.get("match_id") or "").strip()
                if mid:
                    return mid
        for _, items in payload.items():
            if isinstance(items, list) and items:
                first = items[0] if isinstance(items[0], dict) else {}
                mid = str(first.get("id") or first.get("match_id") or "").strip()
                if mid:
                    return mid
    except Exception:
        pass
    return ""


async def resolve_match(
    client: FaceitClient,
    nickname: str,
    forced_match_id: str = "",
) -> Tuple[str, str, str, str, dict]:
    """
    Résout (player_id, match_id, our_faction, enemy_faction, match_details).
    Plusieurs strategies de fallback pour trouver le match actif.
    """
    print(f"\n{Fore.WHITE}[1/4] Résolution du joueur {Fore.CYAN}{nickname}{Fore.WHITE}...{Style.RESET_ALL}")
    player_data = await client.get_player_by_nickname(nickname)
    if not player_data:
        raise RuntimeError(f"Joueur '{nickname}' introuvable sur FACEIT.")

    player_id = player_data["player_id"]
    player_details = await client.get_player(player_id) or player_data
    profile = player_details
    resolved_nickname = str(profile.get("nickname") or player_data.get("nickname") or nickname or "").strip()

    game_data = (profile.get("games") or {}).get(GAME_ID) or {}
    our_elo   = game_data.get("faceit_elo", 1000)
    print(f"  ✓ {Fore.CYAN}{nickname}{Style.RESET_ALL} — ELO {Fore.YELLOW}{our_elo}{Style.RESET_ALL} ({elo_to_level_label(our_elo)})")

    # ── Résolution du match ─────────────────────────────────────────────────────
    print(f"\n{Fore.WHITE}[2/4] Recherche du match en cours...{Style.RESET_ALL}")
    match_id = ""

    if forced_match_id and is_plausible_match_id(forced_match_id):
        match_id = forced_match_id
        print(f"  ⚙️  Match forcé : {Fore.YELLOW}{match_id}{Style.RESET_ALL}")

    if not match_id:
        match_id = _extract_active_match_id(profile) or _extract_active_match_id(player_data)
        if match_id:
            print(f"  ✓ Match via profil joueur : {Fore.YELLOW}{match_id}{Style.RESET_ALL}")

    if not match_id:
        match_id = await resolve_match_via_web_api(player_id)
        if match_id:
            print(f"  ✓ Match via API web interne : {Fore.YELLOW}{match_id}{Style.RESET_ALL}")

    if not match_id:
        now = int(time.time())
        history = await client.get_player_history(player_id, limit=5, game=GAME_ID,
                                                   from_ts=now - ACTIVE_LOOKBACK_SEC)
        for item in (history or {}).get("items", []):
            mid = str(item.get("match_id") or "").strip()
            if not is_plausible_match_id(mid):
                continue
            details = await client.get_match(mid)
            if details and is_active_status(details.get("status")):
                match_id = mid
                print(f"  ✓ Match via history récent : {Fore.YELLOW}{match_id}{Style.RESET_ALL}")
                break

    if not match_id:
        raise RuntimeError(
            f"Aucune partie en cours trouvée pour '{nickname}'. "
            "Vérifiez que le joueur est bien en match sur CS2 FACEIT."
        )

    # ── Détails du match ────────────────────────────────────────────────────────
    print(f"\n{Fore.WHITE}[3/4] Récupération des détails du match...{Style.RESET_ALL}")
    match = await client.get_match(match_id)
    if not match:
        raise RuntimeError(f"Impossible de récupérer le match {match_id}.")

    teams = match.get("teams") or {}
    faction_keys = list(teams.keys())
    if len(faction_keys) < 2:
        raise RuntimeError("Structure de teams inattendue dans le match.")

    our_faction = _resolve_player_faction(
        teams,
        player_id=player_id,
        nickname_candidates=[nickname, resolved_nickname],
    )
    if not our_faction:
        debug_lines = []
        for fk in faction_keys:
            preview = _team_member_debug_preview(teams.get(fk) or {})
            debug_lines.append(f"  - {fk}: {preview or 'aucun joueur détecté'}")
        debug_dump = "\n".join(debug_lines)
        raise RuntimeError(
            "Impossible d'identifier l'équipe du joueur dans le roster du match.\n"
            f"  nickname input    : {nickname}\n"
            f"  nickname résolu   : {resolved_nickname or '--'}\n"
            f"  player_id         : {player_id}\n"
            f"  match_id          : {match_id}\n"
            "  Aperçu rosters:\n"
            f"{debug_dump}"
        )

    enemy_candidates = [k for k in faction_keys if k != our_faction]
    if not enemy_candidates:
        raise RuntimeError(
            f"Impossible de déterminer l'équipe adverse pour match_id={match_id} (our_faction={our_faction})."
        )
    enemy_faction = enemy_candidates[0]

    map_name = "inconnue"
    voting = match.get("voting") or {}
    picks  = (voting.get("map") or {}).get("pick") or []
    if picks:
        map_name = picks[0]

    print(f"  ✓ Map       : {Fore.YELLOW}{map_name}{Style.RESET_ALL}")
    print(f"  ✓ Équipe    : {Fore.CYAN}{teams[our_faction].get('name', our_faction)}{Style.RESET_ALL}"
          f" vs {Fore.MAGENTA}{teams[enemy_faction].get('name', enemy_faction)}{Style.RESET_ALL}")
    print(f"  ✓ Room      : {FACEIT_WEB_BASE}/en/cs2/room/{match_id}")

    return player_id, match_id, our_faction, enemy_faction, match


# ─── STATS ANALYSIS ───────────────────────────────────────────────────────────

async def get_player_metrics(client: FaceitClient, player: dict, map_name: str) -> dict:
    pid  = player["player_id"]
    elo  = player.get("faceit_elo", 1000)
    level = player.get("game_skill_level", 5)

    metrics = {
        "nickname":      player.get("nickname", "?"),
        "player_id":     pid,
        "elo":           elo,
        "level":         level,
        "kd":            1.0,
        "winrate":       0.5,
        "map_winrate":   0.5,
        "hs_pct":        0.0,
        "avg_kills":     15.0,
        "matches_analyzed": 0,
        "map_matches":   0,
    }

    # Tente de récupérer l'ELO réel
    try:
        detail = await client._get(f"/players/{pid}")
        if detail:
            gd  = (detail.get("games") or {}).get(GAME_ID) or {}
            elo  = gd.get("faceit_elo", elo)
            level = gd.get("skill_level", level)
            metrics.update({"elo": elo, "level": level})
    except Exception:
        pass

    data = await client.get_player_stats_matches(pid, limit=STATS_LIMIT)
    if not data or not data.get("items"):
        return metrics

    items = data["items"]
    metrics["matches_analyzed"] = len(items)

    kills_list, deaths_list, hs_list, wins = [], [], [], 0
    map_wins, map_total = 0, 0

    for item in items:
        s = item.get("stats") or {}
        try:
            k  = float(s.get("Kills",    s.get("kills",    0)))
            d  = float(s.get("Deaths",   s.get("deaths",   1)))
            hs = float(s.get("Headshots",s.get("headshots",0)))
            result    = str(s.get("Result", s.get("result", "0")))
            match_map = str(s.get("Map",    s.get("map",    "")))

            kills_list.append(k)
            deaths_list.append(d)
            hs_list.append(hs)
            if result == "1":
                wins += 1

            map_clean  = map_name.lower().replace("de_", "")
            item_clean = match_map.lower().replace("de_", "")
            if map_clean and map_clean in item_clean:
                map_total += 1
                if result == "1":
                    map_wins += 1

        except (ValueError, TypeError):
            continue

    n = len(kills_list)
    if n > 0:
        metrics["kd"]        = sum(kills_list) / max(sum(deaths_list), 1)
        metrics["winrate"]   = wins / n
        metrics["avg_kills"] = sum(kills_list) / n
        metrics["hs_pct"]   = sum(hs_list) / max(sum(kills_list), 1)

    metrics["map_winrate"] = (map_wins / map_total) if map_total > 0 else metrics["winrate"]
    metrics["map_matches"] = map_total
    return metrics


def compute_player_score(m: dict) -> float:
    s  = WEIGHTS["elo"]         * normalize(m["elo"],         "elo")
    s += WEIGHTS["kd"]          * normalize(m["kd"],          "kd")
    s += WEIGHTS["winrate"]     * normalize(m["winrate"],      "winrate")
    s += WEIGHTS["map_winrate"] * normalize(m["map_winrate"],  "map_winrate")
    s += WEIGHTS["hs_pct"]      * normalize(m["hs_pct"],       "hs_pct")
    s += WEIGHTS["avg_kills"]   * normalize(m["avg_kills"],    "avg_kills")
    return clamp(s)


def compute_base_win_probability(team_score: float, enemy_score: float) -> float:
    diff = team_score - enemy_score
    k    = 10.0
    prob = 1 / (1 + math.exp(-k * diff))
    return clamp(prob, 0.05, 0.95)


async def run_stats_analysis(
    client: FaceitClient,
    match: dict,
    our_faction: str,
    enemy_faction: str,
    map_name: str,
    nickname: str,
) -> Tuple[float, List[dict], List[dict]]:
    """Analyse les stats des 10 joueurs et retourne (base_prob, our_metrics, enemy_metrics)."""

    teams        = match.get("teams") or {}
    our_roster   = (teams.get(our_faction)    or {}).get("roster") or []
    enemy_roster = (teams.get(enemy_faction) or {}).get("roster") or []

    print(f"\n{Fore.WHITE}[4/4] Analyse des stats de {len(our_roster)+len(enemy_roster)} joueurs...{Style.RESET_ALL}")

    async def fetch(player_info: dict, faction: str) -> dict:
        pid  = player_info.get("player_id")
        nick = player_info.get("nickname", "?")
        elo  = player_info.get("faceit_elo", 1000)
        level = player_info.get("game_skill_level", 5)
        try:
            detail = await client._get(f"/players/{pid}")
            if detail:
                gd    = (detail.get("games") or {}).get(GAME_ID) or {}
                elo   = gd.get("faceit_elo", elo)
                level = gd.get("skill_level", level)
        except Exception:
            pass
        enriched = {**player_info, "faceit_elo": elo, "game_skill_level": level}
        m = await get_player_metrics(client, enriched, map_name)
        m["faction"] = faction
        sc = compute_player_score(m)
        tag = "◄" if faction == our_faction else " "
        print(f"  {tag} {nick:<20} ELO:{m['elo']:>5}  K/D:{m['kd']:.2f}  WR:{m['winrate']*100:.0f}%  MapWR:{m['map_winrate']*100:.0f}%  Score:{sc:.3f}")
        return m

    tasks  = [fetch(p, our_faction)   for p in our_roster]
    tasks += [fetch(p, enemy_faction) for p in enemy_roster]
    all_m  = await asyncio.gather(*tasks)

    our_m   = [m for m in all_m if m["faction"] == our_faction]
    enemy_m = [m for m in all_m if m["faction"] == enemy_faction]

    our_score   = sum(compute_player_score(m) for m in our_m)   / max(len(our_m),   1)
    enemy_score = sum(compute_player_score(m) for m in enemy_m) / max(len(enemy_m), 1)

    base_prob = compute_base_win_probability(our_score, enemy_score)
    return base_prob, our_m, enemy_m


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def print_team_table(team_name: str, players_metrics: List[dict], is_ours: bool) -> float:
    color = Fore.CYAN if is_ours else Fore.MAGENTA
    tag   = " ◄ VOTRE ÉQUIPE" if is_ours else ""
    print(f"\n{color}{'═'*80}\n  {team_name.upper()}{tag}\n{'═'*80}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}  {'Joueur':<20} {'ELO':>6} {'Lvl':>4} {'K/D':>7} {'WR%':>7} {'WR Map':>9} {'HS%':>6} {'Score':>7}{Style.RESET_ALL}")
    print(f"  {'-'*74}")

    scores = []
    for m in players_metrics:
        sc = compute_player_score(m)
        scores.append(sc)
        map_wr = f"{m['map_winrate']*100:.0f}%" + ("*" if m["map_matches"] == 0 else "")
        print(f"  {m['nickname'][:19]:<20} {m['elo']:>6} {m['level']:>4}  "
              f"{color_kd(m['kd']):>14}  "
              f"{m['winrate']*100:>5.0f}%  "
              f"{m['map_winrate']*100:>6.0f}%  "
              f"{m['hs_pct']*100:>5.0f}%  "
              f"{color}{sc:.3f}{Style.RESET_ALL}")

    avg = sum(scores) / len(scores) if scores else 0.0
    print(f"  {'-'*74}")
    print(f"  {'Score moyen équipe':<20} {color}{avg:.4f}{Style.RESET_ALL}")
    return avg


def print_static_analysis(
    our_team: str,
    enemy_team: str,
    our_m: List[dict],
    enemy_m: List[dict],
    base_prob: float,
    map_name: str,
):
    print("\n\n" + "═"*80)
    print("  📊  ANALYSE INITIALE (avant le début ou hors score)")
    print("═"*80)
    print_team_table(our_team,    our_m,   is_ours=True)
    print_team_table(enemy_team, enemy_m, is_ours=False)
    _print_prob_bar(our_team, base_prob, map_name, label="BASE (stats uniquement)")


def _print_prob_bar(team: str, prob: float, map_name: str, label: str = "", score_info: str = ""):
    bar_len = 50
    filled  = round(prob * bar_len)
    empty   = bar_len - filled
    color   = Fore.GREEN if prob >= 0.55 else (Fore.YELLOW if prob >= 0.45 else Fore.RED)
    bar     = f"{color}{'█' * filled}{Fore.WHITE}{'░' * empty}{Style.RESET_ALL}"

    if prob >= 0.65:
        verdict = f"{Fore.GREEN}✅ FAVORABLE"
    elif prob >= 0.55:
        verdict = f"{Fore.GREEN}🟢 Légèrement favorable"
    elif prob >= 0.45:
        verdict = f"{Fore.YELLOW}⚖️  Équilibré"
    elif prob >= 0.35:
        verdict = f"{Fore.RED}🔴 Légèrement défavorable"
    else:
        verdict = f"{Fore.RED}❌ DÉFAVORABLE"

    score_str = f"  Score : {Fore.YELLOW}{score_info}{Style.RESET_ALL}\n" if score_info else ""

    print(f"\n{'═'*80}")
    if label:
        print(f"  🎯  {label}")
    print(f"  🗺️  MAP : {Fore.WHITE}{map_name.upper()}{Style.RESET_ALL}")
    print(f"  Équipe  : {Fore.CYAN}{team}{Style.RESET_ALL}")
    print(f"{'═'*80}")
    print(f"\n{score_str}  [{bar}]  {color}{prob*100:.1f}%{Style.RESET_ALL}  ← {verdict}{Style.RESET_ALL}\n")


def print_live_update(
    our_team: str,
    enemy_team: str,
    our_rounds: int,
    enemy_rounds: int,
    base_prob: float,
    dynamic_prob: float,
    score_prob: float,
    map_name: str,
    source: str,
    poll_num: int,
):
    ts = time.strftime("%H:%M:%S")
    print(f"\n{'─'*80}")
    print(f"  🔴 LIVE — Poll #{poll_num}  [{ts}]  Source: {source}")
    print(f"  Score : {Fore.CYAN}{our_team}{Style.RESET_ALL} {Fore.WHITE}{our_rounds}{Style.RESET_ALL}"
          f" – {Fore.WHITE}{enemy_rounds}{Style.RESET_ALL} {Fore.MAGENTA}{enemy_team}{Style.RESET_ALL}")
    rounds_played = our_rounds + enemy_rounds
    print(f"  Rounds joués : {rounds_played} / ~{2*(ROUNDS_TO_WIN-1)}")
    print(f"{'─'*80}")

    bar_len = 50
    filled  = round(dynamic_prob * bar_len)
    empty   = bar_len - filled
    color   = Fore.GREEN if dynamic_prob >= 0.55 else (Fore.YELLOW if dynamic_prob >= 0.45 else Fore.RED)
    bar     = f"{color}{'█' * filled}{Fore.WHITE}{'░' * empty}{Style.RESET_ALL}"

    print(f"\n  Win Probability (DYNAMIQUE)   [{bar}]  {color}{dynamic_prob*100:.1f}%{Style.RESET_ALL}")
    print(f"  ├─ Base (stats joueurs)    : {base_prob*100:.1f}%")
    print(f"  └─ Score (état du match)   : {score_prob*100:.1f}%")

    rounds_left_us    = ROUNDS_TO_WIN - our_rounds
    rounds_left_enemy = ROUNDS_TO_WIN - enemy_rounds
    print(f"\n  Rounds manquants : {Fore.CYAN}{our_team}{Style.RESET_ALL} — {rounds_left_us} | "
          f"{Fore.MAGENTA}{enemy_team}{Style.RESET_ALL} — {rounds_left_enemy}")

    if dynamic_prob >= 0.65:
        verdict = f"{Fore.GREEN}✅ TRÈS FAVORABLE"
    elif dynamic_prob >= 0.55:
        verdict = f"{Fore.GREEN}🟢 Légèrement favorable"
    elif dynamic_prob >= 0.45:
        verdict = f"{Fore.YELLOW}⚖️  Match serré"
    elif dynamic_prob >= 0.35:
        verdict = f"{Fore.RED}🔴 Défavorable"
    else:
        verdict = f"{Fore.RED}❌ TRÈS DÉFAVORABLE"

    print(f"\n  Verdict : {verdict}{Style.RESET_ALL}\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv: list) -> Tuple[str, str, bool, bool]:
    nickname, forced_match_id, output_json = "", str(os.getenv("FACEIT_MATCH_ID","")).strip(), False
    run_once = False
    positional = []
    i = 0
    while i < len(argv):
        tok = str(argv[i]).strip()
        if tok == "--json":
            output_json = True
        elif tok in ("--once", "--one-shot"):
            run_once = True
        elif tok in ("--match-id", "-m") and i + 1 < len(argv):
            forced_match_id = str(argv[i + 1]).strip()
            i += 1
        else:
            positional.append(tok)
        i += 1

    if positional:
        nickname = positional[0]
    if len(positional) >= 2 and not forced_match_id and is_plausible_match_id(positional[1]):
        forced_match_id = positional[1]
    return nickname, forced_match_id, output_json, run_once


# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    api_key = str(os.getenv("FACEIT_API_KEY") or "").strip()
    if not api_key:
        print(f"{Fore.RED}[ERREUR] FACEIT_API_KEY manquante dans le .env{Style.RESET_ALL}")
        sys.exit(1)

    nickname, forced_match_id, output_json, run_once = parse_args(sys.argv[1:])

    if not nickname:
        nickname = input(f"{Fore.CYAN}▶ Nickname FACEIT : {Style.RESET_ALL}").strip()
    if not nickname:
        print(f"{Fore.RED}[ERREUR] Nickname vide.{Style.RESET_ALL}")
        sys.exit(1)

    ssl_opt   = build_ssl_option()
    timeout   = aiohttp.ClientTimeout(total=60, connect=15, sock_read=45)
    connector = aiohttp.TCPConnector(ssl=ssl_opt)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
        client = FaceitClient(api_key, session)

        # ── Résolution du match ─────────────────────────────────────────────────
        try:
            player_id, match_id, our_faction, enemy_faction, match = await resolve_match(
                client, nickname, forced_match_id
            )
        except RuntimeError as e:
            print(f"{Fore.RED}[ERREUR] {e}{Style.RESET_ALL}")
            if output_json:
                emit_json({"ok": False, "nickname": nickname, "error": str(e)})
            sys.exit(1)

        teams       = match.get("teams") or {}
        our_team    = (teams.get(our_faction)    or {}).get("name", our_faction)
        enemy_team  = (teams.get(enemy_faction) or {}).get("name", enemy_faction)

        map_name    = "inconnue"
        picks       = ((match.get("voting") or {}).get("map") or {}).get("pick") or []
        if picks:
            map_name = picks[0]

        # ── Analyse statique des stats joueurs ──────────────────────────────────
        base_prob, our_m, enemy_m = await run_stats_analysis(
            client, match, our_faction, enemy_faction, map_name, nickname
        )

        print_static_analysis(our_team, enemy_team, our_m, enemy_m, base_prob, map_name)

        print(f"\n{Fore.WHITE}{'═'*80}")
        print(f"  🔴 DÉMARRAGE DU SUIVI EN DIRECT  (refresh toutes les {POLL_INTERVAL}s)")
        print(f"     Appuyez sur Ctrl+C pour arrêter.")
        if run_once:
            print("     Mode --once actif : un snapshot live sera calculé puis le script se termine.")
        print(f"{'═'*80}{Style.RESET_ALL}\n")

        if output_json:
            emit_json({
                "ok": True, "type": "initial_analysis",
                "nickname": nickname, "player_id": player_id, "match_id": match_id,
                "map_name": map_name, "our_team": our_team, "enemy_team": enemy_team,
                "base_win_probability": round(base_prob, 6),
                "base_win_probability_pct": round(base_prob * 100, 2),
            })

        # ── Boucle de polling ───────────────────────────────────────────────────
        poll_num         = 0
        last_our_rounds  = -1
        last_enemy_rounds = -1

        try:
            while True:
                poll_num += 1
                our_r, enemy_r, source, our_side, enemy_side = await fetch_live_score(
                    client, match_id, our_faction, enemy_faction
                )

                # Calculs de probabilité
                # On atténue l'extrême de base_prob pour éviter des live probs
                # trop optimistes/pessimistes malgré un score réel défavorable.
                round_win_p = 0.5 + (clamp(base_prob) - 0.5) * ROUND_WIN_BASE_INFLUENCE
                score_prob   = compute_score_probability(our_r, enemy_r, round_win_p)
                dynamic_prob = blend_probabilities(base_prob, score_prob, our_r, enemy_r)

                # Affiche uniquement si le score a changé (ou 1er poll)
                score_changed = (our_r != last_our_rounds or enemy_r != last_enemy_rounds)
                if score_changed or poll_num == 1:
                    print_live_update(
                        our_team, enemy_team,
                        our_r, enemy_r,
                        base_prob, dynamic_prob, score_prob,
                        map_name, source, poll_num,
                    )
                    last_our_rounds   = our_r
                    last_enemy_rounds = enemy_r

                    if output_json:
                        emit_json({
                            "ok": True, "type": "live_update",
                            "poll": poll_num,
                            "nickname": nickname,
                            "player_id": player_id,
                            "match_id": match_id,
                            "map_name": map_name,
                            "our_team": our_team,
                            "enemy_team": enemy_team,
                            "score_our": our_r,
                            "score_enemy": enemy_r,
                            "our_side": our_side,
                            "enemy_side": enemy_side,
                            "score_source": source,
                            "base_win_probability":    round(base_prob,    6),
                            "score_win_probability":   round(score_prob,   6),
                            "dynamic_win_probability": round(dynamic_prob, 6),
                            "dynamic_win_probability_pct": round(dynamic_prob * 100, 2),
                        })

                if run_once:
                    break

                # Fin du match détecté
                if our_r >= ROUNDS_TO_WIN:
                    print(f"\n  🏆  {Fore.GREEN}VICTOIRE de {our_team} ({our_r}–{enemy_r}) !{Style.RESET_ALL}\n")
                    if output_json:
                        emit_json({"ok": True, "type": "match_over", "winner": our_team,
                                   "score": f"{our_r}-{enemy_r}"})
                    break
                if enemy_r >= ROUNDS_TO_WIN:
                    print(f"\n  ❌  {Fore.RED}DÉFAITE contre {enemy_team} ({our_r}–{enemy_r}).{Style.RESET_ALL}\n")
                    if output_json:
                        emit_json({"ok": True, "type": "match_over", "winner": enemy_team,
                                   "score": f"{our_r}-{enemy_r}"})
                    break

                print(f"  ⏳ Prochain refresh dans {POLL_INTERVAL}s...  ", end="", flush=True)
                await asyncio.sleep(POLL_INTERVAL)
                print(f"\r{' '*60}\r", end="", flush=True)

        except KeyboardInterrupt:
            print(f"\n\n{Fore.YELLOW}  ↩ Suivi interrompu.{Style.RESET_ALL}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        if "--json" in sys.argv:
            emit_json({"ok": False, "error": str(exc)})
        raise
