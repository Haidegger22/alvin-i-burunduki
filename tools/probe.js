/* Быстрый пробник состояния игры через CDP.
 *
 * Подключается к уже запущенному Chromium, находит вкладку с игрой и
 * выполняет переданное выражение. Удобно для отладки без перезапуска записи.
 *
 * Запуск: node tools/probe.js --port 9333 --expr "window.__game.state"
 *         node tools/probe.js --port 9333 --open "http://127.0.0.1:8123/index.html#demo"
 */
const http = require("http");

const args = {};
process.argv.slice(2).forEach((a, i, arr) => {
  if (a.startsWith("--")) args[a.slice(2)] = arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : true;
});
const PORT = Number(args.port || 9333);
const EXPR = args.expr || "1+1";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJSON(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let d = "";
      res.on("data", (c) => (d += c));
      res.on("end", () => resolve(JSON.parse(d)));
    }).on("error", reject);
  });
}

async function main() {
  const version = await getJSON(`http://127.0.0.1:${PORT}/json/version`);
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  let id = 1;
  const pending = new Map();
  let sessionId = null;

  const send = (method, params = {}, useSession = true) => {
    const msg = { id: id++, method, params };
    if (useSession && sessionId) msg.sessionId = sessionId;
    ws.send(JSON.stringify(msg));
    return new Promise((r) => pending.set(msg.id, r));
  };

  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result || m.error); pending.delete(m.id); }
  };

  const targets = await send("Target.getTargets", {}, false);
  const page = (targets.targetInfos || []).find((t) => t.type === "page" && !t.url.startsWith("about:"));
  if (!page) { console.error("нет открытой вкладки с игрой"); process.exit(1); }
  const attached = await send("Target.attachToTarget", { targetId: page.targetId, flatten: true }, false);
  sessionId = attached.sessionId;
  await send("Runtime.enable");

  if (args.open) {
    await send("Page.enable");
    await send("Page.navigate", { url: args.open });
    await sleep(2500);
  }
  if (args.wait) await sleep(Number(args.wait) * 1000);

  const res = await send("Runtime.evaluate", { expression: EXPR, returnByValue: true, awaitPromise: true });
  if (res && res.exceptionDetails) {
    console.log("ошибка выполнения:", res.exceptionDetails.exception?.description || res.exceptionDetails.text);
  } else {
    console.log(typeof res?.result?.value === "string" ? res.result.value : JSON.stringify(res?.result?.value, null, 1));
  }
  ws.close();
}

main().catch((e) => { console.error("пробник упал:", e.message); process.exit(1); });
