// npm install playwright; NODE_PATH=<node_modules> CHROMIUM_PATH=/usr/bin/chromium node scripts/ui_smoke.cjs
// SM_BASE_URL selects an environment; SM_SESSION_COOKIE optionally supplies a tenant session.
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined,
    headless: true, args: ['--no-sandbox', '--no-proxy-server', '--host-resolver-rules=MAP demo.127.0.0.1.nip.io 127.0.0.1'] });
  try {
    const base = process.env.SM_BASE_URL || 'http://127.0.0.1:5000';
    for (const width of [360, 768, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: 900 },
        extraHTTPHeaders: process.env.SM_PROXY_TEST === '1' ? { 'X-Forwarded-Proto': 'https' } : {} });
      if (process.env.SM_SESSION_COOKIE) await context.addCookies([
        { name: 'sessionid', value: process.env.SM_SESSION_COOKIE, url: base }
      ]);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      page.on('requestfailed', r => errors.push(`Resource failed: ${r.url()}`));
      const paths = process.env.SM_PLATFORM === '1' ? ['/platform/', '/platform/tenants/'] : process.env.SM_SESSION_COOKIE ? ['/dashboard/', '/invoices/', '/finance/'] : ['/', '/login/'];
      for (const path of paths) {
        const response = await page.goto(base + path);
        if (!response.ok()) throw new Error(`${width} ${path}: HTTP ${response.status()}`);
        if (new URL(page.url()).pathname !== path) throw new Error(`Unexpected redirect from ${path}`);
        if (width < 992) {
          await page.locator('.navbar-toggler').click();
          await page.locator('#mainNavbar.show').waitFor();
        }
        await page.locator('#theme-toggle').click();
        const dark = await page.locator('html').getAttribute('data-theme');
        await page.reload();
        if (await page.locator('html').getAttribute('data-theme') !== dark) throw new Error('Theme not retained');
        if (process.env.SM_SESSION_COOKIE && width < 992) {
          const nav = process.env.SM_PLATFORM === '1' ? '#platform-navigation' : '#tenant-navigation';
          const button = page.locator(`button[data-bs-target="${nav}"]`);
          await button.click();
          await page.locator(`${nav}.show`).waitFor();
          if (!await page.locator(`${nav} a`).first().isVisible()) throw new Error('Workspace menu is inaccessible');
          await button.click();
          await page.locator(`${nav}:not(.show):not(.collapsing)`).waitFor({ state: 'attached' });
        }
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        if (overflow) throw new Error(`Horizontal page overflow: ${width} ${path}`);
        if (process.env.SM_SCREENSHOT_DIR) {
          const fs = require('node:fs');
          fs.mkdirSync(process.env.SM_SCREENSHOT_DIR, { recursive: true });
          await page.screenshot({ path: `${process.env.SM_SCREENSHOT_DIR}/${width}-${path.replaceAll('/', '') || 'home'}.png`, fullPage: true });
        }
        console.log(`PASS ${width}px ${path}: theme persistence, no page overflow`);
      }
      if (errors.length) throw new Error(errors.join('\n'));
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
