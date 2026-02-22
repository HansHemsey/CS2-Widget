# Security Guidelines

This project is intended to be publishable as a public repository.
To avoid leaking secrets:

## Never commit secrets
- Keep API keys in local `.env` only.
- Do not store keys in `script.js`, HTML, docs, or test scripts.
- Ensure `.env` is ignored by `.gitignore`.

## Required runtime model
- Browser/UI must call local proxy only.
- Proxy injects upstream auth server-side from `.env`.
- Frontend must not send API keys.

## If a key has been exposed
1. Revoke/regenerate the key immediately in provider dashboard.
2. Update local `.env`.
3. If key was committed in git history, rewrite history before public push.

## Pre-push checklist
- `rg -n --hidden -S "API_KEY|FACEIT_API_KEY|LEETIFY_API_KEY|Bearer " -g '!.venv/**' .`
- `rg -n --hidden -S "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" -g '!.venv/**' .`
- Confirm no real keys are found in tracked files.
- Confirm `.env` and local caches are ignored.

