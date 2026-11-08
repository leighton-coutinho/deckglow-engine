// `npm run stage`: collects what the installer ships into app/build/:
//   build/runtime/   the TouchDesigner runtime (copied to Documents\DeckGlow by setup)
//   build/engine/    ReactiveVisualEngine.exe (Release, static C++ runtime)
//
// Ships the program only - never this computer's state: no Packs/, bridge
// token, backups, numbered autosaves, preview images or smoke output; only the
// first-party approvals and validation reports (com.deckglow.*), and not the
// Stub Scene test fixture.
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = fileURLToPath(new URL('..', import.meta.url));
const REPO = path.resolve(APP, '..');
const TD = path.join(REPO, 'touchDesigner');
const OUT = path.join(APP, 'build');
const RT = path.join(OUT, 'runtime');
const ENGINE = process.env.DECKGLOW_ENGINE_EXE || path.join(REPO, 'x64', 'Release', 'ReactiveVisualEngine.exe');
const version = JSON.parse(readFileSync(path.join(APP, 'package.json'), 'utf8')).version;

const fail = (msg) => { console.error(`stage: ${msg}`); process.exit(1); };
if (!existsSync(ENGINE)) fail(`no engine at ${ENGINE} - build it: MSBuild ReactiveVisualEngine.vcxproj -p:Configuration=Release -p:Platform=x64`);
const PROJECT = path.join(TD, 'engine_input_block1.toe');
if (!existsSync(PROJECT)) fail('no touchDesigner/engine_input_block1.toe');

rmSync(OUT, { recursive: true, force: true });
mkdirSync(path.join(RT, 'touchDesigner', 'library'), { recursive: true });
mkdirSync(path.join(RT, 'touchDesigner', 'validation'), { recursive: true });
mkdirSync(path.join(OUT, 'engine'), { recursive: true });

const skip = (src) => /(__pycache__|\.toe\.dir|\.toe\.toc|\.pyc$)/.test(src);
const copy = (rel, filter = () => true) => cpSync(path.join(REPO, rel), path.join(RT, rel), {
  recursive: true, filter: (src) => !skip(src) && filter(src),
});

copy('touchDesigner/engine_input_block1.toe');
copy('touchDesigner/modules', (src) => !/[\\/]stub_scene([\\/]|$)/.test(src));
copy('touchDesigner/tools');
copy('touchDesigner/examples');
copy('docs');

// first-party approvals and reports only
const approved = JSON.parse(readFileSync(path.join(TD, 'library', 'approved.json'), 'utf8'));
const firstParty = Object.fromEntries(Object.entries(approved.approved || {}).filter(([id]) => id.startsWith('com.deckglow.')));
writeFileSync(path.join(RT, 'touchDesigner', 'library', 'approved.json'), JSON.stringify({ ...approved, approved: firstParty }, null, 2) + '\n');
const folders = new Set(Object.values(firstParty).map((a) => a.folder));
let reports = 0;
for (const f of readdirSync(path.join(TD, 'validation'))) {
  if (folders.has(f.replace(/\.json$/, ''))) {
    cpSync(path.join(TD, 'validation', f), path.join(RT, 'touchDesigner', 'validation', f));
    reports++;
  }
}

let commit = null;
try { commit = execFileSync('git', ['-C', REPO, 'rev-parse', '--short', 'HEAD'], { encoding: 'utf8' }).trim(); } catch { /* not a checkout */ }
writeFileSync(path.join(RT, 'runtime.json'), JSON.stringify({ version, built: new Date().toISOString(), commit }, null, 2) + '\n');
cpSync(ENGINE, path.join(OUT, 'engine', 'ReactiveVisualEngine.exe'));

const size = (dir) => readdirSync(dir, { withFileTypes: true }).reduce((n, e) => n + (e.isDirectory() ? size(path.join(dir, e.name)) : statSync(path.join(dir, e.name)).size), 0);
console.log(`stage: runtime ${version} (${commit ?? 'no commit'}) - ${(size(RT) / 1e6).toFixed(1)} MB, ${Object.keys(firstParty).length} approvals, ${reports} reports`);
console.log(`stage: modules ${readdirSync(path.join(RT, 'touchDesigner', 'modules')).join(', ')}`);
console.log(`stage: engine ${(statSync(path.join(OUT, 'engine', 'ReactiveVisualEngine.exe')).size / 1e3).toFixed(0)} KB`);
