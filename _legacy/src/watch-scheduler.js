const { readTargetsConfig, getTargetById } = require('./config');
const { runSingleTarget } = require('./controller');
const { SCAN_PROFILES } = require('./phases');

const entries = new Map();

function defaultIntervalMs() {
  return Number(process.env.LINE_WATCH_INTERVAL_SEC) * 1000 || 10800 * 1000;
}

function defaultFullScanEvery() {
  const raw = Number(process.env.LINE_FULL_SCAN_EVERY);
  return Number.isInteger(raw) && raw >= 0 ? raw : 6;
}

function buildInitialProgress() {
  return {
    phase: 'idle',
    text: '待命',
    candidateCount: null,
    selectedCount: null,
    downloadedCount: 0,
  };
}

function applyResultToProgress(progress, result) {
  const dl = result.download.downloadedCount || 0;
  const sel = result.download.selectedCount || 0;
  const cand = result.download.candidateCount || 0;
  progress.downloadedCount = dl;
  progress.selectedCount = sel;
  progress.candidateCount = cand;
  if (dl > 0) {
    progress.phase = 'downloaded';
    progress.text = `已下載 ${dl}/${sel}`;
  } else if (cand > 0) {
    progress.phase = 'complete';
    progress.text = '沒有新圖';
  } else {
    progress.phase = 'complete';
    progress.text = '完成';
  }
}

async function fireCycle(target, runtime) {
  const entry = entries.get(target.id);
  if (!entry) return;
  if (entry.inflight) return;

  entry.cycleCount += 1;
  const fullScanEvery = runtime.fullScanEvery;
  const scanProfile = entry.cycleCount === 1 || (fullScanEvery > 0 && entry.cycleCount % fullScanEvery === 0)
    ? SCAN_PROFILES.FULL
    : SCAN_PROFILES.WATCH_FAST;

  entry.progress.phase = 'scanning';
  entry.progress.text = scanProfile === SCAN_PROFILES.WATCH_FAST
    ? `快速掃描中（第 ${entry.cycleCount} 輪）`
    : `完整掃描中（第 ${entry.cycleCount} 輪）`;
  entry.lastStartedAt = new Date().toISOString();

  entry.inflight = (async () => {
    try {
      const result = await runSingleTarget(target, {
        useState: true,
        scanProfile,
        'cdp-url': runtime.cdpUrl,
        python: runtime.python,
      });
      entry.lastResult = result;
      applyResultToProgress(entry.progress, result);
    } catch (error) {
      entry.lastError = error.message || String(error);
      entry.progress.phase = 'error';
      entry.progress.text = `錯誤：${entry.lastError}`;
    } finally {
      entry.lastEndedAt = new Date().toISOString();
    }
  })();

  entry.inflight.finally(() => {
    entry.inflight = null;
    if (!entries.has(target.id)) return;
    entry.nextFireMs = Date.now() + runtime.intervalMs;
    entry.timer = setTimeout(() => fireCycle(target, runtime), runtime.intervalMs);
    entry.timer.unref?.();
    if (entry.progress.phase !== 'error') {
      entry.progress.text = `${entry.progress.text}，等待下次監控`;
    }
  });
}

function runtimeFromOptions(options = {}) {
  return {
    intervalMs: options.intervalMs || defaultIntervalMs(),
    fullScanEvery: Number.isInteger(options.fullScanEvery) ? options.fullScanEvery : defaultFullScanEvery(),
    cdpUrl: options.cdpUrl,
    python: options.python || process.env.LINE_PYTHON || 'python',
  };
}

function addEntry(target, runtime, initialDelayMs) {
  if (entries.has(target.id)) {
    return entries.get(target.id);
  }
  const entry = {
    targetId: target.id,
    cycleCount: 0,
    nextFireMs: Date.now() + initialDelayMs,
    inflight: null,
    timer: null,
    progress: buildInitialProgress(),
    startedAt: new Date().toISOString(),
    lastStartedAt: null,
    lastEndedAt: null,
    lastResult: null,
    lastError: null,
    runtime,
    target,
  };
  entry.timer = setTimeout(() => fireCycle(target, runtime), initialDelayMs);
  entry.timer.unref?.();
  entry.progress.phase = 'scheduled';
  entry.progress.text = initialDelayMs > 0
    ? `預定 ${Math.round(initialDelayMs / 1000)} 秒後開始`
    : '排程中';
  entries.set(target.id, entry);
  return entry;
}

async function startAll(options = {}) {
  const runtime = runtimeFromOptions(options);
  const config = await readTargetsConfig();
  const enabled = config.targets.filter(t => t.enabled !== false);
  const count = enabled.length || 1;
  const added = [];
  enabled.forEach((target, index) => {
    if (entries.has(target.id)) return;
    const offset = Math.round((index / count) * runtime.intervalMs);
    added.push(addEntry(target, runtime, offset));
  });
  return added.map(serializeEntry);
}

async function startOne(targetId, options = {}) {
  const target = await getTargetById(targetId);
  if (!target) throw new Error(`Unknown target: ${targetId}`);
  const runtime = runtimeFromOptions(options);
  return serializeEntry(addEntry(target, runtime, 0));
}

async function stopOne(targetId) {
  const entry = entries.get(targetId);
  if (!entry) return null;
  if (entry.timer) clearTimeout(entry.timer);
  entries.delete(targetId);
  if (entry.inflight) {
    try { await entry.inflight; } catch {}
  }
  return serializeEntry(entry);
}

async function stopAll() {
  const all = [...entries.values()];
  for (const entry of all) {
    if (entry.timer) clearTimeout(entry.timer);
    entries.delete(entry.targetId);
  }
  await Promise.allSettled(all.map(e => e.inflight).filter(Boolean));
  return all.map(serializeEntry);
}

function serializeEntry(entry) {
  if (!entry) return null;
  return {
    id: `watch:${entry.targetId}:${entry.startedAt}`,
    key: `watch:${entry.targetId}`,
    kind: 'watch',
    targetId: entry.targetId,
    status: entry.inflight ? 'running' : 'idle',
    startedAt: entry.startedAt,
    endedAt: entry.lastEndedAt,
    exitCode: null,
    logs: '',
    progress: { ...entry.progress },
    pid: null,
    cycleCount: entry.cycleCount,
    nextFireMs: entry.nextFireMs,
    lastError: entry.lastError,
  };
}

function snapshotOne(targetId) {
  return serializeEntry(entries.get(targetId));
}

function snapshotAll() {
  return [...entries.values()].map(serializeEntry);
}

function isRunning(targetId) {
  return entries.has(targetId);
}

module.exports = {
  startAll,
  startOne,
  stopOne,
  stopAll,
  snapshotAll,
  snapshotOne,
  isRunning,
};
