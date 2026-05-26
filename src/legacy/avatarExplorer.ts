import * as riveRuntime from '@rive-app/canvas';
import wasmUrl from '@rive-app/canvas/rive.wasm?url';
import fallbackWasmUrl from '@rive-app/canvas/rive_fallback.wasm?url';

const runtimeGlobal = window as any;
riveRuntime.RuntimeLoader.setWasmUrl(wasmUrl);
riveRuntime.RuntimeLoader.setWasmFallbackUrl(fallbackWasmUrl);
runtimeGlobal.rive = riveRuntime;

// ===================== STATE =====================
let riveInst = null;
let sharedRiveFile = null;
let smNames = [];
let currentSM = '';
let triggerInput = null;
let fireTimeout = null;
let builderConfig = null;
let currentInputValues = {};
let stateMachineInputs = {};
let riveBuffer = null;
let tileInstances = new Map();
let dirtyTabs = new Set();
let currentTabIdx = 0;
let tileDrawPending = false;
let bgColorMap = {};
let defaultInputValues = {};
let hasAvatarChanges = false;
let statusTimer = null;
let historyReady = false;
let historyApplying = false;
let avatarHistory = { past: [], future: [] };
let aiGenerating = false;
let turnstileWidgetId = null;
let turnstileToken = '';
let aiSession = null;
let aiPinnedStatus = '';
let aiFinalReceived = false;
let suppressTurnstileCallbacks = false;
let mentionRange = null;
let semanticCatalog = null;
let semanticCatalogStatus = { ready: false, error: 'semantic_catalog_loading' };
let captureCanvas = null;
let captureRiveInst = null;
let captureRivePromise = null;

const STORAGE_KEY = 'duolingoAvatarCreator.avatarState.v1';
const HISTORY_KEY = 'duolingoAvatarCreator.avatarHistory.v1';
const AI_SESSION_KEY = 'duolingoAvatarCreator.aiSession.v1';
const HISTORY_LIMIT = 30;
const API_BASE_URL = 'https://duolingo-avator-creator.wei-shi-ws.workers.dev';
const SUPPORTED_MENTIONS = ['current', 'default'];
let backendConfig = {
  baseUrl: API_BASE_URL,
  available: false,
  config: null,
};
window.avatarBackend = backendConfig;
window.avatarGenerationDebug = { lastFinal: null };

const TAB_DEFS = [
  { icon: 'avatar_builder_body_unselected_dark.svg', label: 'Body', idx: 0 },
  { icon: 'avatar_builder_face_unselected_dark.svg', label: 'Eyes', idx: 1 },
  { icon: 'avatar_builder_hair_unselected_dark.svg', label: 'Hair', idx: 2 },
  { icon: 'avatar_builder_face_details_unselected_dark.svg', label: 'Face', idx: 3 },
  { icon: 'avatar_builder_facial_hair_unselected_dark.svg', label: 'Beard', idx: 4 },
  { icon: 'avatar_builder_headwear_unselected_dark.svg', label: 'Hat', idx: 5 },
  { icon: 'avatar_builder_tshirt_unselected_dark.svg', label: 'Shirt', idx: 6 },
  { icon: 'avatar_builder_background_unselected_dark.svg', label: 'BG', idx: 7 },
];

const canvas = document.getElementById('riveCanvas');
const previewPanel = document.getElementById('previewPanel');
const exportCanvas = document.getElementById('exportCanvas');
const tabBar = document.getElementById('tabBar');
const tabContent = document.getElementById('tabContent');
const loadingOverlay = document.getElementById('loadingOverlay');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const thumbStatus = document.getElementById('thumbStatus');
const generateContent = document.getElementById('generateContent');
const aiPrompt = document.getElementById('aiPrompt');
const mentionMenu = document.getElementById('mentionMenu');
const aiStatus = document.getElementById('aiStatus');
const aiStream = document.getElementById('aiStream');
const aiResult = document.getElementById('aiResult');
const aiSteps = document.getElementById('aiSteps');
const aiWarnings = document.getElementById('aiWarnings');
const generateBtn = document.getElementById('generateBtn');
const verifyAiBtn = document.getElementById('verifyAiBtn');
const aiMiniPreview = document.getElementById('aiMiniPreview');
const turnstileContainer = document.getElementById('turnstileContainer');
const undoBtn = document.getElementById('undoBtn');
const redoBtn = document.getElementById('redoBtn');

if (verifyAiBtn) verifyAiBtn.remove();

// ===================== TRIGGER =====================
function scheduleTrigger() {
  if (!triggerInput) return;
  if (fireTimeout) clearTimeout(fireTimeout);
  fireTimeout = setTimeout(() => { triggerInput.fire(); fireTimeout = null; }, 100);
}

// ===================== SHARED RIVEFILE =====================
async function createSharedRiveFile(buffer) {
  const ab = new Uint8Array(buffer);
  const riveFile = new window.rive.RiveFile({
    buffer: ab,
    enableRiveAssetCDN: false,
  });
  await riveFile.init();
  return riveFile;
}

// ===================== MAIN RIVE =====================
async function loadRiveFile(buffer) {
  riveBuffer = buffer;

  // Clean up old state
  if (riveInst) { try { riveInst.cleanup(); } catch(e) {} riveInst = null; }
  if (captureRiveInst) { try { captureRiveInst.cleanup(); } catch(e) {} captureRiveInst = null; }
  captureRivePromise = null;
  destroyAllTileInstances();
  smNames = []; currentSM = ''; stateMachineInputs = {}; currentInputValues = {};
  defaultInputValues = {}; hasAvatarChanges = false;
  historyReady = false; historyApplying = false; avatarHistory = { past: [], future: [] };
  sharedRiveFile = null;

  try {
    sharedRiveFile = await createSharedRiveFile(buffer);
  } catch(e) {
    console.error('RiveFile init error:', e);
    loadingOverlay.classList.add('hidden');
    return;
  }

  const Rive = window.rive?.Rive;
  const Layout = window.rive?.Layout;
  const Fit = window.rive?.Fit;
  const Alignment = window.rive?.Alignment;
  if (!Rive) return;

  riveInst = new Rive({
    layout: Layout && Fit && Alignment ? new Layout({ fit: Fit.Cover, alignment: Alignment.Center }) : undefined,
    canvas, riveFile: sharedRiveFile, autoplay: false,
    onLoad: () => onMainLoaded(),
    onLoadError: (err) => console.error('Rive error:', err),
  });
}

function onMainLoaded() {
  if (!riveInst) return;
  const ab = riveInst.riveFile.file.defaultArtboard();
  smNames = [];
  for (let i = 0; i < ab.stateMachineCount(); i++) smNames.push(ab.stateMachineByIndex(i).name);
  setStatus('Ready', 'ok');

  riveInst.play(smNames);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      selectStateMachine('SMAvatar');
      applyConfigDefaults();
      applySavedAvatarState();
      loadAvatarHistory();
      historyReady = true;
      updateHistoryButtons();
      renderUI();
      handleRoute();
      loadingOverlay.classList.add('hidden');
    });
  });
}

function selectStateMachine(name) {
  if (!riveInst || !name) return;
  currentSM = name;
  const inputs = riveInst.stateMachineInputs(name);
  if (!inputs) return;

  stateMachineInputs = {}; currentInputValues = {}; triggerInput = null;
  for (const inp of inputs) {
    stateMachineInputs[inp.name] = inp;
    if (inp.type === 58) { if (inp.name === 'bounce_trig') triggerInput = inp; }
    else currentInputValues[inp.name] = inp.value;
  }
  updateBackground();
}

// ===================== TILE RIVE INSTANCES =====================
function createTileInstance(canvas, fb) {
  return new Promise((resolve) => {
    const Layout = window.rive?.Layout;
    const Fit = window.rive?.Fit;
    const Alignment = window.rive?.Alignment;
    const layout = Layout && Fit && Alignment
      ? new Layout({ fit: Fit.Cover, alignment: Alignment.Center })
      : undefined;

    const instance = new window.rive.Rive({
      canvas: canvas,
      riveFile: sharedRiveFile,
      layout: layout,
      autoplay: false,
      stateMachines: 'SMAvatar',
      onLoad: () => {
        const inputs = instance.stateMachineInputs('SMAvatar');
        if (!inputs) { resolve(instance); return; }
        instance._inputs = inputs;

        // Build lookup map in one pass, also find trigger
        const inputMap = Object.create(null);
        let trig = null;
        for (const inp of inputs) {
          inputMap[inp.name] = inp;
          if (inp.type === 58 && inp.name === 'bounce_trig') trig = inp;
        }

        // Set baseline: all currentInputValues
        for (const inp of inputs) {
          if ((inp.type === 56 || inp.type === 59) && currentInputValues[inp.name] !== undefined) {
            if (inp.type === 56) inp.value = currentInputValues[inp.name];
            else inp.value = !!currentInputValues[inp.name];
          }
        }

        // Apply featureButton overrides (O(1) lookup via map)
        for (const [key, val] of Object.entries(fb.statesToOverride)) {
          const inp = inputMap[key];
          if (!inp) continue;
          if (inp.type === 56) inp.value = val;
          else if (inp.type === 59) inp.value = !!val;
        }

        // Fire trigger + draw
        if (trig) trig.fire();
        instance.drawFrame();
        resolve(instance);
      },
      onLoadError: () => resolve(null),
    });
  });
}

function destroyTabInstances(tabIdx) {
  for (const [key, instance] of tileInstances) {
    if (key.startsWith(`${tabIdx}-`)) {
      try { instance.cleanup(); } catch(e) {}
      tileInstances.delete(key);
    }
  }
}

function destroyAllTileInstances() {
  for (const [, instance] of tileInstances) {
    try { instance.cleanup(); } catch(e) {}
  }
  tileInstances.clear();
}

function setStatus(text, state = 'ok', transient = false) {
  if (statusDot) statusDot.className = `dot ${state}`;
  if (statusText) statusText.textContent = text;
  if (statusTimer) {
    clearTimeout(statusTimer);
    statusTimer = null;
  }
  if (transient) {
    statusTimer = setTimeout(() => {
      if (statusDot) statusDot.className = 'dot ok';
      if (statusText) statusText.textContent = 'Ready';
      statusTimer = null;
    }, 1400);
  }
}

function updateTileInstancesForState(stateName, newValue) {
  for (const [key, instance] of tileInstances) {
    // Only update instances on the visible tab; others will be rebuilt lazily
    if (!key.startsWith(`${currentTabIdx}-`)) continue;
    const inputs = instance._inputs;
    if (!inputs) continue;
    let inp = null;
    for (const x of inputs) { if (x.name === stateName) { inp = x; break; } }
    if (!inp) continue;
    if (inp.type === 56) inp.value = newValue;
    else if (inp.type === 59) inp.value = !!newValue;
  }
  // Deduplicate rAF — only schedule one draw pass per frame
  if (tileDrawPending) return;
  tileDrawPending = true;
  requestAnimationFrame(() => {
    tileDrawPending = false;
    for (const [key, instance] of tileInstances) {
      if (!key.startsWith(`${currentTabIdx}-`)) continue;
      try { instance.drawFrame(); } catch(e) {}
    }
  });
}

async function renderTabTiles(tabIdx) {
  if (!sharedRiveFile || !builderConfig) return;

  // If tab already has live instances and isn't dirty, nothing to do
  if (hasActiveTabInstances(tabIdx) && !dirtyTabs.has(tabIdx)) return;

  // Only destroy old instances if this tab is dirty (state changed)
  if (dirtyTabs.has(tabIdx)) {
    destroyTabInstances(tabIdx);
  }

  const panels = [...tabContent.querySelectorAll('.tab-panel')];
  const panel = panels[tabIdx];
  if (!panel) return;

  const tabs = builderConfig.avatarBuilderConfig.stateChooserTabs;
  const tab = tabs[tabIdx];
  if (!tab) return;

  const tileGrids = panel.querySelectorAll('.tile-grid');
  let gridIdx = 0;
  const workItems = [];

  for (const section of tab.sections) {
    if (section.buttonType !== 'FEATURE' || gridIdx >= tileGrids.length) continue;
    const grid = tileGrids[gridIdx];
    const tiles = grid.querySelectorAll('.tile');

    for (let i = 0; i < section.featureButtons.length; i++) {
      const tile = tiles[i];
      if (!tile) continue;
      const fb = section.featureButtons[i];

      // Find or create tile canvas
      let tileCanvas = tile.querySelector('canvas');
      if (!tileCanvas) {
        tileCanvas = document.createElement('canvas');
        tileCanvas.width = 252;
        tileCanvas.height = 252;
        tileCanvas.className = 'tile-canvas';
        tile.appendChild(tileCanvas);
        const ph = tile.querySelector('.tile-placeholder');
        if (ph) ph.style.display = 'none';
      }

      workItems.push({ key: `${tabIdx}-${gridIdx}-${i}`, tileCanvas, fb, tile });
    }
    gridIdx++;
  }

  if (workItems.length === 0) {
    dirtyTabs.delete(tabIdx);
    thumbStatus.textContent = '';
    return;
  }

  thumbStatus.textContent = `Loading... 0/${workItems.length}`;
  let done = 0;

  // Batch creation: 8 at a time, yield to browser between batches
  const BATCH_SIZE = 8;
  for (let i = 0; i < workItems.length; i += BATCH_SIZE) {
    const batch = workItems.slice(i, i + BATCH_SIZE);
    const results = await Promise.all(batch.map(async (w) => {
      const instance = await createTileInstance(w.tileCanvas, w.fb);
      return { ...w, instance };
    }));
    for (const r of results) {
      if (r.instance) {
        tileInstances.set(r.key, r.instance);
        r.tile.classList.remove('loading');
      }
      done++;
      thumbStatus.textContent = `Loading... ${done}/${workItems.length}`;
    }
    // Yield to browser between batches
    if (i + BATCH_SIZE < workItems.length) {
      await new Promise(r => setTimeout(r, 0));
    }
  }

  dirtyTabs.delete(tabIdx);
  thumbStatus.textContent = '';
}

// ===================== LOCAL STATE =====================
function getSerializableAvatarState() {
  const state = {};
  for (const [key, value] of Object.entries(currentInputValues)) {
    if (typeof value === 'number' || typeof value === 'boolean') state[key] = value;
  }
  return state;
}

function statesMatch(a, b) {
  const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
  for (const key of keys) {
    if (a?.[key] !== b?.[key]) return false;
  }
  return true;
}

function isDefaultAvatarState() {
  if (Object.keys(defaultInputValues).length === 0) return true;
  return statesMatch(getSerializableAvatarState(), defaultInputValues);
}

function markAllTabsDirty() {
  for (let i = 0; i < TAB_DEFS.length; i++) dirtyTabs.add(i);
}

function updateSaveStatus() {
  hasAvatarChanges = !isDefaultAvatarState();
  document.querySelectorAll('[data-save-status]').forEach((el) => {
    el.textContent = hasAvatarChanges
      ? 'Custom avatar saved on this device.'
      : 'Default avatar. No custom state is saved.';
  });
  if (hasAvatarChanges) setStatus('Saved locally', 'ok', true);
  else setStatus('Ready', 'ok');
}

function saveAvatarState() {
  if (Object.keys(defaultInputValues).length === 0) return;
  try {
    if (isDefaultAvatarState()) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        version: 1,
        state: getSerializableAvatarState(),
      }));
    }
  } catch(e) {}
  updateSaveStatus();
}

function loadSavedAvatarState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const state = parsed?.state;
    if (!state || typeof state !== 'object') return null;
    const clean = {};
    for (const [key, value] of Object.entries(state)) {
      if (typeof value === 'number' || typeof value === 'boolean') clean[key] = value;
    }
    return Object.keys(clean).length > 0 ? clean : null;
  } catch(e) {
    return null;
  }
}

function applyInputValue(name, value) {
  const inp = stateMachineInputs[name];
  if (!inp) return false;
  if (inp.type === 56 && typeof value === 'number') {
    inp.value = value;
    currentInputValues[name] = value;
    return true;
  }
  if (inp.type === 59 && typeof value === 'boolean') {
    inp.value = value;
    currentInputValues[name] = value;
    return true;
  }
  return false;
}

function cleanAvatarStateSnapshot(state) {
  const clean = {};
  if (!state || typeof state !== 'object') return clean;
  for (const [key, value] of Object.entries(state)) {
    if (!stateMachineInputs[key]) continue;
    if (typeof value === 'number' || typeof value === 'boolean') clean[key] = value;
  }
  return clean;
}

function cloneAvatarState(state) {
  return { ...cleanAvatarStateSnapshot(state) };
}

function loadAvatarHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    const past = Array.isArray(parsed?.past) ? parsed.past : [];
    const future = Array.isArray(parsed?.future) ? parsed.future : [];
    avatarHistory = {
      past: past.map(cleanAvatarStateSnapshot).filter(s => Object.keys(s).length).slice(-HISTORY_LIMIT),
      future: future.map(cleanAvatarStateSnapshot).filter(s => Object.keys(s).length).slice(0, HISTORY_LIMIT),
    };
  } catch(e) {
    avatarHistory = { past: [], future: [] };
  }
}

function persistAvatarHistory() {
  if (!historyReady || historyApplying) return;
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify({
      version: 1,
      past: avatarHistory.past.slice(-HISTORY_LIMIT),
      future: avatarHistory.future.slice(0, HISTORY_LIMIT),
    }));
  } catch(e) {}
  updateHistoryButtons();
}

function clearAvatarHistory() {
  avatarHistory = { past: [], future: [] };
  try { localStorage.removeItem(HISTORY_KEY); } catch(e) {}
  updateHistoryButtons();
}

function recordHistoryBeforeChange() {
  if (!historyReady || historyApplying) return;
  const current = cloneAvatarState(getSerializableAvatarState());
  const last = avatarHistory.past[avatarHistory.past.length - 1];
  if (last && statesMatch(last, current)) return;
  avatarHistory.past.push(current);
  if (avatarHistory.past.length > HISTORY_LIMIT) avatarHistory.past.shift();
  avatarHistory.future = [];
}

function commitAvatarMutation() {
  saveAvatarState();
  persistAvatarHistory();
  updateHistoryButtons();
}

function applyAvatarSnapshot(state, options = {}) {
  const clean = cleanAvatarStateSnapshot(state);
  let applied = false;
  historyApplying = true;
  for (const [name, value] of Object.entries(clean)) {
    if (applyInputValue(name, value)) applied = true;
  }
  historyApplying = false;
  if (!applied) return false;
  scheduleTrigger();
  updateBackground();
  destroyAllTileInstances();
  dirtyTabs.clear();
  markAllTabsDirty();
  refreshAllHighlights();
  if (!document.body.classList.contains('mode-generate')) renderTabTiles(currentTabIdx);
  if (options.save !== false) saveAvatarState();
  updateHistoryButtons();
  setTimeout(updateAiPreviewSnapshot, 180);
  return true;
}

function undoAvatarChange() {
  if (!avatarHistory.past.length) return;
  const current = cloneAvatarState(getSerializableAvatarState());
  const previous = avatarHistory.past.pop();
  avatarHistory.future.unshift(current);
  if (avatarHistory.future.length > HISTORY_LIMIT) avatarHistory.future.pop();
  applyAvatarSnapshot(previous);
  persistAvatarHistory();
}

function redoAvatarChange() {
  if (!avatarHistory.future.length) return;
  const current = cloneAvatarState(getSerializableAvatarState());
  const next = avatarHistory.future.shift();
  avatarHistory.past.push(current);
  if (avatarHistory.past.length > HISTORY_LIMIT) avatarHistory.past.shift();
  applyAvatarSnapshot(next);
  persistAvatarHistory();
}

function updateHistoryButtons() {
  if (undoBtn) undoBtn.disabled = avatarHistory.past.length === 0;
  if (redoBtn) redoBtn.disabled = avatarHistory.future.length === 0;
}

function applySavedAvatarState() {
  const saved = loadSavedAvatarState();
  if (!saved) {
    updateSaveStatus();
    return false;
  }
  let applied = false;
  for (const [name, value] of Object.entries(saved)) {
    if (applyInputValue(name, value)) applied = true;
  }
  if (!applied) {
    updateSaveStatus();
    return false;
  }
  scheduleTrigger();
  updateBackground();
  markAllTabsDirty();
  updateSaveStatus();
  return true;
}

function clearSavedAvatar() {
  try { localStorage.removeItem(STORAGE_KEY); } catch(e) {}
  clearAvatarHistory();
  resetAll({ record: false });
  try { localStorage.removeItem(STORAGE_KEY); } catch(e) {}
  clearAvatarHistory();
  updateSaveStatus();
}

function confirmResetAll() {
  if (!window.confirm('Reset avatar to default?')) return;
  resetAll();
}

function openFilePicker() {
  document.getElementById('fileInput')?.click();
}

function openMoreSheet() {
  const sheet = document.getElementById('moreSheet');
  if (!sheet) return;
  sheet.classList.add('open');
  sheet.setAttribute('aria-hidden', 'false');
}

function closeMoreSheet() {
  const sheet = document.getElementById('moreSheet');
  if (!sheet) return;
  sheet.classList.remove('open');
  sheet.setAttribute('aria-hidden', 'true');
}

function openTermsSheet() {
  const sheet = document.getElementById('termsSheet');
  if (!sheet) return;
  sheet.classList.add('open');
  sheet.setAttribute('aria-hidden', 'false');
}

function closeTermsSheet() {
  const sheet = document.getElementById('termsSheet');
  if (!sheet) return;
  sheet.classList.remove('open');
  sheet.setAttribute('aria-hidden', 'true');
}

function openGeneratePage() {
  if (window.location.hash !== '#generate') window.location.hash = 'generate';
  else showGeneratePage();
}

function showGeneratePage() {
  document.body.classList.add('mode-generate');
  if (generateContent) generateContent.hidden = false;
  updateAiPreviewSnapshot();
  updateAiControls();
  renderTurnstileIfNeeded();
}

function showEditorPage() {
  if (window.location.hash === '#generate') {
    history.pushState('', document.title, window.location.pathname + window.location.search);
  }
  document.body.classList.remove('mode-generate');
  if (generateContent) generateContent.hidden = true;
  switchTab(currentTabIdx || 0);
}

function handleRoute() {
  if (window.location.hash === '#generate') showGeneratePage();
  else showEditorPage();
}

function getGenerationConfig() {
  return backendConfig?.config?.generation || {};
}

function apiUrl(endpoint) {
  return String(endpoint || '').startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
}

function isAiConfigured() {
  return !!(
    backendConfig?.available
    && backendConfig?.config?.features?.avatarGeneration
    && getGenerationConfig().turnstileSiteKey
  );
}

function getConfigSourceVersion() {
  return builderConfig?.avatarBuilderConfig?.riveFileVersion || '';
}

function isSemanticCatalogReady() {
  return !!semanticCatalogStatus.ready;
}

function getSemanticCatalogMessage() {
  if (semanticCatalogStatus.ready) return '';
  if (semanticCatalogStatus.error === 'semantic_catalog_version_mismatch') {
    return 'Semantic catalog version mismatch. Regenerate the semantic catalog before using AI generation.';
  }
  if (semanticCatalogStatus.error === 'semantic_catalog_loading') {
    return 'Semantic catalog is loading.';
  }
  return 'Semantic catalog unavailable. Regenerate the semantic catalog before using AI generation.';
}

function getStoredAiSession() {
  try {
    const stored = JSON.parse(sessionStorage.getItem(AI_SESSION_KEY) || 'null');
    if (!stored || typeof stored.sessionToken !== 'string' || typeof stored.expiresAt !== 'number') return null;
    return stored;
  } catch(e) {
    return null;
  }
}

function hasValidAiSession() {
  const session = aiSession || getStoredAiSession();
  if (!session || !session.sessionToken || session.expiresAt <= Date.now() + 5000) {
    if (session?.sessionToken) resetTurnstileWidget();
    aiSession = null;
    try { sessionStorage.removeItem(AI_SESSION_KEY); } catch(e) {}
    return false;
  }
  aiSession = session;
  return true;
}

function getAiSessionToken() {
  return hasValidAiSession() ? aiSession.sessionToken : '';
}

function saveAiSession(session) {
  aiSession = session;
  try { sessionStorage.setItem(AI_SESSION_KEY, JSON.stringify(session)); } catch(e) {}
}

function clearAiSession() {
  aiSession = null;
  try { sessionStorage.removeItem(AI_SESSION_KEY); } catch(e) {}
}

function resetTurnstileWidget() {
  if (!window.turnstile || turnstileWidgetId === null) return;
  suppressTurnstileCallbacks = true;
  try { window.turnstile.reset(turnstileWidgetId); } catch(e) {}
  setTimeout(() => { suppressTurnstileCallbacks = false; }, 250);
}

function updateAiControls(message) {
  if (!generateBtn || !aiStatus) return;
  if (message) aiPinnedStatus = message;
  const configured = isAiConfigured();
  const semanticReady = isSemanticCatalogReady();
  const promptReady = !!aiPrompt?.value.trim();
  const tokenReady = !!turnstileToken;
  const sessionReady = hasValidAiSession();
  if (verifyAiBtn) {
    verifyAiBtn.hidden = true;
    verifyAiBtn.disabled = true;
  }
  generateBtn.disabled = aiGenerating || !configured || !semanticReady || !promptReady || !(sessionReady || tokenReady);
  if (message) {
    aiStatus.textContent = message;
  } else if (!configured) {
    aiStatus.textContent = 'AI generation is unavailable until the backend and Turnstile are configured.';
  } else if (!semanticReady) {
    aiStatus.textContent = getSemanticCatalogMessage();
  } else if (aiGenerating) {
    aiStatus.textContent = 'Generating editable avatar...';
  } else if (aiPinnedStatus) {
    aiStatus.textContent = aiPinnedStatus;
  } else if (!promptReady) {
    aiStatus.textContent = 'Describe the avatar to generate.';
  } else if (sessionReady) {
    aiStatus.textContent = 'Ready to generate.';
  } else if (tokenReady) {
    aiStatus.textContent = 'Ready to generate. Verification will run automatically.';
  } else {
    aiStatus.textContent = 'Complete the Turnstile check, then generate.';
  }
}

function updateAiPreviewSnapshot() {
  if (!aiMiniPreview || !canvas) return;
  try {
    aiMiniPreview.src = canvas.toDataURL('image/png');
  } catch(e) {}
}

function renderTurnstileIfNeeded() {
  if (!document.body.classList.contains('mode-generate')) return;
  if (window.__TEST_TURNSTILE_TOKEN__) {
    turnstileToken = window.__TEST_TURNSTILE_TOKEN__;
    if (turnstileContainer) turnstileContainer.textContent = 'Turnstile test token ready.';
    updateAiControls();
    return;
  }
  const siteKey = getGenerationConfig().turnstileSiteKey;
  if (!siteKey || !turnstileContainer) {
    updateAiControls();
    return;
  }
  if (!window.turnstile) {
    turnstileContainer.textContent = 'Loading verification...';
    setTimeout(renderTurnstileIfNeeded, 500);
    return;
  }
  if (turnstileWidgetId !== null) return;
  turnstileContainer.textContent = '';
  turnstileWidgetId = window.turnstile.render(turnstileContainer, {
    sitekey: siteKey,
    callback: (token) => {
      turnstileToken = token;
      aiPinnedStatus = '';
      updateAiControls();
    },
    'expired-callback': () => {
      if (suppressTurnstileCallbacks) return;
      turnstileToken = '';
      updateAiControls(hasValidAiSession() ? undefined : 'Turnstile expired. Complete it again before generating.');
    },
    'error-callback': () => {
      if (suppressTurnstileCallbacks) return;
      turnstileToken = '';
      updateAiControls(hasValidAiSession() ? undefined : 'Turnstile failed. Please try again.');
    },
  });
}

async function loadBackendConfig() {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/config`, {
      headers: { 'Accept': 'application/json' },
    });
    if (!resp.ok) return;
    backendConfig = {
      baseUrl: API_BASE_URL,
      available: true,
      config: await resp.json(),
    };
    window.avatarBackend = backendConfig;
    updateAiControls();
    renderTurnstileIfNeeded();
  } catch(e) {
    window.avatarBackend = backendConfig;
    updateAiControls();
  }
}

async function loadSemanticCatalog() {
  semanticCatalogStatus = { ready: false, error: 'semantic_catalog_loading' };
  try {
    const resp = await fetch('avatar_semantic_catalog.json', {
      headers: { 'Accept': 'application/json' },
    });
    if (!resp.ok) {
      semanticCatalog = null;
      semanticCatalogStatus = { ready: false, error: 'semantic_catalog_required' };
      updateAiControls();
      return;
    }
    const catalog = await resp.json();
    if (!catalog || catalog.semanticVersion !== 1 || !Array.isArray(catalog.options) || !catalog.options.length) {
      semanticCatalog = null;
      semanticCatalogStatus = { ready: false, error: 'semantic_catalog_required' };
      updateAiControls();
      return;
    }
    if (catalog.sourceVersion !== getConfigSourceVersion()) {
      semanticCatalog = catalog;
      semanticCatalogStatus = { ready: false, error: 'semantic_catalog_version_mismatch' };
      updateAiControls();
      return;
    }
    semanticCatalog = catalog;
    semanticCatalogStatus = { ready: true, error: '' };
    updateAiControls();
  } catch(e) {
    semanticCatalog = null;
    semanticCatalogStatus = { ready: false, error: 'semantic_catalog_required' };
    updateAiControls();
  }
}

window.addEventListener('beforeunload', (e) => {
  if (!hasAvatarChanges) return;
  e.preventDefault();
  e.returnValue = '';
});

// ===================== VALUE SETTING =====================
function findTabForState(stateName) {
  const tabs = builderConfig?.avatarBuilderConfig?.stateChooserTabs;
  if (!tabs) return -1;
  for (let i = 0; i < TAB_DEFS.length; i++) {
    const tab = tabs[i];
    if (!tab) continue;
    for (const section of tab.sections) {
      if (section.buttonType === 'FEATURE') {
        for (const fb of section.featureButtons) { if (fb.state === stateName) return i; }
      }
      if (section.buttonType === 'IMAGE') {
        for (const ib of section.imageButtons) { if (ib.state === stateName) return i; }
      }
    }
  }
  return -1;
}

function invalidateThumbnails(stateName) {
  if (!stateName) {
    for (let i = 0; i < TAB_DEFS.length; i++) dirtyTabs.add(i);
  } else {
    const changedTab = findTabForState(stateName);
    for (let i = 0; i < TAB_DEFS.length; i++) {
      if (i !== changedTab) dirtyTabs.add(i);
    }
    // Update current tab's live tile instances
    const val = currentInputValues[stateName];
    if (val !== undefined) updateTileInstancesForState(stateName, val);
  }
}

function setSMValue(name, value, options = {}) {
  const inp = stateMachineInputs[name];
  if (!inp) return;
  if (options.record !== false) recordHistoryBeforeChange();
  if (inp.type === 56) {
    inp.value = value;
    currentInputValues[name] = value;
  } else if (inp.type === 59) {
    const boolValue = !!value;
    inp.value = boolValue;
    currentInputValues[name] = boolValue;
  }
  invalidateThumbnails(name);
  if (options.save !== false) commitAvatarMutation();
}

function applyFeatureButton(fb) {
  const primaryState = fb.state;
  recordHistoryBeforeChange();
  for (const [key, val] of Object.entries(fb.statesToOverride)) {
    if (val === 0 && key !== primaryState) continue;
    setSMValue(key, val, { record: false, save: false });
  }
  commitAvatarMutation();
}

// ===================== BACKGROUND =====================
function updateBackground() {
  const bgVal = currentInputValues['BackgroundColor'];
  const hex = bgColorMap[bgVal] || bgColorMap[1] || '#E5E5E5';
  previewPanel.style.backgroundColor = hex;
  canvas.style.backgroundColor = hex;
}

function buildBgColorMap() {
  if (!builderConfig) return;
  const tabs = builderConfig.avatarBuilderConfig.stateChooserTabs;
  for (const tab of tabs) {
    for (const section of tab.sections) {
      if (section.buttonType === 'IMAGE') {
        for (const ib of section.imageButtons) {
          if (ib.state === 'BackgroundColor') bgColorMap[ib.value] = ib.color;
        }
      }
    }
  }
}

// ===================== AI GENERATION =====================
function buildAvatarCatalog() {
  const tabs = builderConfig?.avatarBuilderConfig?.stateChooserTabs || [];
  const states = {};
  const semanticById = new Map();
  for (const option of semanticCatalog?.options || []) {
    semanticById.set(`${option.state}:${option.value}`, option);
  }
  for (let tabIdx = 0; tabIdx < tabs.length; tabIdx++) {
    const tab = tabs[tabIdx];
    const tabLabel = TAB_DEFS.find(d => d.idx === tabIdx)?.label || `Tab ${tabIdx + 1}`;
    for (const section of tab.sections || []) {
      const sectionLabel = section.header || tabLabel;
      if (section.buttonType === 'IMAGE') {
        section.imageButtons.forEach((ib, index) => {
          if (!states[ib.state]) states[ib.state] = [];
          states[ib.state].push({
            value: ib.value,
            tab: tabLabel,
            section: sectionLabel,
            kind: 'color',
            color: ib.color,
            index,
            ...(semanticById.get(`${ib.state}:${ib.value}`) || {}),
          });
        });
      } else if (section.buttonType === 'FEATURE') {
        section.featureButtons.forEach((fb, index) => {
          if (!states[fb.state]) states[fb.state] = [];
          states[fb.state].push({
            value: fb.value,
            tab: tabLabel,
            section: sectionLabel,
            kind: 'feature',
            index,
            ...(semanticById.get(`${fb.state}:${fb.value}`) || {}),
          });
        });
      }
    }
  }
  return {
    semanticVersion: semanticCatalog?.semanticVersion,
    sourceVersion: semanticCatalog?.sourceVersion,
    configSourceVersion: getConfigSourceVersion(),
    states,
    semanticOptions: semanticCatalog?.options || [],
  };
}

function detectContextMode(prompt) {
  if (/\B@current\b/.test(prompt)) return 'current';
  if (/\B@default\b/.test(prompt)) return 'default';
  return 'default';
}

function getGenerationBaselineState(contextMode) {
  return contextMode === 'current'
    ? getSerializableAvatarState()
    : cloneAvatarState(defaultInputValues);
}

async function verifyAiSession() {
  if (aiGenerating) return;
  return ensureAiSessionToken({ showStatus: true });
}

async function requestAiSessionToken(token) {
  const endpoint = backendConfig?.config?.endpoints?.avatarSession || '/api/avatar/session';
  const response = await fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ turnstileToken: token }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.sessionToken) {
    throw new Error(body.message || body.error || `Verification failed with ${response.status}.`);
  }
  saveAiSession({
    sessionToken: body.sessionToken,
    expiresAt: Number(body.expiresAt || Date.now() + (body.ttlSeconds || 1800) * 1000),
  });
  turnstileToken = '';
  resetTurnstileWidget();
  return aiSession.sessionToken;
}

async function ensureAiSessionToken(options = {}) {
  if (!isAiConfigured()) {
    updateAiControls('AI generation is unavailable until the backend is configured.');
    return '';
  }
  const existingToken = getAiSessionToken();
  if (existingToken) return existingToken;

  const token = turnstileToken;
  if (!token) {
    updateAiControls('Complete the Turnstile check, then generate.');
    return '';
  }

  if (options.showStatus !== false) updateAiControls('Verifying before generation...');
  try {
    const sessionToken = await requestAiSessionToken(token);
    if (options.showStatus !== false) updateAiControls('Verified. Starting generation...');
    return sessionToken;
  } catch(e) {
    clearAiSession();
    turnstileToken = '';
    resetTurnstileWidget();
    updateAiControls(e.message || 'Verification failed. Please complete the Turnstile check and try again.');
    return '';
  }
}

function resetAiOutput() {
  if (aiStream) aiStream.textContent = 'Agent notes will appear here.';
  if (aiResult) aiResult.classList.remove('ready');
  if (aiSteps) aiSteps.innerHTML = '';
  if (aiWarnings) {
    aiWarnings.classList.remove('ready');
    aiWarnings.textContent = '';
  }
}

function appendAiStreamText(text) {
  if (!aiStream || !text) return;
  if (aiStream.textContent === 'Agent notes will appear here.') aiStream.textContent = '';
  aiStream.textContent += text;
}

function renderAiResult(result) {
  if (!aiResult || !aiSteps) return;
  aiSteps.innerHTML = '';
  for (const step of result.steps || []) {
    const li = document.createElement('li');
    li.textContent = step;
    aiSteps.appendChild(li);
  }
  if (aiWarnings) {
    const warnings = result.warnings || [];
    aiWarnings.textContent = warnings.length ? warnings.join(' ') : '';
    aiWarnings.classList.toggle('ready', warnings.length > 0);
  }
  aiResult.classList.add('ready');
}

function applyGeneratedAvatarState(state) {
  if (!state || typeof state !== 'object') return false;
  recordHistoryBeforeChange();
  let applied = false;
  for (const [name, value] of Object.entries(state)) {
    if (applyInputValue(name, value)) applied = true;
  }
  if (!applied) return false;
  scheduleTrigger();
  updateBackground();
  destroyAllTileInstances();
  dirtyTabs.clear();
  markAllTabsDirty();
  refreshAllHighlights();
  commitAvatarMutation();
  setTimeout(updateAiPreviewSnapshot, 180);
  return true;
}

function parseSseFrame(frame) {
  let event = 'message';
  const data = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    if (line.startsWith('data:')) data.push(line.slice(5).trim());
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join('\n')) };
  } catch(e) {
    return { event, data: { text: data.join('\n') } };
  }
}

async function readGenerationStream(response) {
  if (!response.body?.getReader) {
    const text = await response.text();
    for (const frame of text.trim().split('\n\n')) handleGenerationEvent(parseSseFrame(frame));
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split('\n\n');
    buffer = frames.pop() || '';
    for (const frame of frames) handleGenerationEvent(parseSseFrame(frame));
  }
  if (buffer.trim()) handleGenerationEvent(parseSseFrame(buffer.trim()));
}

function handleGenerationEvent(payload) {
  if (!payload) return;
  const { event, data } = payload;
  if (event === 'status' && !aiFinalReceived) updateAiControls(data.message);
  if (event === 'plan_delta') appendAiStreamText(data.text || '');
  if (event === 'final') {
    aiFinalReceived = true;
    window.avatarGenerationDebug.lastFinal = data;
    const applied = applyGeneratedAvatarState(data.avatarState);
    renderAiResult(data);
    updateAiControls(applied ? 'Generated avatar applied. You can keep editing.' : 'Generated result had no applicable changes.');
  }
  if (event === 'error') {
    throw new Error(data.message || data.error || 'Generation failed.');
  }
}

async function startAvatarGeneration() {
  if (aiGenerating || !aiPrompt) return;
  const prompt = aiPrompt.value.trim();
  if (!prompt) {
    updateAiControls('Describe the avatar first.');
    return;
  }
  if (!isAiConfigured()) {
    updateAiControls('AI generation is unavailable until the backend is configured.');
    return;
  }
  if (!isSemanticCatalogReady()) {
    updateAiControls(getSemanticCatalogMessage());
    return;
  }

  const contextMode = detectContextMode(prompt);
  aiGenerating = true;
  aiPinnedStatus = '';
  aiFinalReceived = false;
  updateAiControls('Preparing generation...');

  try {
    const sessionToken = await ensureAiSessionToken({ showStatus: true });
    if (!sessionToken) return;

    resetAiOutput();
    updateAiControls('Starting generation...');
    const endpoint = backendConfig?.config?.endpoints?.avatarGenerate || '/api/avatar/generate';
    const response = await fetch(apiUrl(endpoint), {
      method: 'POST',
      headers: {
        'Accept': 'text/event-stream',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt,
        contextMode,
        baselineState: getGenerationBaselineState(contextMode),
        catalog: buildAvatarCatalog(),
        sessionToken,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      if (/^session_/.test(body.error || '')) {
        clearAiSession();
        resetTurnstileWidget();
        throw new Error('Verification expired. Complete the Turnstile check, then click Generate again.');
      }
      if (/^semantic_catalog_/.test(body.error || '')) {
        throw new Error(getSemanticCatalogMessage());
      }
      throw new Error(body.message || body.error || `Generation failed with ${response.status}.`);
    }
    await readGenerationStream(response);
  } catch(e) {
    updateAiControls(e.message || 'Generation failed. Please try again later.');
  } finally {
    aiGenerating = false;
    updateAiControls(aiPinnedStatus || undefined);
  }
}

function getMentionRange(text, cursor) {
  const before = text.slice(0, cursor);
  const match = before.match(/(^|\s)@([a-zA-Z]*)$/);
  if (!match) return null;
  const start = cursor - match[0].trimStart().length;
  return { start, end: cursor, query: match[2].toLowerCase() };
}

function renderMentionMenu() {
  if (!aiPrompt || !mentionMenu) return;
  mentionRange = getMentionRange(aiPrompt.value, aiPrompt.selectionStart || 0);
  if (!mentionRange) {
    mentionMenu.classList.remove('open');
    return;
  }
  const options = SUPPORTED_MENTIONS.filter(name => name.startsWith(mentionRange.query));
  if (!options.length) {
    mentionMenu.classList.remove('open');
    return;
  }
  mentionMenu.innerHTML = '';
  for (const name of options) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'mention-option';
    btn.textContent = `@${name}`;
    btn.onclick = () => insertMention(name);
    mentionMenu.appendChild(btn);
  }
  mentionMenu.classList.add('open');
}

function insertMention(name) {
  if (!aiPrompt) return;
  const mention = `@${name}`;
  const start = mentionRange?.start ?? aiPrompt.selectionStart ?? aiPrompt.value.length;
  const end = mentionRange?.end ?? aiPrompt.selectionEnd ?? start;
  const before = aiPrompt.value.slice(0, start);
  const after = aiPrompt.value.slice(end);
  const prefix = before && !/\s$/.test(before) ? ' ' : '';
  const value = `${before}${prefix}${mention} ${after.replace(/^\s*/, '')}`;
  const cursor = (before + prefix + mention + ' ').length;
  aiPrompt.value = value;
  aiPrompt.focus();
  aiPrompt.setSelectionRange(cursor, cursor);
  mentionRange = null;
  mentionMenu?.classList.remove('open');
  updateAiControls();
}

// ===================== EXPORT =====================
function getCurrentBgHex() {
  const bgVal = currentInputValues['BackgroundColor'];
  return bgColorMap[bgVal] || '#E5E5E5';
}

function exportPNG() {
  const bgHex = getCurrentBgHex();
  const srcW = canvas.width;
  const srcH = canvas.height;
  exportCanvas.width = srcW;
  exportCanvas.height = srcH;
  const ctx = exportCanvas.getContext('2d');
  ctx.fillStyle = bgHex;
  ctx.fillRect(0, 0, srcW, srcH);
  ctx.drawImage(canvas, 0, 0);
  const link = document.createElement('a');
  link.download = `avatar_${Date.now()}.png`;
  link.href = exportCanvas.toDataURL('image/png');
  link.click();
}

function createTabButton(def) {
  const btn = document.createElement('button');
  btn.className = 'tab-btn';
  btn.innerHTML = `<img src="${def.icon}" alt="${def.label}"><span class="tab-label">${def.label}</span>`;
  btn.onclick = () => switchTab(def.idx);
  return btn;
}

// ===================== UI RENDER =====================
function renderUI() {
  if (!builderConfig) return;
  const tabs = builderConfig.avatarBuilderConfig.stateChooserTabs;

  tabBar.innerHTML = '';
  tabContent.innerHTML = '';

  TAB_DEFS.forEach((def) => {
    tabBar.appendChild(createTabButton(def));

    const tab = tabs[def.idx];
    if (!tab) return;
    const panel = document.createElement('div');
    panel.className = 'tab-panel';

    for (const section of tab.sections) {
      const secDiv = document.createElement('div');
      secDiv.className = 'section';
      const header = document.createElement('div');
      header.className = 'section-header';
      header.textContent = section.header;
      secDiv.appendChild(header);

      if (section.buttonType === 'IMAGE') {
        const grid = document.createElement('div');
        grid.className = 'swatch-grid';
        const stateName = section.imageButtons[0]?.state;
        const currentVal = currentInputValues[stateName];

        for (const ib of section.imageButtons) {
          const swatch = document.createElement('div');
          swatch.className = 'swatch';
          swatch.dataset.state = ib.state;
          swatch.dataset.value = ib.value;
          if (ib.value === currentVal) swatch.classList.add('selected');
          swatch.style.backgroundColor = ib.color;
          swatch.title = ib.color;
          swatch.onclick = () => {
            setSMValue(ib.state, ib.value);
            if (ib.state === 'BackgroundColor') updateBackground();
            grid.querySelectorAll('.swatch').forEach(s => s.classList.remove('selected'));
            swatch.classList.add('selected');
          };
          grid.appendChild(swatch);
        }
        secDiv.appendChild(grid);
      } else if (section.buttonType === 'FEATURE') {
        const grid = document.createElement('div');
        grid.className = 'tile-grid';
        const stateName = section.featureButtons[0]?.state;
        const currentVal = currentInputValues[stateName];

        for (const fb of section.featureButtons) {
          const tile = document.createElement('div');
          tile.className = 'tile loading';
          tile.dataset.state = fb.state;
          tile.dataset.value = fb.value;
          if (fb.value === currentVal) tile.classList.add('selected');

          const ph = document.createElement('span');
          ph.className = 'tile-placeholder';
          ph.textContent = fb.value === 0 ? '✕' : '';
          tile.appendChild(ph);

          tile.onclick = () => {
            applyFeatureButton(fb);
            updateBackground();
            grid.querySelectorAll('.tile').forEach(t => t.classList.remove('selected'));
            tile.classList.add('selected');
            refreshAllHighlights();
          };
          grid.appendChild(tile);
        }
        secDiv.appendChild(grid);
      }
      panel.appendChild(secDiv);
    }
    tabContent.appendChild(panel);
  });

  switchTab(0);
  updateSaveStatus();
  setTimeout(() => renderTabTiles(0), 200);
}

function switchTab(idx) {
  currentTabIdx = idx;
  tabBar.querySelectorAll('.tab-btn').forEach((b, i) => b.classList.toggle('active', i === idx));
  tabContent.querySelectorAll('.tab-panel').forEach((p, i) => p.classList.toggle('active', i === idx));

  if (dirtyTabs.has(idx) || !hasActiveTabInstances(idx)) {
    renderTabTiles(idx);
  } else {
    refreshAllHighlights();
  }
}

function hasActiveTabInstances(tabIdx) {
  for (const key of tileInstances.keys()) {
    if (key.startsWith(`${tabIdx}-`)) return true;
  }
  return false;
}

function refreshAllHighlights() {
  const tabs = builderConfig?.avatarBuilderConfig?.stateChooserTabs;
  if (!tabs) return;
  const panels = tabContent.querySelectorAll('.tab-panel');
  panels.forEach((panel, ti) => {
    const def = TAB_DEFS.find(d => d.idx === ti);
    if (!def || def.idx >= tabs.length) return;
    const tab = tabs[def.idx];
    let si = 0, fi = 0;
    const swatchGrids = panel.querySelectorAll('.swatch-grid');
    const tileGrids = panel.querySelectorAll('.tile-grid');
    for (const section of tab.sections) {
      if (section.buttonType === 'IMAGE' && si < swatchGrids.length) {
        const cur = currentInputValues[section.imageButtons[0]?.state];
        swatchGrids[si].querySelectorAll('.swatch').forEach(s => {
          s.classList.toggle('selected', parseInt(s.dataset.value) === cur);
        });
        si++;
      } else if (section.buttonType === 'FEATURE' && fi < tileGrids.length) {
        const cur = currentInputValues[section.featureButtons[0]?.state];
        tileGrids[fi].querySelectorAll('.tile').forEach(t => {
          t.classList.toggle('selected', parseInt(t.dataset.value) === cur);
        });
        fi++;
      }
    }
  });
}

function applyConfigDefaults() {
  if (!builderConfig || !currentSM) return;
  const defaults = builderConfig.avatarBuilderConfig.defaultBuiltAvatarState;
  if (!defaults) return;
  for (const [name, value] of Object.entries(defaults)) {
    const inp = stateMachineInputs[name];
    if (!inp) continue;
    if (inp.type === 56) {
      inp.value = value;
      currentInputValues[name] = value;
    } else if (inp.type === 59) {
      const boolValue = !!value;
      inp.value = boolValue;
      currentInputValues[name] = boolValue;
    }
  }
  defaultInputValues = { ...getSerializableAvatarState() };
  scheduleTrigger();
  updateBackground();
  dirtyTabs.clear();
  markAllTabsDirty();
  updateSaveStatus();
}

// ===================== RESET =====================
function resetAll(options = {}) {
  if (!builderConfig || !currentSM) return;
  const defaults = Object.keys(defaultInputValues).length
    ? defaultInputValues
    : builderConfig.avatarBuilderConfig.defaultBuiltAvatarState;
  if (!defaults) return;
  if (options.record !== false) recordHistoryBeforeChange();
  for (const [name, value] of Object.entries(defaults)) {
    applyInputValue(name, value);
  }
  scheduleTrigger();
  updateBackground();
  destroyAllTileInstances();
  dirtyTabs.clear();
  markAllTabsDirty();
  commitAvatarMutation();
  if (builderConfig) renderUI();
  setTimeout(updateAiPreviewSnapshot, 180);
}

// Dedicated deterministic renderer for automation screenshots. It does not
// touch editor state, history, storage, thumbnails, or AI preview state.
function createAvatarLayout() {
  const Layout = window.rive?.Layout;
  const Fit = window.rive?.Fit;
  const Alignment = window.rive?.Alignment;
  return Layout && Fit && Alignment
    ? new Layout({ fit: Fit.Cover, alignment: Alignment.Center })
    : undefined;
}

function ensureCaptureCanvas() {
  if (captureCanvas) return captureCanvas;
  captureCanvas = document.createElement('canvas');
  captureCanvas.width = canvas.width;
  captureCanvas.height = canvas.height;
  captureCanvas.style.cssText = [
    'position:fixed',
    'left:-10000px',
    'top:-10000px',
    `width:${canvas.width}px`,
    `height:${canvas.height}px`,
    'opacity:0',
    'pointer-events:none',
  ].join(';');
  captureCanvas.setAttribute('aria-hidden', 'true');
  document.body.appendChild(captureCanvas);
  return captureCanvas;
}

function createCaptureRiveInstance(targetCanvas) {
  return new Promise((resolve, reject) => {
    const Rive = window.rive?.Rive;
    if (!Rive || !sharedRiveFile) {
      reject(new Error('Rive capture runtime is not ready'));
      return;
    }
    let settled = false;
    const instance = new Rive({
      canvas: targetCanvas,
      riveFile: sharedRiveFile,
      layout: createAvatarLayout(),
      autoplay: false,
      stateMachines: 'SMAvatar',
      onLoad: () => {
        settled = true;
        resolve(instance);
      },
      onLoadError: (err) => {
        settled = true;
        reject(err || new Error('Rive capture instance failed to load'));
      },
    });
    setTimeout(() => {
      if (!settled) reject(new Error('Rive capture instance timed out'));
    }, 5000);
  });
}

async function getCaptureRiveInstance() {
  if (captureRiveInst) return captureRiveInst;
  if (!captureRivePromise) {
    captureRivePromise = createCaptureRiveInstance(ensureCaptureCanvas())
      .then((instance) => {
        captureRiveInst = instance;
        return instance;
      })
      .finally(() => {
        captureRivePromise = null;
      });
  }
  return captureRivePromise;
}

function applyStateToInputs(inputs, state) {
  const inputMap = Object.create(null);
  let trigger = null;
  for (const inp of inputs || []) {
    inputMap[inp.name] = inp;
    if (inp.type === 58 && inp.name === 'bounce_trig') trigger = inp;
  }
  const applyValues = (values) => {
    for (const [name, value] of Object.entries(values || {})) {
      const inp = inputMap[name];
      if (!inp) continue;
      if (inp.type === 56 && typeof value === 'number') inp.value = value;
      else if (inp.type === 59) inp.value = !!value;
    }
  };
  const defaults = Object.keys(defaultInputValues).length
    ? defaultInputValues
    : builderConfig?.avatarBuilderConfig?.defaultBuiltAvatarState;
  applyValues(defaults);
  applyValues(state);
  return trigger;
}

function resetCaptureInstance(instance, state) {
  instance.reset({ stateMachines: 'SMAvatar', autoplay: false });
  const trigger = applyStateToInputs(instance.stateMachineInputs('SMAvatar'), state);
  if (trigger) trigger.fire();
  if (typeof instance.animator?.advanceIfPaused === 'function') {
    instance.animator.advanceIfPaused();
  }
}

function captureCanvasHash(targetCanvas) {
  const ctx = targetCanvas.getContext('2d', { willReadFrequently: true });
  const pixels = ctx.getImageData(0, 0, targetCanvas.width, targetCanvas.height).data;
  let hash = 2166136261;
  for (let i = 0; i < pixels.length; i += 32) {
    hash ^= pixels[i];
    hash = Math.imul(hash, 16777619);
    hash ^= pixels[i + 1] || 0;
    hash = Math.imul(hash, 16777619);
    hash ^= pixels[i + 2] || 0;
    hash = Math.imul(hash, 16777619);
    hash ^= pixels[i + 3] || 0;
    hash = Math.imul(hash, 16777619);
  }
  return String(hash >>> 0);
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

async function waitForCaptureStable(instance, targetCanvas) {
  const maxFrames = 16;
  let previousHash = '';
  let sameFrameCount = 0;
  for (let frame = 1; frame <= maxFrames; frame++) {
    instance.drawFrame();
    await nextFrame();
    const hash = captureCanvasHash(targetCanvas);
    if (hash === previousHash) sameFrameCount += 1;
    else sameFrameCount = 0;
    if (sameFrameCount >= 1) {
      return { stable: true, frameCount: frame };
    }
    previousHash = hash;
  }
  return { stable: false, frameCount: maxFrames };
}

async function captureWithInstance(state, options = {}) {
  const start = performance.now();
  const useStrictInstance = options.strict === true;
  const targetCanvas = useStrictInstance ? document.createElement('canvas') : ensureCaptureCanvas();
  let instance = null;
  if (useStrictInstance) {
    targetCanvas.width = canvas.width;
    targetCanvas.height = canvas.height;
    targetCanvas.style.cssText = [
      'position:fixed',
      'left:-10000px',
      'top:-10000px',
      `width:${canvas.width}px`,
      `height:${canvas.height}px`,
      'opacity:0',
      'pointer-events:none',
    ].join(';');
    targetCanvas.setAttribute('aria-hidden', 'true');
    document.body.appendChild(targetCanvas);
    instance = await createCaptureRiveInstance(targetCanvas);
  } else {
    instance = await getCaptureRiveInstance();
  }
  try {
    resetCaptureInstance(instance, state);
    const settle = await waitForCaptureStable(instance, targetCanvas);
    return {
      dataUrl: targetCanvas.toDataURL('image/png'),
      timingMs: Math.round((performance.now() - start) * 100) / 100,
      stable: settle.stable,
      frameCount: settle.frameCount,
      fallbackUsed: useStrictInstance,
    };
  } finally {
    if (useStrictInstance && instance) {
      try { instance.cleanup(); } catch(e) {}
    }
    if (useStrictInstance) targetCanvas.remove();
  }
}

// ===================== EVENTS =====================
document.addEventListener('change', async (e) => {
  if (e.target?.id !== 'fileInput') return;
  const file = e.target.files?.[0];
  if (!file) return;
  loadRiveFile(await file.arrayBuffer());
});

if (aiPrompt) {
  aiPrompt.addEventListener('input', () => {
    aiPinnedStatus = '';
    renderMentionMenu();
    updateAiControls();
  });
  aiPrompt.addEventListener('keyup', renderMentionMenu);
  aiPrompt.addEventListener('click', renderMentionMenu);
  aiPrompt.addEventListener('blur', () => setTimeout(() => mentionMenu?.classList.remove('open'), 120));
}

window.addEventListener('hashchange', handleRoute);

document.addEventListener('keydown', (e) => {
  const target = e.target;
  const tag = target?.tagName?.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || target?.isContentEditable) return;
  const isUndo = (e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'z' && !e.shiftKey;
  const isRedo = (e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'z' && e.shiftKey;
  if (isUndo) {
    e.preventDefault();
    undoAvatarChange();
  } else if (isRedo) {
    e.preventDefault();
    redoAvatarChange();
  }
});

function installAvatarGlobals() {
  const global = window;
  Object.assign(global, {
    openGeneratePage,
    showGeneratePage,
    showEditorPage,
    exportPNG,
    confirmResetAll,
    resetAll,
    openFilePicker,
    clearSavedAvatar,
    openMoreSheet,
    closeMoreSheet,
    openTermsSheet,
    closeTermsSheet,
    undoAvatarChange,
    redoAvatarChange,
    switchTab,
    setSMValue,
    applyFeatureButton,
    renderTabTiles,
    hasActiveTabInstances,
    verifyAiSession,
    startAvatarGeneration,
    insertMention,
  });
  Object.defineProperties(global, {
    riveInst: { configurable: true, get: () => riveInst },
    sharedRiveFile: { configurable: true, get: () => sharedRiveFile },
    smNames: { configurable: true, get: () => smNames },
    currentSM: { configurable: true, get: () => currentSM },
    triggerInput: { configurable: true, get: () => triggerInput },
    builderConfig: { configurable: true, get: () => builderConfig },
    currentInputValues: { configurable: true, get: () => currentInputValues },
    stateMachineInputs: { configurable: true, get: () => stateMachineInputs },
    tileInstances: { configurable: true, get: () => tileInstances },
    dirtyTabs: { configurable: true, get: () => dirtyTabs },
    currentTabIdx: { configurable: true, get: () => currentTabIdx },
    API_BASE_URL: { configurable: true, get: () => API_BASE_URL },
    backendConfig: { configurable: true, get: () => backendConfig, set: (value) => { backendConfig = value; global.avatarBackend = backendConfig; } },
    canvas: { configurable: true, get: () => canvas },
    exportCanvas: { configurable: true, get: () => exportCanvas },
    aiPrompt: { configurable: true, get: () => aiPrompt },
    generateBtn: { configurable: true, get: () => generateBtn },
    verifyAiBtn: { configurable: true, get: () => verifyAiBtn },
    semanticCatalog: { configurable: true, get: () => semanticCatalog },
    semanticCatalogStatus: { configurable: true, get: () => semanticCatalogStatus },
  });
  global.__avatarTestHooks = {
    isReady: () => !!riveInst && sharedRiveFile !== null && tileInstances.size > 0,
    getState: () => getSerializableAvatarState(),
    setStatePatch: (patch) => applyGeneratedAvatarState(patch),
    captureAvatarState: (state, options = {}) => captureWithInstance(state, options),
    switchTab,
    openGeneratePage,
    showEditorPage,
    undo: undoAvatarChange,
    redo: redoAvatarChange,
    getTileCount: () => tileInstances.size,
    getCurrentTab: () => currentTabIdx,
    isSemanticCatalogReady,
  };
}

// ===================== INIT =====================
async function init() {
  loadBackendConfig();
  try {
    const resp = await fetch('avatar_builder_config.json');
    if (resp.ok) {
      builderConfig = await resp.json();
      buildBgColorMap();
      await loadSemanticCatalog();
    }
  } catch(e) { console.warn('Config:', e.message); }
  try {
    const resp = await fetch('avatar_builder_25_sept2025.riv');
    if (resp.ok) { loadRiveFile(await resp.arrayBuffer()); }
    else { loadingOverlay.classList.add('hidden'); }
  } catch(e) { loadingOverlay.classList.add('hidden'); }
}
installAvatarGlobals();
init();
