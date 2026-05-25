import { z } from 'zod';

const SERVICE_NAME = 'duolingo-avator-creator';
const SERVICE_VERSION = '0.3.0';
const DEFAULT_TEXT_MODEL = '@cf/meta/llama-3.1-8b-instruct-fast';
const MAX_PROMPT_LENGTH = 800;
const MAX_CATALOG_OPTIONS = 420;
const AI_SESSION_TTL_SECONDS = 30 * 60;

type AvatarValue = number | boolean;
type AvatarState = Record<string, AvatarValue>;
type ContextMode = 'current' | 'default';
type CatalogOption = {
  value: AvatarValue;
  tab: string;
  section: string;
  kind: string;
  color?: string;
  index?: number;
};
type SemanticRequirement = {
  state: string;
  notValue?: AvatarValue;
};
type SemanticOption = CatalogOption & {
  optionId: string;
  state: string;
  group: string;
  tags: string[];
  confidence: number;
  visible: boolean;
  needsReview: boolean;
  requires: SemanticRequirement[];
  statesToOverride: AvatarState;
};
type AvatarCatalog = {
  semanticVersion?: number;
  sourceVersion?: string;
  configSourceVersion?: string;
  states: Record<string, CatalogOption[]>;
  semanticOptions: SemanticOption[];
};
type SelectionTrace = {
  trait: string;
  matchedOptionId: string;
  state: string;
  value: AvatarValue;
  score: number;
  reason: string;
};
type SanitizedModelResult = {
  avatarState: AvatarState;
  steps: string[];
  summary: string;
  confidence: number;
  warnings: string[];
  selectionTrace: SelectionTrace[];
};
type EditableAvatarResult = SanitizedModelResult & {
  usedFallback: boolean;
};
type TraitIntent = {
  group: string;
  tags: string[];
  color?: string;
  required: boolean;
};
type SanitizedTraitResult = {
  summary: string;
  confidence: number;
  selectionIntent: TraitIntent[];
  warnings: string[];
};
type ValidatedGenerationRequest = {
  prompt: string;
  contextMode: ContextMode;
  baselineState: AvatarState;
  catalog: AvatarCatalog;
  sessionToken: string;
};
type JsonError = 'invalid_content_type' | 'invalid_json';
type RuntimeEnv = Partial<Env> & {
  AI?: Ai;
  AI_SESSION_SECRET?: string;
  AI_SESSION_TTL_SECONDS?: string | number;
  MAX_PROMPT_LENGTH?: string | number;
  TURNSTILE_TEST_RESULT?: string;
};
type SseEvent = 'status' | 'final' | 'plan_delta' | 'error';
type EnqueueSse = (event: SseEvent, data: unknown) => void;

const avatarValueSchema = z.union([z.number().finite(), z.boolean()]);
const avatarStateSchema = z.record(z.string(), avatarValueSchema);
const catalogStatesSchema = z.object({
  states: z.record(z.string().min(1), z.array(z.unknown())),
}).passthrough();
const semanticRequirementSchema = z.object({
  state: z.string(),
  notValue: avatarValueSchema.optional(),
}).passthrough();
const catalogOptionSchema = z.object({
  value: avatarValueSchema,
  tab: z.unknown().optional(),
  section: z.unknown().optional(),
  kind: z.unknown().optional(),
  color: z.unknown().optional(),
  index: z.unknown().optional(),
}).passthrough();
const semanticOptionSchema = catalogOptionSchema.extend({
  optionId: z.string().min(1),
  state: z.string().min(1),
  group: z.string().min(1),
  tags: z.array(z.string().min(1)).min(1),
  confidence: z.number().min(0).max(1),
  visible: z.boolean(),
  needsReview: z.boolean(),
  requires: z.array(semanticRequirementSchema).optional(),
  statesToOverride: avatarStateSchema.optional(),
}).passthrough();
const modelChangeSchema = z.object({
  state: z.unknown().optional(),
  value: z.unknown().optional(),
  valueNumber: z.unknown().optional(),
  valueBoolean: z.unknown().optional(),
}).passthrough();
const modelResultSchema = z.object({
  avatarState: z.unknown().optional(),
  steps: z.unknown().optional(),
  summary: z.unknown().optional(),
  confidence: z.unknown().optional(),
  warnings: z.unknown().optional(),
}).passthrough();
const modelTraitIntentSchema = z.object({
  group: z.unknown().optional(),
  tags: z.unknown().optional(),
  color: z.unknown().optional(),
  required: z.unknown().optional(),
}).passthrough();
const modelTraitResultSchema = z.object({
  summary: z.unknown().optional(),
  confidence: z.unknown().optional(),
  targetTraits: z.unknown().optional(),
  selectionIntent: z.unknown().optional(),
  warnings: z.unknown().optional(),
}).passthrough();
const sessionRequestSchema = z.object({
  turnstileToken: z.string().trim().min(1),
}).passthrough();
const generationRequestSchema = z.object({
  prompt: z.unknown().optional(),
  contextMode: z.unknown().optional(),
  baselineState: z.unknown().optional(),
  catalog: z.unknown().optional(),
  sessionToken: z.unknown().optional(),
}).passthrough();
const turnstileResponseSchema = z.object({
  success: z.boolean().optional(),
  'error-codes': z.array(z.string()).optional(),
}).passthrough();
const sessionPayloadSchema = z.object({
  iss: z.string(),
  iat: z.number().finite(),
  exp: z.number().finite(),
  origin: z.string(),
});
const sseFinalPayloadSchema = z.object({
  ok: z.literal(true),
  contextMode: z.enum(['current', 'default']),
  model: z.string(),
  avatarState: avatarStateSchema,
  steps: z.array(z.string()),
  summary: z.string(),
  confidence: z.number().min(0).max(1),
  warnings: z.array(z.string()),
  usedFallback: z.boolean(),
  selectionTrace: z.array(z.object({
    trait: z.string(),
    matchedOptionId: z.string(),
    state: z.string(),
    value: avatarValueSchema,
    score: z.number(),
    reason: z.string(),
  })),
}).strict();

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

const ALLOWED_ORIGINS = new Set([
  'https://wishflow.github.io',
  'https://duolingo-avator-creator.pages.dev',
]);
const LOCAL_DEV_ORIGIN_PATTERN = new RegExp('^http://(localhost|127\\.0\\.0\\.1)(:\\d+)?$');

function isAllowedOrigin(origin: string | null): boolean {
  if (!origin) return false;
  if (ALLOWED_ORIGINS.has(origin)) return true;
  return LOCAL_DEV_ORIGIN_PATTERN.test(origin);
}

function corsHeaders(request: Request): Headers {
  const origin = request.headers.get('Origin');
  const headers = new Headers({
    'Vary': 'Origin',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Max-Age': '86400',
  });
  if (isAllowedOrigin(origin)) {
    headers.set('Access-Control-Allow-Origin', origin || '');
  }
  return headers;
}

function jsonResponse(request: Request, body: unknown, status = 200): Response {
  const headers = corsHeaders(request);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  return new Response(JSON.stringify(body), { status, headers });
}

function sseHeaders(request: Request): Headers {
  const headers = corsHeaders(request);
  headers.set('Content-Type', 'text/event-stream; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  headers.set('Connection', 'keep-alive');
  return headers;
}

function methodNotAllowed(request: Request, allowedMethods: string[]): Response {
  const headers = corsHeaders(request);
  headers.set('Allow', allowedMethods.join(', '));
  headers.set('Content-Type', 'application/json; charset=utf-8');
  return new Response(JSON.stringify({
    ok: false,
    error: 'method_not_allowed',
    allowedMethods,
  }), { status: 405, headers });
}

function getServiceName(env: RuntimeEnv): string {
  return env?.SERVICE_NAME || SERVICE_NAME;
}

function getServiceVersion(env: RuntimeEnv): string {
  return env?.SERVICE_VERSION || SERVICE_VERSION;
}

function getTextModel(env: RuntimeEnv): string {
  return env?.AI_TEXT_MODEL || DEFAULT_TEXT_MODEL;
}

function getTurnstileSiteKey(env: RuntimeEnv): string {
  return env?.TURNSTILE_SITE_KEY || '';
}

function getMaxPromptLength(env: RuntimeEnv): number {
  const configured = Number(env?.MAX_PROMPT_LENGTH || MAX_PROMPT_LENGTH);
  return Number.isFinite(configured) ? Math.min(Math.max(configured, 80), 2000) : MAX_PROMPT_LENGTH;
}

function getAiSessionTtlSeconds(env: RuntimeEnv): number {
  const configured = Number(env?.AI_SESSION_TTL_SECONDS || AI_SESSION_TTL_SECONDS);
  return Number.isFinite(configured) ? Math.min(Math.max(configured, 60), 24 * 60 * 60) : AI_SESSION_TTL_SECONDS;
}

function normalizePrompt(value: unknown, maxLength: number): string {
  if (typeof value !== 'string') return '';
  return value.replace(/\s+/g, ' ').trim().slice(0, maxLength + 1);
}

function normalizeContextMode(value: unknown): ContextMode {
  if (value === 'current' || value === 'default') return value;
  return 'default';
}

function cleanStateSnapshot(value: unknown): AvatarState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const clean: AvatarState = {};
  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw === 'number' && Number.isFinite(raw)) clean[key] = raw;
    if (typeof raw === 'boolean') clean[key] = raw;
  }
  return clean;
}

function getSemanticCatalogError(catalog: unknown): 'semantic_catalog_required' | 'semantic_catalog_version_mismatch' | null {
  if (!catalog || typeof catalog !== 'object' || Array.isArray(catalog)) return 'semantic_catalog_required';
  const raw = catalog as Record<string, unknown>;
  if (raw.semanticVersion !== 1) return 'semantic_catalog_required';
  if (!Array.isArray(raw.semanticOptions) || !raw.semanticOptions.length) return 'semantic_catalog_required';
  const sourceVersion = typeof raw.sourceVersion === 'string' ? raw.sourceVersion : '';
  const configSourceVersion = typeof raw.configSourceVersion === 'string' ? raw.configSourceVersion : '';
  if (!sourceVersion || !configSourceVersion || sourceVersion !== configSourceVersion) {
    return 'semantic_catalog_version_mismatch';
  }
  return null;
}

function normalizeCatalog(catalog: unknown): AvatarCatalog | null {
  const parsedCatalog = catalogStatesSchema.safeParse(catalog);
  if (!parsedCatalog.success) return null;
  const { states } = parsedCatalog.data;
  const rawCatalog = catalog && typeof catalog === 'object' && !Array.isArray(catalog)
    ? catalog as Record<string, unknown>
    : {};

  const normalized: AvatarCatalog['states'] = {};
  let optionCount = 0;
  for (const [stateName, options] of Object.entries(states)) {
    if (!stateName || optionCount >= MAX_CATALOG_OPTIONS) continue;
    const cleanOptions: CatalogOption[] = [];
    const seen = new Set<string>();
    for (const rawOption of options) {
      if (optionCount >= MAX_CATALOG_OPTIONS) break;
      const parsedOption = catalogOptionSchema.safeParse(rawOption);
      if (!parsedOption.success) continue;
      const option = parsedOption.data;
      const value = option.value;
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

  const semanticOptions: SemanticOption[] = [];
  const rawSemanticOptions = Array.isArray(rawCatalog.semanticOptions) ? rawCatalog.semanticOptions : [];
  const allowedValues = buildAllowedValues({ states: normalized, semanticOptions: [] });
  for (const rawOption of rawSemanticOptions) {
    const parsed = semanticOptionSchema.safeParse(rawOption);
    if (!parsed.success) continue;
    const option = parsed.data;
    if (!isAllowedStateValue(allowedValues, option.state, option.value)) continue;
    semanticOptions.push({
      value: option.value,
      tab: String(option.tab || '').slice(0, 40),
      section: String(option.section || '').slice(0, 60),
      kind: String(option.kind || '').slice(0, 20),
      color: typeof option.color === 'string' ? option.color.slice(0, 20) : undefined,
      index: Number.isFinite(Number(option.index)) ? Number(option.index) : undefined,
      optionId: option.optionId.slice(0, 80),
      state: option.state,
      group: option.group.slice(0, 48),
      tags: option.tags.map((tag) => tag.slice(0, 48)).slice(0, 16),
      confidence: option.confidence,
      visible: option.visible,
      needsReview: option.needsReview,
      requires: (option.requires || []).map((item) => ({
        state: item.state,
        notValue: item.notValue,
      })).slice(0, 4),
      statesToOverride: cleanStateSnapshot(option.statesToOverride || { [option.state]: option.value }),
    });
    if (semanticOptions.length >= MAX_CATALOG_OPTIONS) break;
  }

  return Object.keys(normalized).length ? {
    semanticVersion: Number(rawCatalog.semanticVersion),
    sourceVersion: typeof rawCatalog.sourceVersion === 'string' ? rawCatalog.sourceVersion : undefined,
    configSourceVersion: typeof rawCatalog.configSourceVersion === 'string' ? rawCatalog.configSourceVersion : undefined,
    states: normalized,
    semanticOptions,
  } : null;
}

function buildAllowedValues(catalog: AvatarCatalog): Map<string, Set<string>> {
  const allowed = new Map<string, Set<string>>();
  for (const [stateName, options] of Object.entries(catalog.states)) {
    const values = new Set<string>();
    for (const option of options) values.add(`${typeof option.value}:${option.value}`);
    allowed.set(stateName, values);
  }
  return allowed;
}

function isAllowedStateValue(allowed: Map<string, Set<string>>, stateName: string, value: AvatarValue): boolean {
  return allowed.get(stateName)?.has(`${typeof value}:${value}`) || false;
}

function sanitizeModelResult(rawResult: unknown, catalog: AvatarCatalog): SanitizedModelResult {
  const allowed = buildAllowedValues(catalog);
  const warnings: string[] = [];
  const avatarState: AvatarState = {};

  const result = modelResultSchema.safeParse(rawResult).success
    ? modelResultSchema.parse(rawResult)
    : {};
  const changes = Array.isArray(result.avatarState)
    ? result.avatarState
    : avatarStateSchema.safeParse(result.avatarState).success
      ? Object.entries(avatarStateSchema.parse(result.avatarState)).map(([state, value]) => ({ state, value }))
      : [];

  for (const rawChange of changes) {
    const parsedChange = modelChangeSchema.safeParse(rawChange);
    if (!parsedChange.success) continue;
    const change = parsedChange.data;
    const stateName = typeof change.state === 'string' ? change.state : '';
    let value: unknown = change.value;
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
    selectionTrace: [],
  };
}

function parseJsonModeResponse(response: unknown): unknown {
  const value = response && typeof response === 'object' && 'response' in response
    ? response.response
    : response;
  if (typeof value === 'string') return JSON.parse(value);
  return value;
}

function avatarJsonSchema(catalog: AvatarCatalog): Record<string, unknown> {
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

function traitJsonSchema(catalog: AvatarCatalog): Record<string, unknown> {
  const groups = [...new Set(catalog.semanticOptions.map((option) => option.group))].sort();
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      summary: { type: 'string' },
      confidence: { type: 'number', minimum: 0, maximum: 1 },
      targetTraits: {
        type: 'object',
        additionalProperties: {
          oneOf: [
            { type: 'string' },
            { type: 'array', items: { type: 'string' } },
          ],
        },
      },
      selectionIntent: {
        type: 'array',
        items: {
          type: 'object',
          additionalProperties: false,
          properties: {
            group: { type: 'string', enum: groups },
            tags: { type: 'array', items: { type: 'string' }, minItems: 1 },
            color: { type: 'string' },
            required: { type: 'boolean' },
          },
          required: ['group', 'tags'],
        },
      },
      warnings: {
        type: 'array',
        items: { type: 'string' },
      },
    },
    required: ['summary', 'confidence', 'selectionIntent', 'warnings'],
  };
}

function buildTraitCatalog(catalog: AvatarCatalog): Record<string, string[]> {
  const groups: Record<string, Set<string>> = {};
  for (const option of catalog.semanticOptions) {
    if (!option.visible || option.needsReview) continue;
    groups[option.group] ||= new Set<string>();
    for (const tag of option.tags) groups[option.group].add(tag);
  }
  const result: Record<string, string[]> = {};
  for (const [group, tags] of Object.entries(groups)) {
    result[group] = [...tags].sort().slice(0, 80);
  }
  return result;
}

function buildExplanationMessages({ prompt, contextMode, result }: {
  prompt: string;
  contextMode: ContextMode;
  result: EditableAvatarResult;
}): Array<{ role: string; content: string }> {
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

function buildTraitMessages({ prompt, contextMode, baselineState, catalog }: ValidatedGenerationRequest): Array<{ role: string; content: string }> {
  return [
    {
      role: 'system',
      content: [
        'You convert an avatar request into visual target traits for a Duolingo-style avatar editor.',
        'Do not choose raw option numbers, state names, or state values.',
        'Use only groups and tags from the supplied semantic taxonomy.',
        'For real or fictional people, infer a small set of recognizable visual traits, but treat the result as a stylized approximation.',
        'Prefer visible traits such as facial hair, headwear, hair shape, expression, clothing color, background color, glasses, wrinkles, and skin tone.',
        'Do not output traits for unavailable or unsupported details.',
      ].join(' '),
    },
    {
      role: 'user',
      content: JSON.stringify({
        prompt,
        contextMode,
        baselineState,
        semanticTaxonomy: buildTraitCatalog(catalog),
        outputRules: {
          selectionIntent: 'Array of { group, tags, required }. Tags must come from semanticTaxonomy[group].',
          targetTraits: 'Optional human-readable trait map using the same groups and tags.',
          warnings: 'Mention approximation limits or traits that cannot be represented.',
        },
      }),
    },
  ];
}

function sanitizeTraitResult(rawResult: unknown, catalog: AvatarCatalog): SanitizedTraitResult {
  const taxonomy = buildTraitCatalog(catalog);
  const result = modelTraitResultSchema.safeParse(rawResult).success
    ? modelTraitResultSchema.parse(rawResult)
    : {};
  const intents: TraitIntent[] = [];
  const addIntent = (rawGroup: unknown, rawTags: unknown, rawRequired: unknown, rawColor?: unknown) => {
    const group = typeof rawGroup === 'string' ? rawGroup : '';
    if (!group || !taxonomy[group]) return;
    const tags = (Array.isArray(rawTags) ? rawTags : [rawTags])
      .map((tag) => String(tag || '').trim())
      .filter((tag) => taxonomy[group].includes(tag))
      .slice(0, 8);
    if (!tags.length) return;
    intents.push({
      group,
      tags,
      color: typeof rawColor === 'string' ? rawColor.slice(0, 40) : undefined,
      required: rawRequired === true,
    });
  };

  if (Array.isArray(result.selectionIntent)) {
    for (const rawIntent of result.selectionIntent) {
      const parsed = modelTraitIntentSchema.safeParse(rawIntent);
      if (!parsed.success) continue;
      addIntent(parsed.data.group, parsed.data.tags, parsed.data.required, parsed.data.color);
    }
  }

  if (!intents.length && result.targetTraits && typeof result.targetTraits === 'object' && !Array.isArray(result.targetTraits)) {
    for (const [group, rawTags] of Object.entries(result.targetTraits as Record<string, unknown>)) {
      addIntent(group, rawTags, true);
    }
  }

  const warnings = Array.isArray(result.warnings)
    ? result.warnings.map((warning) => String(warning).trim()).filter(Boolean).slice(0, 8)
    : [];

  return {
    summary: String(result.summary || '').trim().slice(0, 280),
    confidence: Math.max(0, Math.min(1, Number(result.confidence ?? 0.55))),
    selectionIntent: intents.slice(0, 12),
    warnings,
  };
}

function encodeSse(event: SseEvent, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function streamFromString(value: string): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller: ReadableStreamDefaultController<Uint8Array>) {
      controller.enqueue(new TextEncoder().encode(value));
      controller.close();
    },
  });
}

function parseAiStreamPayload(payload: string): string {
  if (!payload || payload === '[DONE]') return '';
  try {
    const parsed = z.record(z.string(), z.unknown()).parse(JSON.parse(payload));
    const choices = Array.isArray(parsed.choices) ? parsed.choices : [];
    const firstChoice = choices[0] && typeof choices[0] === 'object' ? choices[0] as Record<string, unknown> : {};
    const delta = firstChoice.delta && typeof firstChoice.delta === 'object' ? firstChoice.delta as Record<string, unknown> : {};
    return (typeof parsed.response === 'string' && parsed.response)
      || (typeof parsed.text === 'string' && parsed.text)
      || (typeof parsed.delta === 'string' && parsed.delta)
      || (typeof delta.content === 'string' && delta.content)
      || (typeof firstChoice.text === 'string' && firstChoice.text)
      || '';
  } catch (_) {
    return payload;
  }
}

async function pipeAiPlanStream(aiStream: unknown, enqueue: EnqueueSse): Promise<void> {
  const stream = typeof aiStream === 'string' ? streamFromString(aiStream) : aiStream;
  if (!(stream instanceof ReadableStream)) return;
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

async function verifyTurnstile(request: Request, token: string, env: RuntimeEnv): Promise<{ success: boolean; errors: string[] }> {
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
  const body = turnstileResponseSchema.safeParse(await response.json().catch(() => ({}))).data || {};
  return {
    success: !!body.success,
    errors: Array.isArray(body['error-codes']) ? body['error-codes'] : [],
  };
}

function toBase64(binary: string): string {
  return btoa(binary);
}

function fromBase64(value: string): string {
  return atob(value);
}

function bytesToBase64url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return toBase64(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function base64urlToBytes(value: string): Uint8Array {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  const binary = fromBase64(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function stringToBase64url(value: string): string {
  return bytesToBase64url(new TextEncoder().encode(value));
}

function base64urlToString(value: string): string {
  return new TextDecoder().decode(base64urlToBytes(value));
}

function getAiSessionSecret(env: RuntimeEnv): string {
  return env?.AI_SESSION_SECRET || env?.TURNSTILE_SECRET_KEY || '';
}

async function signSessionPayload(payloadPart: string, env: RuntimeEnv): Promise<string> {
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

async function createAiSessionToken(request: Request, env: RuntimeEnv): Promise<{ sessionToken: string; expiresAt: number; ttlSeconds: number }> {
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

async function verifyAiSessionToken(request: Request, token: unknown, env: RuntimeEnv): Promise<{
  success: true;
  payload: z.infer<typeof sessionPayloadSchema>;
} | {
  success: false;
  error: 'session_required' | 'session_invalid' | 'session_expired' | 'session_origin_mismatch';
}> {
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
    const payload = sessionPayloadSchema.parse(JSON.parse(base64urlToString(parts[0])));
    const now = Math.floor(Date.now() / 1000);
    if (!payload || payload.exp <= now) return { success: false, error: 'session_expired' };
    if (payload.origin !== request.headers.get('Origin')) return { success: false, error: 'session_origin_mismatch' };
    if (payload.iss !== getServiceName(env)) return { success: false, error: 'session_invalid' };
    return { success: true, payload };
  } catch (_) {
    return { success: false, error: 'session_invalid' };
  }
}

function optionsForState(catalog: AvatarCatalog, stateName: string): CatalogOption[] {
  return catalog.states[stateName] || [];
}

function chooseOption(
  catalog: AvatarCatalog,
  baselineState: AvatarState,
  stateName: string,
  predicate: (option: CatalogOption) => boolean = () => true,
): CatalogOption | null {
  const options = optionsForState(catalog, stateName);
  return options.find((option) => predicate(option) && baselineState[stateName] !== option.value)
    || options.find(predicate)
    || null;
}

function chooseOptionByRatio(catalog: AvatarCatalog, baselineState: AvatarState, stateName: string, ratio: number): CatalogOption | null {
  const options = optionsForState(catalog, stateName);
  if (!options.length) return null;
  const index = Math.max(0, Math.min(options.length - 1, Math.round((options.length - 1) * ratio)));
  const preferred = options[index];
  if (preferred && baselineState[stateName] !== preferred.value) return preferred;
  return chooseOption(catalog, baselineState, stateName);
}

function parseHexColor(hex: unknown): { r: number; g: number; b: number } | null {
  const match = String(hex || '').match(/^#?([0-9a-f]{6})$/i);
  if (!match) return null;
  const value = Number.parseInt(match[1], 16);
  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255,
  };
}

function colorLuminance(option: CatalogOption): number {
  const rgb = parseHexColor(option.color);
  if (!rgb) return 1;
  return (0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b) / 255;
}

function colorDistance(option: CatalogOption, targetHex: string): number {
  const rgb = parseHexColor(option.color);
  const target = parseHexColor(targetHex);
  if (!rgb || !target) return Number.POSITIVE_INFINITY;
  return ((rgb.r - target.r) ** 2) + ((rgb.g - target.g) ** 2) + ((rgb.b - target.b) ** 2);
}

function chooseDarkColor(catalog: AvatarCatalog, baselineState: AvatarState, stateName: string): CatalogOption | null {
  return [...optionsForState(catalog, stateName)]
    .filter((option) => option.color && baselineState[stateName] !== option.value)
    .sort((a, b) => colorLuminance(a) - colorLuminance(b))[0]
    || chooseOption(catalog, baselineState, stateName, (option) => !!option.color);
}

function chooseClosestColor(catalog: AvatarCatalog, baselineState: AvatarState, stateName: string, targetHex: string): CatalogOption | null {
  return [...optionsForState(catalog, stateName)]
    .filter((option) => option.color && baselineState[stateName] !== option.value)
    .sort((a, b) => colorDistance(a, targetHex) - colorDistance(b, targetHex))[0]
    || chooseOption(catalog, baselineState, stateName, (option) => !!option.color);
}

function requirementMet(requirement: SemanticRequirement, baselineState: AvatarState, avatarState: AvatarState): boolean {
  const value = avatarState[requirement.state] ?? baselineState[requirement.state];
  if (requirement.notValue !== undefined) return value !== undefined && value !== requirement.notValue;
  return value !== undefined;
}

function scoreSemanticOption(intent: TraitIntent, option: SemanticOption, baselineState: AvatarState, avatarState: AvatarState): number {
  if (!option.visible || option.needsReview) return -1;
  if (option.group !== intent.group) return -1;
  if (baselineState[option.state] === option.value || avatarState[option.state] === option.value) return -1;
  if (option.requires.some((requirement) => !requirementMet(requirement, baselineState, avatarState))) return -1;
  const matchedTags = intent.tags.filter((tag) => option.tags.includes(tag));
  if (!matchedTags.length) return -1;
  const requiredWeight = intent.required ? 0.1 : 0;
  return matchedTags.length + option.confidence + requiredWeight;
}

function buildSelectionTrace(intent: TraitIntent, option: SemanticOption, score: number): SelectionTrace {
  const matchedTags = intent.tags.filter((tag) => option.tags.includes(tag));
  return {
    trait: `${intent.group}:${intent.tags.join('+')}`,
    matchedOptionId: option.optionId,
    state: option.state,
    value: option.value,
    score: Number(score.toFixed(3)),
    reason: `matched tags: ${matchedTags.join(', ')}`,
  };
}

function applySemanticOption(avatarState: AvatarState, option: SemanticOption): void {
  avatarState[option.state] = option.value;
}

function buildAvatarStateFromTraits(result: SanitizedTraitResult, validated: ValidatedGenerationRequest): {
  avatarState: AvatarState;
  selectionTrace: SelectionTrace[];
  warnings: string[];
} {
  const { baselineState, catalog } = validated;
  const avatarState: AvatarState = {};
  const selectionTrace: SelectionTrace[] = [];
  const warnings = [...result.warnings];
  const orderedIntents = [...result.selectionIntent].sort((a, b) => {
    const aRequires = catalog.semanticOptions.some((option) => option.group === a.group && option.requires.length > 0) ? 1 : 0;
    const bRequires = catalog.semanticOptions.some((option) => option.group === b.group && option.requires.length > 0) ? 1 : 0;
    return aRequires - bRequires;
  });

  for (const intent of orderedIntents) {
    let best: { option: SemanticOption; score: number } | null = null;
    for (const option of catalog.semanticOptions) {
      const score = scoreSemanticOption(intent, option, baselineState, avatarState);
      if (score < 0) continue;
      if (!best || score > best.score) best = { option, score };
    }
    if (!best) {
      if (intent.required) warnings.push(`No visible supported option matched ${intent.group}: ${intent.tags.join(', ')}.`);
      continue;
    }
    applySemanticOption(avatarState, best.option);
    selectionTrace.push(buildSelectionTrace(intent, best.option, best.score));
  }

  return {
    avatarState: removeNoopChanges(avatarState, baselineState),
    selectionTrace,
    warnings: warnings.slice(0, 10),
  };
}

function buildTraitFallback(validated: ValidatedGenerationRequest, warning?: string): SanitizedTraitResult {
  const lower = validated.prompt.toLowerCase();
  const intents: TraitIntent[] = [];
  const add = (group: string, tags: string[], required = false) => {
    intents.push({ group, tags, required });
  };
  if (/black|dark|深|黑/.test(lower)) {
    add('clothing_color', ['dark'], true);
    add('background_color', ['dark'], false);
  }
  if (/white|light|浅|白/.test(lower)) add('clothing_color', ['light'], true);
  if (/mustache|moustache|beard|facial hair|胡子|胡须|小胡子/.test(lower)) {
    add('facial_hair', ['mustache'], true);
    add('facial_hair_color', ['dark'], false);
  }
  if (/hat|cap|headwear|帽/.test(lower)) add('headwear', ['hat'], true);
  if (/glasses|spectacles|眼镜/.test(lower)) add('glasses', ['glasses'], true);
  if (/serious|stern|严肃|威严/.test(lower)) add('expression', ['serious'], false);
  if (/smile|happy|开心|微笑/.test(lower)) add('expression', ['smile'], false);
  if (!intents.length) {
    add('clothing_color', ['dark'], true);
    add('background_color', ['blue'], false);
  }
  return {
    summary: warning || 'Used deterministic target traits where model semantics were uncertain.',
    confidence: 0.42,
    selectionIntent: intents,
    warnings: warning ? [warning] : ['Used deterministic target traits where model semantics were uncertain.'],
  };
}

function buildStepsFromAvatarState(avatarState: AvatarState, catalog: AvatarCatalog): string[] {
  return Object.entries(avatarState).map(([stateName, value]) => {
    const option = optionsForState(catalog, stateName).find((item) => item.value === value);
    const tab = option?.tab || stateName;
    const section = option?.section || stateName;
    const optionLabel = typeof option?.index === 'number' && Number.isFinite(option.index)
      ? `option ${option.index + 1}`
      : 'the matching option';
    if (option?.kind === 'color' && option.color) {
      return `Open ${tab}, find ${section}, then choose the ${option.color} color swatch (${optionLabel}).`;
    }
    return `Open ${tab}, find ${section}, then choose ${optionLabel}.`;
  }).slice(0, 12);
}

function summarizeAvatarState(avatarState: AvatarState): string {
  const states = Object.keys(avatarState);
  if (!states.length) return 'No editable avatar changes were produced.';
  return `Applied ${states.length} editable avatar choices: ${states.join(', ')}.`;
}

function buildFallbackResult(validated: ValidatedGenerationRequest, warning?: string): EditableAvatarResult {
  const { catalog } = validated;
  const traitResult = buildTraitFallback(validated, warning);
  const built = buildAvatarStateFromTraits(traitResult, validated);
  const avatarState = built.avatarState;
  const warnings = built.warnings.length ? built.warnings : traitResult.warnings;

  return {
    avatarState,
    steps: buildStepsFromAvatarState(avatarState, catalog),
    summary: summarizeAvatarState(avatarState),
    confidence: traitResult.confidence,
    warnings: warnings.slice(0, 10),
    selectionTrace: built.selectionTrace,
    usedFallback: true,
  };
}

function removeNoopChanges(avatarState: AvatarState, baselineState: AvatarState): AvatarState {
  const clean: AvatarState = {};
  for (const [stateName, value] of Object.entries(avatarState || {})) {
    if (baselineState[stateName] !== value) clean[stateName] = value;
  }
  return clean;
}

function completeStructuredResult(
  result: SanitizedModelResult,
  validated: ValidatedGenerationRequest,
  warning?: string,
): EditableAvatarResult {
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
    selectionTrace: result.selectionTrace || [],
    usedFallback: false,
  };
}

async function buildEditableAvatarResult(
  validated: ValidatedGenerationRequest,
  env: RuntimeEnv & { AI: Ai },
  model: string,
): Promise<EditableAvatarResult> {
  try {
    const structured = await env.AI.run(model, {
      messages: buildTraitMessages(validated),
      max_tokens: 900,
      temperature: 0.2,
      response_format: {
        type: 'json_schema',
        json_schema: traitJsonSchema(validated.catalog),
      },
    });
    const parsedResult = parseJsonModeResponse(structured);
    const safeResult = sanitizeTraitResult(parsedResult, validated.catalog);
    const built = buildAvatarStateFromTraits(safeResult, validated);
    if (!Object.keys(built.avatarState).length) {
      return buildFallbackResult(validated, 'Model returned no visible semantic matches, so deterministic target traits were used.');
    }
    return {
      avatarState: built.avatarState,
      steps: buildStepsFromAvatarState(built.avatarState, validated.catalog),
      summary: safeResult.summary || summarizeAvatarState(built.avatarState),
      confidence: safeResult.confidence,
      warnings: built.warnings,
      selectionTrace: built.selectionTrace,
      usedFallback: false,
    };
  } catch (error) {
    return buildFallbackResult(
      validated,
      `Structured semantic output failed, so deterministic target traits were used: ${getErrorMessage(error, 'unknown error')}.`,
    );
  }
}

async function readJsonBody(request: Request): Promise<{ body: unknown } | { error: JsonError }> {
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

function validateGenerationRequest(request: Request, body: unknown, env: RuntimeEnv): ValidatedGenerationRequest | {
  status: number;
  body: { ok: false; error: string; maxPromptLength?: number };
} {
  if (!isAllowedOrigin(request.headers.get('Origin'))) {
    return { status: 403, body: { ok: false, error: 'origin_not_allowed' } };
  }
  if (!env?.AI) {
    return { status: 503, body: { ok: false, error: 'ai_not_configured' } };
  }
  if (!env?.TURNSTILE_SECRET_KEY || !getTurnstileSiteKey(env)) {
    return { status: 503, body: { ok: false, error: 'turnstile_not_configured' } };
  }

  const parsedRequest = generationRequestSchema.safeParse(body);
  const parsedBody = parsedRequest.success ? parsedRequest.data : {};
  const maxPromptLength = getMaxPromptLength(env);
  const prompt = normalizePrompt(parsedBody.prompt, maxPromptLength);
  if (!prompt) return { status: 400, body: { ok: false, error: 'prompt_required' } };
  if (prompt.length > maxPromptLength) return { status: 400, body: { ok: false, error: 'prompt_too_long', maxPromptLength } };
  if (typeof parsedBody.sessionToken !== 'string' || !parsedBody.sessionToken.trim()) {
    return { status: 401, body: { ok: false, error: 'session_required' } };
  }

  const semanticError = getSemanticCatalogError(parsedBody.catalog);
  if (semanticError) return { status: 400, body: { ok: false, error: semanticError } };

  const catalog = normalizeCatalog(parsedBody.catalog);
  if (!catalog) return { status: 400, body: { ok: false, error: 'catalog_required' } };

  return {
    prompt,
    contextMode: normalizeContextMode(parsedBody.contextMode),
    baselineState: cleanStateSnapshot(parsedBody.baselineState),
    catalog,
    sessionToken: parsedBody.sessionToken.trim(),
  };
}

async function handleAvatarSession(request: Request, env: RuntimeEnv): Promise<Response> {
  if (!isAllowedOrigin(request.headers.get('Origin'))) {
    return jsonResponse(request, { ok: false, error: 'origin_not_allowed' }, 403);
  }
  if (!env?.TURNSTILE_SECRET_KEY || !getTurnstileSiteKey(env)) {
    return jsonResponse(request, { ok: false, error: 'turnstile_not_configured' }, 503);
  }

  const parsed = await readJsonBody(request);
  if ('error' in parsed) return jsonResponse(request, { ok: false, error: parsed.error }, 400);
  const sessionRequest = sessionRequestSchema.safeParse(parsed.body);
  if (!sessionRequest.success) return jsonResponse(request, { ok: false, error: 'turnstile_token_required' }, 400);
  const token = sessionRequest.data.turnstileToken;

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

function hasConfiguredAi(env: RuntimeEnv): env is RuntimeEnv & { AI: Ai } {
  return !!env.AI;
}

async function handleAvatarGenerate(request: Request, env: RuntimeEnv): Promise<Response> {
  const parsed = await readJsonBody(request);
  if ('error' in parsed) return jsonResponse(request, { ok: false, error: parsed.error }, 400);

  const validated = validateGenerationRequest(request, parsed.body, env);
  if ('status' in validated) return jsonResponse(request, validated.body, validated.status);
  if (!hasConfiguredAi(env)) return jsonResponse(request, { ok: false, error: 'ai_not_configured' }, 503);

  const session = await verifyAiSessionToken(request, validated.sessionToken, env);
  if (!session.success) {
    return jsonResponse(request, {
      ok: false,
      error: session.error,
    }, session.error === 'session_required' ? 401 : 403);
  }

  const encoder = new TextEncoder();
  const model = getTextModel(env);
  const body = new ReadableStream<Uint8Array>({
    async start(controller: ReadableStreamDefaultController<Uint8Array>) {
      const enqueue: EnqueueSse = (event, data) => controller.enqueue(encoder.encode(encodeSse(event, data)));
      try {
        enqueue('status', { message: 'Building editable avatar configuration...' });
        const safeResult = await buildEditableAvatarResult(validated, env, model);
        const finalPayload = sseFinalPayloadSchema.parse({
          ok: true,
          contextMode: validated.contextMode,
          model: 'workers-ai',
          ...safeResult,
        });
        enqueue('final', finalPayload);

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
          message: getErrorMessage(error, 'Avatar generation failed.'),
        });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(body, { status: 200, headers: sseHeaders(request) });
}

async function handleRequest(request: Request, env: RuntimeEnv = {}): Promise<Response> {
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
} satisfies ExportedHandler<RuntimeEnv>;

export {
  buildFallbackResult,
  createAiSessionToken,
  handleRequest,
  isAllowedOrigin,
  normalizeCatalog,
  sanitizeModelResult,
  verifyAiSessionToken,
};
