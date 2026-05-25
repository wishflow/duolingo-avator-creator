import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import worker, { normalizeCatalog, sanitizeModelResult } from '../worker/index.ts';

const API_URL = 'https://duolingo-avator-creator.wei-shi-ws.workers.dev';

const TEST_CATALOG = {
  states: {
    Body: [
      { value: 1, tab: 'Body', section: 'Body', kind: 'feature', index: 0 },
      { value: 5, tab: 'Body', section: 'Body', kind: 'feature', index: 1 },
    ],
    BackgroundColor: [
      { value: 1, tab: 'BG', section: 'Background', kind: 'color', color: '#E5E5E5', index: 0 },
      { value: 6, tab: 'BG', section: 'Background', kind: 'color', color: '#9069CD', index: 1 },
    ],
  },
};

function makeAiMock(result = {}) {
  const calls = [];
  return {
    calls,
    async run(model, input) {
      calls.push({ model, input });
      if (input.stream) {
        return new ReadableStream({
          start(controller) {
            const encoder = new TextEncoder();
            controller.enqueue(encoder.encode('data: {"response":"Choose a bold shirt and clean background."}\n\n'));
            controller.enqueue(encoder.encode('data: {"response":" Keep the avatar editable."}\n\n'));
            controller.close();
          },
        });
      }
      if (result.throwStructured) throw new Error('mock structured failure');
      if (result.response !== undefined) {
        return { response: result.response };
      }
      return {
        response: {
          summary: 'Generated editable avatar.',
          confidence: 0.82,
          avatarState: [
            { state: 'Body', valueNumber: 5, reason: 'Requested stronger body silhouette.' },
            { state: 'BackgroundColor', valueNumber: 6, reason: 'Requested purple background.' },
            ...(result.extraChanges || []),
          ],
          steps: ['Open Body and choose option 5.', 'Open BG and choose the purple swatch.'],
          warnings: result.warnings || [],
        },
      };
    },
  };
}

function testEnv(overrides = {}) {
  return {
    SERVICE_NAME: 'duolingo-avator-creator',
    SERVICE_VERSION: 'test',
    TURNSTILE_SITE_KEY: '1x00000000000000000000AA',
    TURNSTILE_SECRET_KEY: 'secret',
    TURNSTILE_TEST_RESULT: 'pass',
    AI_TEXT_MODEL: '@cf/test/model',
    AI: makeAiMock(),
    ...overrides,
  };
}

async function fetchWorker(path, init = {}, env = testEnv()) {
  const request = new Request(`${API_URL}${path}`, init);
  return worker.fetch(request, env);
}

async function readSse(response) {
  const text = await response.text();
  const events = [];
  for (const frame of text.trim().split('\n\n')) {
    const event = frame.split('\n').find((line) => line.startsWith('event:'))?.slice(6).trim();
    const data = frame.split('\n').find((line) => line.startsWith('data:'))?.slice(5).trim();
    if (event && data) events.push({ event, data: JSON.parse(data) });
  }
  return events;
}

async function createSession(env = testEnv(), origin = 'http://127.0.0.1:8775') {
  const response = await fetchWorker('/api/avatar/session', {
    method: 'POST',
    headers: {
      Origin: origin,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ turnstileToken: 'token' }),
  }, env);
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.ok(body.sessionToken);
  return body.sessionToken;
}

describe('Cloudflare Worker API', () => {
  it('returns health payload', async () => {
    const response = await fetchWorker('/health', {
      headers: { Origin: 'https://wishflow.github.io' },
    });
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.service, 'duolingo-avator-creator');
    assert.equal(body.version, 'test');
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'https://wishflow.github.io');
  });

  it('returns public AI generation config', async () => {
    const response = await fetchWorker('/api/config', {
      headers: { Origin: 'https://duolingo-avator-creator.pages.dev' },
    });
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.apiVersion, 'v1');
    assert.equal(body.features.avatarGeneration, true);
    assert.equal(body.features.llmProxy, true);
    assert.equal(body.generation.turnstileSiteKey, '1x00000000000000000000AA');
    assert.equal(body.generation.sessionTtlSeconds, 1800);
    assert.deepEqual(body.generation.supportedMentions, ['current', 'default']);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'https://duolingo-avator-creator.pages.dev');
  });

  it('requires Turnstile token before creating an AI session', async () => {
    const ai = makeAiMock();
    const response = await fetchWorker('/api/avatar/session', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    }, testEnv({ AI: ai }));
    const body = await response.json();

    assert.equal(response.status, 400);
    assert.equal(body.error, 'turnstile_token_required');
    assert.equal(ai.calls.length, 0);
  });

  it('rejects failed Turnstile validation', async () => {
    const ai = makeAiMock();
    const response = await fetchWorker('/api/avatar/session', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        turnstileToken: 'token',
      }),
    }, testEnv({ AI: ai, TURNSTILE_TEST_RESULT: 'fail' }));
    const body = await response.json();

    assert.equal(response.status, 403);
    assert.equal(body.error, 'turnstile_failed');
    assert.equal(ai.calls.length, 0);
  });

  it('requires a verified AI session before calling AI', async () => {
    const ai = makeAiMock();
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: '@current make a purple avatar',
        contextMode: 'current',
        baselineState: { Body: 1, BackgroundColor: 1 },
        catalog: TEST_CATALOG,
      }),
    }, testEnv({ AI: ai }));
    const body = await response.json();

    assert.equal(response.status, 401);
    assert.equal(body.error, 'session_required');
    assert.equal(ai.calls.length, 0);
  });

  it('streams final editable avatar state and applied edit notes', async () => {
    const ai = makeAiMock();
    const env = testEnv({ AI: ai });
    const sessionToken = await createSession(env);
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: '@current make a purple avatar',
        contextMode: 'current',
        baselineState: { Body: 1, BackgroundColor: 1 },
        sessionToken,
        catalog: TEST_CATALOG,
      }),
    }, env);
    const events = await readSse(response);
    const final = events.find((item) => item.event === 'final')?.data;

    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Content-Type'), 'text/event-stream; charset=utf-8');
    assert.ok(events.some((item) => item.event === 'plan_delta'));
    assert.equal(final.ok, true);
    assert.deepEqual(final.avatarState, { Body: 5, BackgroundColor: 6 });
    assert.equal(final.contextMode, 'current');
    assert.equal(final.model, 'workers-ai');
    assert.equal(typeof final.summary, 'string');
    assert.equal(typeof final.confidence, 'number');
    assert.equal(typeof final.usedFallback, 'boolean');
    assert.ok(Array.isArray(final.steps));
    assert.ok(Array.isArray(final.warnings));
    assert.equal(ai.calls.length, 2);
    assert.equal(ai.calls[0].input.response_format.type, 'json_schema');
    assert.equal(ai.calls[1].input.stream, true);
  });

  it('rejects invalid JSON and content types', async () => {
    const badJson = await fetchWorker('/api/avatar/session', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: '{',
    });
    const badJsonBody = await badJson.json();

    assert.equal(badJson.status, 400);
    assert.equal(badJsonBody.error, 'invalid_json');

    const badType = await fetchWorker('/api/avatar/session', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'text/plain',
      },
      body: 'turnstileToken=token',
    });
    const badTypeBody = await badType.json();

    assert.equal(badType.status, 400);
    assert.equal(badTypeBody.error, 'invalid_content_type');
  });

  it('rejects invalid prompt, catalog, and session payloads before calling AI', async () => {
    const ai = makeAiMock();
    const env = testEnv({ AI: ai });

    const invalidSession = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: 'green hoodie',
        sessionToken: 'invalid-session',
        catalog: TEST_CATALOG,
      }),
    }, env);
    const invalidSessionBody = await invalidSession.json();
    assert.equal(invalidSession.status, 403);
    assert.equal(invalidSessionBody.error, 'session_invalid');

    const missingPrompt = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: '   ',
        sessionToken: 'unused',
        catalog: TEST_CATALOG,
      }),
    }, env);
    const missingPromptBody = await missingPrompt.json();
    assert.equal(missingPrompt.status, 400);
    assert.equal(missingPromptBody.error, 'prompt_required');

    const invalidCatalog = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: 'green hoodie',
        sessionToken: 'unused',
        catalog: { states: { Body: [{ value: { nested: true } }] } },
      }),
    }, env);
    const invalidCatalogBody = await invalidCatalog.json();
    assert.equal(invalidCatalog.status, 400);
    assert.equal(invalidCatalogBody.error, 'catalog_required');
    assert.equal(ai.calls.length, 0);
  });

  it('filters dirty model output before sending final payload', async () => {
    const dirtyWarnings = Array.from({ length: 12 }, (_, index) => `dirty warning ${index + 1}`);
    const ai = makeAiMock({
      response: {
        summary: 'Dirty model output still produced valid edits.',
        confidence: 1.5,
        avatarState: [
          { state: 'Body', valueNumber: 5 },
          { state: 'Body', valueNumber: 999 },
          { state: 'BackgroundColor', valueNumber: 6 },
          { state: 'UnknownState', valueNumber: 1 },
          { state: 'BackgroundColor', valueBoolean: true },
          { state: 'Body', value: 'bad' },
        ],
        steps: Array.from({ length: 20 }, (_, index) => `dirty step ${index + 1}`),
        warnings: dirtyWarnings,
      },
    });
    const env = testEnv({ AI: ai });
    const sessionToken = await createSession(env);
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: '@current make a purple avatar',
        contextMode: 'current',
        baselineState: { Body: 1, BackgroundColor: 1 },
        sessionToken,
        catalog: TEST_CATALOG,
      }),
    }, env);
    const events = await readSse(response);
    const final = events.find((item) => item.event === 'final')?.data;

    assert.equal(response.status, 200);
    assert.equal(final.ok, true);
    assert.deepEqual(final.avatarState, { Body: 5, BackgroundColor: 6 });
    assert.equal(final.confidence, 1);
    assert.equal(final.usedFallback, false);
    assert.ok(final.warnings.length <= 10);
    assert.ok(final.warnings.some((warning) => warning.includes('UnknownState')));
    assert.ok(final.steps.every((step) => step.startsWith('Open ')));
  });

  it('rejects sessions from a different origin', async () => {
    const ai = makeAiMock();
    const env = testEnv({ AI: ai });
    const sessionToken = await createSession(env, 'http://127.0.0.1:8775');
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'https://wishflow.github.io',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: 'green hoodie',
        sessionToken,
        catalog: TEST_CATALOG,
      }),
    }, env);
    const body = await response.json();

    assert.equal(response.status, 403);
    assert.equal(body.error, 'session_origin_mismatch');
    assert.equal(ai.calls.length, 0);
  });

  it('falls back to deterministic editable changes if structured AI output fails', async () => {
    const ai = makeAiMock({ throwStructured: true });
    const env = testEnv({ AI: ai });
    const sessionToken = await createSession(env);
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: 'make a dark avatar',
        baselineState: { Body: 1, BackgroundColor: 1 },
        sessionToken,
        catalog: TEST_CATALOG,
      }),
    }, env);
    const events = await readSse(response);
    const final = events.find((item) => item.event === 'final')?.data;

    assert.equal(response.status, 200);
    assert.equal(final.ok, true);
    assert.ok(Object.keys(final.avatarState).length > 0);
    assert.ok(final.steps.length > 0);
    assert.equal(final.usedFallback, true);
    assert.ok(final.warnings.some((warning) => warning.includes('safe editor mapping')));
  });

  it('filters unsupported model state values', () => {
    const clean = sanitizeModelResult({
      avatarState: [
        { state: 'Body', value: 5 },
        { state: 'Body', valueNumber: 999 },
        { state: 'UnknownState', value: 1 },
      ],
      steps: ['Pick a valid body.'],
      warnings: ['Some details are approximate.'],
      confidence: 0.9,
    }, normalizeCatalog(TEST_CATALOG));

    assert.deepEqual(clean.avatarState, { Body: 5 });
    assert.ok(clean.warnings.some((warning) => warning.includes('Body')));
    assert.ok(clean.warnings.some((warning) => warning.includes('UnknownState')));
  });

  it('returns clear errors when AI or Turnstile config is missing', async () => {
    const baseRequest = {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: 'green hoodie',
        sessionToken: 'invalid-session',
        catalog: TEST_CATALOG,
      }),
    };

    const noAiEnv = testEnv({ AI: undefined });
    const noAiSession = await createSession(noAiEnv);
    const noAi = await fetchWorker('/api/avatar/generate', {
      ...baseRequest,
      body: JSON.stringify({
        prompt: 'green hoodie',
        sessionToken: noAiSession,
        catalog: TEST_CATALOG,
      }),
    }, noAiEnv);
    const noAiBody = await noAi.json();
    assert.equal(noAi.status, 503);
    assert.equal(noAiBody.error, 'ai_not_configured');

    const noTurnstile = await fetchWorker('/api/avatar/generate', baseRequest, testEnv({ TURNSTILE_SECRET_KEY: '' }));
    const noTurnstileBody = await noTurnstile.json();
    assert.equal(noTurnstile.status, 503);
    assert.equal(noTurnstileBody.error, 'turnstile_not_configured');
  });

  it('handles preflight requests', async () => {
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'OPTIONS',
      headers: {
        Origin: 'http://localhost:5173',
        'Access-Control-Request-Method': 'POST',
      },
    });

    assert.equal(response.status, 204);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:5173');
    assert.match(response.headers.get('Access-Control-Allow-Methods'), /POST/);
  });

  it('does not allow unknown origins', async () => {
    const response = await fetchWorker('/health', {
      headers: { Origin: 'https://example.com' },
    });

    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), null);
  });
});
