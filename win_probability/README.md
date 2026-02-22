# 🎯 FACEIT CS2 — Win Probability Calculator

Calcule en temps réel la probabilité de victoire d'un joueur sur sa partie FACEIT CS2 en cours,
en analysant les statistiques des 10 joueurs de la room.

---

## ⚙️ Installation

```bash
# 1. Aller à la racine du projet
cd /chemin/vers/cs2_widget

# 2. Installer les dépendances
pip install -r win_probability/requirements.txt

# 3. Configurer les clés en local (jamais dans script.js)
cp .env.example .env
# Puis éditer .env:
# FACEIT_API_KEY=...
# LEETIFY_API_KEY=...
```

### Obtenir une clé API FACEIT
1. Aller sur https://developers.faceit.com
2. Créer une application ("Apps" → "Create App")
3. Dans votre app → **API Keys** → copier la **Server-side API Key**

---

## 🚀 Utilisation

```bash
# Avec le nickname en argument
python win_probability/faceit_winprob.py MonNickname

# Avec un match_id forcé (si la détection auto ne voit pas la game live)
python win_probability/faceit_winprob.py MonNickname --match-id 1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Sortie machine-readable (JSON marker)
python win_probability/faceit_winprob.py MonNickname --json

# Ou en mode interactif (demande le nickname au lancement)
python win_probability/faceit_winprob.py
```

Option `.env` équivalente (override permanent):
```bash
FACEIT_MATCH_ID=1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

## API locale (pour le widget)

Le `proxy-server.mjs` expose maintenant:

```bash
GET /resolve-live-match?nickname=<FACEIT_NICKNAME>
GET /win-probability?nickname=<FACEIT_NICKNAME>[&match_id=<MATCH_ID>]
```

Exemple:

```bash
curl "http://127.0.0.1:8787/resolve-live-match?nickname=Kerler"
```

Puis calcul complet:

```bash
curl "http://127.0.0.1:8787/win-probability?nickname=Kerler&match_id=1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Exemple (auto-détection du match_id, recommandé):

```bash
curl "http://127.0.0.1:8787/win-probability?nickname=Kerler"
```

Réponse JSON (succès):

```json
{
  "ok": true,
  "nickname": "Kerler",
  "player_id": "...",
  "match_id": "1-...",
  "map_name": "de_mirage",
  "our_team_name": "faction1",
  "enemy_team_name": "faction2",
  "win_probability": 0.624,
  "win_probability_pct": 62.4,
  "forced_match_id": true
}
```

> ⚠️ **Le joueur doit avoir une partie CS2 en cours sur FACEIT au moment de l'analyse.**
>
> En mode auto, le proxy lance `resolve_live_match.py` pour résoudre le `match_id` avant d'appeler `faceit_winprob.py`.

Si tu as une erreur TLS Python du type `SSLCertVerificationError`, tu peux temporairement tester en désactivant la vérification:

```bash
FACEIT_SSL_VERIFY=false node proxy-server.mjs
```

Puis remettre `FACEIT_SSL_VERIFY=true` en usage normal.

---

## 📊 Métriques analysées

| Métrique | Poids | Description |
|---|---|---|
| ELO FACEIT | 30% | Niveau global du joueur |
| K/D ratio | 20% | Ratio kills/deaths sur 30 derniers matchs |
| Win Rate global | 20% | % de victoires sur 30 derniers matchs |
| Win Rate sur la map | 20% | % de victoires sur la map jouée |
| Headshot % | 5% | Précision (headshots / kills) |
| Avg Kills/match | 5% | Fragging power moyen |

### Algorithme

1. Chaque métrique est **normalisée** entre 0 et 1 selon des bornes réalistes CS2 FACEIT
2. Un **score pondéré** est calculé pour chaque joueur
3. Le score moyen de chaque équipe est comparé via une **fonction logistique** pour produire une probabilité
4. La probabilité est bornée entre **5% et 95%** (on ne peut jamais garantir 0% ou 100%)

---

## 🖥️ Exemple de sortie

```
[1/4] Résolution du joueur s1mple...
  ✓ Joueur trouvé : s1mple | ELO 3247 | Level 10

[2/4] Recherche du match en cours...
  ✓ Match trouvé : 1-abc123...

[3/4] Récupération des détails du match...
  ✓ Map       : de_mirage
  ✓ Équipe    : team_s1mple vs faction2

[4/4] Analyse des stats de 10 joueurs...
  ✓ s1mple              ELO: 3247  K/D:1.85  WR:72%  MapWR:68%
  ...

══════════════════════════════════════════
  TEAM_S1MPLE ◄ VOTRE ÉQUIPE
══════════════════════════════════════════
  Joueur               ELO    Lvl    K/D     WR%   WR Map    HS%   Score
  ──────────────────────────────────────────────────────────────────────
  s1mple               3247    10   1.85   72.0%    68.0%   45%   0.851
  ...

  Probabilité de victoire pour team_s1mple

  [█████████████████████████████████░░░░░░░░░░░░░░░░]  62.4%

  ✅ FAVORABLE — Bonne chance !
```

---

## ⚠️ Limitations

- Requiert que le joueur ait une **partie active** (status: `ongoing`)
- Le **win rate par map** se base sur l'historique des 30 derniers matchs ; si le joueur n'a pas joué cette map récemment, le win rate global est utilisé à la place (affiché avec `*`)
- Les résultats sont indicatifs — le CS reste un jeu d'équipe et l'algorithme ne tient pas compte de la communication, des strats, ou du tilt 😄
