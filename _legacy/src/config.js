const fs = require('fs/promises');
const path = require('path');

const APP_DIR = path.resolve(__dirname, '..');
const ROOT_DIR = path.resolve(APP_DIR, '..');
const CONFIG_DIR = path.join(ROOT_DIR, 'config');
const TARGETS_PATH = path.join(CONFIG_DIR, 'targets.json');

async function ensureTargetsFile() {
  await fs.mkdir(CONFIG_DIR, { recursive: true });
  try {
    await fs.access(TARGETS_PATH);
  } catch {
    await fs.writeFile(TARGETS_PATH, JSON.stringify({ targets: [] }, null, 2), 'utf8');
  }
}

async function readTargetsConfig() {
  await ensureTargetsFile();
  const raw = await fs.readFile(TARGETS_PATH, 'utf8');
  const parsed = JSON.parse(raw);
  return {
    targets: Array.isArray(parsed.targets) ? parsed.targets : [],
  };
}

async function writeTargetsConfig(config) {
  await ensureTargetsFile();
  await fs.writeFile(TARGETS_PATH, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
}

async function upsertTarget(target) {
  const config = await readTargetsConfig();
  const index = config.targets.findIndex(item => item.id === target.id);
  if (index >= 0) {
    config.targets[index] = target;
  } else {
    config.targets.push(target);
  }
  await writeTargetsConfig(config);
  return target;
}

async function removeTarget(id) {
  const config = await readTargetsConfig();
  const idx = config.targets.findIndex(t => t.id === id);
  if (idx < 0) return false;
  config.targets.splice(idx, 1);
  await writeTargetsConfig(config);
  return true;
}

async function getTargetById(id) {
  const config = await readTargetsConfig();
  return config.targets.find(target => target.id === id) || null;
}

function resolveProjectPath(value) {
  return path.isAbsolute(value) ? value : path.join(ROOT_DIR, value);
}

async function ensureTargetDirs(target) {
  const dirs = [target.downloadDir, target.travelDir, target.otherDir, target.errorDir]
    .filter(Boolean)
    .map(resolveProjectPath);
  await Promise.all(dirs.map(dir => fs.mkdir(dir, { recursive: true })));
}

module.exports = {
  APP_DIR,
  ROOT_DIR,
  TARGETS_PATH,
  readTargetsConfig,
  writeTargetsConfig,
  upsertTarget,
  removeTarget,
  getTargetById,
  resolveProjectPath,
  ensureTargetDirs,
};
