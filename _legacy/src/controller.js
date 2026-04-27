const { DEFAULT_CDP_URL, connectBrowser } = require('./browser-attach');
const {
  readTargetsConfig,
  upsertTarget,
  getTargetById,
  ensureTargetDirs,
  resolveProjectPath,
} = require('./config');
const { getLinePages, scoreTargetMatch, describePage } = require('./line-pages');
const { runDownloader } = require('./downloader-bridge');
const { runClassifier } = require('./classify');
const { readTargetState, writeTargetState } = require('./state');
const { SCAN_PROFILES } = require('./phases');
const { buildTargetFromPage } = require('./target-builder');

function getCdpUrl(options) {
  return options['cdp-url'] || DEFAULT_CDP_URL;
}

const PROGRESS_SENTINEL = '##LDL_PROGRESS##';
function emitProgress(payload) {
  try {
    process.stdout.write(`${PROGRESS_SENTINEL}${JSON.stringify(payload)}\n`);
  } catch {}
}

async function withBrowser(cdpUrl, fn) {
  const browser = await connectBrowser(cdpUrl);
  return fn(browser);
}

async function listPages(options = {}) {
  const cdpUrl = getCdpUrl(options);
  return withBrowser(cdpUrl, async browser => {
    const pages = await getLinePages(browser);
    if (!pages.length) {
      console.log('No LINE pages found.');
      return;
    }
    pages.forEach((page, index) => {
      console.log(describePage(page, index));
    });
  });
}

async function bindTarget(options = {}) {
  if (!options.target) {
    throw new Error('bind requires --target');
  }
  const cdpUrl = getCdpUrl(options);
  return withBrowser(cdpUrl, async browser => {
    const pages = await getLinePages(browser);
    if (!pages.length) {
      throw new Error('No LINE pages found. Open LINE Web in the automation Chrome first.');
    }

    let selected;
    if (options.page !== undefined) {
      const index = Number(options.page);
      if (!Number.isInteger(index) || index < 0 || index >= pages.length) {
        throw new Error(`Invalid --page value: ${options.page}`);
      }
      selected = pages[index];
    } else if (pages.length === 1) {
      selected = pages[0];
    } else {
      const listing = pages.map((page, index) => describePage(page, index)).join('\n');
      throw new Error(`Multiple LINE pages found. Pass --page.\n${listing}`);
    }

    const target = buildTargetFromPage(selected, { id: options.target, label: options.label });
    await ensureTargetDirs(target);
    await upsertTarget(target);

    if (target.id !== options.target) {
      console.log(`請注意：target id "${options.target}" 已正規化為 "${target.id}"`);
    }
    console.log(`已綁定 target: ${target.id}`);
    console.log(`label: ${target.label}`);
    console.log(`groupName: ${target.groupName}`);
    if (target.groupFingerprint.chatId) {
      console.log(`chatId: ${target.groupFingerprint.chatId}`);
    }
    console.log(`downloadDir: ${resolveProjectPath(target.downloadDir)}`);
  });
}

function findBestPageMatch(pages, target) {
  const chatId = target.groupFingerprint?.chatId || '';
  if (chatId) {
    const exact = pages.find(page => page.chatId === chatId);
    if (exact) {
      return { page: exact, score: 1000, matchedBy: 'chatId' };
    }
  }

  const ranked = pages
    .map(page => ({ page, score: scoreTargetMatch(page, target) }))
    .filter(item => item.score >= 30)
    .sort((left, right) => right.score - left.score);

  if (!ranked.length) {
    return null;
  }
  if (ranked.length > 1 && ranked[0].score === ranked[1].score) {
    return null;
  }
  return { ...ranked[0], matchedBy: 'fallback' };
}

async function listTargets() {
  const config = await readTargetsConfig();
  if (!config.targets.length) {
    console.log('No targets configured.');
    return;
  }
  config.targets.forEach(target => {
    console.log(`${target.id} | ${target.label} | ${target.groupName} | ${target.enabled ? 'enabled' : 'disabled'}`);
  });
}

async function runSingleTarget(target, options) {
  const cdpUrl = getCdpUrl(options);
  return withBrowser(cdpUrl, browser => runSingleTargetWithBrowser(browser, target, options));
}

async function runSingleTargetWithBrowser(browser, target, options) {
  await ensureTargetDirs(target);
  const pages = await getLinePages(browser);
  const match = findBestPageMatch(pages, target);
  if (!match) {
    throw new Error(`No matching LINE page found for target "${target.id}".`);
  }

  const useState = options.useState === true || options.useState === 'true';
  const state = useState
    ? await readTargetState(target.id)
    : { seenKeys: [], lastRunAt: null, lastSuccessAt: null };

  const result = await runDownloader(match.page.page, target, {
    seenKeys: state.seenKeys,
    scanProfile: options.scanProfile || SCAN_PROFILES.FULL,
  });

  if (useState) {
    const now = new Date().toISOString();
    const downloadedKeys = Array.isArray(result.downloadedKeys) ? result.downloadedKeys.filter(Boolean) : [];
    state.lastRunAt = now;
    if (downloadedKeys.length) {
      state.seenKeys = [...new Set([...(state.seenKeys || []), ...downloadedKeys])];
      state.lastSuccessAt = now;
    }
    await writeTargetState(target.id, state);
  }

  let classify = null;
  let classifyError = null;
  if (result.downloadedCount > 0) {
    try {
      classify = await runClassifier(target, { python: options.python });
    } catch (error) {
      classifyError = error && error.message ? error.message : String(error);
    }
  }

  emitProgress({
    type: 'result',
    targetId: target.id,
    phase: 'ok',
    candidateCount: result.candidateCount || 0,
    selectedCount: result.selectedCount || 0,
    downloadedCount: result.downloadedCount || 0,
    failedCount: Array.isArray(result.failedKeys) ? result.failedKeys.length : 0,
  });

  return {
    match,
    download: result,
    classify,
    classifyError,
  };
}

function printRunResult(target, result) {
  console.log(`target: ${target.id}`);
  console.log(`matched score: ${result.match.score}`);
  console.log(`matched by: ${result.match.matchedBy}`);
  console.log(`downloaded: ${result.download.downloadedCount}/${result.download.selectedCount}`);
  if (result.download.candidateCount) {
    console.log(`candidates: ${result.download.candidateCount}`);
  }
  const s = result.download.summaryCounts || {};
  if (Object.keys(s).length) {
    console.log(`candidate sources: idb ${s.idb || 0} / cache ${s.cache || 0} / opfs ${s.opfs || 0} / perf ${s.perf || 0} / dom ${s.dom || 0} / deduped ${s.deduped || 0}`);
  }
  if (typeof result.download.contentDedupedCount === 'number' && result.download.contentDedupedCount > 0) {
    console.log(`content deduped: ${result.download.contentDedupedCount}`);
  }
  if (result.download.savedFileSourceCounts && Object.keys(result.download.savedFileSourceCounts).length) {
    const sourceSummary = Object.entries(result.download.savedFileSourceCounts)
      .map(([key, value]) => `${key} ${value}`)
      .join(' / ');
    console.log(`download sources: ${sourceSummary}`);
  }
  console.log(`download dir: ${resolveProjectPath(target.downloadDir)}`);
  if (result.download.downloadErrors.length) {
    console.log('download errors:');
    result.download.downloadErrors.forEach(item => console.log(`  - ${item}`));
  }
  if (result.download.failedDetails && result.download.failedDetails.length) {
    console.log('failed downloads:');
    result.download.failedDetails.forEach(item => {
      const target = item.url || item.key || '(unknown)';
      console.log(`  - ${target}: ${item.reason || 'unknown'}`);
    });
  }
  if (result.classify) {
    console.log(result.classify.stdout.trim());
  } else if (result.classifyError) {
    console.log(`Classification skipped: ${result.classifyError}`);
  } else {
    console.log('No new images to classify.');
  }
}

async function runTarget(options = {}) {
  if (!options.target) {
    throw new Error('run requires --target');
  }
  const target = await getTargetById(options.target);
  if (!target) {
    throw new Error(`Unknown target: ${options.target}`);
  }

  const result = await runSingleTarget(target, options);
  printRunResult(target, result);
}

async function runAllTargets(options = {}) {
  const config = await readTargetsConfig();
  const targets = config.targets.filter(target => target.enabled);
  if (!targets.length) {
    throw new Error('No enabled targets configured.');
  }

  const cdpUrl = getCdpUrl(options);
  await withBrowser(cdpUrl, async browser => {
    for (const target of targets) {
      console.log(`\n=== ${target.id} ===`);
      const result = await runSingleTargetWithBrowser(browser, target, options);
      printRunResult(target, result);
    }
  });
}

function parseIntervalMs(options = {}) {
  const raw = options['interval-sec'] || '300';
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`Invalid interval: ${raw}`);
  }
  return Math.round(value * 1000);
}

function parseFullScanEvery(options = {}) {
  const raw = options['full-scan-every'] || '6';
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`Invalid full scan cadence: ${raw}`);
  }
  return value;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function watchTarget(options = {}) {
  if (!options.target) {
    throw new Error('watch requires --target');
  }
  const target = await getTargetById(options.target);
  if (!target) {
    throw new Error(`Unknown target: ${options.target}`);
  }

  const intervalMs = parseIntervalMs(options);
  const fullScanEvery = parseFullScanEvery(options);
  console.log(`watch target: ${target.id}`);
  console.log(`interval: ${Math.round(intervalMs / 1000)} sec`);
  console.log(`full scan every: ${fullScanEvery || 'never'} cycle(s)`);
  console.log(`download dir: ${resolveProjectPath(target.downloadDir)}`);
  console.log('Press Ctrl+C to stop.\n');

  let cycle = 0;
  while (true) {
    cycle += 1;
    const cycleStartedMs = Date.now();
    const startedAt = new Date();
    const scanProfile = cycle === 1 || (fullScanEvery > 0 && cycle % fullScanEvery === 0)
      ? SCAN_PROFILES.FULL
      : SCAN_PROFILES.WATCH_FAST;
    console.log(`[${startedAt.toISOString()}] cycle ${cycle} start (${scanProfile})`);
    emitProgress({ type: 'cycle_start', targetId: target.id, cycle, scanProfile });
    try {
      const result = await runSingleTarget(target, { ...options, useState: true, scanProfile });
      printRunResult(target, result);
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      console.error(`watch error: ${message}`);
      emitProgress({ type: 'error', targetId: target.id, cycle, message });
    }
    const endedAt = new Date();
    const elapsedMs = Date.now() - cycleStartedMs;
    const sleepMs = Math.max(0, intervalMs - elapsedMs);
    const lagMs = Math.max(0, elapsedMs - intervalMs);
    if (lagMs) {
      console.log(`[${endedAt.toISOString()}] cycle lag: ${Math.round(lagMs / 1000)} sec`);
    }
    console.log(`[${endedAt.toISOString()}] sleeping ${Math.round(sleepMs / 1000)} sec\n`);
    emitProgress({ type: 'cycle_end', targetId: target.id, cycle, sleepSec: Math.round(sleepMs / 1000) });
    await sleep(sleepMs);
  }
}

module.exports = {
  listPages,
  bindTarget,
  listTargets,
  runTarget,
  runAllTargets,
  runSingleTarget,
  watchTarget,
};
