const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const {
  DEFAULT_CDP_URL,
  connectBrowser,
} = require('./browser-attach');
const {
  ROOT_DIR,
  readTargetsConfig,
  getTargetById,
  upsertTarget,
  removeTarget,
  ensureTargetDirs,
  resolveProjectPath,
} = require('./config');
const { readTargetState, clearTargetState, removeTargetState } = require('./state');
const { getLinePages } = require('./line-pages');
const { safeId, buildTargetFromPage } = require('./target-builder');
const controller = require('./controller');
const scheduler = require('./watch-scheduler');

const DEFAULT_UI_PORT = 8787;
const jobs = new Map();

const PAGE_HEALTH_TTL_MS = Number(process.env.LINE_PAGE_HEALTH_TTL_MS) || 15000;
const CDP_START_TIMEOUT_MS = Number(process.env.LINE_CDP_START_TIMEOUT_MS) || 15000;
let pageHealthCache = { expiresAt: 0, signature: '', data: null };

function openBrowser(url) {
  spawn('cmd', ['/c', 'start', '', url], {
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
  }).unref();
}

function invalidatePageHealthCache() {
  pageHealthCache = { expiresAt: 0, signature: '', data: null };
}

function json(res, status, payload) {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  });
  res.end(body);
}

function text(res, status, body, contentType = 'text/plain; charset=utf-8') {
  res.writeHead(status, {
    'content-type': contentType,
    'cache-control': 'no-store',
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      if (!chunks.length) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch (error) {
        reject(new Error(`Invalid JSON: ${error.message}`));
      }
    });
    req.on('error', reject);
  });
}

function getCdpUrl() {
  return process.env.LINE_CDP_URL || `http://127.0.0.1:${process.env.LINE_CDP_PORT || '9333'}`;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function isCdpUnavailableError(error) {
  const message = error && (error.message || String(error));
  return /ECONNREFUSED|ECONNRESET|connect|CDP|websocket url/i.test(message || '');
}

function ensureChromeProfileDir() {
  const explicitProfile = process.env.LINE_CDP_PROFILE;
  const primaryProfile = explicitProfile || path.join(process.env.LocalAppData || ROOT_DIR, 'line-official-download-cdp-profile');
  try {
    fs.mkdirSync(primaryProfile, { recursive: true });
    return primaryProfile;
  } catch (error) {
    if (explicitProfile) throw error;
  }
  const fallbackProfile = path.join(ROOT_DIR, 'config', 'chrome-profile');
  fs.mkdirSync(fallbackProfile, { recursive: true });
  return fallbackProfile;
}

async function waitForBrowser(cdpUrl, timeoutMs = CDP_START_TIMEOUT_MS) {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    try {
      return await connectBrowser(cdpUrl);
    } catch (error) {
      lastError = error;
      await sleep(500);
    }
  }
  throw lastError || new Error(`Timed out waiting for Chromium CDP: ${cdpUrl}`);
}

async function ensureAutomationBrowser() {
  const cdpUrl = getCdpUrl();
  try {
    return await connectBrowser(cdpUrl);
  } catch (error) {
    if (!isCdpUnavailableError(error)) throw error;
  }
  await openAutomationChromeOrTab();
  return waitForBrowser(cdpUrl);
}

async function getLinePagesWithAutoOpen(browser) {
  let pages = await getLinePages(browser);
  if (pages.length) return pages;

  await openAutomationChromeOrTab();
  await sleep(1500);
  pages = await getLinePages(browser);
  return pages;
}

function chooseCurrentChatPage(pages, requestedIndex, selector = {}) {
  if (selector.chatId) {
    const byChatId = pages.find(page => page.chatId === selector.chatId);
    if (byChatId) return byChatId;
  }
  if (selector.pageUrl) {
    const byUrl = pages.find(page => page.url === selector.pageUrl);
    if (byUrl) return byUrl;
  }
  if (requestedIndex !== undefined && requestedIndex !== null && requestedIndex !== '') {
    const index = Number(requestedIndex);
    if (!Number.isInteger(index) || index < 0 || index >= pages.length) {
      throw new Error(`Invalid page index: ${requestedIndex}`);
    }
    return pages[index];
  }
  const chatPages = pages.filter(page => page.chatId || /#\/chats\//.test(page.url || ''));
  if (chatPages.length === 1) return chatPages[0];
  if (chatPages.length > 1) {
    const withId = chatPages.filter(page => page.chatId);
    if (withId.length === 1) return withId[0];
    throw new Error('Multiple LINE chat pages found. Pick one from the scanned page list.');
  }
  throw new Error('No active LINE chat page found. Open the group in the automation Chrome first.');
}

function getTaskStatusText(status) {
  if (status === 'watching') return '監控中';
  if (status === 'downloading') return '下載中';
  return '待命';
}

function buildPageHealth(target, pages) {
  const chatId = target.groupFingerprint?.chatId || '';
  if (!chatId) {
    return { status: 'no_chat_id', text: '沒有 chatId' };
  }
  if (!pages.length) {
    return { status: 'line_not_ready', text: 'LINE 未登入或未開啟' };
  }
  const exact = pages.find(page => page.chatId === chatId);
  if (exact) {
    return {
      status: 'present',
      text: '分頁存在',
      url: exact.url,
      pageTitle: exact.chatroomName || exact.selectedChatTitle || exact.title,
    };
  }
  const names = [
    target.groupName,
    target.label,
    target.groupFingerprint?.chatroomName,
    target.groupFingerprint?.selectedChatTitle,
  ].filter(Boolean);
  const nameMatch = pages.find(page => {
    const pageName = `${page.chatroomName || ''} ${page.selectedChatTitle || ''} ${page.headerTexts?.join(' ') || ''}`;
    return names.some(name => name && pageName.includes(name));
  });
  if (nameMatch && nameMatch.chatId && nameMatch.chatId !== chatId) {
    return {
      status: 'chatId_mismatch',
      text: 'chatId 不符',
      url: nameMatch.url,
      actualChatId: nameMatch.chatId,
    };
  }
  return { status: 'missing', text: '分頁不存在' };
}

async function getTargetsPageHealth(targets) {
  const out = {};
  try {
    const browser = await connectBrowser(getCdpUrl());
    const pages = await getLinePages(browser);
    for (const target of targets) {
      out[target.id] = buildPageHealth(target, pages);
    }
  } catch (error) {
    for (const target of targets) {
      out[target.id] = {
        status: 'cdp_unavailable',
        text: '專用 Chrome 未連線',
        error: error.message || String(error),
      };
    }
  }
  return out;
}

async function getTargetsPageHealthCached(targets) {
  const now = Date.now();
  const signature = targets.map(t => `${t.id}:${t.groupFingerprint?.chatId || ''}`).join('|');
  if (now < pageHealthCache.expiresAt && pageHealthCache.signature === signature && pageHealthCache.data) {
    return pageHealthCache.data;
  }
  const data = await getTargetsPageHealth(targets);
  pageHealthCache = { expiresAt: now + PAGE_HEALTH_TTL_MS, signature, data };
  return data;
}

async function listTargets() {
  const config = await readTargetsConfig();
  const [pageHealth, states] = await Promise.all([
    getTargetsPageHealthCached(config.targets),
    Promise.all(config.targets.map(target => readTargetState(target.id))),
  ]);
  return config.targets.map((target, index) => {
    const state = states[index];
    const runJob = jobs.get(`run:${target.id}`);
    const watchSnapshot = scheduler.snapshotOne(target.id);
    const isWatching = !!watchSnapshot;
    const lastJob = watchSnapshot || runJob || null;
    const taskStatus = runJob && runJob.status === 'running'
      ? 'downloading'
      : (isWatching ? 'watching' : 'idle');
    return {
      id: target.id,
      label: target.label,
      groupName: target.groupName,
      chatId: target.groupFingerprint?.chatId || '',
      enabled: target.enabled !== false,
      downloadDir: resolveProjectPath(target.downloadDir),
      travelDir: resolveProjectPath(target.travelDir),
      otherDir: resolveProjectPath(target.otherDir),
      seenCount: Array.isArray(state.seenKeys) ? state.seenKeys.length : 0,
      lastRunAt: state.lastRunAt || null,
      lastSuccessAt: state.lastSuccessAt || null,
      running: isWatching,
      taskStatus,
      taskStatusText: getTaskStatusText(taskStatus),
      pageHealth: pageHealth[target.id] || {
        status: 'unknown',
        text: '狀態未知',
      },
      lastJob,
    };
  });
}

async function listPages() {
  const browser = await ensureAutomationBrowser();
  const pages = await getLinePagesWithAutoOpen(browser);
  return pages.map((page, index) => ({
    index,
    title: page.title,
    url: page.url,
    chatId: page.chatId,
    chatroomName: page.chatroomName,
    selectedChatTitle: page.selectedChatTitle,
    selectedChatDescription: page.selectedChatDescription,
    headerTexts: page.headerTexts,
  }));
}

async function bindCurrentGroup(body) {
  const browser = await ensureAutomationBrowser();
  const pages = await getLinePagesWithAutoOpen(browser);
  const page = chooseCurrentChatPage(pages, body.pageIndex, body);
  const id = safeId(body.id);
  const config = await readTargetsConfig();
  const existingById = config.targets.find(target => target.id === id) || null;
  const existingByChatId = page.chatId
    ? config.targets.find(target => target.groupFingerprint?.chatId === page.chatId)
    : null;
  if (
    existingById &&
    existingById.groupFingerprint?.chatId &&
    page.chatId &&
    existingById.groupFingerprint.chatId !== page.chatId &&
    body.confirmOverwrite !== true
  ) {
    return {
      requiresConfirm: true,
      reason: 'target_id_conflict',
      message: `Target ID "${id}" is already bound to another chat. Confirm to overwrite it.`,
      existingTarget: existingById,
      page: {
        title: page.title,
        url: page.url,
        chatId: page.chatId,
        chatroomName: page.chatroomName,
        selectedChatTitle: page.selectedChatTitle,
      },
    };
  }
  if (
    existingByChatId &&
    existingByChatId.id !== id &&
    body.confirmDuplicateChatId !== true
  ) {
    return {
      requiresConfirm: true,
      reason: 'chat_id_already_bound',
      message: `This chat is already bound as "${existingByChatId.id}". Confirm to bind another target to the same chat.`,
      existingTarget: existingByChatId,
      page: {
        title: page.title,
        url: page.url,
        chatId: page.chatId,
        chatroomName: page.chatroomName,
        selectedChatTitle: page.selectedChatTitle,
      },
    };
  }
  const target = buildTargetFromPage(page, {
    id,
    label: body.label,
  });
  const action = existingByChatId && existingByChatId.id === id
    ? 'already-bound'
    : (existingById ? 'updated' : 'created');
  await ensureTargetDirs(target);
  await upsertTarget(target);
  return {
    action,
    target,
    page: {
      title: page.title,
      url: page.url,
      chatId: page.chatId,
      chatroomName: page.chatroomName,
      selectedChatTitle: page.selectedChatTitle,
    },
  };
}

function getLineExtensionIdFromUrl(url) {
  const match = String(url || '').match(/^chrome-extension:\/\/([^/]+)\/index\.html/i);
  return match ? match[1] : '';
}

function getLineExtensionId(target, pages = []) {
  const configured = target.pageFingerprint?.urlIncludes || '';
  if (/^[a-z]{32}$/i.test(configured)) return configured;
  for (const page of pages) {
    const id = getLineExtensionIdFromUrl(page.url);
    if (id) return id;
  }
  return '';
}

function getTargetChatUrl(target, pages = []) {
  const chatId = target.groupFingerprint?.chatId || '';
  if (!chatId) {
    throw new Error(`Target "${target.id}" has no chatId.`);
  }
  const extensionId = getLineExtensionId(target, pages);
  if (!extensionId) {
    throw new Error('LINE Chrome extension page not found. Open LINE in the automation Chrome first.');
  }
  return `chrome-extension://${extensionId}/index.html#/chats/${encodeURIComponent(chatId)}`;
}

function getLineHomeUrl(pages = []) {
  for (const page of pages) {
    const extensionId = getLineExtensionIdFromUrl(page.url);
    if (extensionId) {
      return `chrome-extension://${extensionId}/index.html#/chats`;
    }
  }
  return 'https://line.me/R/';
}

async function openTargetTab(targetId, options = {}) {
  const target = await getTargetById(targetId);
  if (!target) {
    throw new Error(`Unknown target: ${targetId}`);
  }
  const browser = await connectBrowser(getCdpUrl());
  const pages = await getLinePages(browser);
  const chatId = target.groupFingerprint?.chatId || '';
  const existing = chatId ? pages.find(page => page.chatId === chatId) : null;
  if (existing) {
    if (options.focus !== false) {
      await existing.page.bringToFront();
    }
    return {
      id: target.id,
      label: target.label,
      opened: false,
      reused: true,
      url: existing.url,
      chatId,
    };
  }

  const url = getTargetChatUrl(target, pages);
  const context = browser.contexts()[0];
  if (!context) {
    throw new Error('No Chrome browser context found.');
  }
  const page = await context.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  if (options.focus !== false) {
    await page.bringToFront();
  }
  return {
    id: target.id,
    label: target.label,
    opened: true,
    reused: false,
    url,
    chatId,
  };
}

async function openAllTargetTabs() {
  const config = await readTargetsConfig();
  const targets = config.targets.filter(target => target.enabled !== false);
  const results = [];
  for (const target of targets) {
    try {
      results.push(await openTargetTab(target.id, { focus: false }));
    } catch (error) {
      results.push({
        id: target.id,
        label: target.label,
        opened: false,
        reused: false,
        error: error.message || String(error),
      });
    }
  }
  return results;
}

const FINISHED_RUN_JOB_TTL_MS = 5 * 60 * 1000;

function startRunJob(targetId) {
  const key = `run:${targetId}`;
  const id = `${key}:${Date.now()}`;
  const job = {
    id,
    key,
    kind: 'run',
    targetId,
    status: 'running',
    startedAt: new Date().toISOString(),
    endedAt: null,
    exitCode: null,
    logs: [],
    progress: {
      phase: 'scanning',
      text: '掃描中',
      candidateCount: null,
      selectedCount: null,
      downloadedCount: 0,
    },
    progressBuffer: '',
  };
  jobs.set(key, job);

  const append = chunk => {
    const text = String(chunk);
    job.logs.push(text);
    updateJobProgress(job, text);
    if (job.logs.join('').length > 20000) {
      job.logs = [job.logs.join('').slice(-20000)];
    }
  };
  const finish = code => {
    job.status = code === 0 ? 'finished' : 'failed';
    job.exitCode = code;
    job.endedAt = new Date().toISOString();
    if (code === 0 && job.progress.phase !== 'complete') {
      job.progress.phase = 'complete';
      job.progress.text = '完成';
    }
    if (code !== 0) {
      job.progress.phase = 'error';
      job.progress.text = '失敗';
    }
    delete job.child;
    setTimeout(() => {
      if (jobs.get(key) === job) jobs.delete(key);
    }, FINISHED_RUN_JOB_TTL_MS).unref();
  };

  setImmediate(async () => {
    try {
      const target = await getTargetById(targetId);
      if (!target) throw new Error(`Unknown target: ${targetId}`);
      const result = await controller.runSingleTarget(target, {
        useState: true,
        'cdp-url': getCdpUrl(),
        python: process.env.LINE_PYTHON || 'python',
      });
      applyProgressEvent(job, {
        type: 'result',
        targetId,
        phase: 'ok',
        candidateCount: result.download.candidateCount || 0,
        selectedCount: result.download.selectedCount || 0,
        downloadedCount: result.download.downloadedCount || 0,
        failedCount: Array.isArray(result.download.failedKeys) ? result.download.failedKeys.length : 0,
      });
      if (result.classifyError) {
        append(`Classification skipped: ${result.classifyError}\n`);
      }
      finish(0);
    } catch (error) {
      append(`${error && error.stack ? error.stack : (error.message || String(error))}\n`);
      finish(1);
    }
  });

  return job;
}

const PROGRESS_SENTINEL = '##LDL_PROGRESS##';

function applyProgressEvent(job, event) {
  if (!event || typeof event !== 'object') return;
  switch (event.type) {
    case 'cycle_start':
      job.progress.phase = 'scanning';
      job.progress.text = event.scanProfile === 'watch-fast'
        ? `快速掃描中（第 ${event.cycle} 輪）`
        : `完整掃描中（第 ${event.cycle} 輪）`;
      break;
    case 'result': {
      const downloaded = Number(event.downloadedCount) || 0;
      const selected = Number(event.selectedCount) || 0;
      const candidates = Number(event.candidateCount) || 0;
      job.progress.downloadedCount = downloaded;
      job.progress.selectedCount = selected;
      job.progress.candidateCount = candidates;
      if (downloaded > 0) {
        job.progress.phase = 'downloaded';
        job.progress.text = `已下載 ${downloaded}/${selected}`;
      } else if (candidates > 0) {
        job.progress.phase = 'complete';
        job.progress.text = '沒有新圖';
      } else {
        job.progress.phase = 'complete';
        job.progress.text = '完成';
      }
      break;
    }
    case 'cycle_end':
      job.progress.phase = 'complete';
      job.progress.text = '完成，等待下次監控';
      break;
    case 'error':
      job.progress.phase = 'error';
      job.progress.text = event.message ? `錯誤：${event.message}` : '發生錯誤';
      break;
  }
}

function updateJobProgress(job, chunk) {
  const combined = (job.progressBuffer || '') + chunk;
  const lines = combined.split('\n');
  job.progressBuffer = lines.pop();
  for (const line of lines) {
    if (!line.startsWith(PROGRESS_SENTINEL)) continue;
    try {
      applyProgressEvent(job, JSON.parse(line.slice(PROGRESS_SENTINEL.length)));
    } catch {}
  }
}

async function startAllWatches() {
  await openAllTargetTabs();
  return scheduler.startAll({ cdpUrl: getCdpUrl() });
}

async function stopAllWatches() {
  return scheduler.stopAll();
}

function serializeJob(job) {
  if (!job) return null;
  const { child, progressBuffer, ...safe } = job;
  return {
    ...safe,
    logs: Array.isArray(safe.logs) ? safe.logs.join('') : '',
  };
}

async function openAutomationChromeOrTab() {
  try {
    const browser = await connectBrowser(getCdpUrl());
    const context = browser.contexts()[0];
    if (!context) {
      throw new Error('No Chrome browser context found.');
    }
    const existingHome = context.pages().find(page => {
      const pageUrl = page.url();
      return getLineExtensionIdFromUrl(pageUrl) && /#\/chats\/?$/.test(pageUrl || '');
    });
    if (existingHome) {
      await existingHome.bringToFront();
      return {
        existingChrome: true,
        openedTab: false,
        reusedTab: true,
        url: existingHome.url(),
      };
    }
    const pages = await getLinePages(browser);
    const url = getLineHomeUrl(pages);
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.bringToFront();
    return {
      existingChrome: true,
      openedTab: true,
      url,
    };
  } catch {
    // CDP 未起，繼續往下啟動專用 Chrome
  }

  const candidates = [
    path.join(process.env.ProgramFiles || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(process.env['ProgramFiles(x86)'] || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(process.env.LocalAppData || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  ];
  const chrome = candidates.find(candidate => candidate && fs.existsSync(candidate));
  if (!chrome) throw new Error('Chrome not found.');
  const profile = ensureChromeProfileDir();
  const port = process.env.LINE_CDP_PORT || '9333';
  spawn(chrome, [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    '--new-window',
    'https://line.me/R/',
  ], {
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
  }).unref();
  return {
    existingChrome: false,
    openedTab: false,
    chrome,
    profile,
    port,
  };
}

async function handleRequest(req, res) {
  const url = new URL(req.url, 'http://localhost');
  if (!url.pathname.startsWith('/api/')) {
    return text(res, 200, UI_HTML, 'text/html; charset=utf-8');
  }
  if (req.method === 'GET' && url.pathname === '/api/targets') {
    return json(res, 200, { targets: await listTargets() });
  }
  if (req.method === 'GET' && url.pathname === '/api/pages') {
    return json(res, 200, { pages: await listPages() });
  }
  if (req.method === 'GET' && url.pathname === '/api/jobs') {
    const runJobs = [...jobs.values()].map(serializeJob);
    const watchJobs = scheduler.snapshotAll();
    return json(res, 200, { jobs: [...runJobs, ...watchJobs] });
  }
  if (req.method === 'POST' && url.pathname === '/api/bind') {
    const result = await bindCurrentGroup(await readBody(req));
    if (result && result.target) invalidatePageHealthCache();
    return json(res, 200, result);
  }
  if (req.method === 'POST' && url.pathname === '/api/tabs/open') {
    const body = await readBody(req);
    if (!body.id) throw new Error('Missing target id.');
    const tab = await openTargetTab(safeId(body.id));
    invalidatePageHealthCache();
    return json(res, 200, { tab });
  }
  if (req.method === 'POST' && url.pathname === '/api/tabs/open-all') {
    const tabs = await openAllTargetTabs();
    invalidatePageHealthCache();
    return json(res, 200, { tabs });
  }
  if (req.method === 'POST' && url.pathname === '/api/run') {
    const body = await readBody(req);
    if (!body.id) throw new Error('Missing target id.');
    const id = safeId(body.id);
    const tab = await openTargetTab(id, { focus: false });
    return json(res, 200, { tab, job: serializeJob(startRunJob(id)) });
  }
  if (req.method === 'POST' && url.pathname === '/api/targets/unbind') {
    const body = await readBody(req);
    if (!body.id) throw new Error('Missing target id.');
    const id = safeId(body.id);
    try { await scheduler.stopOne(id); } catch {}
    await removeTargetState(id);
    const removed = await removeTarget(id);
    invalidatePageHealthCache();
    return json(res, 200, { ok: removed, id });
  }
  if (req.method === 'POST' && url.pathname === '/api/targets/clear-state') {
    const body = await readBody(req);
    if (!body.id) throw new Error('Missing target id.');
    const id = safeId(body.id);
    await clearTargetState(id);
    return json(res, 200, { ok: true, id });
  }
  if (req.method === 'POST' && url.pathname === '/api/watch/start') {
    const body = await readBody(req);
    if (!body.id) throw new Error('Missing target id.');
    const id = safeId(body.id);
    const tab = await openTargetTab(id, { focus: false });
    const job = await scheduler.startOne(id, { cdpUrl: getCdpUrl() });
    return json(res, 200, { tab, job });
  }
  if (req.method === 'POST' && url.pathname === '/api/watch/start-all') {
    return json(res, 200, { jobs: await startAllWatches() });
  }
  if (req.method === 'POST' && url.pathname === '/api/watch/stop') {
    const body = await readBody(req);
    if (!body.id) throw new Error('Missing target id.');
    return json(res, 200, { job: await scheduler.stopOne(safeId(body.id)) });
  }
  if (req.method === 'POST' && url.pathname === '/api/watch/stop-all') {
    return json(res, 200, { jobs: await stopAllWatches() });
  }
  if (req.method === 'POST' && url.pathname === '/api/chrome/start') {
    return json(res, 200, await openAutomationChromeOrTab());
  }
  return json(res, 404, { error: 'Not found' });
}

function startServer(options = {}) {
  const port = Number(options.port || process.env.LINE_UI_PORT || DEFAULT_UI_PORT);
  const host = '127.0.0.1';
  const url = `http://${host}:${port}`;
  const server = http.createServer(async (req, res) => {
    try {
      await handleRequest(req, res);
    } catch (error) {
      json(res, 500, { error: error.message || String(error) });
    }
  });
  server.on('error', error => {
    if (error && error.code === 'EADDRINUSE') {
      console.log(`LINE group manager UI is already running: ${url}`);
      if (options.open !== false) openBrowser(url);
      return;
    }
    console.error(error.message || error);
    process.exitCode = 1;
  });
  server.listen(port, host, () => {
    console.log(`LINE group manager UI: ${url}`);
    if (options.open !== false) openBrowser(url);
  });
  return server;
}

const UI_HTML = `<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LINE 群組抓圖管理</title>
  <style>
    :root {
      --ink: #17211b;
      --muted: #65736b;
      --paper: #f6f1e8;
      --card: rgba(255, 252, 245, 0.9);
      --line: #d8cbb7;
      --green: #06c755;
      --dark: #123026;
      --amber: #c77d18;
      --danger: #b83b35;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Noto Serif TC", "Microsoft JhengHei", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 15% 15%, rgba(6, 199, 85, 0.14), transparent 28rem),
        radial-gradient(circle at 90% 10%, rgba(199, 125, 24, 0.18), transparent 24rem),
        linear-gradient(135deg, #f8f3ea 0%, #efe4d2 100%);
      min-height: 100vh;
    }
    main {
      width: min(1180px, calc(100% - 36px));
      margin: 0 auto;
      padding: 34px 0 56px;
    }
    header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 22px;
    }
    h1 {
      font-size: clamp(22px, 3vw, 32px);
      letter-spacing: -0.03em;
      margin: 0;
      line-height: 1;
    }
    .sub {
      color: var(--muted);
      margin: 6px 0 0;
      font-size: 13px;
    }
    .toolbar, .panel, .target {
      background: var(--card);
      border: 1px solid var(--line);
      box-shadow: 0 20px 70px rgba(58, 40, 20, 0.11);
      backdrop-filter: blur(10px);
    }
    .toolbar {
      border-radius: 999px;
      padding: 10px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    button, input, select {
      font: inherit;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 8px 14px;
      font-size: 13px;
      color: white;
      background: var(--dark);
      cursor: pointer;
      transition: transform .15s ease, opacity .15s ease;
    }
    button:hover { transform: translateY(-1px); }
    button:disabled { opacity: .45; cursor: not-allowed; transform: none; }
    button.secondary { background: #6d5b43; }
    button.good { background: var(--green); color: #052916; }
    button.warn { background: var(--amber); }
    button.danger { background: var(--danger); }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(340px, .7fr);
      gap: 18px;
      align-items: start;
    }
    .panel {
      border-radius: 24px;
      padding: 18px;
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 18px;
    }
    .targets {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 10px;
      max-height: calc(100vh - 260px);
      overflow-y: auto;
      padding: 4px 4px 4px 0;
    }
    .target {
      border-radius: 16px;
      padding: 12px 14px;
      display: grid;
      gap: 6px;
      animation: rise .35s ease both;
      transition: transform .15s ease, box-shadow .15s ease;
    }
    .target:hover {
      transform: translateY(-1px);
      box-shadow: 0 8px 22px rgba(58, 40, 20, 0.14);
    }
    .target-title {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: start;
    }
    .target-head {
      min-width: 0;
      flex: 1;
    }
    .target h3 {
      margin: 0;
      font-size: 15px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .target details {
      margin-top: 4px;
    }
    .target details summary {
      font-size: 12px;
      margin-bottom: 4px;
    }
    .meta {
      color: var(--muted);
      font-size: 12px;
      word-break: break-all;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .meta.small {
      font-size: 11px;
    }
    .actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
    }
    .actions .btn-link {
      background: transparent;
      color: var(--muted);
      border: 1px solid transparent;
      padding: 4px 8px;
      font-size: 12px;
      border-radius: 8px;
    }
    .actions .btn-link:hover {
      background: rgba(0, 0, 0, 0.05);
      color: var(--ink);
      transform: none;
    }
    .actions .btn-link.danger-link:hover {
      color: var(--danger);
      background: rgba(184, 59, 53, 0.08);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 10px;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      gap: 6px;
    }
    .dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #b5bfb8;
      flex-shrink: 0;
    }
    .dot.idle { background: #b5bfb8; }
    .dot.running { background: var(--green); animation: pulse 1.4s ease-in-out infinite; }
    .dot.watching { background: var(--green); }
    .dot.downloading { background: var(--amber); animation: pulse 1.4s ease-in-out infinite; }
    .dot.error { background: var(--danger); }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.85); }
    }
    .pagehealth {
      font-size: 11px;
      color: var(--muted);
    }
    .pagehealth.warn { color: var(--amber); }
    .pagehealth.error { color: var(--danger); }
    .form {
      display: grid;
      gap: 10px;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
    }
    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 11px 12px;
      background: rgba(255,255,255,.72);
      color: var(--ink);
    }
    pre {
      min-height: 120px;
      max-height: 280px;
      overflow: auto;
      margin: 0;
      padding: 12px;
      border-radius: 12px;
      background: #17211b;
      color: #e9f5ed;
      font: 11px/1.5 Consolas, monospace;
      white-space: pre-wrap;
    }
    details {
      margin-top: 10px;
    }
    summary {
      cursor: pointer;
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 10px;
    }
    .page-list {
      display: grid;
      gap: 8px;
    }
    .page {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 10px;
      background: rgba(255,255,255,.5);
      cursor: pointer;
    }
    .page.selected {
      outline: 3px solid rgba(6,199,85,.3);
      border-color: var(--green);
    }
    .toast {
      position: fixed;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%) translateY(20px);
      min-width: 200px;
      max-width: 80vw;
      padding: 10px 18px;
      border-radius: 999px;
      background: rgba(23, 33, 27, 0.92);
      color: #e9f5ed;
      font-size: 13px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
      opacity: 0;
      pointer-events: none;
      transition: opacity .25s ease, transform .25s ease;
      z-index: 9999;
      text-align: center;
    }
    .toast.show {
      opacity: 1;
      transform: translateX(-50%) translateY(0);
    }
    .toast.error { background: var(--danger); color: #fff; }
    @keyframes rise {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @media (max-width: 850px) {
      header { display: block; }
      .toolbar { border-radius: 24px; margin-top: 16px; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>LINE 群組抓圖管理</h1>
        <p class="sub">先在專用 Chrome 進入群組，再用這裡綁定或開始抓取。</p>
      </div>
      <div class="toolbar">
        <button class="warn" onclick="startAllWatch()">開始全部監控</button>
        <button class="danger" onclick="stopAllWatch()">停止全部監控</button>
      </div>
    </header>

    <div class="grid">
      <section class="panel">
        <h2>已綁定群組</h2>
        <div id="targets" class="targets"></div>
      </section>

      <aside class="panel">
        <h2>綁定新群組</h2>
        <div class="form">
          <p class="meta">操作：先在專用 Chrome 的 LINE 點進群組，按「掃描目前群組」，選到正確頁面後再綁定。</p>
          <div class="actions">
            <button class="secondary" onclick="startChrome()">開專用 Chrome</button>
            <button class="secondary" onclick="scanPages()">掃描目前群組</button>
          </div>
          <div id="pages" class="page-list"></div>
          <label>Target ID（英文/數字，已存在會覆蓋）
            <input id="bindId" placeholder="例如 metro2">
          </label>
          <label>顯示名稱（可留空）
            <input id="bindLabel" placeholder="例如 大都會第二群">
          </label>
          <button class="good" onclick="bindGroupSafe()">綁定選取群組</button>
        </div>
      </aside>
    </div>

  </main>

  <div id="status" class="toast" aria-live="polite"></div>

  <script>
    let selectedPageIndex = '';
    let scannedPages = [];
    let targetCache = [];

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: { 'content-type': 'application/json' },
        ...options,
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || res.statusText);
      return data;
    }

    let _statusTimer = null;
    function setStatus(text, opts) {
      const el = document.getElementById('status');
      if (!el) return;
      el.textContent = text || '';
      el.classList.toggle('error', !!(opts && opts.error));
      el.classList.toggle('show', !!text);
      clearTimeout(_statusTimer);
      if (text) {
        _statusTimer = setTimeout(() => el.classList.remove('show'), (opts && opts.error) ? 6000 : 3500);
      }
    }

    function showError(error) {
      setStatus(error.message || String(error), { error: true });
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[ch]));
    }

    function makeIdUnique(base, currentId) {
      const used = new Set(targetCache.map(target => target.id));
      if (!used.has(base) || base === currentId) return base;
      for (let i = 2; i < 1000; i += 1) {
        const candidate = base + '-' + i;
        if (!used.has(candidate)) return candidate;
      }
      return base + '-' + Date.now();
    }

    function suggestTargetId(page) {
      const existing = targetCache.find(target => target.chatId && page.chatId && target.chatId === page.chatId);
      if (existing) return existing.id;
      if (page.chatId) {
        const tail = page.chatId.replace(/[^a-zA-Z0-9]/g, '').slice(-10).toLowerCase();
        return makeIdUnique('line-' + (tail || Date.now()));
      }
      const raw = page.chatroomName || page.selectedChatTitle || page.title || 'group';
      const slug = raw
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 28);
      return makeIdUnique(slug || 'group');
    }

    function prefillBindFromPage(page, force) {
      if (!page) return;
      const label = page.chatroomName || page.selectedChatTitle || page.title || '';
      const id = suggestTargetId(page);
      const bindId = document.getElementById('bindId');
      const bindLabel = document.getElementById('bindLabel');
      if (force || !bindId.value.trim()) bindId.value = id;
      if (force || !bindLabel.value.trim()) bindLabel.value = label;
    }

    async function refreshTargets() {
      const data = await api('/api/targets');
      targetCache = data.targets || [];
      const box = document.getElementById('targets');
      if (!data.targets.length) {
        box.innerHTML = '<p class="meta">尚未綁定任何群組。</p>';
        return;
      }
      box.innerHTML = data.targets.map(target => {
        const label = escapeHtml(target.label || target.id);
        const group = escapeHtml(target.groupName || '');
        const taskStatus = target.taskStatus || 'idle';
        const status = escapeHtml(target.taskStatusText || (target.running ? '監控中' : '待命'));
        const progress = escapeHtml(target.lastJob?.progress?.text || target.taskStatusText || '待命');
        const pageHealthText = target.pageHealth?.text || '狀態未知';
        const pageHealthStatus = target.pageHealth?.status || '';
        const pageHealthClass = (pageHealthStatus === 'present') ? ''
          : (pageHealthStatus === 'cdp_unavailable' || pageHealthStatus === 'line_not_ready' || pageHealthStatus === 'missing' || pageHealthStatus === 'no_chat_id') ? 'error'
          : 'warn';
        const phaseClass = target.lastJob?.progress?.phase === 'error' ? 'error' : taskStatus;
        const id = escapeHtml(target.id);
        const chatId = escapeHtml(target.chatId || '(無)');
        const seen = target.seenCount || 0;
        const lastSuccess = escapeHtml(target.lastSuccessAt || '尚未');
        const lastRun = escapeHtml(target.lastRunAt || '尚未');
        return \`
        <article class="target">
          <div class="target-title">
            <div class="target-head">
              <h3 title="\${label}">\${label}</h3>
              <div class="meta" title="\${group}">\${group}</div>
            </div>
            <span class="badge"><span class="dot \${phaseClass}"></span>\${status}</span>
          </div>
          <div class="meta small">已記錄 \${seen} ｜ \${progress}</div>
          <div class="pagehealth \${pageHealthClass}">\${escapeHtml(pageHealthText)} · 上次成功 \${lastSuccess}</div>
          <div class="actions">
            <button class="good" onclick="runOnce('\${id}')">立即抓取</button>
            <button class="btn-link" onclick="clearGroupState('\${id}')">清空紀錄</button>
            <button class="btn-link danger-link" onclick="unbindGroup('\${id}')">解除綁定</button>
          </div>
          <details>
            <summary>詳細</summary>
            <div class="meta small">id: \${id}</div>
            <div class="meta small">chatId: \${chatId}</div>
            <div class="meta small">上次檢查：\${lastRun}</div>
          </details>
        </article>\`;
      }).join('');
    }

    async function scanPages() {
      try {
        setStatus('正在掃描專用 Chrome 的 LINE 頁面...');
        await api('/api/chrome/start', { method: 'POST', body: '{}' });
        const data = await api('/api/pages');
        // 只保留實際有 chatId 的聊天分頁（LINE 首頁 / 分類清單無 chatId）
        const chatPages = data.pages.filter(page => !!page.chatId);
        scannedPages = chatPages;
        if (chatPages.length === 1) {
          selectedPageIndex = chatPages[0].index;
          prefillBindFromPage(chatPages[0], true);
        } else if (chatPages.length && !chatPages.some(page => page.index === selectedPageIndex)) {
          selectedPageIndex = chatPages[0].index;
          prefillBindFromPage(chatPages[0], false);
        }
        if (!chatPages.length) {
          document.getElementById('pages').innerHTML = '<p class="meta">未找到聊天分頁。請在專用 Chrome 登入 LINE 並點進要抓的群組。</p>';
          setStatus('未找到聊天分頁');
          return;
        }
        document.getElementById('pages').innerHTML = chatPages.map(page => \`
          <div class="page \${selectedPageIndex === page.index ? 'selected' : ''}" onclick="selectPage(\${page.index})">
            <strong>\${escapeHtml(page.chatroomName || page.selectedChatTitle || '(未知群組)')}</strong>
            <div class="meta">\${escapeHtml(page.selectedChatDescription || '')}</div>
          </div>
        \`).join('');
        setStatus(\`找到 \${chatPages.length} 個聊天分頁\`);
      } catch (error) {
        showError(error);
      }
    }

    function selectPage(index) {
      selectedPageIndex = index;
      const page = scannedPages.find(item => item.index === index) || {};
      prefillBindFromPage(page, true);
      scanPages();
    }

    async function bindGroupSafe() {
      try {
        const id = document.getElementById('bindId').value.trim();
        if (!id) throw new Error('請輸入 Target ID，例如 metro2。');
        const label = document.getElementById('bindLabel').value.trim();
        const selectedPage = scannedPages.find(item => item.index === selectedPageIndex) || {};
        const payload = {
          id,
          label,
          pageIndex: selectedPageIndex,
          chatId: selectedPage.chatId || '',
          pageUrl: selectedPage.url || '',
        };
        setStatus('正在綁定...');
        let data = await api('/api/bind', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        if (data.requiresConfirm) {
          const ok = confirm(data.message || '此操作可能覆蓋既有綁定，是否繼續？');
          if (!ok) {
            setStatus('已取消綁定');
            return;
          }
          if (data.reason === 'target_id_conflict') payload.confirmOverwrite = true;
          if (data.reason === 'chat_id_already_bound') payload.confirmDuplicateChatId = true;
          data = await api('/api/bind', {
            method: 'POST',
            body: JSON.stringify(payload),
          });
        }
        const actionText = data.action === 'created'
          ? '新增'
          : (data.action === 'updated' ? '更新' : '已綁定');
        setStatus(\`\${actionText}：\${data.target.label}，準備首次抓取...\`);
        // /api/run 內部會 openTargetTab，不用先額外 openAllTabs；bridge 也會等 LINE render 完
        try {
          await api('/api/run', { method: 'POST', body: JSON.stringify({ id: data.target.id }) });
          setStatus(\`\${actionText}完成：\${data.target.label} - 首次抓取已啟動\`);
        } catch (runErr) {
          setStatus(\`\${actionText}完成但首次抓取失敗：\${runErr.message}\`, { error: true });
        }
        await refreshAll();
      } catch (error) {
        showError(error);
      }
    }

    async function openTab(id) {
      try {
        setStatus(\`正在打開 \${id} 的群組分頁...\`);
        const data = await api('/api/tabs/open', { method: 'POST', body: JSON.stringify({ id }) });
        const action = data.tab && data.tab.reused ? '已切到既有分頁' : '已打開新分頁';
        setStatus(\`\${action}：\${id}\`);
        await refreshTargets();
      } catch (error) {
        showError(error);
      }
    }

    async function openAllTabs() {
      try {
        setStatus('正在補齊全部已綁定群組分頁...');
        const data = await api('/api/tabs/open-all', { method: 'POST', body: '{}' });
        const tabs = data.tabs || [];
        const opened = tabs.filter(tab => tab.opened).length;
        const reused = tabs.filter(tab => tab.reused).length;
        const failed = tabs.filter(tab => tab.error).length;
        setStatus(\`群組分頁已補齊：新開 \${opened}，已存在 \${reused}，失敗 \${failed}\`);
        await refreshTargets();
      } catch (error) {
        showError(error);
      }
    }

    async function runOnce(id) {
      try {
        setStatus(\`開始抓取 \${id}...\`);
        await api('/api/run', { method: 'POST', body: JSON.stringify({ id }) });
        await refreshAll();
      } catch (error) {
        showError(error);
      }
    }

    async function clearGroupState(id) {
      if (!confirm('確定清空 ' + id + ' 的下載紀錄（seenKeys）？\\n\\n下次執行時會重新判斷所有可見的圖是否下載。已下載的檔案不會被刪除。')) return;
      try {
        await api('/api/targets/clear-state', { method: 'POST', body: JSON.stringify({ id }) });
        setStatus('已清空紀錄：' + id);
        await refreshAll();
      } catch (error) {
        showError(error);
      }
    }

    async function unbindGroup(id) {
      if (!confirm('確定解除綁定 ' + id + '？\\n\\n將刪除 target 設定 + seenKeys（已下載的檔案不會被刪除）。\\n之後可重新綁定。')) return;
      try {
        await api('/api/targets/unbind', { method: 'POST', body: JSON.stringify({ id }) });
        setStatus('已解除綁定：' + id);
        await refreshAll();
      } catch (error) {
        showError(error);
      }
    }

    async function startAllWatch() {
      try {
        setStatus('正在啟動全部群組監控...');
        const data = await api('/api/watch/start-all', { method: 'POST', body: '{}' });
        setStatus(\`已啟動 \${(data.jobs || []).length} 個群組監控\`);
        await refreshAll();
      } catch (error) {
        showError(error);
      }
    }

    async function stopAllWatch() {
      try {
        setStatus('正在停止全部群組監控...');
        const data = await api('/api/watch/stop-all', { method: 'POST', body: '{}' });
        setStatus(\`已停止 \${(data.jobs || []).length} 個群組監控\`);
        await refreshAll();
      } catch (error) {
        showError(error);
      }
    }

    async function startChrome() {
      try {
        const data = await api('/api/chrome/start', { method: 'POST', body: '{}' });
        if (data.existingChrome && data.openedTab) {
          setStatus('專用 Chrome 已存在，已在同一個 Chrome 開新 LINE 分頁');
        } else {
          setStatus(\`已啟動專用 Chrome，port \${data.port}\`);
        }
      } catch (error) {
        showError(error);
      }
    }

    async function refreshAll() {
      try {
        await refreshTargets();
      } catch (error) {
        showError(error);
      }
    }

    refreshAll();
    setInterval(refreshAll, 5000);
  </script>
</body>
</html>`;

module.exports = {
  startServer,
};
