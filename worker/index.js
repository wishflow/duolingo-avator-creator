const SERVICE_NAME = 'duolingo-avator-creator';
const SERVICE_VERSION = '0.2.0';
const DEFAULT_TEXT_MODEL = '@cf/meta/llama-3.1-8b-instruct-fast';
const MAX_PROMPT_LENGTH = 800;
const MAX_CATALOG_OPTIONS = 420;

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
    const value = change.value;
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
            value: {},
            reason: { type: 'string' },
          },
          required: ['state', 'value'],
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

function buildPlanningMessages({ prompt, contextMode, baselineState, catalog }) {
  const catalogSummary = JSON.stringify(catalog);
  const stateSummary = JSON.stringify(baselineState);
  return [
    {
      role: 'system',
      content: [
        'You are an avatar design planner for a browser-based Duolingo-style avatar editor.',
        'Write a concise, user-facing plan. Do not mention APIs, model names, JSON, schema, internal state IDs, or implementation details.',
        'Mention visible design choices such as skin tone, hair, eyes, shirt, accessories, expression, and background.',
        'Use the same language as the user prompt when possible.',
      ].join(' '),
    },
    {
      role: 'user',
      content: [
        `User request: ${prompt}`,
        `Context mode: ${contextMode}`,
        `Baseline avatar state: ${stateSummary}`,
        `Available editor catalog: ${catalogSummary}`,
        'Describe the avatar edits you will make in 4-8 short sentences.',
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
          avatarState: 'Array of supported { state, value, reason } changes only.',
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
  if (typeof body?.turnstileToken !== 'string' || !body.turnstileToken.trim()) {
    return { status: 400, body: { ok: false, error: 'turnstile_token_required' } };
  }

  const catalog = normalizeCatalog(body?.catalog);
  if (!catalog) return { status: 400, body: { ok: false, error: 'catalog_required' } };

  return {
    prompt,
    contextMode: normalizeContextMode(body?.contextMode),
    baselineState: cleanStateSnapshot(body?.baselineState),
    catalog,
    turnstileToken: body.turnstileToken.trim(),
  };
}

async function handleAvatarGenerate(request, env) {
  const parsed = await readJsonBody(request);
  if (parsed.error) return jsonResponse(request, { ok: false, error: parsed.error }, 400);

  const validated = validateGenerationRequest(request, parsed.body, env);
  if (validated.status) return jsonResponse(request, validated.body, validated.status);

  const turnstile = await verifyTurnstile(request, validated.turnstileToken, env);
  if (!turnstile.success) {
    return jsonResponse(request, {
      ok: false,
      error: 'turnstile_failed',
      details: turnstile.errors,
    }, 403);
  }

  const encoder = new TextEncoder();
  const model = getTextModel(env);
  const body = new ReadableStream({
    async start(controller) {
      const enqueue = (event, data) => controller.enqueue(encoder.encode(encodeSse(event, data)));
      try {
        enqueue('status', { message: 'Planning avatar changes...' });
        const planStream = await env.AI.run(model, {
          messages: buildPlanningMessages(validated),
          stream: true,
          max_tokens: 380,
          temperature: 0.5,
        });
        await pipeAiPlanStream(planStream, enqueue);

        enqueue('status', { message: 'Building editable avatar configuration...' });
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
        enqueue('final', {
          ok: true,
          contextMode: validated.contextMode,
          model: 'workers-ai',
          ...safeResult,
        });
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
        supportedMentions: ['current', 'default'],
      },
      endpoints: {
        avatarGenerate: '/api/avatar/generate',
      },
    });
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
  handleRequest,
  isAllowedOrigin,
  normalizeCatalog,
  sanitizeModelResult,
};
