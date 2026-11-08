// Finds a Python 3 to run the runtime's plain-Python tools (mock bridge).
// TouchDesigner's bundled Python is preferred; DECKGLOW_PYTHON overrides.
import { existsSync } from 'node:fs';
export function findPython() {
  const candidates = [
    process.env.DECKGLOW_PYTHON,
    'C:/Program Files/Derivative/TouchDesigner/bin/python.exe',
  ].filter(Boolean);
  for (const c of candidates) if (existsSync(c)) return c;
  return process.platform === 'win32' ? 'python' : 'python3';
}
