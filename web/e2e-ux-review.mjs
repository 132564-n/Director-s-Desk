import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const screenshots = join(process.cwd(), "..", "data", "screenshots");
await mkdir(screenshots, { recursive: true });
const errors = [];

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });

  await page.keyboard.press("Tab");
  const skipLinkFocused = await page.evaluate(() => document.activeElement?.classList.contains("skip-link"));
  if (!skipLinkFocused) throw new Error("Skip link is not the first keyboard target");

  const resize = page.locator('.resize-handle[aria-label="调整会话栏宽度"]');
  const widthBefore = (await page.locator(".conversation-drawer").boundingBox())?.width ?? 0;
  await resize.focus();
  await page.keyboard.press("ArrowRight");
  const widthAfter = (await page.locator(".conversation-drawer").boundingBox())?.width ?? 0;
  if (widthAfter <= widthBefore) throw new Error("Keyboard sidebar resize failed");

  await page.getByRole("button", { name: "新建会话" }).click();
  await page.locator(".conversation-sheet").waitFor();
  await page.keyboard.press("Escape");
  await page.locator(".conversation-sheet").waitFor({ state: "detached" });

  await page.locator(".message-feed").evaluate((element) => { element.scrollTop = 0; });
  await page.locator(".message-feed").hover();
  await page.mouse.wheel(0, 300);
  await page.locator(".jump-latest").waitFor();
  await page.screenshot({ path: join(screenshots, "chat-layout-fixed-desktop.png"), fullPage: true });

  const mobile = await browser.newPage({ viewport: { width: 390, height: 667 } });
  mobile.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  mobile.on("pageerror", (error) => errors.push(error.message));
  await mobile.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  if (await mobile.locator(".drawer-scrim").isVisible()) throw new Error("Mobile drawer opens by default");
  await mobile.screenshot({ path: join(screenshots, "chat-layout-fixed-mobile.png"), fullPage: true });
  await mobile.getByRole("button", { name: "打开会话栏" }).click();
  await mobile.waitForTimeout(250);
  const drawerBox = await mobile.locator(".conversation-drawer").boundingBox();
  if (!drawerBox || drawerBox.x < -1) throw new Error("Mobile conversation drawer did not open");

  if (errors.length) throw new Error(`Console errors: ${errors.join(" | ")}`);
  console.log(JSON.stringify({
    skipLinkFocused,
    keyboardResizeDelta: widthAfter - widthBefore,
    desktop: "chat-layout-fixed-desktop.png",
    mobile: "chat-layout-fixed-mobile.png",
    consoleErrors: 0,
  }));
} finally {
  await browser.close();
}
