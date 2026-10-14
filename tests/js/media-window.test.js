// A display window shows the media named for it, without the theme saying so.
//
// A media kind is named after the display it captures, so a window that is a display has
// exactly one obvious thing to show. Every theme wrote the same handful of lines to show
// it, and the Reference theme - written to demonstrate best practice - could not avoid
// them either. That is the signal a behavior belongs in core.
//
// The mapping is the part worth testing. A contract 1 window is called `bg` and its media
// is `backglass`; a window a theme invented is neither, and must resolve to nothing
// rather than to a lookup that quietly finds nothing.

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import { newCore, fixture } from "./support/load-core.js";

const ROWS = fixture("theme_payload.json").contract1;

const BRIDGE_DEFAULTS = {
  get_tables: "[]",
  get_theme_assets_port: 8000,
  get_initial_table_index: 0,
  get_theme_config: {},
  get_keymapping: {},
  get_joymaping: {},
  get_mainmenu_config: {},
  get_monitors: [],
  get_collections: [],
};

/** A core on a named window, with a page that may or may not offer a render target. */
async function coreOn(windowName, { target = true, themeConfig = {} } = {}) {
  const { vpin, browser } = newCore({ windowName });
  vpin.call = (method) => Promise.resolve(
    method === "get_theme_config" ? themeConfig : BRIDGE_DEFAULTS[method]);
  vpin.init();
  await browser.WebSocket.instances.at(-1).onopen();

  const stage = { children: [], getAttribute: () => "", replaceChildren(...kids) { this.children = kids; } };
  if (target) browser.document._queryAll["[data-vpin-media]"] = [stage];

  vpin.tableData = ROWS;
  vpin.themeAssetsPort = 8000;
  return { vpin, stage, browser };
}

// The receive path, which is how a secondary window learns the wheel moved. It is not
// the controller, so the send path's selection hook never runs there.
const step = (vpin, index = 0) =>
  vpin.handleEvent({ type: "TableIndexUpdate", index });

describe("the media kind a window shows", () => {
  test("a contract 1 window resolves through its own spelling", async () => {
    const { vpin } = await coreOn("bg");
    assert.equal(vpin.windowMediaKind, "backglass");
  });

  test("a contract 2 window is already the kind", async () => {
    const { vpin } = await coreOn("backglass");
    assert.equal(vpin.windowMediaKind, "backglass");
  });

  test("a window a theme invented is not a media kind", async () => {
    const { vpin } = await coreOn("marquee");
    assert.equal(vpin.windowMediaKind, null);
  });

  test("the controller is not a display, so it renders nothing here", async () => {
    // `table` is contract 1's playfield, which IS a kind - so the guard that keeps core
    // off the controller cannot be the kind lookup. A controller opts out by having no
    // target element, which is what every controller page looks like.
    const { vpin, stage } = await coreOn("table", { target: false });
    step(vpin);
    assert.deepEqual(stage.children, []);
  });
});

describe("core rendering the window's media", () => {
  test("it draws into the element the page offers", async () => {
    const { vpin, stage } = await coreOn("backglass");
    step(vpin);
    assert.equal(stage.children.length, 1);
  });

  test("a value on the element names the kind, in any window", async () => {
    const { vpin, browser } = await coreOn("table", { target: false });
    const named = { children: [], getAttribute: () => "playfield",
      replaceChildren(...kids) { this.children = kids; } };
    browser.document._queryAll["[data-vpin-media]"] = [named];
    step(vpin);
    assert.equal(named.children.length, 1);
  });

  test("every marked element is drawn into, each with its own kind", async () => {
    const { vpin, stage, browser } = await coreOn("backglass");
    const other = { children: [], getAttribute: () => "playfield",
      replaceChildren(...kids) { this.children = kids; } };
    browser.document._queryAll["[data-vpin-media]"] = [stage, other];
    step(vpin);
    assert.equal(stage.children.length, 1);
    assert.equal(other.children.length, 1);
  });

  test("a value that is not a kind draws nothing", async () => {
    const { vpin, browser } = await coreOn("backglass", { target: false });
    const odd = { children: [], getAttribute: () => "true",
      replaceChildren(...kids) { this.children = kids; } };
    browser.document._queryAll["[data-vpin-media]"] = [odd];
    step(vpin);
    assert.deepEqual(odd.children, []);
  });

  test("a page with no target is left alone", async () => {
    const { vpin, stage } = await coreOn("backglass", { target: false });
    step(vpin);
    assert.deepEqual(stage.children, []);
  });

  test("a theme can turn it off and keep the element", async () => {
    const { vpin, stage } = await coreOn("backglass",
      { themeConfig: { media_window: { enabled: false } } });
    step(vpin);
    assert.deepEqual(stage.children, []);
  });

  test("it is on without the theme asking", async () => {
    const { vpin } = await coreOn("backglass");
    assert.equal(vpin.enabled("core_media_window"), true);
  });

  test("it draws on startup, without waiting to be told the wheel moved", async () => {
    // The controller only broadcasts a restore when the remembered index is past the
    // first game. At index 0 nothing arrives, so a window that only drew on a selection
    // message stayed blank from launch - which is what the cabinet showed.
    const { vpin, browser } = newCore({ windowName: "backglass" });
    const stage = { children: [], getAttribute: () => "", replaceChildren(...kids) { this.children = kids; } };
    browser.document._queryAll["[data-vpin-media]"] = [stage];
    vpin.call = (method) => Promise.resolve(
      method === "get_tables" ? JSON.stringify(ROWS) : BRIDGE_DEFAULTS[method]);

    vpin.init();
    await browser.WebSocket.instances.at(-1).onopen();

    assert.equal(stage.children.length, 1, "nothing moved the wheel, and it still drew");
  });

  test("a page with no theme script still receives events", async () => {
    // The default is only usable if a window core draws needs no script of its own, and
    // incoming events reach handleEvent through window.receiveEvent - which a page with
    // no theme.js does not define. Core pumps its own in that case.
    const { vpin, stage, browser } = await coreOn("backglass");
    const socket = vpin._ws;
    delete browser.window.receiveEvent;

    socket.onmessage({ data: JSON.stringify(
      { type: "event", message: { type: "TableIndexUpdate", index: 0 } }) });
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.equal(stage.children.length, 1, "no script on the page, and it still drew");
  });
});

describe("playfield art drawn by core is turned to fit the surface", () => {
  const AFM = ROWS.findIndex((row) => row.tableDirName === "Attack from Mars (Bally 1995)");
  const MM = ROWS.findIndex((row) => row.tableDirName === "Medieval Madness (Williams 1997)");

  /** A marked element that answers attribute reads and holds what core draws into it. */
  async function drawn(kind, attributes = {}, { layout = true, priority } = {}) {
    const themeConfig = layout ? { layout: { enabled: true } } : {};
    const { vpin, browser } = await coreOn("table", { target: false, themeConfig });
    if (priority) vpin.mediaPriorities = { ...vpin.mediaPriorities, [kind]: priority };
    const target = {
      children: [],
      getAttribute: (name) => (name === "data-vpin-media" ? kind : attributes[name] ?? null),
      replaceChildren(...kids) { this.children = kids; },
    };
    browser.document._queryAll["[data-vpin-media]"] = [target];
    return { vpin, target, show: (index) => step(vpin, index) };
  }

  test("a playfield picture is marked and set up for rotation", async () => {
    const { target, show } = await drawn("playfield", {}, { priority: "image" });
    show(AFM);

    const [node] = target.children;
    assert.ok(node.classes.has("vpinfe-playfield-media"));
    assert.ok(node.listeners.load, "it is measured once the picture knows its size");
  });

  test("a playfield video is measured when its metadata arrives", async () => {
    const { target, show } = await drawn("playfield");
    show(AFM);

    const [node] = target.children;
    assert.ok(node.classes.has("vpinfe-playfield-media"));
    assert.ok(node.listeners.loadedmetadata);
  });

  test("a theme that did not opt into layout gets an unmarked node", async () => {
    const { target, show } = await drawn("playfield", {}, { layout: false });
    show(AFM);

    assert.equal(target.children[0].classes.size, 0);
  });

  test("a backglass is never turned", async () => {
    const { target, show } = await drawn("backglass");
    show(AFM);

    assert.equal(target.children[0].classes.size, 0);
  });

  test("the user's priority decides between the still and the video", async () => {
    const image = await drawn("playfield", {}, { priority: "image" });
    image.show(AFM);
    const video = await drawn("playfield", {}, { priority: "video" });
    video.show(AFM);

    assert.ok(image.target.children[0].src.endsWith(".png"));
    assert.ok(video.target.children[0].src.endsWith(".mp4"));
  });

  test("an element can ask for the still whatever the priority is", async () => {
    const { target, show } = await drawn("playfield",
      { "data-vpin-media-prefer": "image" }, { priority: "video" });
    show(AFM);

    assert.ok(target.children[0].src.endsWith(".png"));
  });

  test("an element can ask for the video whatever the priority is", async () => {
    const { target, show } = await drawn("playfield",
      { "data-vpin-media-prefer": "video" }, { priority: "image" });
    show(AFM);

    assert.ok(target.children[0].src.endsWith(".mp4"));
  });

  test("a preference for what a game lacks falls back to what it has", async () => {
    const { target, show } = await drawn("backglass", { "data-vpin-media-prefer": "video" });
    show(MM);

    assert.ok(target.children[0]?.src.endsWith(".png"), "no backglass video, so the still");
  });

  test("the same game again keeps its node", async () => {
    const { target, show } = await drawn("playfield");
    show(AFM);
    const [first] = target.children;
    show(AFM);

    assert.equal(target.children[0], first, "a playing video is not restarted");
  });

  test("a reloaded library draws it again", async () => {
    const { vpin, target, show } = await drawn("playfield");
    show(AFM);
    const [first] = target.children;
    vpin.tableData = ROWS.map((row) => ({ ...row }));
    show(AFM);

    assert.notEqual(target.children[0], first, "a picture replaced under its URL is fetched anew");
  });

  test("another game replaces it", async () => {
    const { target, show } = await drawn("playfield", {}, { priority: "image" });
    show(AFM);
    const [first] = target.children;
    show(ROWS.findIndex((row) => row.tableDirName !== ROWS[AFM].tableDirName
      && row.playfieldImagePath));

    assert.notEqual(target.children[0], first);
  });
});

describe("dimming every window while VPX launches", () => {
  test("it is set on the document, not left to the theme", async () => {
    // A theme's script runs in the controller only, so a theme doing this for itself
    // dims one screen and leaves the others lit - which is what the cabinet showed.
    const { vpin, browser } = await coreOn("backglass");
    await vpin.handleEvent({ type: "TableLaunching" });
    assert.equal(browser.document.documentElement.dataset.vpinfeLaunching, "true");

    await vpin.handleEvent({ type: "TableLaunchComplete" });
    assert.equal(browser.document.documentElement.dataset.vpinfeLaunching, undefined);
  });

  test("a theme can turn it off", async () => {
    const { vpin, browser } = await coreOn("backglass",
      { themeConfig: { launch_dim: { enabled: false } } });
    await vpin.handleEvent({ type: "TableLaunching" });
    assert.equal(browser.document.documentElement.dataset.vpinfeLaunching, undefined);
  });
});
