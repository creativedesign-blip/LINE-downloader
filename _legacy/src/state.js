const fs = require('fs/promises');
const path = require('path');

const { ROOT_DIR } = require('./config');

const STATE_DIR = path.join(ROOT_DIR, 'config', 'state');

function getTargetStatePath(targetId) {
  return path.join(STATE_DIR, `${targetId}.json`);
}

async function readTargetState(targetId) {
  const filepath = getTargetStatePath(targetId);
  try {
    const raw = await fs.readFile(filepath, 'utf8');
    const parsed = JSON.parse(raw);
    return {
      version: 1,
      seenKeys: Array.isArray(parsed.seenKeys) ? parsed.seenKeys.filter(Boolean) : [],
      lastRunAt: parsed.lastRunAt || null,
      lastSuccessAt: parsed.lastSuccessAt || null,
    };
  } catch (error) {
    if (error && error.code === 'ENOENT') {
      return {
        version: 1,
        seenKeys: [],
        lastRunAt: null,
        lastSuccessAt: null,
      };
    }
    throw error;
  }
}

async function writeTargetState(targetId, state) {
  await fs.mkdir(STATE_DIR, { recursive: true });
  const filepath = getTargetStatePath(targetId);
  const payload = {
    version: 1,
    seenKeys: Array.from(new Set((state.seenKeys || []).filter(Boolean))).slice(-5000),
    lastRunAt: state.lastRunAt || null,
    lastSuccessAt: state.lastSuccessAt || null,
  };
  await fs.writeFile(filepath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  return payload;
}

async function clearTargetState(targetId) {
  await writeTargetState(targetId, { seenKeys: [], lastRunAt: null, lastSuccessAt: null });
}

async function removeTargetState(targetId) {
  const filepath = getTargetStatePath(targetId);
  try { await fs.unlink(filepath); }
  catch (error) { if (error && error.code !== 'ENOENT') throw error; }
}

module.exports = {
  STATE_DIR,
  getTargetStatePath,
  readTargetState,
  writeTargetState,
  clearTargetState,
  removeTargetState,
};
