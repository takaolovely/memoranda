const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("web/index.html", "utf8");
const match = html.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(match, "inline application script exists");
const script = match[1];
new vm.Script(script, { filename: "web/index.html" });

function makeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => data.has(key) ? data.get(key) : null,
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
  };
}

class Element {
  constructor(id = "") {
    this.id = id;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.style = {};
    this.dataset = {};
    this.value = "";
    this.textContent = "";
    this._innerHTML = "";
    this.className = "";
    this.classList = { add() {}, remove() {}, toggle() {} };
    this.scrollHeight = 0;
    this.scrollTop = 0;
  }
  set innerHTML(value) {
    this._innerHTML = value;
    if (value === "") this.children = [];
  }
  get innerHTML() { return this._innerHTML; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key] || null; }
  querySelector() { return new Element(); }
  scrollIntoView() {}
  focus() {}
}

async function runPage(localStorage, replies, serverHistory) {
  const elements = new Map();
  const getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const document = {
    getElementById,
    createElement: () => new Element(),
    querySelectorAll: () => [],
    querySelector: () => null,
    documentElement: new Element("documentElement"),
    title: "Memoranda",
  };
  const fetch = async (url, options = {}) => {
    if (url.startsWith("/api/i18n")) return { json: async () => ({
      ui_welcome: "Welcome", ui_thinking: "Thinking…", ui_opening: "Opening…",
      ui_none_yet: "None yet", ui_rem_none: "No reminders", ui_biz_ac_service: "AC repair",
      unknown_key: "Unknown key", ui_open: "Open",
    }) };
    const body = options.body ? JSON.parse(options.body) : {};
    let out;
    if (url === "/api/pack" && body.action === "enter") {
      out = { ok: true, pack_id: "fixture-pack", lang: "en", currency: "USD", timezone: "UTC", state: { pack: { playbook: "ac_service" } } };
    } else if (url === "/api/state") {
      out = { ok: true, pack_id: "fixture-pack", lang: "en", currency: "USD", timezone: "UTC", queued: 0, history: serverHistory.slice(), state: { pack: { playbook: "ac_service" }, people: [] }, reminders: [] };
    } else if (url === "/api/turn" || url === "/api/web/turn") {
      out = replies.shift();
      // The web channel keeps its transcript on the server, not in browser
      // storage, so a later read of the same book sees the earlier lines.
      // /api/web/turn is the endpoint that persists; mirror that here.
      if (url === "/api/web/turn" && out && out.ok) {
        serverHistory.push({ role: "me", text: body.text });
        serverHistory.push({ role: "bot", text: out.say });
      }
    } else {
      throw new Error("unexpected request: " + url);
    }
    return { json: async () => out };
  };
  const context = {
    document, window: { sessionStorage: makeStorage() }, localStorage, fetch,
    navigator: { language: "en", clipboard: { writeText: async () => {} } },
    console, URLSearchParams, encodeURIComponent, setTimeout, clearTimeout,
  };
  vm.runInNewContext(script, context, { filename: "web/index.html" });
  for (let i = 0; i < 5; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  return { elements, context };
}

(async () => {
  const local = makeStorage({ fieldpack_key: "test-passkey", fieldpack_lang: "en" });
  // Stands in for the server-side transcript store (data/web_history.json).
  const serverHistory = [];
  const replies = [{ ok: true, kind: "answer", say: "Logged it for tomorrow.", state: { people: [] } }];
  const first = await runPage(local, replies, serverHistory);
  const input = first.context.document.getElementById("sayIn");
  const form = first.context.document.getElementById("sayForm");
  input.value = "Serviced the air conditioner for Alex";
  await form.listeners.submit({ preventDefault() {} });
  const firstTranscript = first.elements.get("log").children.map((node) => node.textContent);
  assert.ok(firstTranscript.includes("Serviced the air conditioner for Alex"));
  assert.ok(firstTranscript.includes("Logged it for tomorrow."));
  assert.equal(local.getItem("memoranda_chat_fixture-pack"), null, "transcript is not stored in persistent localStorage");
  assert.equal(serverHistory.length, 2, "the turn is persisted server-side, question and reply");

  const reloaded = await runPage(local, [], serverHistory);
  const restored = reloaded.elements.get("log").children.map((node) => node.textContent);
  assert.ok(restored.includes("Serviced the air conditioner for Alex"), "user message restored after page refresh");
  assert.ok(restored.includes("Logged it for tomorrow."), "assistant reply restored after page refresh");
  assert.equal(restored.filter((line) => line === "Logged it for tomorrow.").length, 1, "reply is not duplicated on refresh");
  console.log("PASS: chat transcript survives a simulated page refresh by being read back from the server, scoped by pack, with no duplicate response.");
})().catch((err) => { console.error(err); process.exit(1); });
