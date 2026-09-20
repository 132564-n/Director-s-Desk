import assert from "node:assert/strict";
import { chromium } from "playwright-core";

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});

const now = new Date().toISOString();
const longMessage = [
  "结论：开场应先给出失控的送信动作，再揭示主角身份。",
  "依据：动作钩子比世界观说明更快，前三秒已有明确危险和目标。",
  "风险或异议：如果立刻解释旧城规则，节奏会被说明文字拖慢。",
  "建议动作：保留一处视觉线索，把规则解释推迟到第二场。",
  "详细说明：镜头从被雨打湿的信封开始，跟随手部进入奔跑动作；转角后只让观众看到追兵投影，不展示全貌。第二场再借守门人的阻拦补充规则。这样既能建立悬念，也能让角色通过行动完成信息交代。为了验证折叠区域，这里保留足够长的制作补充，包括机位、节奏、信息顺序和连续性提醒，但默认不占据会议主视图。",
].join("\n");

const conversation = {
  id: "conversation-phase2",
  episode_id: "project-phase2",
  title: "开场钩子会",
  goal: "确定前三秒钩子",
  members: ["总导演", "编剧", "分镜导演", "连续性审校"],
  template: "剧情会",
  created_at: now,
  updated_at: now,
  status: "running",
  pinned: false,
  archived: false,
  active_turn_id: "message-user",
  current_round: 2,
  max_rounds: 4,
  discussion_note: "人物动机仍需编剧与审校确认",
  calls_made: 5,
  proposals: {},
  decisions: {},
  messages: [
    { id: "message-system", kind: "system", content: "会话已建立。", created_at: now, sender_name: "系统", sender_role: null, model: "", round: 0, reply_to: null, attachment_ids: [], proposal_id: null, discarded: false },
    { id: "message-user", kind: "user", content: "讨论开场钩子", created_at: now, sender_name: "你", sender_role: null, model: "autonomous", round: 0, reply_to: null, attachment_ids: [], proposal_id: null, discarded: false },
    { id: "message-agent", kind: "agent", content: longMessage, created_at: now, sender_name: "编剧", sender_role: "编剧", model: "deepseek-flash", round: 2, reply_to: "message-user", attachment_ids: [], proposal_id: null, discarded: false },
  ],
};

const episodes = [{
  id: "project-phase2",
  title: "雾城来信",
  target_duration_seconds: 240,
  active_stage: "outline",
  stage_statuses: { outline: "ready", script: "blocked", direction: "blocked" },
}];
const shelf = { proposals: [], decisions: [], artifacts: [], assets: [] };

try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  await page.route("http://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = { "access-control-allow-origin": "*", "content-type": "application/json" };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
    if (url.pathname === "/episodes") return route.fulfill({ json: episodes, headers });
    if (url.pathname === "/conversations") return route.fulfill({ json: [conversation], headers });
    if (url.pathname === "/conversations/conversation-phase2") return route.fulfill({ json: conversation, headers });
    if (url.pathname === "/episodes/project-phase2/shelf") return route.fulfill({ json: shelf, headers });
    return route.fulfill({ status: 404, json: { detail: "mock route missing" }, headers });
  });

  await page.goto("http://127.0.0.1:3000", { waitUntil: "domcontentloaded" });
  await page.locator(".message-copy details").waitFor();
  assert.match(await page.locator(".run-ticket").innerText(), /R2\/4/);
  assert.match(await page.locator(".agent-typing").innerText(), /人物动机仍需编剧与审校确认/);
  assert.match(await page.locator(".agent-typing").innerText(), /5 次模型调用/);
  const detail = page.locator(".message-copy details");
  assert.equal(await detail.getAttribute("open"), null);
  await detail.locator("summary").click();
  assert.ok(await detail.getAttribute("open") !== null);
  assert.match(await detail.innerText(), /镜头从被雨打湿的信封开始/);

  await page.setViewportSize({ width: 390, height: 667 });
  const layout = await page.evaluate(() => {
    const composer = document.querySelector(".chat-composer")?.getBoundingClientRect();
    return {
      overflow: document.documentElement.scrollWidth > innerWidth,
      composerBottom: composer?.bottom ?? 0,
      viewportHeight: innerHeight,
    };
  });
  assert.equal(layout.overflow, false);
  assert.ok(layout.composerBottom <= layout.viewportHeight + 1);
  assert.deepEqual(errors, []);
  console.log("PASS: adaptive round status, call progress, long-message expansion, mobile composer; endpoints mocked, user data unchanged.");
} finally {
  await browser.close();
}
