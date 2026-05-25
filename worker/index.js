const SERVICE_NAME = 'duolingo-avator-creator';
const SERVICE_VERSION = '0.3.0';
const DEFAULT_TEXT_MODEL = '@cf/meta/llama-3.1-8b-instruct-fast';
const MAX_PROMPT_LENGTH = 800;
const MAX_CATALOG_OPTIONS = 420;
const AI_SESSION_TTL_SECONDS = 30 * 60;

const ALLOWED_ORIGINS = new Set([
  'https://wishflow.github.io',
  'https://duolingo-avator-creator.pages.dev',
]);
const LOCAL_DEV_ORIGIN_PATTERN = new RegExp('^http://(localhost|127\\.0\\.0\\.1)(:\\d+)?$');

function isAllowedOrigin(origin) {
  if (!origin) return false;
  if (ALLOWED_ORIGINS.has(origin)) return true;
  return LOCAL_DEV_ORIGIN_PATTERN.test(origin);
}

function corsHeaders(request) {
  const origin = request.headers.get('Origin');
  const headers = new Headers({
    'Vary': 'Origin',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Max-Age': '86400',
  });
  if (isAllowedOrigin(origin)) {
    headers.set('Access-Control-Allow-Origin', origin);
  }
  return headers;
}

function jsonResponse(request, body, status = 200) {
  const headers = corsHeaders(request);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  return new Response(JSON.stringify(body), { status, headers });
}

function sseHeaders(request) {
  const headers = corsHeaders(request);
  headers.set('Content-Type', 'text/event-stream; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  headers.set('Connection', 'keep-alive');
  return headers;
}

function methodNotAllowed(request, allowedMethods) {
  const headers = corsHeaders(request);
  headers.set('Allow', allowedMethods.join(', '));
  headers.set('Content-Type', 'application/json; charset=utf-8');
  return new Response(JSON.stringify({
    ok: false,
    error: 'method_not_allowed',
    allowedMethods,
  }), { status: 405, headers });
}

function getServiceName(env) {
  return env?.SERVICE_NAME || SERVICE_NAME;
}

function getServiceVersion(env) {
  return env?.SERVICE_VERSION || SERVICE_VERSION;
}

function getTextModel(env) {
  return env?.AI_TEXT_MODEL || DEFAULT_TEXT_MODEL;
}

function getTurnstileSiteKey(env) {
  return env?.TURNSTILE_SITE_KEY || '';
}

function getMaxPromptLength(env) {
  const configured = Number(env?.MAX_PROMPT_LENGTH || MAX_PROMPT_LENGTH);
  return Number.isFinite(configured) ? Math.min(Math.max(configured, 80), 2000) : MAX_PROMPT_LENGTH;
}

function getAiSessionTtlSeconds(env) {
  const configured = Number(env?.AI_SESSION_TTL_SECONDS || AI_SESSION_TTL_SECONDS);
  return Number.isFinite(configured) ? Math.min(Math.max(configured, 60), 24 * 60 * 60) : AI_SESSION_TTL_SECONDS;
}

function normalizePrompt(value, maxLength) {
  if (typeof value !== 'string') return '';
  return value.replace(/\s+/g, ' ').trim().slice(0, maxLength + 1);
}

function normalizeContextMode(value) {
  if (value === 'current' || value === 'default') return value;
  return 'default';
}

function cleanStateSnapshot(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const clean = {};
  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw === 'number' && Number.isFinite(raw)) clean[key] = raw;
    if (typeof raw === 'boolean') clean[key] = raw;
  }
  return clean;
}

function normalizeCatalog(catalog) {
  const states = catalog?.states;
  if (!states || typeof states !== 'object' || Array.isArray(states)) return null;

  const normalized = {};
  let optionCount = 0;
  for (const [stateName, options] of Object.entries(states)) {
    if (!Array.isArray(options) || !stateName || optionCount >= MAX_CATALOG_OPTIONS) continue;
    const cleanOptions = [];
    const seen = new Set();
    for (const option of options) {
      if (!option || typeof option !== 'object' || optionCount >= MAX_CATALOG_OPTIONS) break;
      const value = option.value;
      if (typeof value !== 'number' && typeof value !== 'boolean') continue;
      const key = `${typeof value}:${value}`;
      if (seen.has(key)) continue;
      seen.add(key);
      cleanOptions.push({
        value,
        tab: String(option.tab || '').slice(0, 40),
        section: String(option.section || '').slice(0, 60),
        kind: String(option.kind || '').slice(0, 20),
        color: typeof option.color === 'string' ? option.color.slice(0, 20) : undefined,
        index: Number.isFinite(Number(option.index)) ? Number(option.index) : undefined,
      });
      optionCount++;
    }
    if (cleanOptions.length) normalized[stateName] = cleanOptions;
  }

  return Object.keys(normalized).length ? { states: normalized } : null;
}

function buildAllowedValues(catalog) {
  const allowed = new Map();
  for (const [stateName, options] of Object.entries(catalog.states)) {
    const values = new Set();
    for (const option of options) values.add(`${typeof option.value}:${option.value}`);
    allowed.set(stateName, values);
  }
  return allowed;
}

function isAllowedStateValue(allowed, stateName, value) {
  return allowed.get(stateName)?.has(`${typeof value}:${value}`) || false;
}

function sanitizeModelResult(rawResult, catalog) {
  const allowed = buildAllowedValues(catalog);
  const warnings = [];
  const avatarState = {};

  const result = rawResult && typeof rawResult === 'object' ? rawResult : {};
  const changes = Array.isArray(result.avatarState)
    ? result.avatarState
    : Object.entries(result.avatarState || {}).map(([state, value]) => ({ state, value }));

  for (const change of changes) {
    if (!change || typeof change !== 'object') continue;
    const stateName = String(change.state || '');
    let value = change.value;
    if (typeof value !== 'number' && typeof value !== 'boolean') {
      if (typeof change.valueNumber === 'number' && Number.isFinite(change.valueNumber)) value = change.valueNumber;
      if (typeof change.valueBoolean === 'boolean') value = change.valueBoolean;
    }
    if (!stateName || (typeof value !== 'number' && typeof value !== 'boolean')) continue;
    if (!isAllowedStateValue(allowed, stateName, value)) {
      warnings.push(`Skipped unsupported value for ${stateName}.`);
      continue;
    }
    avatarState[stateName] = value;
  }

  const steps = Array.isArray(result.steps)
    ? result.steps.map((step) => String(step).trim()).filter(Boolean).slice(0, 12)
    : [];
  const summary = String(result.summary || '').trim().slice(0, 280);
  const confidence = Math.max(0, Math.min(1, Number(result.confidence ?? 0.6)));
  const extraWarnings = Array.isArray(result.warnings)
    ? result.warnings.map((warning) => String(warning).trim()).filter(Boolean).slice(0, 6)
    : [];

  return {
    avatarState,
    steps,
    summary,
    confidence,
    warnings: [...warnings, ...extraWarnings].slice(0, 10),
  };
}

function parseJsonModeResponse(response) {
  const value = response?.response ?? response;
  if (typeof value === 'string') return JSON.parse(value);
  return value;
}

function avatarJsonSchema(catalog) {
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      summary: { type: 'string' },
      confidence: { type: 'number', minimum: 0, maximum: 1 },
      avatarState: {
        type: 'array',
        items: {
          type: 'object',
          additionalProperties: false,
          properties: {
            state: { type: 'string', enum: Object.keys(catalog.states) },
            valueNumber: { type: 'number' },
            valueBoolean: { type: 'boolean' },
            reason: { type: 'string' },
          },
          required: ['state'],
        },
      },
      steps: {
        type: 'array',
        items: { type: 'string' },
      },
      warnings: {
        type: 'array',
        items: { type: 'string' },
      },
    },
    required: ['summary', 'confidence', 'avatarState', 'steps', 'warnings'],
  };
}

function buildExplanationMessages({ prompt, contextMode, result }) {
  const applied = JSON.stringify({
    summary: result.summary,
    avatarState: result.avatarState,
    steps: result.steps,
    warnings: result.warnings,
  });
  return [
    {
      role: 'system',
      content: [
        'You explain avatar edits that were already applied in a browser-based avatar editor.',
        'Write concise user-facing notes. Do not mention APIs, model names, JSON, schema, internal state IDs, or implementation details.',
        'Only describe the applied changes and the manual guide. Do not invent unavailable details.',
        'Use the same language as the user prompt when possible.',
      ].join(' '),
    },
    {
      role: 'user',
      content: [
        `User request: ${prompt}`,
        `Context mode: ${contextMode}`,
        `Applied result: ${applied}`,
        'Explain the applied editable avatar in 3-6 short sentences.',
      ].join('\n'),
    },
  ];
}

function buildStructuredMessages({ prompt, contextMode, baselineState, catalog }) {
  return [
    {
      role: 'system',
      content: [
        'You convert a user avatar request into supported avatar editor options.',
        'Return only choices that are available in the supplied catalog.',
        'Prefer a small coherent set of changes over changing every state.',
        'If the catalog lacks semantic labels, choose conservative values based on tab, section, color, and option index.',
        'Every avatarState item must set exactly one of valueNumber or valueBoolean.',
        'Write detailed manual reproduction steps for a user following the editor categories.',
      ].join(' '),
    },
    {
      role: 'user',
      content: JSON.stringify({
        prompt,
        contextMode,
        baselineState,
        catalog,
        outputRules: {
          avatarState: 'Array of supported { state, valueNumber or valueBoolean, reason } changes only.',
          steps: 'Detailed manual guide, 6-12 steps, same language as user prompt when possible.',
          warnings: 'Mention uncertain choices caused by missing semantic labels.',
        },
      }),
    },
  ];
}

function encodeSse(event, data) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function streamFromString(value) {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(value));
      controller.close();
    },
  });
}

function parseAiStreamPayload(payload) {
  if (!payload || payload === '[DONE]') return '';
  try {
    const parsed = JSON.parse(payload);
    return parsed.response
      || parsed.text
      || parsed.delta
      || parsed.choices?.[0]?.delta?.content
      || parsed.choices?.[0]?.text
      || '';
  } catch (_) {
    return payload;
  }
}

async function pipeAiPlanStream(aiStream, enqueue) {
  const stream = typeof aiStream === 'string' ? streamFromString(aiStream) : aiStream;
  if (!stream?.getReader) return;
  const decoder = new TextDecoder();
  const reader = stream.getReader();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split('\n\n');
    buffer = frames.pop() || '';
    for (const frame of frames) {
      const dataLines = frame.split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim());
      if (!dataLines.length) continue;
      const text = parseAiStreamPayload(dataLines.join('\n'));
      if (text) enqueue('plan_delta', { text });
    }
  }

  const trailing = buffer.trim();
  if (trailing && !trailing.startsWith('data:')) enqueue('plan_delta', { text: trailing });
}

async function verifyTurnstile(request, token, env) {
  if (env?.TURNSTILE_TEST_RESULT) {
    return {
      success: env.TURNSTILE_TEST_RESULT === 'pass',
      errors: env.TURNSTILE_TEST_RESULT === 'pass' ? [] : ['test_turnstile_failure'],
    };
  }

  if (!env?.TURNSTILE_SECRET_KEY) {
    return { success: false, errors: ['missing_turnstile_secret'] };
  }

  const form = new URLSearchParams();
  form.set('secret', env.TURNSTILE_SECRET_KEY);
  form.set('response', token);
  const ip = request.headers.get('CF-Connecting-IP');
  if (ip) form.set('remoteip', ip);

  const response = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  });
  const body = await response.json().catch(() => ({}));
  return {
    success: !!body.success,
    errors: Array.isArray(body['error-codes']) ? body['error-codes'] : [],
  };
}

function toBase64(binary) {
  if (typeof btoa === 'function') return btoa(binary);
  return Buffer.from(binary, 'binary').toString('base64');
}

function fromBase64(value) {
  if (typeof atob === 'function') return atob(value);
  return Buffer.from(value, 'base64').toString('binary');
}

function bytesToBase64url(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return toBase64(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function base64urlToBytes(value) {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  const binary = fromBase64(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function stringToBase64url(value) {
  return bytesToBase64url(new TextEncoder().encode(value));
}

function base64urlToString(value) {
  return new TextDecoder().decode(base64urlToBytes(value));
}

function getAiSessionSecret(env) {
  return env?.AI_SESSION_SECRET || env?.TURNSTILE_SECRET_KEY || '';
}

async function signSessionPayload(payloadPart, env) {
  const secret = getAiSessionSecret(env);
  if (!secret) throw new Error('missing_session_secret');
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign', 'verify'],
  );
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payloadPart));
  return bytesToBase64url(new Uint8Array(signature));
}

async function createAiSessionToken(request, env) {
  const origin = request.headers.get('Origin') || '';
  const now = Math.floor(Date.now() / 1000);
  const ttlSeconds = getAiSessionTtlSeconds(env);
  const payload = {
    iss: getServiceName(env),
    iat: now,
    exp: now + ttlSeconds,
    origin,
  };
  const payloadPart = stringToBase64url(JSON.stringify(payload));
  const signaturePart = await signSessionPayload(payloadPart, env);
  return {
    sessionToken: `${payloadPart}.${signaturePart}`,
    expiresAt: payload.exp * 1000,
    ttlSeconds,
  };
}

async function verifyAiSessionToken(request, token, env) {
  if (typeof token !== 'string' || !token.trim()) {
    return { success: false, error: 'session_required' };
  }
  const parts = token.split('.');
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    return { success: false, error: 'session_invalid' };
  }
  try {
    const expectedSignature = await signSessionPayload(parts[0], env);
    if (expectedSignature !== parts[1]) return { success: false, error: 'session_invalid' };
    const payload = JSON.parse(base64urlToString(parts[0]));
    const now = Math.floor(Date.now() / 1000);
    if (!payload || payload.exp <= now) return { success: false, error: 'session_expired' };
    if (payload.origin !== request.headers.get('Origin')) return { success: false, error: 'session_origin_mismatch' };
    if (payload.iss !== getServiceName(env)) return { success: false, error: 'session_invalid' };
    return { success: true, payload };
  } catch (_) {
    return { success: false, error: 'session_invalid' };
  }
}

function optionsForState(catalog, stateName) {
  return catalog.states[stateName] || [];
}

function chooseOption(catalog, baselineState, stateName, predicate = () => true) {
  const options = optionsForState(catalog, stateName);
  return options.find((option) => predicate(option) && baselineState[stateName] !== option.value)
    || options.find(predicate)
    || null;
}

function chooseOptionByRatio(catalog, baselineState, stateName, ratio) {
  const options = optionsForState(catalog, stateName);
  if (!options.length) return null;
  const index = Math.max(0, Math.min(options.length - 1, Math.round((options.length - 1) * ratio)));
  const preferred = options[index];
  if (preferred && baselineState[stateName] !== preferred.value) return preferred;
  return chooseOption(catalog, baselineState, stateName);
}

function parseHexColor(hex) {
  const match = String(hex || '').match(/^#?([0-9a-f]{6})$/i);
  if (!match) return null;
  const value = Number.parseInt(match[1], 16);
  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255,
  };
}

function colorLuminance(option) {
  const rgb = parseHexColor(option.color);
  if (!rgb) return 1;
  return (0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b) / 255;
}

function colorDistance(option, targetHex) {
  const rgb = parseHexColor(option.color);
  const target = parseHexColor(targetHex);
  if (!rgb || !target) return Number.POSITIVE_INFINITY;
  return ((rgb.r - target.r) ** 2) + ((rgb.g - target.g) ** 2) + ((rgb.b - target.b) ** 2);
}

function chooseDarkColor(catalog, baselineState, stateName) {
  return [...optionsForState(catalog, stateName)]
    .filter((option) => option.color && baselineState[stateName] !== option.value)
    .sort((a, b) => colorLuminance(a) - colorLuminance(b))[0]
    || chooseOption(catalog, baselineState, stateName, (option) => !!option.color);
}

function chooseClosestColor(catalog, baselineState, stateName, targetHex) {
  return [...optionsForState(catalog, stateName)]
    .filter((option) => option.color && baselineState[stateName] !== option.value)
    .sort((a, b) => colorDistance(a, targetHex) - colorDistance(b, targetHex))[0]
    || chooseOption(catalog, baselineState, stateName, (option) => !!option.color);
}

function buildStepsFromAvatarState(avatarState, catalog) {
  return Object.entries(avatarState).map(([stateName, value]) => {
    const option = optionsForState(catalog, stateName).find((item) => item.value === value);
    const tab = option?.tab || stateName;
    const section = option?.section || stateName;
    const optionLabel = Number.isFinite(option?.index) ? `option ${option.index + 1}` : 'the matching option';
    if (option?.kind === 'color' && option.color) {
      return `Open ${tab}, find ${section}, then choose the ${option.color} color swatch (${optionLabel}).`;
    }
    return `Open ${tab}, find ${section}, then choose ${optionLabel}.`;
  }).slice(0, 12);
}

function summarizeAvatarState(avatarState) {
  const states = Object.keys(avatarState);
  if (!states.length) return 'No editable avatar changes were produced.';
  return `Applied ${states.length} editable avatar choices: ${states.join(', ')}.`;
}

function buildFallbackResult(validated, warning) {
  const { prompt, baselineState, catalog } = validated;
  const lower = prompt.toLowerCase();
  const avatarState = {};
  const warnings = warning ? [warning] : [];

  const add = (stateName, option) => {
    if (!option) return;
    if (baselineState[stateName] === option.value) return;
    if (avatarState[stateName] !== undefined) return;
    avatarState[stateName] = option.value;
  };

  const colorTargets = [
    [/purple|violet|lavender|紫/, '#9069CD'],
    [/blue|cyan|sky|蓝/, '#44A1CD'],
    [/green|lime|emerald|绿/, '#78B13B'],
    [/yellow|gold|金|黄/, '#F3CB3F'],
    [/orange|橙/, '#F3A13F'],
    [/red|pink|rose|红|粉/, '#C03C64'],
    [/black|dark|深|黑/, '#424242'],
    [/white|light|pale|白|浅/, '#ECF0F1'],
  ];

  const matchedColor = colorTargets.find(([pattern]) => pattern.test(lower));
  if (matchedColor) {
    add('ClothingColor', chooseClosestColor(catalog, baselineState, 'ClothingColor', matchedColor[1]));
    add('BackgroundColor', chooseClosestColor(catalog, baselineState, 'BackgroundColor', matchedColor[1]));
  }

  if (/鲁迅|lu\s*xun|luxun/.test(lower)) {
    add('SkinTone', chooseOptionByRatio(catalog, baselineState, 'SkinTone', 0.25));
    add('MainHair', chooseOptionByRatio(catalog, baselineState, 'MainHair', 0.18));
    add('MainHairColor', chooseDarkColor(catalog, baselineState, 'MainHairColor'));
    add('Glasses', chooseOption(catalog, baselineState, 'Glasses', (option) => option.value !== 0));
    add('GlassesColor', chooseDarkColor(catalog, baselineState, 'GlassesColor'));
    add('Wrinkles', chooseOption(catalog, baselineState, 'Wrinkles', (option) => option.value !== 0));
    add('FacialHair', chooseOption(catalog, baselineState, 'FacialHair', (option) => option.value !== 0));
    add('FacialHairColor', chooseDarkColor(catalog, baselineState, 'FacialHairColor'));
    add('ClothingColor', chooseDarkColor(catalog, baselineState, 'ClothingColor'));
    add('BackgroundColor', chooseClosestColor(catalog, baselineState, 'BackgroundColor', '#AFAFAF'));
  }

  if (/glasses|spectacles|眼镜/.test(lower)) {
    add('Glasses', chooseOption(catalog, baselineState, 'Glasses', (option) => option.value !== 0));
    add('GlassesColor', chooseDarkColor(catalog, baselineState, 'GlassesColor'));
  }
  if (/beard|mustache|moustache|facial hair|胡子|胡须/.test(lower)) {
    add('FacialHair', chooseOption(catalog, baselineState, 'FacialHair', (option) => option.value !== 0));
    add('FacialHairColor', chooseDarkColor(catalog, baselineState, 'FacialHairColor'));
  }
  if (/hat|cap|headwear|帽/.test(lower)) {
    add('Headwear', chooseOption(catalog, baselineState, 'Headwear', (option) => option.value !== 0));
  }
  if (/earring|earrings|piercing|耳环|耳钉/.test(lower)) {
    add('Piercings', chooseOption(catalog, baselineState, 'Piercings', (option) => option.value !== 0));
  }
  if (/nose ring|nose piercing|鼻环/.test(lower)) {
    add('Nose Piercing', chooseOption(catalog, baselineState, 'Nose Piercing', (option) => option.value !== 0));
  }
  if (/wrinkle|older|aged|elder|老|年长|皱纹/.test(lower)) {
    add('Wrinkles', chooseOption(catalog, baselineState, 'Wrinkles', (option) => option.value !== 0));
  }
  if (/hair|hairstyle|发型|头发/.test(lower)) {
    add('MainHair', chooseOption(catalog, baselineState, 'MainHair', (option) => option.value !== 0));
  }
  if (/smile|happy|cheerful|开心|微笑|快乐/.test(lower)) {
    add('Expression', chooseOptionByRatio(catalog, baselineState, 'Expression', 0.15));
  }
  if (/serious|wise|calm|thoughtful|严肃|智慧|沉思/.test(lower)) {
    add('Expression', chooseOptionByRatio(catalog, baselineState, 'Expression', 0.55));
  }

  if (!Object.keys(avatarState).length) {
    add('BackgroundColor', chooseClosestColor(catalog, baselineState, 'BackgroundColor', '#84D7FF'));
    add('Body', chooseOption(catalog, baselineState, 'Body'));
  }

  if (!warning) {
    warnings.push('Used deterministic editor mapping where model semantics were uncertain.');
  }

  return {
    avatarState,
    steps: buildStepsFromAvatarState(avatarState, catalog),
    summary: summarizeAvatarState(avatarState),
    confidence: 0.48,
    warnings: warnings.slice(0, 10),
    usedFallback: true,
  };
}

function removeNoopChanges(avatarState, baselineState) {
  const clean = {};
  for (const [stateName, value] of Object.entries(avatarState || {})) {
    if (baselineState[stateName] !== value) clean[stateName] = value;
  }
  return clean;
}

function completeStructuredResult(result, validated, warning) {
  const avatarState = removeNoopChanges(result.avatarState, validated.baselineState);
  if (!Object.keys(avatarState).length) {
    return buildFallbackResult(validated, warning || 'Model returned no visible editable changes, so a safe editor mapping was used.');
  }
  const warnings = [...(result.warnings || [])];
  if (warning) warnings.unshift(warning);
  return {
    avatarState,
    steps: buildStepsFromAvatarState(avatarState, validated.catalog),
    summary: result.summary || summarizeAvatarState(avatarState),
    confidence: result.confidence,
    warnings: warnings.slice(0, 10),
    usedFallback: false,
  };
}

async function buildEditableAvatarResult(validated, env, model) {
  try {
    const structured = await env.AI.run(model, {
      messages: buildStructuredMessages(validated),
      max_tokens: 1100,
      temperature: 0.2,
      response_format: {
        type: 'json_schema',
        json_schema: avatarJsonSchema(validated.catalog),
      },
    });
    const parsedResult = parseJsonModeResponse(structured);
    const safeResult = sanitizeModelResult(parsedResult, validated.catalog);
    return completeStructuredResult(safeResult, validated);
  } catch (error) {
    return buildFallbackResult(
      validated,
      `Structured model output failed, so a safe editor mapping was used: ${error?.message || 'unknown error'}.`,
    );
  }
}

async function readJsonBody(request) {
  const contentType = request.headers.get('Content-Type') || '';
  if (!contentType.includes('application/json')) {
    return { error: 'invalid_content_type' };
  }
  try {
    return { body: await request.json() };
  } catch (_) {
    return { error: 'invalid_json' };
  }
}

function validateGenerationRequest(request, body, env) {
  if (!isAllowedOrigin(request.headers.get('Origin'))) {
    return { status: 403, body: { ok: false, error: 'origin_not_allowed' } };
  }
  if (!env?.AI) {
    return { status: 503, body: { ok: false, error: 'ai_not_configured' } };
  }
  if (!env?.TURNSTILE_SECRET_KEY || !getTurnstileSiteKey(env)) {
    return { status: 503, body: { ok: false, error: 'turnstile_not_configured' } };
  }

  const maxPromptLength = getMaxPromptLength(env);
  const prompt = normalizePrompt(body?.prompt, maxPromptLength);
  if (!prompt) return { status: 400, body: { ok: false, error: 'prompt_required' } };
  if (prompt.length > maxPromptLength) return { status: 400, body: { ok: false, error: 'prompt_too_long', maxPromptLength } };
  if (typeof body?.sessionToken !== 'string' || !body.sessionToken.trim()) {
    return { status: 401, body: { ok: false, error: 'session_required' } };
  }

  const catalog = normalizeCatalog(body?.catalog);
  if (!catalog) return { status: 400, body: { ok: false, error: 'catalog_required' } };

  return {
    prompt,
    contextMode: normalizeContextMode(body?.contextMode),
    baselineState: cleanStateSnapshot(body?.baselineState),
    catalog,
    sessionToken: body.sessionToken.trim(),
  };
}

async function handleAvatarSession(request, env) {
  if (!isAllowedOrigin(request.headers.get('Origin'))) {
    return jsonResponse(request, { ok: false, error: 'origin_not_allowed' }, 403);
  }
  if (!env?.TURNSTILE_SECRET_KEY || !getTurnstileSiteKey(env)) {
    return jsonResponse(request, { ok: false, error: 'turnstile_not_configured' }, 503);
  }

  const parsed = await readJsonBody(request);
  if (parsed.error) return jsonResponse(request, { ok: false, error: parsed.error }, 400);
  const token = typeof parsed.body?.turnstileToken === 'string' ? parsed.body.turnstileToken.trim() : '';
  if (!token) return jsonResponse(request, { ok: false, error: 'turnstile_token_required' }, 400);

  const turnstile = await verifyTurnstile(request, token, env);
  if (!turnstile.success) {
    return jsonResponse(request, {
      ok: false,
      error: 'turnstile_failed',
      details: turnstile.errors,
    }, 403);
  }

  const session = await createAiSessionToken(request, env);
  return jsonResponse(request, {
    ok: true,
    ...session,
  });
}

async function handleAvatarGenerate(request, env) {
  const parsed = await readJsonBody(request);
  if (parsed.error) return jsonResponse(request, { ok: false, error: parsed.error }, 400);

  const validated = validateGenerationRequest(request, parsed.body, env);
  if (validated.status) return jsonResponse(request, validated.body, validated.status);

  const session = await verifyAiSessionToken(request, validated.sessionToken, env);
  if (!session.success) {
    return jsonResponse(request, {
      ok: false,
      error: session.error,
    }, session.error === 'session_required' ? 401 : 403);
  }

  const encoder = new TextEncoder();
  const model = getTextModel(env);
  const body = new ReadableStream({
    async start(controller) {
      const enqueue = (event, data) => controller.enqueue(encoder.encode(encodeSse(event, data)));
      try {
        enqueue('status', { message: 'Building editable avatar configuration...' });
        const safeResult = await buildEditableAvatarResult(validated, env, model);
        enqueue('final', {
          ok: true,
          contextMode: validated.contextMode,
          model: 'workers-ai',
          ...safeResult,
        });

        enqueue('status', { message: 'Writing applied edit notes...' });
        try {
          const planStream = await env.AI.run(model, {
            messages: buildExplanationMessages({ ...validated, result: safeResult }),
            stream: true,
            max_tokens: 320,
            temperature: 0.4,
          });
          await pipeAiPlanStream(planStream, enqueue);
        } catch (_) {
          if (safeResult.summary) enqueue('plan_delta', { text: safeResult.summary });
        }
      } catch (error) {
        enqueue('error', {
          ok: false,
          error: 'generation_failed',
          message: error?.message || 'Avatar generation failed.',
        });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(body, { status: 200, headers: sseHeaders(request) });
}

async function handleRequest(request, env = {}) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(request) });
  }

  const url = new URL(request.url);

  if (url.pathname === '/health') {
    if (request.method !== 'GET') return methodNotAllowed(request, ['GET', 'OPTIONS']);
    return jsonResponse(request, {
      ok: true,
      service: getServiceName(env),
      version: getServiceVersion(env),
    });
  }

  if (url.pathname === '/api/config') {
    if (request.method !== 'GET') return methodNotAllowed(request, ['GET', 'OPTIONS']);
    return jsonResponse(request, {
      ok: true,
      service: getServiceName(env),
      version: getServiceVersion(env),
      apiVersion: 'v1',
      features: {
        avatarGeneration: true,
        llmProxy: true,
      },
      generation: {
        turnstileSiteKey: getTurnstileSiteKey(env),
        maxPromptLength: getMaxPromptLength(env),
        sessionTtlSeconds: getAiSessionTtlSeconds(env),
        supportedMentions: ['current', 'default'],
      },
      endpoints: {
        avatarSession: '/api/avatar/session',
        avatarGenerate: '/api/avatar/generate',
      },
    });
  }

  if (url.pathname === '/api/avatar/session') {
    if (request.method !== 'POST') return methodNotAllowed(request, ['POST', 'OPTIONS']);
    return handleAvatarSession(request, env);
  }

  if (url.pathname === '/api/avatar/generate') {
    if (request.method !== 'POST') return methodNotAllowed(request, ['POST', 'OPTIONS']);
    return handleAvatarGenerate(request, env);
  }

  return jsonResponse(request, {
    ok: false,
    error: 'not_found',
  }, 404);
}

export default {
  fetch: handleRequest,
};

export {
  buildFallbackResult,
  createAiSessionToken,
  handleRequest,
  isAllowedOrigin,
  normalizeCatalog,
  sanitizeModelResult,
  verifyAiSessionToken,
};
