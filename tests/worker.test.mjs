import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import worker, { normalizeCatalog, sanitizeModelResult } from '../worker/index.js';

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
      return {
        response: {
          summary: 'Generated editable avatar.',
          confidence: 0.82,
          avatarState: [
            { state: 'Body', value: 5, reason: 'Requested stronger body silhouette.' },
            { state: 'BackgroundColor', value: 6, reason: 'Requested purple background.' },
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
    assert.deepEqual(body.generation.supportedMentions, ['current', 'default']);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'https://duolingo-avator-creator.pages.dev');
  });

  it('requires Turnstile token before calling AI', async () => {
    const ai = makeAiMock();
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ prompt: 'green hoodie', catalog: TEST_CATALOG }),
    }, testEnv({ AI: ai }));
    const body = await response.json();

    assert.equal(response.status, 400);
    assert.equal(body.error, 'turnstile_token_required');
    assert.equal(ai.calls.length, 0);
  });

  it('rejects failed Turnstile validation', async () => {
    const ai = makeAiMock();
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt: 'green hoodie',
        turnstileToken: 'token',
        catalog: TEST_CATALOG,
      }),
    }, testEnv({ AI: ai, TURNSTILE_TEST_RESULT: 'fail' }));
    const body = await response.json();

    assert.equal(response.status, 403);
    assert.equal(body.error, 'turnstile_failed');
    assert.equal(ai.calls.length, 0);
  });

  it('streams planning text and final editable avatar state', async () => {
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
        turnstileToken: 'token',
        catalog: TEST_CATALOG,
      }),
    }, testEnv({ AI: ai }));
    const events = await readSse(response);
    const final = events.find((item) => item.event === 'final')?.data;

    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Content-Type'), 'text/event-stream; charset=utf-8');
    assert.ok(events.some((item) => item.event === 'plan_delta'));
    assert.equal(final.ok, true);
    assert.deepEqual(final.avatarState, { Body: 5, BackgroundColor: 6 });
    assert.equal(final.contextMode, 'current');
    assert.equal(ai.calls.length, 2);
    assert.equal(ai.calls[0].input.stream, true);
    assert.equal(ai.calls[1].input.response_format.type, 'json_schema');
  });

  it('filters unsupported model state values', () => {
    const clean = sanitizeModelResult({
      avatarState: [
        { state: 'Body', value: 5 },
        { state: 'Body', value: 999 },
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
        turnstileToken: 'token',
        catalog: TEST_CATALOG,
      }),
    };

    const noAi = await fetchWorker('/api/avatar/generate', baseRequest, testEnv({ AI: undefined }));
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
