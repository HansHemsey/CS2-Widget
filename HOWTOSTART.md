# HOWTOSTART.md

Guide rapide pour lancer le widget CS2 (Faceit + Leetify + Win Probability) en local.

## 1) Prerequis

- `git`
- `node` (Node.js 18+ recommande)
- `python3` (3.9+ recommande)
- acces internet pour les APIs Faceit/Leetify

Verification rapide:

```bash
git --version
node --version
python3 --version
```

## 2) Recuperer le repo

```bash
git clone https://github.com/HansHemsey/CS2-Widget.git
cd CS2-Widget
```

## 3) Configurer Python (venv) + dependances

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r win_probability/requirements.txt
```

## 4) Configurer les variables d'environnement

Creer le fichier `.env` a la racine:

```bash
cp .env.example .env
```

Editer ensuite `.env` et renseigner au minimum:

- `FACEIT_API_KEY=...`
- `LEETIFY_API_KEY=...`

Option par defaut recommande:

- `HOST=127.0.0.1`
- `PORT=8787`
- `FACEIT_SSL_VERIFY=true`

## 5) Lancer les services

Tu as besoin de 2 terminaux.

### Terminal A - Proxy API

```bash
cd /chemin/vers/CS2-Widget
node proxy-server.mjs
```

Healthcheck:

```bash
curl http://127.0.0.1:8787/health
```

### Terminal B - Serveur statique du widget

```bash
cd /chemin/vers/CS2-Widget
python3 -m http.server 5500
```

## 6) Ouvrir le widget

Dans le navigateur:

```text
http://127.0.0.1:5500/index.html?nickname=TON_NICKNAME_FACEIT
```

Version Win Probability only (v2):

```text
http://127.0.0.1:5500/index-v2.html?nickname=TON_NICKNAME_FACEIT
```

Exemple:

```text
http://127.0.0.1:5500/index.html?nickname=ejzboob
```

## 6-bis) Ouvrir le widget depuis un autre PC (meme reseau local)

Exemple si le PC serveur a l'IP `192.168.1.70`:

1. Dans `.env` (sur le PC serveur):

```env
HOST=0.0.0.0
PORT=8787
```

2. Demarrer le proxy normalement:

```bash
node proxy-server.mjs
```

3. Demarrer le serveur statique en ecoute reseau:

```bash
python3 -m http.server 5500 --bind 0.0.0.0
```

4. Depuis l'autre PC, ouvrir:

```text
http://192.168.1.70:5500/index.html?nickname=TON_NICKNAME_FACEIT
```

Ou la vue v2 (Win Probability only):

```text
http://192.168.1.70:5500/index-v2.html?nickname=TON_NICKNAME_FACEIT
```

5. Test utile depuis l'autre PC:

```text
http://192.168.1.70:8787/health
```

Notes:
- `script.js` et `script-v2.js` utilisent automatiquement le meme host que la page widget pour le proxy.
- Si ca ne repond pas, verifier le pare-feu (ports 5500 et 8787).

## 7) Optionnel - UI Streamlit (generateur d'URL)

Dans un 3e terminal (avec venv active):

```bash
cd /chemin/vers/CS2-Widget
source .venv/bin/activate
streamlit run streamlit_app.py
```

Puis ouvrir l'URL affichee par Streamlit (souvent `http://localhost:8501`).

## 8) Arreter les serveurs

Dans chaque terminal de service: `Ctrl + C`.

## 9) Mise a jour du projet

```bash
cd /chemin/vers/CS2-Widget
git pull origin main
source .venv/bin/activate
pip install -r win_probability/requirements.txt
```

## 10) Depannage rapide

### `node: command not found`

Installe Node.js puis relance le terminal.

### Port deja utilise (`8787` ou `5500`)

Change le port:

- Proxy: modifie `PORT` dans `.env`
- Static server: `python3 -m http.server 5501`

Et adapte ensuite l'URL du widget.

### Erreur TLS/SSL FACEIT

Test temporaire:

```bash
FACEIT_SSL_VERIFY=false node proxy-server.mjs
```

Remets `FACEIT_SSL_VERIFY=true` ensuite.

### Le navigateur n'affiche pas les derniers changements

- Safari: `Cmd + Option + R` (hard refresh)
- Ou vide le cache navigateur.

## 11) Securite

- Ne jamais versionner `.env`
- Ne jamais mettre les API keys dans `script.js`/`index.html`
- Les cles doivent rester cote proxy uniquement
