// Removes dist/ so a renamed or deleted source file never lingers in a build.
import { rmSync } from 'node:fs';
rmSync(new URL('../dist', import.meta.url), { recursive: true, force: true });
