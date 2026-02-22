#!/usr/bin/env python3
"""
resolve_live_match.py
Resolve active FACEIT match_id from a nickname.
Uses:
1) FACEIT Data API to resolve player_id
2) FACEIT web API groupByState to resolve active match
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import requests
from curl_cffi import requests as cfrequests
from dotenv import load_dotenv

try:
    import certifi
except Exception:
    certifi = None

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
load_dotenv(dotenv_path=ROOT_DIR / ".env", override=False)
load_dotenv(dotenv_path=SCRIPT_DIR / ".env", override=False)

FACEIT_DATA_BASE = "https://open.faceit.com/data/v4"
FACEIT_WEB_BASE = "https://www.faceit.com"
JSON_MARKER = "__MATCHID_JSON__"

STATE_PRIORITY = [
    "ONGOING",
    "READY",
    "CONFIGURING",
    "VOTING",
    "LIVE",
    "STARTED",
    "IN_PROGRESS",
]


def read_bool_env(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def resolve_requests_verify_option():
    verify_ssl = read_bool_env("FACEIT_SSL_VERIFY", default=True)
    if not verify_ssl:
        return False
    if certifi:
        return certifi.where()
    return True


def resolve_curl_verify_option() -> bool:
    return read_bool_env("FACEIT_SSL_VERIFY", default=True)


def emit(payload: Dict[str, Any]) -> None:
    print(JSON_MARKER + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def get_player_profile(api_key: str, nickname: str) -> Dict[str, Any]:
    response = requests.get(
        f"{FACEIT_DATA_BASE}/players",
        params={"nickname": nickname, "game": "cs2"},
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=12,
        verify=resolve_requests_verify_option(),
    )
    response.raise_for_status()
    data = response.json()
    player_id = str(data.get("player_id") or "").strip()
    if player_id:
        return data
    raise RuntimeError("player_id introuvable pour ce nickname.")


def extract_steam_id_64(player_profile: Dict[str, Any]) -> str:
    if not isinstance(player_profile, dict):
        return ""

    return str(
        player_profile.get("steam_id_64")
        or (player_profile.get("platforms", {}) or {}).get("steam")
        or player_profile.get("new_steam_id")
        or ""
    ).strip()


def get_match_groups(player_id: str) -> Dict[str, Any]:
    response = cfrequests.get(
        f"{FACEIT_WEB_BASE}/api/match/v1/matches/groupByState",
        params={"userId": player_id},
        impersonate="chrome",
        timeout=18,
        verify=resolve_curl_verify_option(),
    )
    response.raise_for_status()
    payload = response.json().get("payload", {})
    return payload if isinstance(payload, dict) else {}


def pick_match_from_groups(groups: Dict[str, Any]) -> Dict[str, str]:
    for state in STATE_PRIORITY:
        items = groups.get(state)
        if not isinstance(items, list) or not items:
            continue

        first = items[0] if isinstance(items[0], dict) else {}
        match_id = str(first.get("id") or first.get("match_id") or "").strip()
        if match_id:
            return {"match_id": match_id, "state": state}

    for state, items in groups.items():
        if not isinstance(items, list) or not items:
            continue
        first = items[0] if isinstance(items[0], dict) else {}
        match_id = str(first.get("id") or first.get("match_id") or "").strip()
        if match_id:
            return {"match_id": match_id, "state": str(state)}

    return {"match_id": "", "state": ""}


def main() -> int:
    nickname = str(sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not nickname:
        emit({"ok": False, "error": "Nickname requis."})
        return 1

    api_key = str(os.getenv("FACEIT_API_KEY") or "").strip()
    if not api_key:
        emit({"ok": False, "error": "FACEIT_API_KEY manquante (.env racine)."})
        return 1

    try:
        player_profile = get_player_profile(api_key=api_key, nickname=nickname)
        player_id = str(player_profile.get("player_id") or "").strip()
        steam_id_64 = extract_steam_id_64(player_profile)
        groups = get_match_groups(player_id=player_id)
        picked = pick_match_from_groups(groups)
        match_id = picked["match_id"]
        state = picked["state"]

        emit(
            {
                "ok": True,
                "nickname": nickname,
                "player_id": player_id,
                "steam_id_64": steam_id_64 or None,
                "match_id": match_id or None,
                "state": state or None,
                "room_url": f"https://www.faceit.com/en/cs2/room/{match_id}" if match_id else None,
            }
        )
        return 0

    except Exception as exc:
        emit({"ok": False, "nickname": nickname, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
