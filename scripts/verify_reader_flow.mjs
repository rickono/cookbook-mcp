/* Synthetic loopback preview only. Start scripts/preview_reader.py separately.
   PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node scripts/verify_reader_flow.mjs
   Requires Playwright and an installed Chrome. No books or screenshots are saved. */
import assert from 'node:assert/strict';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = new URL(process.argv[2] || 'http://localhost:8766');
assert.equal(origin.origin, 'http://localhost:8766', 'Use the synthetic loopback preview');
const browser = await chromium.launch({headless:true, channel:'chrome'});
try {
  const page = await browser.newPage({viewport:{width:1280,height:900}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin + 'reader/login');
  await page.waitForURL('**/reader/catalog');
  assert.match(await page.locator('.preview-banner').textContent(), /Local preview/);
  await page.getByRole('link',{name:'The Weeknight Table',exact:false}).first().click();
  await page.getByRole('link',{name:'Text view',exact:true}).click();
  await page.getByRole('link',{name:'Start reading',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.reader-view.reading-focused'));
  assert.equal(await page.locator('.reading-tools').isVisible(), false);

  const contents = page.locator('.reading-preferences').getByText('Contents',{exact:true});
  await contents.click();
  await page.getByRole('navigation',{name:'Book contents',exact:true}).getByRole('link',{name:'A slower kind of supper',exact:true}).click();
  await page.locator('.reading-preferences:not([hidden])').waitFor();
  const at = new URL(page.url()).searchParams.get('at');
  let expected = '', next = at;
  while (next) {
    const response = await page.request.get(origin + 'reader/content?' + new URLSearchParams({at:next}));
    assert.equal(response.status(),200);
    const data = await response.json();
    expected += data.text;
    next = data.next_text;
  }
  assert.ok(await page.locator('[data-next-text]').count(), 'Sample must exercise continuation');
  const beforeFocus = await page.evaluate(() => document.activeElement.id);
  while (await page.locator('[data-next-text]').count()) {
    const count = await page.locator('#text .source-text').count();
    await page.locator('[data-next-text]').scrollIntoViewIfNeeded();
    await page.waitForFunction(n => document.querySelectorAll('#text .source-text').length > n, count);
  }
  assert.equal(await page.evaluate(() => document.activeElement.id), beforeFocus, 'Automatic loading moved focus');
  const actual = await page.locator('#text .source-text').evaluateAll(nodes => nodes.map(node => node.textContent).join(''));
  assert.equal(actual, expected, 'Continuation lost or duplicated source text');
  assert.equal(await page.locator('#text .source-text').first().evaluate(node => getComputedStyle(node).display),'inline');
  assert.ok(Math.abs(await page.locator('.reading-preferences').evaluate(node => node.getBoundingClientRect().top)) <= 1);

  for (const width of [390,320]) {
    await page.setViewportSize({width,height:844});
    await contents.click();
    const menu = page.getByRole('navigation',{name:'Book contents',exact:true});
    const box = await menu.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= width, 'Contents extends beyond viewport');
    await page.keyboard.press('Escape');
    assert.equal(await menu.isVisible(),false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false);
  }
  await contents.click();
  await page.getByRole('navigation',{name:'Book contents',exact:true}).getByRole('link',{name:'Lemony white beans with greens',exact:true}).click();
  await page.locator('.type-menu summary').click();
  await page.getByRole('button',{name:'Larger text',exact:true}).click();
  await page.keyboard.press('Escape');
  await page.locator('[data-book-next]').click();
  assert.equal(await page.locator('.reading-head h1').textContent(),'Green herb sauce');
  await page.locator('.type-menu summary').click();
  assert.equal(await page.locator('output[data-text-size]').textContent(),'115%');
  await page.keyboard.press('Escape');
  await contents.click();
  await page.getByRole('navigation',{name:'Book contents',exact:true}).getByRole('link',{name:'A slower kind of supper',exact:true}).click();
  let interrupt = true;
  await page.route('**/reader/content?*', route => interrupt ? (interrupt=false, route.abort()) : route.continue());
  await page.locator('[data-next-text]').scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector('[data-reading-status]').textContent.includes('interrupted'));
  const earlier = await page.locator('#text .source-text').first().textContent();
  await page.locator('[data-next-text]').click();
  await page.waitForFunction(() => !document.querySelector('[data-next-text]'));
  assert.equal(await page.locator('#text .source-text').first().textContent(),earlier);
  assert.deepEqual(errors,[]);
  console.log('PASS: complete scroll reading, preserved text/focus, reachable contents at desktop/390px/320px, chapter navigation, retained text size, interrupted-load recovery.');
} finally { await browser.close(); }
