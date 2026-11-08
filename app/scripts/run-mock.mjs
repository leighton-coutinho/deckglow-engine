// `npm run mock [-- --port 9980]`: the stand-in bridge (touchDesigner/tools/mock_bridge.py),
// for working on the app without TouchDesigner. Same protocol code as the real bridge.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { findPython } from './python.mjs';
const script = fileURLToPath(new URL('../../touchDesigner/tools/mock_bridge.py', import.meta.url));
const child = spawn(findPython(), ['-I', '-u', script, ...process.argv.slice(2)], { stdio: 'inherit' });
child.on('exit', (code) => process.exit(code ?? 0));
