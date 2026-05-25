import { existsSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const REQUIRED_SECRETS = ['TURNSTILE_SITE_KEY', 'TURNSTILE_SECRET_KEY'];

function fail(message) {
  console.error(message);
  process.exit(1);
}

function loadDotEnv() {
  if (!existsSync('.env')) return;
  const lines = readFileSync('.env', 'utf8').split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const idx = trimmed.indexOf('=');
    if (idx < 0) continue;
    const key = trimmed.slice(0, idx).trim();
    const value = trimmed.slice(idx + 1).trim();
    if (key && !process.env[key]) process.env[key] = value;
  }
}

loadDotEnv();

const wranglerToml = readFileSync('wrangler.toml', 'utf8');
const hasAiBinding = /\[ai\][\s\S]*?binding\s*=\s*"AI"/m.test(wranglerToml);
if (!hasAiBinding) fail('Missing [ai] binding = "AI" in wrangler.toml');

for (const name of ['CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID']) {
  if (!process.env[name]) fail(`Missing required environment variable: ${name}`);
}

const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const result = spawnSync(npx, ['wrangler', 'secret', 'list', '--format=json'], {
  encoding: 'utf8',
  env: {
    ...process.env,
    XDG_CONFIG_HOME: process.env.XDG_CONFIG_HOME || join(tmpdir(), 'wrangler-config'),
  },
});

if (result.status !== 0) {
  console.error(result.stdout);
  console.error(result.stderr);
  fail('Unable to list Cloudflare Worker secrets.');
}

let parsed;
try {
  const jsonStart = result.stdout.search(/[\[{]/);
  if (jsonStart < 0) throw new Error('No JSON found in wrangler output');
  const jsonText = result.stdout.slice(jsonStart).trim();
  const jsonEnd = jsonText.startsWith('[') ? jsonText.lastIndexOf(']') : jsonText.lastIndexOf('}');
  parsed = JSON.parse(jsonText.slice(0, jsonEnd + 1));
} catch (error) {
  console.error(result.stdout);
  fail(`Unable to parse wrangler secret list output: ${error.message}`);
}

const names = new Set((Array.isArray(parsed) ? parsed : []).map((item) => item.name));
const missing = REQUIRED_SECRETS.filter((name) => !names.has(name));
if (missing.length) fail(`Missing Cloudflare Worker secrets: ${missing.join(', ')}`);

console.log('Cloudflare AI configuration check passed');
