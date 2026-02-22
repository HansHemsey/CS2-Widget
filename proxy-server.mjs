/* proxy-server.mjs - Proxy local simple pour relayer Faceit et Leetify (contourner CORS). */

import http from "node:http";
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, URL } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
loadEnvFile(path.join(__dirname, ".env"));

const PORT = Number(process.env.PORT || 8787);
const HOST = process.env.HOST || "127.0.0.1";
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "*";
const WINPROB_TIMEOUT_MS = Number(process.env.WINPROB_TIMEOUT_MS || 90000);
const MATCH_RESOLVE_TIMEOUT_MS = Number(process.env.MATCH_RESOLVE_TIMEOUT_MS || 25000);
const FACEIT_API_KEY = String(process.env.FACEIT_API_KEY || "").trim();
const LEETIFY_API_KEY = String(process.env.LEETIFY_API_KEY || "").trim();

const WINPROB_DIR = path.join(__dirname, "win_probability");
const WINPROB_SCRIPT = process.env.WINPROB_SCRIPT || "faceit_winprob.py";
const MATCH_RESOLVE_SCRIPT = process.env.MATCH_RESOLVE_SCRIPT || "resolve_live_match.py";
const DEFAULT_VENV_PYTHON = path.join(__dirname, ".venv", "bin", "python");
const PYTHON_BIN = process.env.PYTHON_BIN || (existsSync(DEFAULT_VENV_PYTHON) ? DEFAULT_VENV_PYTHON : "python3");
const WINPROB_MARKER = "__WINPROB_JSON__";
const MATCH_RESOLVE_MARKER = "__MATCHID_JSON__";

const SERVICE_BASE = {
  faceit: "https://open.faceit.com/data/v4/",
  leetify: "https://api-public.cs-prod.leetify.com/"
};

const server = http.createServer(async (req, res) => {
  setCorsHeaders(res);

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  if (!req.url) {
    respondJson(res, 400, { error: "URL invalide." });
    return;
  }

  const requestUrl = new URL(req.url, `http://${req.headers.host || "localhost"}`);

  if (requestUrl.pathname === "/health") {
    respondJson(res, 200, {
      ok: true,
      service: "proxy-server",
      port: PORT,
      python_bin: PYTHON_BIN,
      faceit_api_key_configured: Boolean(FACEIT_API_KEY),
      leetify_api_key_configured: Boolean(LEETIFY_API_KEY)
    });
    return;
  }

  if (requestUrl.pathname === "/resolve-live-match") {
    if (req.method !== "GET") {
      respondJson(res, 405, { ok: false, error: "Méthode non autorisée. Utilisez GET." });
      return;
    }

    const nickname = String(requestUrl.searchParams.get("nickname") || "").trim();
    if (!nickname) {
      respondJson(res, 400, { ok: false, error: "Paramètre 'nickname' requis." });
      return;
    }

    try {
      const payload = await resolveActiveMatchId({ nickname });
      respondJson(res, payload?.ok ? 200 : 404, payload);
    } catch (error) {
      respondJson(res, 502, {
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
    return;
  }

  if (requestUrl.pathname === "/win-probability") {
    if (req.method !== "GET") {
      respondJson(res, 405, { error: "Méthode non autorisée. Utilisez GET." });
      return;
    }

    const nickname = String(requestUrl.searchParams.get("nickname") || "").trim();
    const requestedMatchId = String(
      requestUrl.searchParams.get("match_id") || requestUrl.searchParams.get("matchId") || ""
    ).trim();

    if (!nickname) {
      respondJson(res, 400, { ok: false, error: "Paramètre 'nickname' requis." });
      return;
    }

    try {
      let resolvedMatch = null;
      let effectiveMatchId = requestedMatchId;

      if (!effectiveMatchId) {
        resolvedMatch = await resolveActiveMatchId({ nickname });
        const candidate = String(resolvedMatch?.match_id || "").trim();
        if (candidate) {
          effectiveMatchId = candidate;
        }
      }

      const payload = await runWinProbability({ nickname, matchId: effectiveMatchId });
      if (resolvedMatch) {
        payload.auto_match_resolve = {
          ok: Boolean(resolvedMatch.ok),
          match_id: resolvedMatch.match_id || null,
          state: resolvedMatch.state || null,
        };
      }
      respondJson(res, 200, payload);
    } catch (error) {
      const statusCode = Number(error?.statusCode) || 502;
      respondJson(res, statusCode, {
        ok: false,
        error: error instanceof Error ? error.message : String(error),
        detail: error?.detail || undefined
      });
    }
    return;
  }

  if (requestUrl.pathname !== "/proxy") {
    respondJson(res, 404, { error: "Route inconnue. Utilisez /proxy." });
    return;
  }

  if (req.method !== "GET") {
    respondJson(res, 405, { error: "Méthode non autorisée. Utilisez GET." });
    return;
  }

  const service = String(requestUrl.searchParams.get("service") || "").trim().toLowerCase();
  const path = String(requestUrl.searchParams.get("path") || "").trim();

  if (!SERVICE_BASE[service]) {
    respondJson(res, 400, { error: "Paramètre 'service' invalide. Valeurs: faceit, leetify." });
    return;
  }

  if (!path || !path.startsWith("/")) {
    respondJson(res, 400, { error: "Paramètre 'path' invalide. Exemple: /players" });
    return;
  }

  const upstreamUrl = new URL(path.slice(1), SERVICE_BASE[service]);

  for (const [key, value] of requestUrl.searchParams.entries()) {
    if (key === "service" || key === "path") {
      continue;
    }
    upstreamUrl.searchParams.set(key, value);
  }

  try {
    const outgoingHeaders = {
      Accept: "application/json",
      ...getServiceAuthHeaders(service)
    };

    const upstreamResponse = await fetch(upstreamUrl.toString(), {
      method: "GET",
      headers: outgoingHeaders
    });

    const contentType = upstreamResponse.headers.get("content-type") || "application/json; charset=utf-8";
    const payload = await upstreamResponse.text();

    res.writeHead(upstreamResponse.status, {
      "Content-Type": contentType,
      "Cache-Control": "no-store"
    });
    res.end(payload);
  } catch (error) {
    respondJson(res, 502, {
      error: "Erreur proxy vers service upstream.",
      detail: error instanceof Error ? error.message : String(error)
    });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Proxy actif sur http://${HOST}:${PORT}`);
  console.log(
    "Routes: GET /health, GET /resolve-live-match?nickname=..., GET /proxy?service=faceit|leetify&path=/..., GET /win-probability?nickname=..."
  );
});

function setCorsHeaders(res) {
  res.setHeader("Access-Control-Allow-Origin", ALLOW_ORIGIN);
  res.setHeader("Access-Control-Allow-Methods", "GET,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type,Accept");
}

function respondJson(res, statusCode, payload) {
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store"
  });
  res.end(JSON.stringify(payload));
}

function getServiceAuthHeaders(service) {
  if (service === "faceit") {
    if (!FACEIT_API_KEY) {
      throw new Error("FACEIT_API_KEY manquante dans .env (racine).");
    }
    return { Authorization: `Bearer ${FACEIT_API_KEY}` };
  }

  if (service === "leetify") {
    if (!LEETIFY_API_KEY) {
      throw new Error("LEETIFY_API_KEY manquante dans .env (racine).");
    }
    return {
      Authorization: `Bearer ${LEETIFY_API_KEY}`,
      _leetify_key: LEETIFY_API_KEY
    };
  }

  throw new Error(`Service inconnu: ${service}`);
}

function loadEnvFile(filePath) {
  if (!existsSync(filePath)) {
    return;
  }

  const raw = readFileSync(filePath, "utf-8");
  const lines = raw.split(/\r?\n/g);

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const eqIdx = trimmed.indexOf("=");
    if (eqIdx <= 0) {
      continue;
    }

    const key = trimmed.slice(0, eqIdx).trim();
    let value = trimmed.slice(eqIdx + 1).trim();

    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    if (!process.env[key]) {
      process.env[key] = value;
    }
  }
}

async function resolveActiveMatchId({ nickname }) {
  if (!existsSync(WINPROB_DIR)) {
    return { ok: false, error: `Dossier introuvable: ${WINPROB_DIR}` };
  }

  const resolverPath = path.join(WINPROB_DIR, MATCH_RESOLVE_SCRIPT);
  if (!existsSync(resolverPath)) {
    return { ok: false, error: `Script resolver introuvable: ${resolverPath}` };
  }

  const { code, stdout, stderr, timedOut } = await spawnProcess(
    PYTHON_BIN,
    [MATCH_RESOLVE_SCRIPT, nickname],
    { cwd: WINPROB_DIR, timeoutMs: MATCH_RESOLVE_TIMEOUT_MS }
  );

  if (timedOut) {
    return {
      ok: false,
      error: `Timeout resolve match (${MATCH_RESOLVE_TIMEOUT_MS} ms).`,
      detail: stderr || stdout,
    };
  }

  const payload = parseMarkedPayload(stdout, MATCH_RESOLVE_MARKER);
  if (payload) {
    return payload;
  }

  if (code !== 0) {
    return {
      ok: false,
      error: `Resolve match script failed (exit=${code}).`,
      detail: stderr || stdout,
    };
  }

  return { ok: false, error: "Resolve match payload introuvable." };
}

async function runWinProbability({ nickname, matchId }) {
  if (!existsSync(WINPROB_DIR)) {
    const err = new Error(`Dossier introuvable: ${WINPROB_DIR}`);
    err.statusCode = 500;
    throw err;
  }

  const args = [WINPROB_SCRIPT, nickname, "--json"];
  if (matchId) {
    args.push("--match-id", matchId);
  }

  const { code, stdout, stderr, timedOut } = await spawnProcess(PYTHON_BIN, args, {
    cwd: WINPROB_DIR,
    timeoutMs: WINPROB_TIMEOUT_MS
  });

  if (timedOut) {
    const err = new Error(`Timeout win probability (${WINPROB_TIMEOUT_MS} ms).`);
    err.statusCode = 504;
    err.detail = stderr || stdout;
    throw err;
  }

  const payload = parseMarkedPayload(stdout, WINPROB_MARKER);
  if (payload) {
    if (payload.ok === false) {
      const err = new Error(payload.error || "Calcul win probability en erreur.");
      err.statusCode = 400;
      err.detail = payload;
      throw err;
    }
    return payload;
  }

  if (code !== 0) {
    const err = new Error(`Le script win probability a échoué (exit=${code}).`);
    err.statusCode = 502;
    err.detail = stderr || stdout;
    throw err;
  }

  const err = new Error("Réponse JSON win probability introuvable dans stdout.");
  err.statusCode = 502;
  err.detail = stdout;
  throw err;
}

function parseMarkedPayload(stdout, marker) {
  const lines = String(stdout || "")
    .split(/\r?\n/g)
    .map((line) => line.trim())
    .filter(Boolean);

  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i];
    if (!line.startsWith(marker)) {
      continue;
    }

    const raw = line.slice(marker.length).trim();
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  return null;
}

function spawnProcess(cmd, args, { cwd, timeoutMs }) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      cwd,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"]
    });

    let stdout = "";
    let stderr = "";
    let settled = false;
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, Math.max(1000, Number(timeoutMs) || 90000));

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("error", (error) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      reject(error);
    });

    child.on("close", (code) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve({ code: Number(code || 0), stdout, stderr, timedOut });
    });
  });
}
