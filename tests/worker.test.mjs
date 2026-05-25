import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import worker, { normalizeCatalog, sanitizeModelResult } from '../worker/index.ts';

const API_URL = 'https://duolingo-avator-creator.wei-shi-ws.workers.dev';

function sem({
  state,
  value,
  group,
  tags,
  kind = 'feature',
  color,
  visible = true,
  needsReview = false,
  requires = [],
  index = 0,
}) {
  return {
    optionId: `${state}:${value}`,
    state,
    value,
    tab: group,
    section: group,
    kind,
    color,
    index,
    group,
    tags,
    confidence: 0.9,
    visible,
    needsReview,
    requires,
    statesToOverride: { [state]: value },
  };
}

const TEST_CATALOG = {
  semanticVersion: 1,
  sourceVersion: 'test-rive',
  configSourceVersion: 'test-rive',
  states: {
    Body: [
      { value: 1, tab: 'Body', section: 'Body', kind: 'feature', index: 0 },
      { value: 5, tab: 'Body', section: 'Body', kind: 'feature', index: 1 },
    ],
    ClothingColor: [
      { value: 1, tab: 'Shirt', section: 'Clothing', kind: 'color', color: '#B782C2', index: 0 },
      { value: 9, tab: 'Shirt', section: 'Clothing', kind: 'color', color: '#424242', index: 1 },
    ],
    BackgroundColor: [
      { value: 1, tab: 'BG', section: 'Background', kind: 'color', color: '#E5E5E5', index: 0 },
      { value: 6, tab: 'BG', section: 'Background', kind: 'color', color: '#9069CD', index: 1 },
    ],
    FacialHair: [
      { value: 0, tab: 'Beard', section: 'Facial hair', kind: 'feature', index: 0 },
      { value: 1, tab: 'Beard', section: 'Facial hair', kind: 'feature', index: 1 },
    ],
    FacialHairColor: [
      { value: 1, tab: 'Beard', section: 'Facial hair color', kind: 'color', color: '#434343', index: 0 },
    ],
    Headwear: [
      { value: 0, tab: 'Hat', section: 'Headwear', kind: 'feature', index: 0 },
      { value: 10, tab: 'Hat', section: 'Headwear', kind: 'feature', index: 1 },
    ],
    Expression: [
      { value: 1, tab: 'Eyes', section: 'Expression', kind: 'feature', index: 0 },
      { value: 31, tab: 'Eyes', section: 'Expression', kind: 'feature', index: 1 },
    ],
    MainHair: [
      { value: 58, tab: 'Hair', section: 'Hairstyle', kind: 'feature', index: 0 },
      { value: 48, tab: 'Hair', section: 'Hairstyle', kind: 'feature', index: 1 },
    ],
    MainHairColor: [
      { value: 1, tab: 'Hair', section: 'Main hair color', kind: 'color', color: '#3D3D3D', index: 0 },
    ],
    Glasses: [
      { value: 0, tab: 'Face', section: 'Glasses', kind: 'feature', index: 0 },
      { value: 1, tab: 'Face', section: 'Glasses', kind: 'feature', index: 1 },
    ],
    GlassesColor: [
      { value: 1, tab: 'Face', section: 'Glasses color', kind: 'color', color: '#1453A3', index: 0 },
      { value: 2, tab: 'Face', section: 'Glasses color', kind: 'color', color: '#9069CD', index: 1 },
    ],
  },
};
TEST_CATALOG.semanticOptions = [
  sem({ state: 'Body', value: 5, group: 'body', tags: ['body_5', 'silhouette'] }),
  sem({ state: 'ClothingColor', value: 9, group: 'clothing_color', tags: ['dark', 'black', 'color'], kind: 'color', color: '#424242' }),
  sem({ state: 'BackgroundColor', value: 6, group: 'background_color', tags: ['purple', 'color'], kind: 'color', color: '#9069CD' }),
  sem({ state: 'FacialHair', value: 1, group: 'facial_hair', tags: ['mustache', 'short', 'classic'] }),
  sem({ state: 'FacialHairColor', value: 1, group: 'facial_hair_color', tags: ['dark', 'black'], kind: 'color', color: '#434343', requires: [{ state: 'FacialHair', notValue: 0 }] }),
  sem({ state: 'Headwear', value: 10, group: 'headwear', tags: ['hat', 'bowler_like', 'brimmed_hat'] }),
  sem({ state: 'Expression', value: 31, group: 'expression', tags: ['serious', 'stern'] }),
  sem({ state: 'MainHair', value: 48, group: 'main_hair', tags: ['short_hair', 'receding_hair'] }),
  sem({ state: 'MainHairColor', value: 1, group: 'main_hair_color', tags: ['dark', 'black'], kind: 'color', color: '#3D3D3D' }),
  sem({ state: 'Glasses', value: 1, group: 'glasses', tags: ['glasses', 'round_glasses'] }),
  sem({ state: 'GlassesColor', value: 2, group: 'glasses_color', tags: ['purple'], kind: 'color', color: '#9069CD', requires: [{ state: 'Glasses', notValue: 0 }] }),
];

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
          selectionIntent: [
            { group: 'body', tags: ['body_5'], required: false },
            { group: 'background_color', tags: ['purple'], required: true },
            ...(result.extraChanges || []),
          ],
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

async function generateAvatar(env, {
  prompt = '@current make a purple avatar',
  contextMode = 'current',
  baselineState = { Body: 1, BackgroundColor: 1 },
  catalog = TEST_CATALOG,
} = {}) {
  const sessionToken = await createSession(env);
  const response = await fetchWorker('/api/avatar/generate', {
    method: 'POST',
    headers: {
      Origin: 'http://127.0.0.1:8775',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      prompt,
      contextMode,
      baselineState,
      sessionToken,
      catalog,
    }),
  }, env);
  const events = await readSse(response);
  return {
    response,
    events,
    final: events.find((item) => item.event === 'final')?.data,
  };
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
    const { response, events, final } = await generateAvatar(env);

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
    assert.ok(Array.isArray(final.selectionTrace));
    assert.deepEqual(final.selectionTrace.map((item) => item.matchedOptionId), ['Body:5', 'BackgroundColor:6']);
    assert.equal(ai.calls.length, 2);
    assert.equal(ai.calls[0].input.response_format.type, 'json_schema');
    assert.ok(ai.calls[0].input.response_format.json_schema.required.includes('selectionIntent'));
    assert.equal(ai.calls[0].input.response_format.json_schema.properties.avatarState, undefined);
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
    assert.equal(invalidCatalogBody.error, 'semantic_catalog_required');
    assert.equal(ai.calls.length, 0);
  });

  it('requires semantic catalog and matching source version before generation', async () => {
    const ai = makeAiMock();
    const env = testEnv({ AI: ai });
    const baseBody = {
      prompt: 'green hoodie',
      sessionToken: 'unused-session',
    };

    const missingCatalog = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(baseBody),
    }, env);
    const missingCatalogBody = await missingCatalog.json();
    assert.equal(missingCatalog.status, 400);
    assert.equal(missingCatalogBody.error, 'semantic_catalog_required');

    const emptySemanticCatalog = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...baseBody,
        catalog: { ...TEST_CATALOG, semanticOptions: [] },
      }),
    }, env);
    const emptySemanticCatalogBody = await emptySemanticCatalog.json();
    assert.equal(emptySemanticCatalog.status, 400);
    assert.equal(emptySemanticCatalogBody.error, 'semantic_catalog_required');

    const mismatchedCatalog = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...baseBody,
        catalog: { ...TEST_CATALOG, configSourceVersion: 'other-rive' },
      }),
    }, env);
    const mismatchedCatalogBody = await mismatchedCatalog.json();
    assert.equal(mismatchedCatalog.status, 400);
    assert.equal(mismatchedCatalogBody.error, 'semantic_catalog_version_mismatch');
    assert.equal(ai.calls.length, 0);
  });

  it('filters dirty semantic model output before sending final payload', async () => {
    const dirtyWarnings = Array.from({ length: 12 }, (_, index) => `dirty warning ${index + 1}`);
    const ai = makeAiMock({
      response: {
        summary: 'Dirty model output still produced valid edits.',
        confidence: 1.5,
        selectionIntent: [
          { group: 'body', tags: ['body_5', 'unsupported_tag'], required: true },
          { group: 'background_color', tags: ['purple'], required: true },
          { group: 'glasses_color', tags: ['purple'], required: true },
          { group: 'unknown_group', tags: ['dark'], required: true },
          { group: 'clothing_color', tags: ['unsupported_tag'], required: true },
        ],
        warnings: dirtyWarnings,
      },
    });
    const env = testEnv({ AI: ai });
    const { response, final } = await generateAvatar(env);

    assert.equal(response.status, 200);
    assert.equal(final.ok, true);
    assert.deepEqual(final.avatarState, { Body: 5, BackgroundColor: 6 });
    assert.equal(final.confidence, 1);
    assert.equal(final.usedFallback, false);
    assert.ok(final.warnings.length <= 10);
    assert.ok(final.warnings.some((warning) => warning.includes('glasses_color')));
    assert.equal(final.avatarState.GlassesColor, undefined);
    assert.ok(final.steps.every((step) => step.startsWith('Open ')));
    assert.deepEqual(final.selectionTrace.map((item) => item.state), ['Body', 'BackgroundColor']);
  });

  it('does not treat no-op default traits as successful visible edits', async () => {
    const ai = makeAiMock({
      response: {
        summary: 'The model selected an option that is already active.',
        confidence: 0.9,
        selectionIntent: [
          { group: 'body', tags: ['body_5'], required: true },
        ],
        warnings: [],
      },
    });
    const env = testEnv({ AI: ai });
    const { response, final } = await generateAvatar(env, {
      prompt: '@current make a dark avatar',
      baselineState: { Body: 5, ClothingColor: 1 },
    });

    assert.equal(response.status, 200);
    assert.equal(final.ok, true);
    assert.equal(final.usedFallback, true);
    assert.deepEqual(final.avatarState, { ClothingColor: 9 });
    assert.deepEqual(final.selectionTrace.map((item) => item.matchedOptionId), ['ClothingColor:9']);
  });

  it('does not treat dependency-only glasses color as a successful visible edit', async () => {
    const ai = makeAiMock({
      response: {
        summary: 'Only a glasses color was selected.',
        confidence: 0.88,
        selectionIntent: [
          { group: 'glasses_color', tags: ['purple'], required: true },
        ],
        warnings: [],
      },
    });
    const env = testEnv({ AI: ai });
    const { response, final } = await generateAvatar(env, {
      prompt: '@current make purple glasses',
      baselineState: { Glasses: 0, GlassesColor: 1 },
    });

    assert.equal(response.status, 200);
    assert.equal(final.ok, true);
    assert.equal(final.usedFallback, true);
    assert.equal(final.avatarState.GlassesColor, undefined);
    assert.equal(final.avatarState.Glasses, 1);
    assert.deepEqual(final.selectionTrace.map((item) => item.matchedOptionId), ['Glasses:1']);
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
    const { response, final } = await generateAvatar(env, {
      prompt: 'make a dark avatar',
      baselineState: { Body: 1, BackgroundColor: 1 },
    });

    assert.equal(response.status, 200);
    assert.equal(final.ok, true);
    assert.ok(Object.keys(final.avatarState).length > 0);
    assert.ok(final.steps.length > 0);
    assert.equal(final.usedFallback, true);
    assert.ok(final.warnings.some((warning) => warning.includes('Structured semantic output failed')));
  });

  it('maps mocked Chaplin traits to visible semantic avatar edits', async () => {
    const ai = makeAiMock({
      response: {
        summary: 'Chaplin-like visual traits.',
        confidence: 0.86,
        selectionIntent: [
          { group: 'facial_hair', tags: ['mustache'], required: true },
          { group: 'facial_hair_color', tags: ['dark'], required: true },
          { group: 'headwear', tags: ['bowler_like', 'hat'], required: true },
          { group: 'clothing_color', tags: ['dark'], required: true },
        ],
        warnings: [],
      },
    });
    const env = testEnv({ AI: ai });
    const { response, final } = await generateAvatar(env, {
      prompt: '生成一个卓别林 @default',
      contextMode: 'default',
      baselineState: {
        FacialHair: 0,
        FacialHairColor: 1,
        Headwear: 0,
        ClothingColor: 1,
      },
    });

    assert.equal(response.status, 200);
    assert.equal(final.ok, true);
    assert.equal(final.usedFallback, false);
    assert.deepEqual(final.avatarState, {
      FacialHair: 1,
      Headwear: 10,
      ClothingColor: 9,
    });
    assert.deepEqual(final.selectionTrace.map((item) => item.matchedOptionId), [
      'FacialHair:1',
      'Headwear:10',
      'ClothingColor:9',
    ]);
    assert.ok(final.selectionTrace.every((item) => item.reason.includes('matched tags')));
  });

  it('maps mocked Stalin traits to visible semantic avatar edits', async () => {
    const ai = makeAiMock({
      response: {
        summary: 'Stalin-like visual traits.',
        confidence: 0.84,
        selectionIntent: [
          { group: 'main_hair', tags: ['short_hair', 'receding_hair'], required: true },
          { group: 'main_hair_color', tags: ['dark'], required: true },
          { group: 'facial_hair', tags: ['mustache'], required: true },
          { group: 'facial_hair_color', tags: ['dark'], required: true },
          { group: 'expression', tags: ['serious'], required: true },
          { group: 'clothing_color', tags: ['dark'], required: true },
        ],
        warnings: [],
      },
    });
    const env = testEnv({ AI: ai });
    const { response, final } = await generateAvatar(env, {
      prompt: '生成一个斯大林 @default',
      contextMode: 'default',
      baselineState: {
        MainHair: 58,
        MainHairColor: 1,
        FacialHair: 0,
        FacialHairColor: 1,
        Expression: 1,
        ClothingColor: 1,
      },
    });

    assert.equal(response.status, 200);
    assert.equal(final.ok, true);
    assert.equal(final.usedFallback, false);
    assert.deepEqual(final.avatarState, {
      MainHair: 48,
      FacialHair: 1,
      Expression: 31,
      ClothingColor: 9,
    });
    assert.deepEqual(final.selectionTrace.map((item) => item.matchedOptionId), [
      'MainHair:48',
      'FacialHair:1',
      'Expression:31',
      'ClothingColor:9',
    ]);
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
    assert.deepEqual(clean.selectionTrace, []);
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
