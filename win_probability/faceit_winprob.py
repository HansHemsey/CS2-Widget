#!/usr/bin/env python3
"""
FACEIT CS2 Win Probability Calculator
Analyse les 10 joueurs d'une room en cours et calcule la probabilité de victoire.
"""

import os
import sys
import asyncio
import re
import time
import json
import ssl
from pathlib import Path
import aiohttp
from dotenv import load_dotenv
from colorama import Fore, Style, init

try:
    import certifi
except Exception:
    certifi = None

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
load_dotenv(dotenv_path=ROOT_DIR / ".env", override=False)
load_dotenv(dotenv_path=SCRIPT_DIR / ".env", override=False)
init(autoreset=True)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
GAME_ID       = "cs2"
BASE_URL      = "https://open.faceit.com/data/v4"
STATS_LIMIT   = 30   # Nombre de matchs analysés par joueur
HISTORY_SCAN_LIMIT = 30
ACTIVE_LOOKBACK_SECONDS = 24 * 3600
ACTIVE_LOOKAHEAD_SECONDS = 12 * 3600

# Poids de chaque métrique dans le score final (doivent sommer à 1.0)
WEIGHTS = {
    "elo":          0.30,   # ELO FACEIT (indicateur de niveau global)
    "kd":           0.20,   # K/D ratio sur 30 matchs
    "winrate":      0.20,   # Win rate global sur 30 matchs
    "map_winrate":  0.20,   # Win rate sur la map en cours
    "hs_pct":       0.05,   # Headshot %
    "avg_kills":    0.05,   # Kills moyens par match
}

# Valeurs de référence pour la normalisation (contexte CS2 FACEIT)
NORM = {
    "elo":       {"min": 500,  "max": 4000},
    "kd":        {"min": 0.4,  "max": 2.5},
    "winrate":   {"min": 0.2,  "max": 0.9},
    "map_winrate":{"min": 0.1, "max": 1.0},
    "hs_pct":    {"min": 0.0,  "max": 0.70},
    "avg_kills": {"min": 5,    "max": 30},
}

# Statuts considérés comme "match en cours / room active"
ACTIVE_MATCH_STATUSES = {
    "ongoing",
    "in_progress",
    "started",
    "ready",
    "configuring",
    "live",
    "voting",
    "captains_picking",
}
# ──────────────────────────────────────────────────────────────────────────────


def clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def normalize(value, key):
    lo, hi = NORM[key]["min"], NORM[key]["max"]
    return clamp((value - lo) / (hi - lo))


def is_active_status(status) -> bool:
    return str(status or "").strip().lower() in ACTIVE_MATCH_STATUSES


def is_active_match_payload(match_payload: dict) -> bool:
    if not isinstance(match_payload, dict):
        return False

    status = str(match_payload.get("status") or "").strip().lower()
    if status and is_active_status(status):
        return True

    # Fallback prudent: un match non "finished" sans finished_at est potentiellement actif.
    if status and status not in {"finished", "cancelled", "aborted"} and not match_payload.get("finished_at"):
        return True

    return False


def is_plausible_match_id(value) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    # Match IDs FACEIT ressemblent le plus souvent à des UUID ou "1-<uuid>".
    return bool(re.match(r"^(?:[0-9]+-)?[0-9a-fA-F-]{20,}$", text))


def find_match_id_deep(data, depth=0, max_depth=5) -> str:
    if depth > max_depth:
        return ""

    if isinstance(data, dict):
        for key, value in data.items():
            key_l = str(key).lower()
            if key_l in {"active_match_id", "ongoing_match_id", "current_match_id", "match_id", "faceit_match_id"}:
                if is_plausible_match_id(value):
                    return str(value).strip()

            nested = find_match_id_deep(value, depth=depth + 1, max_depth=max_depth)
            if nested:
                return nested

    if isinstance(data, list):
        for item in data:
            nested = find_match_id_deep(item, depth=depth + 1, max_depth=max_depth)
            if nested:
                return nested

    return ""


def extract_active_match_id(player_data: dict) -> str:
    if not player_data:
        return ""

    games = player_data.get("games", {}) or {}
    game_data = games.get(GAME_ID, {}) if isinstance(games, dict) else {}
    if not isinstance(game_data, dict):
        game_data = {}

    candidates = [
        player_data.get("active_match_id"),
        player_data.get("ongoing_match_id"),
        player_data.get("match_id"),
        game_data.get("active_match_id"),
        game_data.get("ongoing_match_id"),
        game_data.get("match_id"),
    ]

    for candidate in candidates:
        value = str(candidate or "").strip()
        if is_plausible_match_id(value):
            return value

    deep_match_id = find_match_id_deep(player_data)
    if deep_match_id:
        return deep_match_id

    return ""


def pick_current_match_from_history(history_items: list) -> dict:
    if not history_items:
        return None

    # Priorité 1 : statuts explicitement actifs
    for match in history_items:
        if is_active_status(match.get("status")):
            return match

    # Priorité 2 : match créé mais pas encore fini (rare selon endpoints)
    for match in history_items:
        if not match.get("finished_at"):
            return match

    return None


def parse_cli_inputs(argv):
    """
    Parse:
      - positional: nickname
      - optional: --match-id <id> (ou -m)
      - optional: --json (émission d'une ligne JSON machine-readable)
      - optional: 2e argument positionnel = match_id
    """
    nickname = ""
    forced_match_id = str(os.getenv("FACEIT_MATCH_ID", "")).strip()
    output_json = False
    positional = []

    i = 0
    while i < len(argv):
        token = str(argv[i]).strip()
        if token == "--json":
            output_json = True
            i += 1
            continue

        if token in {"--match-id", "-m"}:
            if i + 1 >= len(argv):
                print(f"{Fore.RED}[ERREUR] Option {token} sans valeur.{Style.RESET_ALL}")
                sys.exit(1)
            forced_match_id = str(argv[i + 1]).strip()
            i += 2
            continue

        positional.append(token)
        i += 1

    if positional:
        nickname = positional[0].strip()

    if len(positional) >= 2 and not forced_match_id:
        candidate = positional[1].strip()
        if is_plausible_match_id(candidate):
            forced_match_id = candidate

    return nickname, forced_match_id, output_json


def emit_machine_payload(enabled: bool, payload: dict):
    if not enabled:
        return
    print("__WINPROB_JSON__" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def read_bool_env(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def build_ssl_option():
    verify_ssl = read_bool_env("FACEIT_SSL_VERIFY", default=True)
    if not verify_ssl:
        return False

    try:
        if certifi:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()
    except Exception:
        return True


def color_pct(pct: float) -> str:
    if pct >= 60:
        return f"{Fore.GREEN}{pct:.1f}%{Style.RESET_ALL}"
    elif pct >= 45:
        return f"{Fore.YELLOW}{pct:.1f}%{Style.RESET_ALL}"
    else:
        return f"{Fore.RED}{pct:.1f}%{Style.RESET_ALL}"


def color_kd(kd: float) -> str:
    if kd >= 1.15:
        return f"{Fore.GREEN}{kd:.2f}{Style.RESET_ALL}"
    elif kd >= 0.9:
        return f"{Fore.YELLOW}{kd:.2f}{Style.RESET_ALL}"
    else:
        return f"{Fore.RED}{kd:.2f}{Style.RESET_ALL}"


def elo_to_level_label(elo: int) -> str:
    thresholds = [500, 750, 900, 1050, 1200, 1350, 1530, 1750, 2000, 2250]
    for i, t in enumerate(thresholds):
        if elo < t:
            return f"Level {i+1}"
    return "Level 10"


# ─── API CLIENT ───────────────────────────────────────────────────────────────

class FaceitClient:
    def __init__(self, api_key: str, session: aiohttp.ClientSession):
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.session = session

    async def _get(self, path: str, params: dict = None):
        url = f"{BASE_URL}{path}"
        async with self.session.get(url, headers=self.headers, params=params) as resp:
            if resp.status == 404:
                return None
            if resp.status == 429:
                print(f"{Fore.RED}[RATE LIMIT] Trop de requêtes, pause 2s...{Style.RESET_ALL}")
                await asyncio.sleep(2)
                return await self._get(path, params)
            resp.raise_for_status()
            return await resp.json()

    async def get_player_by_nickname(self, nickname: str):
        return await self._get("/players", {"nickname": nickname})

    async def get_player(self, player_id: str):
        return await self._get(f"/players/{player_id}")

    async def search_players(self, nickname: str, game: str = GAME_ID, limit: int = 20, offset: int = 0):
        params = {"nickname": nickname, "limit": limit, "offset": offset}
        if game:
            params["game"] = game
        return await self._get("/search/players", params)

    async def get_player_history(
        self,
        player_id: str,
        limit: int = 30,
        offset: int = 0,
        game: str = GAME_ID,
        from_ts: int = None,
        to_ts: int = None,
    ):
        params = {"offset": offset, "limit": limit}
        if game:
            params["game"] = game
        if from_ts is not None:
            params["from"] = int(from_ts)
        if to_ts is not None:
            params["to"] = int(to_ts)
        return await self._get(f"/players/{player_id}/history", params)

    async def get_player_stats_matches(self, player_id: str, limit: int = 30):
        """Stats par match (K/D, kills, HS, résultat)"""
        return await self._get(f"/players/{player_id}/games/{GAME_ID}/stats", {
            "limit": limit, "offset": 0
        })

    async def get_player_lifetime_stats(self, player_id: str):
        """Stats globales lifetime (K/D moyen, win rate, etc.)"""
        return await self._get(f"/players/{player_id}/stats/{GAME_ID}")

    async def get_match(self, match_id: str):
        return await self._get(f"/matches/{match_id}")


# ─── STATS CALCULATOR ─────────────────────────────────────────────────────────

async def get_player_metrics(client: FaceitClient, player: dict, current_map: str) -> dict:
    """
    Collecte et calcule toutes les métriques d'un joueur pour le score final.
    """
    pid      = player["player_id"]
    nickname = player["nickname"]
    elo      = player.get("faceit_elo", 1000)
    level    = player.get("game_skill_level", 5)

    metrics = {
        "nickname":   nickname,
        "player_id":  pid,
        "elo":        elo,
        "level":      level,
        "kd":         1.0,
        "winrate":    0.5,
        "map_winrate":0.5,
        "hs_pct":     0.0,
        "avg_kills":  15.0,
        "matches_analyzed": 0,
        "map_matches": 0,
    }

    # --- Stats sur les 30 derniers matchs ---
    data = await client.get_player_stats_matches(pid, limit=STATS_LIMIT)
    if not data or not data.get("items"):
        return metrics

    items = data["items"]
    metrics["matches_analyzed"] = len(items)

    kills_list, deaths_list, hs_list, wins = [], [], [], 0
    map_wins, map_total = 0, 0

    for item in items:
        s = item.get("stats", {})

        # Récupère les stats avec les clés CS2 FACEIT
        try:
            k  = float(s.get("Kills", s.get("kills", 0)))
            d  = float(s.get("Deaths", s.get("deaths", 1)))
            hs = float(s.get("Headshots", s.get("headshots", 0)))
            result = str(s.get("Result", s.get("result", "0")))
            match_map = str(s.get("Map", s.get("map", "")))

            kills_list.append(k)
            deaths_list.append(d)
            hs_list.append(hs)
            if result == "1":
                wins += 1

            # Win rate sur la map courante
            map_name_clean = current_map.lower().replace("de_", "")
            item_map_clean = match_map.lower().replace("de_", "")
            if map_name_clean and map_name_clean in item_map_clean:
                map_total += 1
                if result == "1":
                    map_wins += 1

        except (ValueError, TypeError):
            continue

    n = len(kills_list)
    if n > 0:
        total_kills  = sum(kills_list)
        total_deaths = sum(deaths_list)
        total_hs     = sum(hs_list)

        metrics["kd"]        = total_kills / max(total_deaths, 1)
        metrics["winrate"]   = wins / n
        metrics["avg_kills"] = total_kills / n
        metrics["hs_pct"]   = total_hs / max(total_kills, 1)

    if map_total > 0:
        metrics["map_winrate"]  = map_wins / map_total
        metrics["map_matches"]  = map_total
    else:
        # Pas assez de données sur cette map → on utilise le winrate général
        metrics["map_winrate"]  = metrics["winrate"]
        metrics["map_matches"]  = 0

    return metrics


def compute_player_score(m: dict) -> float:
    """Score normalisé [0,1] d'un joueur selon toutes les métriques pondérées."""
    score = 0.0
    score += WEIGHTS["elo"]          * normalize(m["elo"],         "elo")
    score += WEIGHTS["kd"]           * normalize(m["kd"],          "kd")
    score += WEIGHTS["winrate"]      * normalize(m["winrate"],      "winrate")
    score += WEIGHTS["map_winrate"]  * normalize(m["map_winrate"],  "map_winrate")
    score += WEIGHTS["hs_pct"]       * normalize(m["hs_pct"],       "hs_pct")
    score += WEIGHTS["avg_kills"]    * normalize(m["avg_kills"],    "avg_kills")
    return clamp(score)


def compute_win_probability(team_score: float, enemy_score: float) -> float:
    """
    Transforme les scores en probabilité via une fonction logistique.
    Retourne la probabilité de victoire de l'équipe cible.
    """
    diff = team_score - enemy_score
    # Facteur k : amplification des différences (10 = modéré)
    k = 10.0
    prob = 1 / (1 + (2.718281828 ** (-k * diff)))
    # On borne entre 5% et 95% pour rester réaliste
    return clamp(prob, 0.05, 0.95)


def compute_avg_elo_gap(our_metrics: list, enemy_metrics: list) -> dict:
    our_elos = [float(m.get("elo", 0)) for m in our_metrics if isinstance(m, dict)]
    enemy_elos = [float(m.get("elo", 0)) for m in enemy_metrics if isinstance(m, dict)]
    if not our_elos or not enemy_elos:
        return {
            "avg_elo_our": None,
            "avg_elo_enemy": None,
            "avg_elo_gap": None,
            "avg_elo_gap_abs": None,
        }

    avg_our = sum(our_elos) / len(our_elos)
    avg_enemy = sum(enemy_elos) / len(enemy_elos)
    gap = avg_our - avg_enemy
    return {
        "avg_elo_our": round(avg_our, 2),
        "avg_elo_enemy": round(avg_enemy, 2),
        "avg_elo_gap": round(gap, 2),
        "avg_elo_gap_abs": round(abs(gap), 2),
    }


def compute_sample_quality(all_metrics: list) -> dict:
    samples = []
    for metric in all_metrics:
        if not isinstance(metric, dict):
            continue
        matches_analyzed = metric.get("matches_analyzed")
        if isinstance(matches_analyzed, (int, float)):
            samples.append(float(matches_analyzed))

    if not samples:
        return {
            "sample_avg_matches": None,
            "sample_quality_ratio": None,
            "sample_quality_pct": None,
            "sample_quality_label": "inconnue",
            "sample_target_matches": STATS_LIMIT,
            "sample_player_count": 0,
        }

    avg_matches = sum(samples) / len(samples)
    ratio = clamp(avg_matches / float(STATS_LIMIT), 0.0, 1.0)
    pct = ratio * 100.0

    if ratio >= 0.8:
        label = "élevée"
    elif ratio >= 0.5:
        label = "moyenne"
    else:
        label = "faible"

    return {
        "sample_avg_matches": round(avg_matches, 2),
        "sample_quality_ratio": round(ratio, 4),
        "sample_quality_pct": round(pct, 1),
        "sample_quality_label": label,
        "sample_target_matches": STATS_LIMIT,
        "sample_player_count": len(samples),
    }


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def print_team_table(team_name: str, players_metrics: list, is_our_team: bool):
    color = Fore.CYAN if is_our_team else Fore.MAGENTA
    tag   = " ◄ VOTRE ÉQUIPE" if is_our_team else ""

    print(f"\n{color}{'═'*80}")
    print(f"  {team_name.upper()}{tag}")
    print(f"{'═'*80}{Style.RESET_ALL}")

    header = f"  {'Joueur':<20} {'ELO':>6} {'Lvl':>4} {'K/D':>7} {'WR%':>7} {'WR Map':>9} {'HS%':>6} {'Score':>7}"
    print(f"{Fore.WHITE}{header}{Style.RESET_ALL}")
    print(f"  {'-'*74}")

    scores = []
    for m in players_metrics:
        sc = compute_player_score(m)
        scores.append(sc)

        map_wr_info = f"{m['map_winrate']*100:.0f}%"
        if m["map_matches"] == 0:
            map_wr_info += "*"

        elo_col  = f"{Fore.YELLOW}{m['elo']}{Style.RESET_ALL}"
        lvl_col  = f"{m['level']}"
        kd_col   = color_kd(m["kd"])
        wr_col   = color_pct(m["winrate"] * 100)
        mwr_col  = color_pct(m["map_winrate"] * 100)
        hs_col   = f"{m['hs_pct']*100:.0f}%"
        sc_col   = f"{Fore.CYAN}{sc:.3f}{Style.RESET_ALL}"

        # On retire les codes ANSI pour le formatage (calc longueur brute)
        nick = m["nickname"][:19]
        print(f"  {nick:<20} {m['elo']:>6} {lvl_col:>4}  {kd_col:>14}  {wr_col:>14}  {mwr_col:>16}  {hs_col:>6}  {sc_col:>12}")

    avg_score = sum(scores) / len(scores) if scores else 0
    print(f"  {'-'*74}")
    avg_color = Fore.CYAN if is_our_team else Fore.MAGENTA
    print(f"  {'Score moyen équipe':<20} {avg_color}{avg_score:.4f}{Style.RESET_ALL}")
    print(f"  (analysé sur ~{STATS_LIMIT} derniers matchs  |  * = map_wr basé sur WR global)")

    return avg_score


def print_result(our_team: str, win_prob: float, map_name: str):
    print(f"\n{'═'*80}")
    print(f"  🗺️  MAP : {Fore.WHITE}{map_name.upper()}{Style.RESET_ALL}")
    print(f"{'═'*80}")

    bar_len   = 50
    filled    = round(win_prob * bar_len)
    empty     = bar_len - filled
    bar_color = Fore.GREEN if win_prob >= 0.55 else (Fore.YELLOW if win_prob >= 0.45 else Fore.RED)
    bar       = f"{bar_color}{'█' * filled}{Fore.WHITE}{'░' * empty}{Style.RESET_ALL}"

    print(f"\n  Probabilité de victoire pour {Fore.CYAN}{our_team}{Style.RESET_ALL}")
    print(f"\n  [{bar}]  {bar_color}{win_prob*100:.1f}%{Style.RESET_ALL}\n")

    if win_prob >= 0.65:
        verdict = f"{Fore.GREEN}✅ FAVORABLE — Bonne chance !"
    elif win_prob >= 0.55:
        verdict = f"{Fore.GREEN}🟢 Légèrement en votre faveur"
    elif win_prob >= 0.45:
        verdict = f"{Fore.YELLOW}⚖️  Match équilibré — Tout se jouera en jeu"
    elif win_prob >= 0.35:
        verdict = f"{Fore.RED}🔴 Légèrement défavorable"
    else:
        verdict = f"{Fore.RED}❌ DÉFAVORABLE — Gros écart de niveau"

    print(f"  {verdict}{Style.RESET_ALL}\n")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    api_key = os.getenv("FACEIT_API_KEY")
    output_json = "--json" in sys.argv[1:]
    if not api_key:
        print(f"{Fore.RED}[ERREUR] Variable FACEIT_API_KEY manquante dans le fichier .env{Style.RESET_ALL}")
        emit_machine_payload(output_json, {"ok": False, "error": "FACEIT_API_KEY manquante dans .env"})
        sys.exit(1)

    # Récupère les inputs CLI (.env possible pour match_id via FACEIT_MATCH_ID)
    nickname, forced_match_id, output_json = parse_cli_inputs(sys.argv[1:])
    if not nickname:
        nickname = input(f"{Fore.CYAN}▶ Entrez le nickname FACEIT du joueur : {Style.RESET_ALL}").strip()

    if not nickname:
        print(f"{Fore.RED}[ERREUR] Nickname vide.{Style.RESET_ALL}")
        emit_machine_payload(output_json, {"ok": False, "error": "Nickname vide"})
        sys.exit(1)

    if forced_match_id and not is_plausible_match_id(forced_match_id):
        print(
            f"{Fore.YELLOW}⚠️  FACEIT_MATCH_ID/--match-id invalide ('{forced_match_id}'), "
            f"ignore et auto-détection utilisée.{Style.RESET_ALL}"
        )
        forced_match_id = ""

    ssl_option = build_ssl_option()
    if ssl_option is False:
        print(f"{Fore.YELLOW}⚠️  FACEIT_SSL_VERIFY=false: vérification TLS désactivée (debug local uniquement).{Style.RESET_ALL}")

    timeout = aiohttp.ClientTimeout(total=60, connect=15, sock_read=45)
    connector = aiohttp.TCPConnector(ssl=ssl_option)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
        client = FaceitClient(api_key, session)

        # ── 1) Résolution du joueur
        print(f"\n{Fore.WHITE}[1/4] Résolution du joueur {Fore.CYAN}{nickname}{Fore.WHITE}...{Style.RESET_ALL}")
        player_data = await client.get_player_by_nickname(nickname)
        if not player_data:
            print(f"{Fore.RED}[ERREUR] Joueur '{nickname}' introuvable sur FACEIT.{Style.RESET_ALL}")
            emit_machine_payload(
                output_json,
                {"ok": False, "nickname": nickname, "error": f"Joueur '{nickname}' introuvable sur FACEIT"},
            )
            sys.exit(1)

        player_id = player_data["player_id"]

        # Le endpoint /players?nickname peut être partiel selon les cas.
        # On rafraîchit donc le profil détaillé par player_id avant de continuer.
        player_details = None
        try:
            player_details = await client.get_player(player_id)
        except Exception as exc:
            print(f"  ⚠️  Impossible de rafraîchir le profil détaillé: {exc}")

        profile = player_details if isinstance(player_details, dict) and player_details else player_data
        game_data = profile.get("games", {}).get(GAME_ID)
        if not game_data:
            print(f"{Fore.RED}[ERREUR] Ce joueur n'a pas de compte CS2 lié sur FACEIT.{Style.RESET_ALL}")
            emit_machine_payload(
                output_json,
                {
                    "ok": False,
                    "nickname": nickname,
                    "player_id": player_id,
                    "error": "Compte CS2 non lié sur FACEIT",
                },
            )
            sys.exit(1)

        our_elo   = game_data.get("faceit_elo", 1000)
        our_level = game_data.get("skill_level", 5)
        print(f"  ✓ Joueur trouvé : {Fore.CYAN}{nickname}{Style.RESET_ALL} | ELO {Fore.YELLOW}{our_elo}{Style.RESET_ALL} | {elo_to_level_label(our_elo)}")

        # ── 2) Recherche du match en cours
        print(f"\n{Fore.WHITE}[2/4] Recherche du match en cours...{Style.RESET_ALL}")
        current_match = None
        search_status = ""
        history_debug = {}
        checked_match_statuses = []
        now_ts = int(time.time())
        from_ts = now_ts - ACTIVE_LOOKBACK_SECONDS
        to_ts = now_ts + ACTIVE_LOOKAHEAD_SECONDS
        history_game_ids = [GAME_ID] + [gid for gid in ["csgo"] if gid != GAME_ID]

        # a) Override manuel (utile quand l'API n'expose pas la game live à temps)
        if forced_match_id:
            current_match = {"match_id": forced_match_id, "status": "forced_match_id"}
            print(f"  ⚙️  Match forcé via argument/env : {Fore.YELLOW}{forced_match_id}{Style.RESET_ALL}")

        # b) Source la plus fiable quand disponible : id de match actif exposé sur le player
        active_match_id = extract_active_match_id(profile) or extract_active_match_id(player_data)
        if not current_match and active_match_id:
            current_match = {"match_id": active_match_id, "status": "active_match_id"}

        # c) Fallback: recherche publique joueur, parfois plus fraîche sur l'état "playing"
        if not current_match:
            try:
                search = await client.search_players(nickname, game=GAME_ID, limit=20, offset=0)
                search_items = search.get("items", []) if search else []
                search_exact = None

                for item in search_items:
                    if item.get("player_id") == player_id:
                        search_exact = item
                        break

                if not search_exact:
                    for item in search_items:
                        if str(item.get("nickname", "")).lower() == nickname.lower():
                            search_exact = item
                            break

                if search_exact:
                    status_value = str(search_exact.get("status") or search_exact.get("playing_status") or "")
                    search_status = f"{status_value} (items={len(search_items)})"
                    search_match_id = extract_active_match_id(search_exact) or find_match_id_deep(search_exact)
                    if search_match_id:
                        current_match = {"match_id": search_match_id, "status": "search_players"}
            except Exception as exc:
                print(f"  ⚠️  Fallback search/players indisponible: {exc}")

        # d) Stratégie "history récent -> /matches/{id}" (approche proposée)
        if not current_match:
            try:
                recent_history = await client.get_player_history(
                    player_id,
                    limit=5,
                    game=GAME_ID,
                    from_ts=from_ts,
                    offset=0,
                )
                recent_items = recent_history.get("items", []) if recent_history else []
            except Exception:
                recent_items = []

            history_debug["cs2_recent_match_check"] = recent_items

            for history_item in recent_items:
                recent_match_id = str(history_item.get("match_id") or "").strip()
                if not is_plausible_match_id(recent_match_id):
                    continue

                try:
                    match_details = await client.get_match(recent_match_id)
                except Exception:
                    match_details = None

                status = str((match_details or {}).get("status") or "").strip().lower()
                checked_match_statuses.append(f"{recent_match_id}:{status or 'unknown'}")

                if is_active_match_payload(match_details):
                    current_match = {"match_id": recent_match_id, "status": f"match_status:{status or 'unknown'}"}
                    break

        # e) Sinon, on inspecte l'history (fenêtre temporelle) sur plusieurs game_ids possibles
        if not current_match:
            for history_game_id in history_game_ids:
                try:
                    history_window = await client.get_player_history(
                        player_id,
                        limit=HISTORY_SCAN_LIMIT,
                        game=history_game_id,
                        from_ts=from_ts,
                        to_ts=to_ts,
                    )
                    window_items = history_window.get("items", []) if history_window else []
                except Exception:
                    window_items = []

                history_debug[f"{history_game_id}_window"] = window_items
                current_match = pick_current_match_from_history(window_items)
                if current_match:
                    break

        # f) Fallback: history brut (sans fenêtre) sur plusieurs game_ids possibles
        if not current_match:
            for history_game_id in history_game_ids:
                try:
                    history_raw = await client.get_player_history(
                        player_id,
                        limit=HISTORY_SCAN_LIMIT,
                        game=history_game_id,
                    )
                    raw_items = history_raw.get("items", []) if history_raw else []
                except Exception:
                    raw_items = []

                history_debug[f"{history_game_id}_raw"] = raw_items
                current_match = pick_current_match_from_history(raw_items)
                if current_match:
                    break

        # g) Fallback final: history tous jeux
        if not current_match:
            try:
                history_all = await client.get_player_history(
                    player_id,
                    limit=HISTORY_SCAN_LIMIT,
                    game=None,
                    from_ts=from_ts,
                    to_ts=to_ts,
                )
                items_all = history_all.get("items", []) if history_all else []
            except Exception:
                items_all = []
            history_debug["all_window"] = items_all
            current_match = pick_current_match_from_history(items_all)

        if not current_match:
            print(f"{Fore.RED}[ERREUR] Aucune partie en cours trouvée pour '{nickname}'.")
            print(f"  Vérifiez que le joueur est bien en partie sur CS2 FACEIT.{Style.RESET_ALL}")

            # Diagnostic rapide pour comprendre le faux négatif
            debug_items = []
            for debug_key in ["cs2_window", "cs2_raw", "csgo_window", "csgo_raw", "all_window"]:
                items = history_debug.get(debug_key, [])
                if items:
                    debug_items = items[:5]
                    print(f"  Debug source history: {debug_key}")
                    break

            if search_status:
                print(f"  Debug search status: {search_status}")
            if checked_match_statuses:
                print(f"  Debug statuses /matches: {', '.join(checked_match_statuses[:5])}")

            if debug_items:
                statuses = [str(m.get("status") or "None") for m in debug_items]
                print(f"  Debug statuts récents: {', '.join(statuses)}")
                ids = [str(m.get("match_id") or "None") for m in debug_items]
                print(f"  Debug match_id récents: {', '.join(ids)}")
            else:
                print("  Debug statuts récents: history vide")

            emit_machine_payload(
                output_json,
                {
                    "ok": False,
                    "nickname": nickname,
                    "player_id": player_id,
                    "forced_match_id": forced_match_id or None,
                    "search_status": search_status,
                    "checked_match_statuses": checked_match_statuses[:5],
                    "error": "Aucune partie en cours trouvée",
                },
            )
            sys.exit(1)

        match_id = current_match["match_id"]
        print(f"  ✓ Match trouvé : {Fore.YELLOW}{match_id}{Style.RESET_ALL}")

        # ── 3) Détails du match (équipes + map)
        print(f"\n{Fore.WHITE}[3/4] Récupération des détails du match...{Style.RESET_ALL}")
        match = await client.get_match(match_id)
        if not match:
            print(f"{Fore.RED}[ERREUR] Impossible de récupérer le match {match_id}.{Style.RESET_ALL}")
            emit_machine_payload(
                output_json,
                {
                    "ok": False,
                    "nickname": nickname,
                    "player_id": player_id,
                    "match_id": match_id,
                    "error": f"Impossible de récupérer le match {match_id}",
                },
            )
            sys.exit(1)

        # Map — contenue dans "voting" ou dans les résultats
        map_name = "inconnue"
        voting = match.get("voting")
        if voting and isinstance(voting, dict):
            map_vote = voting.get("map", {})
            picked   = map_vote.get("pick", [])
            if picked:
                map_name = picked[0]

        # Identifier les deux équipes et celle du joueur cible
        teams = match.get("teams", {})
        faction_keys = list(teams.keys())  # ["faction1", "faction2"]
        if len(faction_keys) < 2:
            print(f"{Fore.RED}[ERREUR] Structure de teams inattendue dans le match.{Style.RESET_ALL}")
            emit_machine_payload(
                output_json,
                {
                    "ok": False,
                    "nickname": nickname,
                    "player_id": player_id,
                    "match_id": match_id,
                    "error": "Structure de teams inattendue dans le match",
                },
            )
            sys.exit(1)

        our_faction_key = None
        for fk, fdata in teams.items():
            for p in fdata.get("roster", []):
                if p.get("player_id") == player_id:
                    our_faction_key = fk
                    break

        if not our_faction_key:
            # Fallback : cherche par nickname
            for fk, fdata in teams.items():
                for p in fdata.get("roster", []):
                    if p.get("nickname", "").lower() == nickname.lower():
                        our_faction_key = fk
                        break

        if not our_faction_key:
            our_faction_key = faction_keys[0]
            print(f"  ⚠️  Impossible de déterminer votre équipe, on prend {our_faction_key} par défaut.")

        enemy_faction_key = [k for k in faction_keys if k != our_faction_key][0]

        our_team_name    = teams[our_faction_key].get("name", our_faction_key)
        enemy_team_name  = teams[enemy_faction_key].get("name", enemy_faction_key)
        our_roster       = teams[our_faction_key].get("roster", [])
        enemy_roster     = teams[enemy_faction_key].get("roster", [])

        print(f"  ✓ Map       : {Fore.YELLOW}{map_name}{Style.RESET_ALL}")
        print(f"  ✓ Équipe    : {Fore.CYAN}{our_team_name}{Style.RESET_ALL} vs {Fore.MAGENTA}{enemy_team_name}{Style.RESET_ALL}")
        print(f"  ✓ Joueurs   : {len(our_roster)} vs {len(enemy_roster)}")

        # ── 4) Collecte des stats de tous les joueurs en parallèle
        print(f"\n{Fore.WHITE}[4/4] Analyse des stats de {len(our_roster) + len(enemy_roster)} joueurs (30 derniers matchs)...{Style.RESET_ALL}")

        async def fetch(player_info, faction_key):
            pid  = player_info.get("player_id")
            nick = player_info.get("nickname", "?")

            # Récupère l'ELO depuis le match (game_skill_level) + player details si possible
            elo   = player_info.get("faceit_elo", 1000)
            level = player_info.get("game_skill_level", 5)

            # Essaye de récupérer l'ELO réel depuis /players/{pid}
            try:
                p_detail = await client._get(f"/players/{pid}")
                if p_detail:
                    gdata = p_detail.get("games", {}).get(GAME_ID, {})
                    elo   = gdata.get("faceit_elo", elo)
                    level = gdata.get("skill_level", level)
            except Exception:
                pass

            enriched = {**player_info, "faceit_elo": elo, "game_skill_level": level}
            m = await get_player_metrics(client, enriched, map_name)
            m["faction"] = faction_key
            print(f"  ✓ {nick:<20} ELO:{elo:>5}  K/D:{m['kd']:.2f}  WR:{m['winrate']*100:.0f}%  MapWR:{m['map_winrate']*100:.0f}%")
            return m

        tasks = []
        for p in our_roster:
            tasks.append(fetch(p, our_faction_key))
        for p in enemy_roster:
            tasks.append(fetch(p, enemy_faction_key))

        all_metrics = await asyncio.gather(*tasks)

        our_metrics   = [m for m in all_metrics if m["faction"] == our_faction_key]
        enemy_metrics = [m for m in all_metrics if m["faction"] == enemy_faction_key]

        # ── Affichage des tableaux
        print("\n\n" + "="*80)
        print("  📊  ANALYSE COMPLÈTE DE LA ROOM")
        print("="*80)

        our_score   = print_team_table(our_team_name,   our_metrics,   is_our_team=True)
        enemy_score = print_team_table(enemy_team_name, enemy_metrics, is_our_team=False)

        # ── Probabilité finale
        win_prob = compute_win_probability(our_score, enemy_score)
        print_result(our_team_name, win_prob, map_name)

        elo_gap_info = compute_avg_elo_gap(our_metrics, enemy_metrics)
        sample_quality_info = compute_sample_quality(all_metrics)

        # ── Score brut pour debug
        print(f"  Score brut  — Votre équipe : {Fore.CYAN}{our_score:.4f}{Style.RESET_ALL}  |  Adversaires : {Fore.MAGENTA}{enemy_score:.4f}{Style.RESET_ALL}")
        print(f"  Méthode     — Pondération : ELO×{WEIGHTS['elo']} | K/D×{WEIGHTS['kd']} | WR×{WEIGHTS['winrate']} | MapWR×{WEIGHTS['map_winrate']} | HS×{WEIGHTS['hs_pct']} | Kills×{WEIGHTS['avg_kills']}")
        if elo_gap_info["avg_elo_gap"] is not None:
            print(
                f"  Écart ELO moyen (nous - eux) : "
                f"{Fore.YELLOW}{elo_gap_info['avg_elo_gap']:+.0f}{Style.RESET_ALL}"
            )
        if sample_quality_info["sample_avg_matches"] is not None:
            print(
                f"  Qualité d'échantillon        : "
                f"{Fore.YELLOW}{sample_quality_info['sample_quality_label']}{Style.RESET_ALL} "
                f"({sample_quality_info['sample_avg_matches']:.1f}/{STATS_LIMIT} matchs/joueur)"
            )
        print()

        emit_machine_payload(
            output_json,
            {
                "ok": True,
                "nickname": nickname,
                "player_id": player_id,
                "match_id": match_id,
                "map_name": map_name,
                "our_team_name": our_team_name,
                "enemy_team_name": enemy_team_name,
                "win_probability": round(win_prob, 6),
                "win_probability_pct": round(win_prob * 100, 2),
                "forced_match_id": bool(forced_match_id),
                "avg_elo_our": elo_gap_info["avg_elo_our"],
                "avg_elo_enemy": elo_gap_info["avg_elo_enemy"],
                "avg_elo_gap": elo_gap_info["avg_elo_gap"],
                "avg_elo_gap_abs": elo_gap_info["avg_elo_gap_abs"],
                "sample_avg_matches": sample_quality_info["sample_avg_matches"],
                "sample_quality_ratio": sample_quality_info["sample_quality_ratio"],
                "sample_quality_pct": sample_quality_info["sample_quality_pct"],
                "sample_quality_label": sample_quality_info["sample_quality_label"],
                "sample_target_matches": sample_quality_info["sample_target_matches"],
                "sample_player_count": sample_quality_info["sample_player_count"],
            },
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        if "--json" in sys.argv[1:]:
            emit_machine_payload(True, {"ok": False, "error": str(exc)})
        raise
