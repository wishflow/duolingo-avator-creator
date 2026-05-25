const SERVICE_NAME = 'duolingo-avator-creator';
const SERVICE_VERSION = '0.1.0';

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
        avatarGeneration: false,
        llmProxy: false,
      },
      endpoints: {
        avatarGenerate: '/api/avatar/generate',
      },
    });
  }

  if (url.pathname === '/api/avatar/generate') {
    if (request.method !== 'POST') return methodNotAllowed(request, ['POST', 'OPTIONS']);
    return jsonResponse(request, {
      ok: false,
      error: 'not_implemented',
      message: 'Avatar generation API is not implemented yet.',
    }, 501);
  }

  return jsonResponse(request, {
    ok: false,
    error: 'not_found',
  }, 404);
}

export default {
  fetch: handleRequest,
};

export { handleRequest, isAllowedOrigin };
