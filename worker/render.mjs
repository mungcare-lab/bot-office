/**
 * STUDIO 렌더 워커 — HTML → PNG (Playwright Chromium)
 * 사용: node render.mjs <spec.json>
 * spec: { html, width, height, out, scale? }
 * 실행 환경: playwright-core + Chromium. (GitHub Actions: npx playwright install chromium)
 */
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

const specPath = process.argv[2];
if (!specPath) {
  console.error('usage: node render.mjs <spec.json>');
  process.exit(2);
}
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const executablePath = process.env.CHROMIUM_PATH || undefined;
const browser = await chromium.launch({
  executablePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none'],
});
try {
  const page = await browser.newPage({
    viewport: { width: Number(spec.width), height: Number(spec.height) },
    deviceScaleFactor: Number(spec.scale ?? 2),
  });
  await page.setContent(spec.html, { waitUntil: 'load' });
  await page.evaluate(async () => {
    if (document.fonts?.ready) await document.fonts.ready;
  });
  await page.waitForTimeout(120);
  await page.screenshot({ path: spec.out, type: spec.type ?? 'png', fullPage: false });
  console.log(JSON.stringify({ ok: true, out: spec.out }));
} finally {
  await browser.close();
}
