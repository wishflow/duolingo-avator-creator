import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import worker from '../worker/index.js';

const API_URL = 'https://duolingo-avator-creator.wei-shi-ws.workers.dev';

async function fetchWorker(path, init = {}) {
  const request = new Request(`${API_URL}${path}`, init);
  return worker.fetch(request, {
    SERVICE_NAME: 'duolingo-avator-creator',
    SERVICE_VERSION: 'test',
  });
}

describe('Cloudflare Worker API skeleton', () => {
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

  it('returns public API config', async () => {
    const response = await fetchWorker('/api/config', {
      headers: { Origin: 'https://duolingo-avator-creator.pages.dev' },
    });
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.apiVersion, 'v1');
    assert.equal(body.features.avatarGeneration, false);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'https://duolingo-avator-creator.pages.dev');
  });

  it('keeps avatar generation as an explicit placeholder', async () => {
    const response = await fetchWorker('/api/avatar/generate', {
      method: 'POST',
      headers: {
        Origin: 'http://127.0.0.1:8775',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ prompt: 'green hoodie' }),
    });
    const body = await response.json();

    assert.equal(response.status, 501);
    assert.equal(body.ok, false);
    assert.equal(body.error, 'not_implemented');
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'http://127.0.0.1:8775');
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
