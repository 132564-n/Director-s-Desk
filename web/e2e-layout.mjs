import { chromium } from "playwright-core";

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});

const viewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
  { width: 390, height: 667 },
  { width: 320, height: 568 },
];
const results = [];

try {
  for (const viewport of viewports) {
    const page = await browser.newPage({ viewport });
    await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
    const scrim = page.locator(".drawer-scrim");
    const drawerInitiallyVisible = await scrim.isVisible();
    if (drawerInitiallyVisible) {
      await scrim.evaluate((element) => element.click());
      await page.waitForTimeout(250);
    }
    await page.locator(".message-feed").waitFor();
    const before = await page.evaluate(() => {
      const shell = document.querySelector(".chat-shell");
      const stage = document.querySelector(".chat-stage");
      const header = document.querySelector(".chat-header");
      const feed = document.querySelector(".message-feed");
      const composer = document.querySelector(".chat-composer");
      if (!shell || !stage || !header || !feed || !composer) throw new Error("chat layout missing");
      const rect = (element) => element.getBoundingClientRect().toJSON();
      return {
        viewportHeight: window.innerHeight,
        bodyScrollHeight: document.body.scrollHeight,
        shell: rect(shell),
        stage: rect(stage),
        header: rect(header),
        feed: rect(feed),
        composer: rect(composer),
        feedClientHeight: feed.clientHeight,
        feedScrollHeight: feed.scrollHeight,
        overflowY: getComputedStyle(feed).overflowY,
      };
    });

    await page.locator(".message-feed").evaluate((element) => { element.scrollTop = 0; });
    await page.locator(".message-feed").hover();
    await page.mouse.wheel(0, 280);
    await page.waitForTimeout(100);
    const wheelScrollTop = await page.locator(".message-feed").evaluate((element) => element.scrollTop);
    const jumpButton = page.locator(".jump-latest");
    const jumpVisible = await jumpButton.isVisible();
    if (jumpVisible) {
      await jumpButton.click();
      await page.waitForTimeout(350);
    }
    const latestGap = await page.locator(".message-feed").evaluate(
      (element) => element.scrollHeight - element.clientHeight - element.scrollTop,
    );
    const failures = [];
    if (before.composer.bottom > before.viewportHeight + 1) failures.push("composer below viewport");
    if (before.composer.right > viewport.width + 1) failures.push("composer overflows horizontally");
    if (before.header.right > viewport.width + 1) failures.push("header overflows horizontally");
    if (before.composer.top < before.header.bottom - 1) failures.push("composer overlaps header");
    if (before.feedClientHeight < 120) failures.push("message feed squeezed below 120px");
    if (before.overflowY !== "auto") failures.push("message feed is not scrollable");
    if (before.feedScrollHeight > before.feedClientHeight && wheelScrollTop <= 0) failures.push("wheel cannot scroll feed");
    if (before.feedScrollHeight > before.feedClientHeight && !jumpVisible) failures.push("jump-to-latest control missing");
    if (jumpVisible && latestGap > 2) failures.push("jump-to-latest did not reach bottom");
    if (before.bodyScrollHeight > before.viewportHeight + 1) failures.push("page itself overflows viewport");
    if (viewport.width <= 760 && drawerInitiallyVisible) failures.push("mobile drawer opens by default");
    results.push({ viewport, drawerInitiallyVisible, ...before, wheelScrollTop, jumpVisible, latestGap, failures });
    await page.close();
  }
} finally {
  await browser.close();
}

console.log(JSON.stringify(results, null, 2));
const failed = results.filter((result) => result.failures.length);
if (failed.length) throw new Error(`Chat layout regression: ${failed.map((item) => `${item.viewport.width}x${item.viewport.height}: ${item.failures.join(", ")}`).join(" | ")}`);
