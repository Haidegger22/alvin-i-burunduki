/* Запись игрового процесса через Chrome DevTools Protocol.
 *
 * Что делает:
 *   1. подключается к headless-Chromium (порт задаётся аргументом),
 *   2. открывает игру, жмёт клавиши по сценарию (как живой игрок),
 *   3. снимает кадры раз в N миллисекунд в каталог frames/,
 *   4. собирает список ошибок JS и печатает отчёт.
 *
 * Запуск: node tools/shoot.js --port 9333 --url "http://127.0.0.1:8123/index.html" \
 *          --out frames --fps 10 --seconds 20
 */
const fs = require("fs");
const path = require("path");
const http = require("http");

const args = {};
process.argv.slice(2).forEach((a, i, arr) => {
  if (a.startsWith("--")) args[a.slice(2)] = arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : true;
});

const PORT = Number(args.port || 9333);
const URL = args.url || "http://127.0.0.1:8123/index.html";
const OUT = args.out || "frames";
const FPS = Number(args.fps || 10);
const SECONDS = Number(args.seconds || 20);
const WIDTH = Number(args.width || 960);
const HEIGHT = Number(args.height || 600);
const TICKS = Number(args.ticks || 0); // >0 — пошаговый режим: сколько игровых кадров на один снятый

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJSON(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => {
        try { resolve(JSON.parse(data)); } catch (e) { reject(e); }
      });
    }).on("error", reject);
  });
}

/* Сценарий нажатий: игрок идёт вправо, прыгает, берёт и бросает ящики,
 * в одном месте прячется в ящик (↓ + X).
 * Если в адресе есть #demo — игру ведёт её собственный авто-пилот,
 * и нажатия не нужны. */
function buildTimeline(url) {
  if (url.includes("#demo")) return [];
  const t = [];
  t.push({ at: 0.3, code: "Enter", key: "Enter" });
  t.push({ at: 0.6, code: "ArrowRight", key: "ArrowRight", hold: true });
  [2.2, 4.0, 6.2, 8.4, 10.6, 12.8, 15.0, 17.2].forEach((at) => {
    t.push({ at, code: "KeyZ", key: "z", hold: false, dur: 0.35 });
  });
  [3.0, 5.4, 7.6, 9.8, 12.0, 14.2, 16.4, 18.2].forEach((at) => {
    t.push({ at, code: "KeyX", key: "x", hold: false, dur: 0.12 });
  });
  return t.sort((a, b) => a.at - b.at);
}

async function main() {
  const version = await getJSON(`http://127.0.0.1:${PORT}/json/version`);
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  let nextId = 1;
  const pending = new Map();
  const errors = [];
  let sessionId = null;

  const send = (method, params = {}, useSession = true) => {
    const id = nextId++;
    const msg = { id, method, params };
    if (useSession && sessionId) msg.sessionId = sessionId;
    ws.send(JSON.stringify(msg));
    return new Promise((resolve) => pending.set(id, resolve));
  };

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg.result || msg.error);
      pending.delete(msg.id);
      return;
    }
    if (msg.method === "Runtime.exceptionThrown") {
      errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    }
    if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
      errors.push(msg.params.args.map((a) => a.value || a.description).join(" "));
    }
  };

  const target = await send("Target.createTarget", { url: "about:blank" }, false);
  const attached = await send("Target.attachToTarget", { targetId: target.targetId, flatten: true }, false);
  sessionId = attached.sessionId;

  await send("Runtime.enable");
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", {
    width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false,
  });

  const loaded = new Promise((resolve) => {
    const check = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.method === "Page.loadEventFired") {
        ws.removeEventListener("message", check);
        resolve();
      }
    };
    ws.addEventListener("message", check);
  });
  await send("Page.navigate", { url: URL });
  await loaded;
  await sleep(1200); // дать спрайтам и звуку загрузиться

  fs.mkdirSync(OUT, { recursive: true });
  const timeline = buildTimeline(URL);
  const totalFrames = Math.round(FPS * SECONDS);
  const stepMs = 1000 / FPS;
  const started = Date.now();
  const held = new Set();

  const pressKey = async (code, key, down) => {
    await send("Input.dispatchKeyEvent", {
      type: down ? "keyDown" : "keyUp",
      code,
      key,
      windowsVirtualKeyCode: code === "Enter" ? 13 : code === "ArrowRight" ? 39 : key.toUpperCase().charCodeAt(0),
      nativeVirtualKeyCode: code === "Enter" ? 13 : 0,
    });
  };

  let lastState = null;
  for (let i = 0; i < totalFrames; i += 1) {
    if (TICKS > 0) {
      // пошаговый режим: игру двигаем мы, а не таймер браузера
      const step = await send("Runtime.evaluate", {
        expression: `window.__step(${TICKS})`,
        returnByValue: true,
      });
      lastState = step?.result?.value ?? lastState;
    } else {
      const elapsed = (Date.now() - started) / 1000;
      for (const item of timeline) {
        if (elapsed >= item.at && !item.done) {
          item.done = true;
          await pressKey(item.code, item.key, true);
          held.add(item.code);
          if (!item.hold) {
            setTimeout(async () => {
              await pressKey(item.code, item.key, false);
              held.delete(item.code);
            }, (item.dur || 0.1) * 1000);
          }
        }
      }
    }
    const shot = await send("Page.captureScreenshot", { format: "png" });
    if (shot && shot.data) {
      fs.writeFileSync(path.join(OUT, `frame_${String(i).padStart(4, "0")}.png`), Buffer.from(shot.data, "base64"));
    }
    if (TICKS === 0) await sleep(Math.max(0, stepMs - 40));
  }

  for (const code of held) await pressKey(code, code.toLowerCase(), false);
  if (lastState) console.log("состояние игры в конце:", lastState);
  const state = await send("Runtime.evaluate", { expression: "JSON.stringify({state: window.__game?.state, score: window.__game?.score, px: Math.round(window.__game?.players?.[0]?.x || 0), hearts: window.__game?.players?.[0]?.hearts, enemies: window.__game?.enemies?.length, crates: window.__game?.crates?.length})", returnByValue: true });

  console.log("состояние игры в конце:", state?.result?.value || state);
  console.log("кадров записано:", fs.readdirSync(OUT).length, "->", OUT);
  if (errors.length) {
    console.log("=== ОШИБКИ JS:", errors.length);
    errors.slice(0, 10).forEach((e) => console.log("   ", String(e).slice(0, 200)));
  } else {
    console.log("=== ошибок JS нет");
  }
  ws.close();
}

main().catch((err) => {
  console.error("ошибка записи:", err.message);
  process.exit(1);
});
