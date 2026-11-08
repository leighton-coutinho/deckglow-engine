// Copies the renderer's static files (HTML, CSS, icons) next to its compiled JS.
import { cpSync, readdirSync } from 'node:fs';
const src = new URL('../src/renderer/', import.meta.url);
const dst = new URL('../dist/web/renderer/', import.meta.url);
for (const name of readdirSync(src)) {
  if (!name.endsWith('.ts')) cpSync(new URL(name, src), new URL(name, dst), { recursive: true });
}
// The renderer's compiled files are ES modules; say so for Node (the tests import them).
import { writeFileSync } from 'node:fs';
writeFileSync(new URL('../dist/web/package.json', import.meta.url), '{ "type": "module" }\n');
