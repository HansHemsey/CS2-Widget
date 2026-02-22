# FACEIT Data API (v4) — Cheatsheet endpoints & keys (d’après la doc officielle)

Source principale : documentation Redocly “Data API” (FACEIT) et l’OpenAPI téléchargeable depuis cette page.  
Base URL : `https://open.faceit.com/data/v4`  
Auth : `Authorization: Bearer <API_KEY>` (clé créée dans FACEIT Developer Portal / App Studio).  

> ⚠️ Notes
> - La Data API expose **des données publiques**.  
> - Beaucoup d’endpoints paginés renvoient une structure du type `{ start, end, items[] }`.  
> - Les champs (response “keys”) peuvent être **très profonds** (objets imbriqués). Ici je liste surtout les **keys importantes / top-level** visibles dans les exemples, + les paramètres (path/query) pour coder vite.

---

## Conventions

### Pagination (fréquent)
| Key | Type | Description |
|---|---|---|
| `offset` | int | Position de départ (>=0) |
| `limit` | int | Nombre d’items à retourner (bornes variables selon l’endpoint) |

### “expanded” (fréquent)
| Key | Type | Description |
|---|---|---|
| `expanded` | `string[]` (CSV) | Demande au backend d’**étendre** certaines entités liées (ex: `organizer`, `game`) |

---

## Championships

| Method | Endpoint | Keys (path/query) | Description | Response keys (top-level / notables) |
|---|---|---|---|---|
| GET | `/championships` | query: `game` (req), `type` (enum all/upcoming/ongoing/past), `offset`, `limit` | Lister les championships d’un jeu | `start`, `end`, `items[]` (dans `items`: `championship_id`, `name`, `status`, `region`, `game_id`, `organizer_id`, `prizes`, `schedule`, …) |
| GET | `/championships/{championship_id}` | path: `championship_id` (req), query: `expanded` | Détails d’un championship | `championship_id`, `name`, `status`, `game_id`, `organizer_id`, `rules_id`, `slots`, `total_groups`, `total_rounds`, … |
| GET | `/championships/{championship_id}/matches` | path: `championship_id` (req), query: `type`, `offset`, `limit` | Matches d’un championship | `start`, `end`, `items[]` |
| GET | `/championships/{championship_id}/results` | path: `championship_id` (req), query: `offset`, `limit` | Résultats d’un championship | `start`, `end`, `items[]` |
| GET | `/championships/{championship_id}/subscriptions` | path: `championship_id` (req), query: `offset`, `limit` | Subscriptions d’un championship | `start`, `end`, `items[]` |

---

## Games

| Method | Endpoint | Keys (path/query) | Description | Response keys (top-level / notables) |
|---|---|---|---|---|
| GET | `/games` | query: `offset`, `limit` | Liste des jeux FACEIT | `start`, `end`, `items[]` (jeu: `game_id`, `short_label`, `long_label`, `assets`, `platforms`, `regions`, …) |
| GET | `/games/{game_id}` | path: `game_id` | Détails d’un jeu | `game_id`, `short_label`, `long_label`, `assets`, `platforms`, `regions`, `parent_game_id`, … |
| GET | `/games/{game_id}/parent` | path: `game_id` | Parent game (si jeu régional) | mêmes keys qu’un `Game` |
| GET | `/games/{game_id}/matchmakings` | path: `game_id`, query: `region`, `offset`, `limit` | Matchmakings d’un jeu | `start`, `end`, `items[]` |
| GET | `/games/{game_id}/queues` | path: `game_id`, query: `entity_type` (req), `entity_id` (req), `offset`, `limit` | Queues filtrées par entité | `start`, `end`, `items[]` (queue list) |
| GET | `/games/{game_id}/queues/{queue_id}` | path: `game_id`, `queue_id` | Détails d’une queue | `id`, `queueName`, `region`, `state`, `open`, + config (`joinType`, `checkIn`, …) |
| GET | `/games/{game_id}/queues/{queue_id}/bans` | path: `game_id`, `queue_id`, query: `offset`, `limit` | Bans d’une queue | `start`, `end`, `items[]` (ban: `banId`, `banStart`, `banEnd`, `nickname`, …) |
| GET | `/games/{game_id}/regions/{region_id}/queues` | path: `game_id`, `region_id`, query: `offset`, `limit` | Queues par région | `start`, `end`, `items[]` |

---

## Hubs

| Method | Endpoint | Keys (path/query) | Description | Response keys (top-level / notables) |
|---|---|---|---|---|
| GET | `/hubs/{hub_id}` | path: `hub_id` (req), query: `expanded` | Détails d’un hub | (hub) `hub_id`, `name`, `game_id`, `organizer_id`, `region`, `description`, … |
| GET | `/hubs/{hub_id}/matches` | path: `hub_id` (req), query: `type`, `offset`, `limit` | Matches d’un hub | `start`, `end`, `items[]` |
| GET | `/hubs/{hub_id}/members` | path: `hub_id` (req), query: `offset`, `limit` | Membres d’un hub | `start`, `end`, `items[]` |
| GET | `/hubs/{hub_id}/roles` | path: `hub_id` (req) | Rôles possibles | `items[]` (selon doc) |
| GET | `/hubs/{hub_id}/rules` | path: `hub_id` (req) | Règles du hub | `rules[]` / texte (selon doc) |
| GET | `/hubs/{hub_id}/stats` | path: `hub_id` (req) | Statistiques du hub | `*` (objet stats selon hub) |

---

## Leaderboards

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/leaderboards/championships/{championship_id}` | path: `championship_id`, query: `offset`, `limit` | Tous les leaderboards d’un championship |
| GET | `/leaderboards/championships/{championship_id}/groups/{group}` | path: `championship_id`, `group`, query: `offset`, `limit` | Ranking d’un groupe (championship) |
| GET | `/leaderboards/hubs/{hub_id}` | path: `hub_id`, query: `offset`, `limit` | Tous les leaderboards d’un hub |
| GET | `/leaderboards/hubs/{hub_id}/general` | path: `hub_id`, query: `offset`, `limit` | All-time ranking d’un hub |
| GET | `/leaderboards/hubs/{hub_id}/seasons/{season_id}` | path: `hub_id`, `season_id`, query: `offset`, `limit` | Ranking saisonnier d’un hub |
| GET | `/leaderboards/{leaderboard_id}` | path: `leaderboard_id`, query: `offset`, `limit` | Ranking via un leaderboard_id |
| GET | `/leaderboards/{leaderboard_id}/players/{player_id}` | path: `leaderboard_id`, `player_id` | Rang d’un joueur sur un leaderboard |

---

## Leagues

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/leagues/{league_id}` | path: `league_id` | Détails d’une league (matchmaking) |
| GET | `/leagues/{league_id}/seasons/{season_id}` | path: `league_id`, `season_id` | Détails d’une saison |
| GET | `/leagues/{league_id}/seasons/{season_id}/players/{player_id}` | path: `league_id`, `season_id`, `player_id` | Détails joueur (league+season) |

---

## Matches

| Method | Endpoint | Keys (path/query) | Description | Response keys (top-level / notables) |
|---|---|---|---|---|
| GET | `/matches/{match_id}` | path: `match_id` | Détails match | `match_id`, `game`, `region`, `competition_id`, `competition_type`, `teams`, `results`, `started_at`, `finished_at`, … |
| GET | `/matches/{match_id}/stats` | path: `match_id` | Stats match | structure stats (selon jeu/mode) |

---

## Matchmakings

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/matchmakings/{matchmaking_id}` | path: `matchmaking_id` | Détails d’un matchmaking |

---

## Organizers

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/organizers` | query: `name` (req) | Détails organizer depuis son nom |
| GET | `/organizers/{organizer_id}` | path: `organizer_id` | Détails organizer |
| GET | `/organizers/{organizer_id}/championships` | path: `organizer_id`, query: `game`, `type`, `offset`, `limit` | Championships d’un organizer |
| GET | `/organizers/{organizer_id}/games` | path: `organizer_id`, query: `offset`, `limit` | Jeux liés à l’organizer |
| GET | `/organizers/{organizer_id}/hubs` | path: `organizer_id`, query: `offset`, `limit` | Hubs de l’organizer |
| GET | `/organizers/{organizer_id}/tournaments` | path: `organizer_id`, query: `game`, `type`, `offset`, `limit` | Tournaments de l’organizer |

---

## Players

### 1) Récupérer un player_id

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/players` | query: `nickname`, `game`, `game_player_id` | Résout un joueur depuis nickname (optionnellement filtré par jeu / id plateforme) |

### 2) Détails / ressources joueur

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/players/{player_id}` | path: `player_id`, query: `expanded` (selon doc) | Détails joueur |
| GET | `/players/{player_id}/bans` | path: `player_id` | Bans d’un joueur |
| GET | `/players/{player_id}/history` | path: `player_id`, query: `from`, `to`, `game`, `offset`, `limit` (selon doc) | Historique de matches |
| GET | `/players/{player_id}/hubs` | path: `player_id`, query: `offset`, `limit` | Hubs du joueur |
| GET | `/players/{player_id}/teams` | path: `player_id`, query: `offset`, `limit` | Teams du joueur |
| GET | `/players/{player_id}/tournaments` | path: `player_id`, query: `game`, `type`, `offset`, `limit` (selon doc) | Tournaments du joueur |
| GET | `/players/{player_id}/stats/{game_id}` | path: `player_id`, `game_id` | Stats joueur (game scope) |
| GET | `/players/{player_id}/games/{game_id}/stats` | path: `player_id`, `game_id`, query: `offset`, `limit` (selon doc) | Stats joueur “pour un nombre de matches” |

---

## Rankings

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/rankings/games/{game_id}/regions/{region}/players` | path: `game_id`, `region`, query: `offset`, `limit` | Ranking global d’un jeu (par région) |
| GET | `/rankings/games/{game_id}/regions/{region}/players/{player_id}` | path: `game_id`, `region`, `player_id` | Position d’un joueur dans le ranking |

---

## Search

> Les endpoints `/search/*` renvoient généralement des listes paginées avec `start/end/items`.

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/search/championships` | query: `game`, `name`, `offset`, `limit`, … | Recherche championships |
| GET | `/search/clans` | query: `game`, `name`, `offset`, `limit`, … | Recherche clans |
| GET | `/search/hubs` | query: `game`, `name`, `offset`, `limit`, … | Recherche hubs |
| GET | `/search/organizers` | query: `name`, `offset`, `limit`, … | Recherche organizers |
| GET | `/search/players` | query: `nickname`, `game`, `country`, `offset`, `limit`, … | Recherche players |
| GET | `/search/teams` | query: `game`, `name`, `offset`, `limit`, … | Recherche teams |
| GET | `/search/tournaments` | query: `game`, `name`, `type`, `offset`, `limit`, … | Recherche tournaments |

---

## Teams

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/teams/{team_id}` | path: `team_id` | Détails team |
| GET | `/teams/{team_id}/stats/{game_id}` | path: `team_id`, `game_id` | Stats team (par jeu) |
| GET | `/teams/{team_id}/tournaments` | path: `team_id`, query: `offset`, `limit` | Tournaments d’une team |

---

## Tournaments

| Method | Endpoint | Keys (path/query) | Description |
|---|---|---|---|
| GET | `/tournaments` | (legacy) | “v1 (no longer used)” (selon doc) |
| GET | `/tournaments/{tournament_id}` | path: `tournament_id`, query: `expanded` | Détails tournament |
| GET | `/tournaments/{tournament_id}/brackets` | path: `tournament_id` | Brackets |
| GET | `/tournaments/{tournament_id}/matches` | path: `tournament_id`, query: `type`, `offset`, `limit` | Matches tournament |
| GET | `/tournaments/{tournament_id}/teams` | path: `tournament_id`, query: `offset`, `limit` | Teams tournament |

---

## Exemples d’enchaînements (logique d’usage)

### A) “Je veux les derniers matches d’un joueur + stats”
1. Résoudre `player_id` via `GET /players?nickname=...`  
2. Récupérer les matches : `GET /players/{player_id}/history?game=cs2&from=<ts>&to=<ts>&offset=0&limit=20`  
3. Pour un match : `GET /matches/{match_id}` puis `GET /matches/{match_id}/stats`

### B) “Je veux la fiche d’un tournoi + ses matches”
1. Rechercher : `GET /search/tournaments?game=cs2&name=...`  
2. Détails : `GET /tournaments/{tournament_id}`  
3. Matches : `GET /tournaments/{tournament_id}/matches?type=all&offset=0&limit=20`

---

## Sources (à garder en tête)
- Doc officielle Data API (Redocly) — liste des groupes + endpoints, paramètres et exemples.
- L’OpenAPI (swagger.json) est téléchargeable depuis la même page (utile si tu veux générer un client).
