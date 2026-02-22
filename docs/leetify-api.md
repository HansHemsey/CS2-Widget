# Leetify Public CS API — Référence complète (endpoints + schémas “Expand all”)

Base serveur (Prod) : `https://api-public.cs-prod.leetify.com`

---

## Authentification & API Key

### Headers acceptés
La clé API doit être passée **soit** :
- `Authorization: Bearer <key>`
- `_leetify_key: <key>`

---

## Group: api-key

### GET `/api-key/validate` — Validate API key

| Élément | Détail |
|---|---|
| Méthode | `GET` |
| Endpoint | `/api-key/validate` |
| Auth | `Authorization` ou `_leetify_key` |
| Codes | `200` si valide ; `401` si invalide/manquante ; `500` si erreur serveur |

---

## Group: player

### GET `/v3/profile` — Get player profile

| Paramètre | Type | Requis | Description |
|---|---:|:---:|---|
| `steam64_id` | string | non* | Steam64 ID du joueur |
| `id` | string | non* | Leetify User ID |

\*Au moins **un** identifiant doit être fourni (`steam64_id` ou `id`).

**Response 200** : `ProfileResponse`

---

### GET `/v3/profile/matches` — Get player match history

| Paramètre | Type | Requis | Description |
|---|---:|:---:|---|
| `steam64_id` | string | non* | Steam64 ID du joueur |
| `id` | string | non* | Leetify User ID |

\*Même logique : fournir au moins un identifiant.

---

## Group: matches

### GET `/v2/matches/{gameId}` — Get match details by game ID

| Paramètre | Type | Requis | Description |
|---|---:|:---:|---|
| `gameId` | string | oui | Game ID |

**Response 200** : `MatchDetailsResponse`

---

### GET `/v2/matches/{dataSource}/{dataSourceId}` — Get match details by data source and data source ID

| Paramètre | Type | Requis | Description |
|---|---:|:---:|---|
| `dataSource` | string | oui | Data source (ex: `faceit`, `matchmaking`) |
| `dataSourceId` | string | oui | ID de match spécifique à la source |

**Response 200** : `MatchDetailsResponse`

---

# Schémas (Schemas) — Expanded

## Schema: `ProfileResponse`

| Key | Type | Notes |
|---|---|---|
| `privacy_mode` | string | ex: `public` |
| `winrate` | number | |
| `total_matches` | number | |
| `first_match_date` | string (date-time) | |
| `name` | string | |
| `bans` | `PlatformBanInfo[]` | |
| `steam64_id` | string | |
| `id` | string | UUID Leetify |
| `ranks` | `Ranks` | |
| `rating` | `Rating` | |
| `stats` | `Stats` | |
| `recent_matches` | `RecentMatch[]` | |
| `recent_teammates` | `RecentTeammate[]` | |

---

## Schema: `Ranks`

| Key | Type | Notes |
|---|---|---|
| `leetify` | number | |
| `premier` | number | |
| `faceit` | number | |
| `faceit_elo` | number\|null | |
| `wingman` | number | |
| `renown` | number | |
| `competitive` | `CompetitiveRank[]` | |

---

## Schema: `CompetitiveRank`

| Key | Type |
|---|---|
| `map_name` | string |
| `rank` | number |

---

## Schema: `Rating`

| Key | Type |
|---|---|
| `aim` | number |
| `positioning` | number |
| `utility` | number |
| `clutch` | number |
| `opening` | number |
| `ct_leetify` | number |
| `t_leetify` | number |

---

## Schema: `Stats`

| Key | Type |
|---|---:|
| `accuracy_enemy_spotted` | number |
| `accuracy_head` | number |
| `counter_strafing_good_shots_ratio` | number |
| `ct_opening_aggression_success_rate` | number |
| `ct_opening_duel_success_percentage` | number |
| `flashbang_hit_foe_avg_duration` | number |
| `flashbang_hit_foe_per_flashbang` | number |
| `flashbang_hit_friend_per_flashbang` | number |
| `flashbang_leading_to_kill` | number |
| `flashbang_thrown` | number |
| `he_foes_damage_avg` | number |
| `he_friends_damage_avg` | number |
| `preaim` | number |
| `reaction_time_ms` | number |
| `spray_accuracy` | number |
| `t_opening_aggression_success_rate` | number |
| `t_opening_duel_success_percentage` | number |
| `traded_deaths_success_percentage` | number |
| `trade_kill_opportunities_per_round` | number |
| `trade_kills_success_percentage` | number |
| `utility_on_death_avg` | number |

---

## Schema: `RecentMatch`

| Key | Type | Notes |
|---|---|---|
| `id` | string | |
| `finished_at` | string (date-time) | |
| `data_source` | string | |
| `outcome` | string | |
| `rank` | number | |
| `rank_type` | string | |
| `map_name` | string | |
| `leetify_rating` | number | |
| `score` | number[2] | ex: `[13,6]` |
| `preaim` | number | |
| `reaction_time_ms` | number | |
| `accuracy_enemy_spotted` | number | |
| `accuracy_head` | number | |
| `spray_accuracy` | number | |

---

## Schema: `RecentTeammate`

| Key | Type |
|---|---|
| `steam64_id` | string |
| `recent_matches_count` | number |

---

## Schema: `PlatformBanInfo`

| Key | Type | Notes |
|---|---|---|
| `platform` | string | requis |
| `platform_nickname` | string | requis |
| `banned_since` | string (date-time) | requis |

---

## Schema: `MatchDetailsResponse`

| Key | Type |
|---|---|
| `id` | string |
| `finished_at` | string (date-time) |
| `data_source` | string |
| `data_source_match_id` | string |
| `map_name` | string |
| `has_banned_player` | boolean |
| `team_scores` | `TeamScore[]` |
| `stats` | `PlayerStats[]` |

---

## Schema: `TeamScore`

| Key | Type |
|---|---:|
| `team_number` | number |
| `score` | number |

---

## Schema: `PlayerStats`

### Identité & tir

| Key | Type |
|---|---|
| `steam64_id` | string |
| `name` | string |
| `mvps` | number |
| `preaim` | number |
| `reaction_time` | number |
| `accuracy` | number |
| `accuracy_enemy_spotted` | number |
| `accuracy_head` | number |
| `shots_fired_enemy_spotted` | number |
| `shots_fired` | number |
| `shots_hit_enemy_spotted` | number |
| `shots_hit_friend` | number |
| `shots_hit_friend_head` | number |
| `shots_hit_foe` | number |
| `shots_hit_foe_head` | number |

### Utility / grenades / counter-strafing

| Key | Type |
|---|---:|
| `utility_on_death_avg` | number |
| `he_foes_damage_avg` | number |
| `he_friends_damage_avg` | number |
| `he_thrown` | number |
| `molotov_thrown` | number |
| `smoke_thrown` | number |
| `counter_strafing_shots_all` | number |
| `counter_strafing_shots_bad` | number |
| `counter_strafing_shots_good` | number |
| `counter_strafing_shots_good_ratio` | number |
| `flashbang_hit_foe` | number |
| `flashbang_leading_to_kill` | number |
| `flashbang_hit_foe_avg_duration` | number |
| `flashbang_hit_friend` | number |
| `flashbang_thrown` | number |
| `flash_assist` | number |

### Score / combat

| Key | Type |
|---|---:|
| `score` | number |
| `initial_team_number` | number |
| `spray_accuracy` | number |
| `total_kills` | number |
| `total_deaths` | number |
| `kd_ratio` | number |
| `rounds_survived` | number |
| `rounds_survived_percentage` | number |
| `dpr` | number |
| `total_assists` | number |
| `total_damage` | number |
| `leetify_rating` | number |
| `ct_leetify_rating` | number |
| `t_leetify_rating` | number |
| `multi1k` | number |
| `multi2k` | number |
| `multi3k` | number |
| `multi4k` | number |
| `multi5k` | number |
| `rounds_count` | number |
| `rounds_won` | number |
| `rounds_lost` | number |
| `total_hs_kills` | number |

### Trade stats

| Key | Type |
|---|---:|
| `trade_kill_opportunities` | number |
| `trade_kill_attempts` | number |
| `trade_kills_succeed` | number |
| `trade_kill_attempts_percentage` | number |
| `trade_kills_success_percentage` | number |
| `trade_kill_opportunities_per_round` | number |
| `traded_death_opportunities` | number |
| `traded_death_attempts` | number |
| `traded_deaths_succeed` | number |
| `traded_death_attempts_percentage` | number |
| `traded_deaths_success_percentage` | number |
| `traded_deaths_opportunities_per_round` | number |

---

# Workflows

## Profil → Historique matches → Détails match
1. `GET /v3/profile?steam64_id=<STEAM64>`
2. `GET /v3/profile/matches?steam64_id=<STEAM64>`
3. `GET /v2/matches/<GAME_ID>` ou `GET /v2/matches/<dataSource>/<dataSourceId>`
