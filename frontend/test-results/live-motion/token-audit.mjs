import fs from 'node:fs';
import path from 'node:path';

const src = path.resolve('src');
function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(path.join(dir, entry.name)) : [path.join(dir, entry.name)]);
}
const contents = files(src).filter(file => /\.(vue|css|js)$/.test(file)).map(file => ({ file, text: fs.readFileSync(file, 'utf8') }));
const tokens = new Set(contents.flatMap(({ text }) => [...text.matchAll(/(--[\w-]+)\s*:/g)].map(match => match[1])));
const issues = [];
for (const { file, text } of contents) {
  const relative = path.relative(src, file);
  for (const match of text.matchAll(/var\(\s*(--[\w-]+)|token(?:Duration|Length|Number|Ease|Value)\(\s*['"](--[\w-]+)['"]/g)) {
    const name = match[1] || match[2];
    if (!tokens.has(name)) issues.push({ file: relative, type: 'undefined-token', value: name });
  }
  if (relative !== path.join('styles', 'tokens.css')) {
    for (const match of text.matchAll(/#[\da-f]{3,8}\b|\b(?:rgba?|hsla?)\(\s*[\d.]/gi)) issues.push({ file: relative, type: 'hardcoded-color', value: match[0] });
  }
}
const result = { passed: issues.length === 0, checkedFiles: contents.length, definedTokens: tokens.size, issues };
fs.writeFileSync(path.resolve('test-results/live-motion/token-audit.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
process.exitCode = result.passed ? 0 : 1;
