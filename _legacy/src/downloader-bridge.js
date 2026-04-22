const fs = require('fs/promises');
const path = require('path');
const crypto = require('crypto');

const { ROOT_DIR, resolveProjectPath } = require('./config');
const { DOWNLOADER_PHASES, SCAN_PROFILES } = require('./phases');

const SCRIPT_PATH = path.join(ROOT_DIR, 'scripts', '00-all-in-one.js');

let downloaderSourceCache = null;

async function loadDownloaderSource() {
  if (!downloaderSourceCache) {
    downloaderSourceCache = await fs.readFile(SCRIPT_PATH, 'utf8');
  }
  return downloaderSourceCache;
}

async function resetInjectionFlag(page) {
  // UI panel removed；只剩重置重複注入的 flag
  await page.evaluate(() => { window.__LINE_DL_ACTIVE__ = false; });
}

async function injectDownloader(page, options = {}) {
  await resetInjectionFlag(page);
  const session = await page.context().newCDPSession(page);
  const source = await loadDownloaderSource();
  const bootstrap = `
    window.__LDL_AUTOMATION__ = true;
    window.__LDL_SCAN_PROFILE__ = ${JSON.stringify(options.scanProfile || SCAN_PROFILES.FULL)};
    window.__LDL_PHASES__ = ${JSON.stringify(DOWNLOADER_PHASES)};
    window.__LDL_SCAN_PROFILES__ = ${JSON.stringify(SCAN_PROFILES)};
  `;
  await session.send('Runtime.enable');
  const result = await session.send('Runtime.evaluate', {
    expression: `${bootstrap}\n${source}`,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    const description =
      result.exceptionDetails.exception?.description ||
      result.exceptionDetails.text ||
      'inject failed';
    throw new Error(description);
  }
}

// Note: 先前嘗試過 5 種 auto-scroll 方法（頁內 scrollTop、合成 WheelEvent、CDP mouse.wheel、
// keyboard Home/PageUp、Input.synthesizeScrollGesture 觸控慣性手勢）——LINE 的 React virtual
// scroll 對所有程式化輸入免疫。唯一可行：operator 手動捲 LINE，訊息自然進入 DOM + Cache。

function countSavedFileSources(filepaths) {
  const counts = {};
  for (const filepath of filepaths) {
    const base = path.basename(filepath).toLowerCase();
    const match = /_(idb|cache|opfs|perf|dom)\.[a-z0-9]+$/.exec(base);
    const key = match ? match[1] : 'unknown';
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

async function uniqueDownloadPath(downloadDir, filename) {
  const parsed = path.parse(filename);
  let candidate = path.join(downloadDir, filename);
  let counter = 1;
  while (true) {
    try {
      await fs.access(candidate);
      candidate = path.join(downloadDir, `${parsed.name}_${counter}${parsed.ext}`);
      counter += 1;
    } catch {
      return candidate;
    }
  }
}

function stripUniqueSuffix(basename) {
  return basename.replace(/_(\d+)(\.[a-z0-9]+)$/i, '$2');
}

async function writeSidecarForSaves(target, downloadSaves, savedFilesMeta) {
  if (!Array.isArray(savedFilesMeta) || !savedFilesMeta.length) return;
  const byName = new Map();
  const byStem = new Map();
  for (const entry of savedFilesMeta) {
    if (!entry || !entry.name) continue;
    byName.set(entry.name, entry);
    byStem.set(stripUniqueSuffix(entry.name), entry);
  }
  const savedAt = new Date().toISOString();
  await Promise.all(downloadSaves.map(async (filepath) => {
    const basename = path.basename(filepath);
    const entry = byName.get(basename) || byStem.get(stripUniqueSuffix(basename));
    if (!entry) return;
    const sidecar = {
      version: 1,
      savedAt,
      source: {
        targetId: target.id,
        targetLabel: target.label || target.id,
        groupName: target.groupName || '',
        chatId: target.groupFingerprint?.chatId || '',
        imageSource: entry.sourceTag || '',
        candidateUrl: entry.url || '',
        candidateFp: entry.fp || '',
      },
    };
    try {
      await fs.writeFile(`${filepath}.json`, JSON.stringify(sidecar, null, 2), 'utf8');
    } catch (error) {
      console.warn(`[sidecar] 寫入失敗 ${filepath}.json: ${error.message}`);
    }
  }));
}

async function sha256File(filepath) {
  const hash = crypto.createHash('sha256');
  const buf = await fs.readFile(filepath);
  hash.update(buf);
  return hash.digest('hex');
}

async function waitForLineReady(page, timeoutMs = 10000) {
  // openTargetTab 用 domcontentloaded 就返回，但 LINE 的 JS 還要時間 fetch + render 訊息。
  // 等到 DOM 出現 <img> 或 message 容器，scanner 才有東西掃。
  try {
    await page.waitForFunction(() => {
      if (document.images && document.images.length > 0) return true;
      if (document.querySelector('[class*="message"], [class*="chatroom"]')) return true;
      return false;
    }, { timeout: timeoutMs });
    // 再等一個短暫 grace period 讓後續 lazy-load 的圖進 DOM/Cache
    await page.waitForTimeout(1500);
  } catch {
    // timeout：就算沒 ready 也繼續，不要 block run
  }
}

function emptyResult(snapshot, downloadErrors, extra = {}) {
  return {
    candidateCount: snapshot.candidateCount || 0,
    selectedCount: 0,
    downloadedCount: 0,
    summaryCounts: snapshot.summaryCounts || {},
    gridSourceCounts: snapshot.gridSourceCounts || {},
    selectedKeys: [],
    downloadedKeys: [],
    failedKeys: [],
    failedDetails: [],
    savedFileSourceCounts: {},
    savedFiles: [],
    downloadErrors,
    ...extra,
  };
}

async function runDownloader(page, target, options = {}) {
  const downloadDir = resolveProjectPath(target.downloadDir);
  const rawSeen = Array.isArray(options.seenKeys) ? options.seenKeys.filter(Boolean) : [];
  const seenKeys = new Set(rawSeen);
  const seenHashes = new Set(
    rawSeen
      .filter(k => k.startsWith('sha256:'))
      .map(k => k.slice('sha256:'.length))
  );

  const downloadSaves = [];
  const downloadErrors = [];
  const dedupedSaves = [];
  const newHashes = new Map();
  const downloadListener = async download => {
    let filepath;
    try {
      filepath = await uniqueDownloadPath(downloadDir, download.suggestedFilename());
      await download.saveAs(filepath);
    } catch (error) {
      downloadErrors.push(error.message);
      return;
    }
    try {
      const hash = await sha256File(filepath);
      if (seenHashes.has(hash) || newHashes.has(hash)) {
        await fs.unlink(filepath).catch(() => {});
        dedupedSaves.push({ filepath, hash, reason: seenHashes.has(hash) ? 'seen' : 'duplicate-in-batch' });
        return;
      }
      newHashes.set(hash, filepath);
      downloadSaves.push(filepath);
    } catch (error) {
      downloadErrors.push(`sha256 check failed for ${filepath}: ${error.message}`);
      downloadSaves.push(filepath);
    }
  };

  page.on('download', downloadListener);

  try {
    await page.bringToFront();
    // 確認 LINE chat JS 已 render 訊息（剛開新分頁時 domcontentloaded 太早）
    await waitForLineReady(page);
    // 不做自動捲動——LINE React virtual scroll 對所有程式化輸入免疫（已驗證）。
    // Scanner 只抓目前 DOM + Cache + perf buffer 裡的圖；operator 手動用 LINE 時會載入更多。
    await injectDownloader(page, options);

    // 用 __LDL_RUN__ 一次完成 scan+dedup+download；bridge 不再點按鈕、不再 waitForFunction
    const profile = options.scanProfile || SCAN_PROFILES.FULL;
    const finalState = await page.evaluate(
      async ({ seenKeys, scanProfile }) => {
        if (typeof window.__LDL_RUN__ !== 'function') {
          throw new Error('__LDL_RUN__ not injected');
        }
        return window.__LDL_RUN__({ seenKeys, scanProfile });
      },
      { seenKeys: Array.from(seenKeys), scanProfile: profile }
    );

    // 等 Playwright 收尾尚未觸發完成的 download event
    await page.waitForTimeout(1500);

    if (finalState.phase === DOWNLOADER_PHASES.ERROR) {
      throw new Error(finalState.error || 'downloader run failed');
    }
    if (finalState.phase === DOWNLOADER_PHASES.EMPTY) {
      return emptyResult(finalState, downloadErrors);
    }

    const total = finalState.candidateCount || 0;
    const selected = finalState.selectedCount || 0;
    if (!selected) {
      return emptyResult(finalState, downloadErrors, {
        candidateCount: total,
      });
    }

    await writeSidecarForSaves(target, downloadSaves, finalState.savedFiles || []);

    const pageKeys = Array.isArray(finalState.downloadedKeys) ? finalState.downloadedKeys : [];
    const hashKeys = [...newHashes.keys()].map(h => `sha256:${h}`);
    const combinedDownloadedKeys = [...new Set([...pageKeys, ...hashKeys])];

    return {
      candidateCount: total,
      selectedCount: selected,
      downloadedCount: downloadSaves.length,
      contentDedupedCount: dedupedSaves.length,
      summaryCounts: finalState.summaryCounts || {},
      gridSourceCounts: finalState.gridSourceCounts || {},
      selectedKeys: finalState.selectedKeys || [],
      downloadedKeys: combinedDownloadedKeys,
      failedKeys: finalState.failedKeys || [],
      failedDetails: finalState.failedDetails || [],
      savedFileSourceCounts: countSavedFileSources(downloadSaves),
      savedFiles: downloadSaves,
      downloadErrors,
    };
  } finally {
    page.off('download', downloadListener);
  }
}

module.exports = {
  runDownloader,
};
