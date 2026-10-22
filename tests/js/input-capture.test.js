// A Manager listens for a controller button or key: while it does, the controller window
// reports each one to Python in the Manager's own selector form and does nothing else with
// it, and it lets go on its own when the Manager stops asking.

import { test, describe, afterEach } from "node:test";
import assert from "node:assert/strict";

import { loadCore } from "./support/load-core.js";

const ticks = () => new Promise(resolve => setTimeout(resolve, 5));

const stillArmed = [];
afterEach(() => {
  for (const off of stillArmed.splice(0)) off();
});

async function controller({ mapping = "standard" } = {}) {
  const { VPinFECore, browser } = loadCore({ windowName: "table" });
  const buttons = [{ pressed: false }, { pressed: false }, { pressed: false }];
  // A browser lists a pad at its own index, empty slots before it.
  browser.navigator.getGamepads = () => [null, null, null, { index: 3, mapping, buttons }];
  const listeners = {};
  browser.window.addEventListener = (type, fn) => { (listeners[type] ||= []).push(fn); };
  const vpin = new VPinFECore();
  vpin.isController = () => true;
  const boot = { get_tables: "[]", get_theme_assets_port: 8000, get_initial_table_index: 0,
                 get_theme_config: {}, get_keymapping: {}, get_joymaping: {},
                 get_mainmenu_config: {}, get_monitors: [], get_collections: [] };
  vpin.call = (method) => Promise.resolve(method in boot ? boot[method] : null);
  const reported = [];
  vpin.callInternal = (method, ...args) => {
    if (method === "library_waiting") return Promise.resolve([]);
    if (method === "signin_pending") return Promise.resolve(null);
    if (method === "get_attract_config") return Promise.resolve({ enabled: false });
    if (method === "input_capture") reported.push(args);
    return Promise.resolve({});
  };
  vpin.init();
  await browser.WebSocket.instances.at(-1).onopen();
  vpin.frontendInputEnabled = true;
  vpin.contract = 2;
  vpin.joyButtonMap = { "0": ["next"] };
  const seen = [];
  vpin.inputHandlers.push((action) => { seen.push(action); });
  const arm = (armed = true, ttl_ms = 6000) => {
    stillArmed.push(() => vpin.handleEvent({ type: "CaptureArm", armed: false }));
    return vpin.handleEvent({ type: "CaptureArm", armed, ttl_ms });
  };
  const hold = async (index, down) => {
    buttons[index].pressed = down;
    browser.frames.step();
    await ticks();
  };
  const key = async (type, code, repeat = false, target = null) => {
    const event = { key: code, code, repeat, target, prevented: false,
                    preventDefault() { event.prevented = true; } };
    await Promise.all((listeners[type] || []).map(fn => fn(event)));
    return event;
  };
  const press = (code, repeat, target) => key("keydown", code, repeat, target);
  const release = (code, target) => key("keyup", code, false, target);
  return { vpin, browser, reported, seen, arm, hold, buttons, press, release };
}

describe("a controller button is reported to a Manager that is listening", () => {
  test("a pad on the standard layout goes by the layout's name", async () => {
    const { reported, arm, hold } = await controller();
    await arm();

    await hold(1, true);
    await hold(1, false);

    assert.deepEqual(reported, [["pad:standard/button:1", "down"],
                                ["pad:standard/button:1", "up"]]);
  });

  test("any other pad goes by its number", async () => {
    const { reported, arm, hold } = await controller({ mapping: "" });
    await arm();

    await hold(0, true);

    assert.deepEqual(reported, [["pad:3/button:0", "down"]]);
  });

  test("what the button does here waits until the Manager is done", async () => {
    const { seen, arm, hold } = await controller();
    await arm();

    await hold(0, true);
    await hold(0, false);

    assert.deepEqual(seen, []);
  });

  test("a button already down when it starts is not reported until let go and pressed again",
       async () => {
         const { reported, arm, hold } = await controller();
         await hold(1, true);
         await arm();

         await hold(1, false);
         await hold(1, true);

         assert.deepEqual(reported, [["pad:standard/button:1", "down"]]);
       });

  test("nothing is reported while no Manager is listening", async () => {
    const { reported, hold } = await controller();

    await hold(1, true);
    await hold(1, false);

    assert.deepEqual(reported, []);
  });

  test("a Manager that stops listening gives the buttons back", async () => {
    const { reported, seen, arm, hold } = await controller();
    await arm();
    await arm(false);

    await hold(0, true);
    await hold(0, false);

    assert.deepEqual(reported, []);
    assert.deepEqual(seen, ["next"]);
  });

  test("it lets go on its own when the Manager stops asking", async () => {
    const { reported, seen, arm, hold } = await controller();
    await arm(true, 20);
    await new Promise(resolve => setTimeout(resolve, 60));

    await hold(0, true);
    await hold(0, false);

    assert.deepEqual(reported, []);
    assert.deepEqual(seen, ["next"]);
  });

  test("a wheel that is repeating stops when the Manager starts listening", async () => {
    const { vpin, seen, arm, hold } = await controller();
    vpin.repeatDelayMs = 20;
    await hold(0, true);
    assert.deepEqual(seen, ["next"]);

    await arm();
    await new Promise(resolve => setTimeout(resolve, 120));

    assert.deepEqual(seen, ["next"]);
  });

  test("asking again keeps it, and keeps what was down when it first started", async () => {
    const { reported, arm, hold } = await controller();
    await hold(1, true);
    await arm();
    await arm();

    await hold(1, false);

    assert.deepEqual(reported, []);
  });
});

describe("a key is reported to a Manager that is listening", () => {
  test("a key goes by the name of its place on the keyboard", async () => {
    const { reported, arm, press, release } = await controller();
    await arm();

    await press("KeyN");
    await release("KeyN");

    assert.deepEqual(reported, [["key:KeyN", "down"], ["key:KeyN", "up"]]);
  });

  test("what the key does here waits until the Manager is done", async () => {
    const { vpin, seen, arm, press, release } = await controller();
    vpin.keyActionMap = { next: ["keyn"] };
    await press("KeyN");
    await release("KeyN");
    assert.deepEqual(seen, ["next"]);
    await arm();

    const event = await press("KeyN");
    await release("KeyN");

    assert.deepEqual(seen, ["next"]);
    assert.equal(event.prevented, true);
  });

  test("the operating system's repeat is not another press", async () => {
    const { reported, arm, press } = await controller();
    await arm();

    await press("KeyN");
    await press("KeyN", true);

    assert.deepEqual(reported, [["key:KeyN", "down"]]);
  });

  test("a key typed in a text field is not reported and still types", async () => {
    const { reported, arm, press, release } = await controller();
    await arm();
    const field = { tagName: "INPUT", type: "text" };

    const down = await press("KeyN", false, field);
    const up = await release("KeyN", field);

    assert.deepEqual(reported, []);
    assert.equal(down.prevented, false);
    assert.equal(up.prevented, false);
  });

  test("a key with no place of its own is not reported", async () => {
    const { reported, arm, press } = await controller();
    await arm();

    await press("");

    assert.deepEqual(reported, []);
  });

  test("a window that is not the controller reports nothing", async () => {
    const { vpin, reported, arm, press } = await controller();
    vpin.isController = () => false;
    await arm();

    await press("KeyN");

    assert.deepEqual(reported, []);
  });

  test("nothing is reported while no Manager is listening", async () => {
    const { reported, press, release } = await controller();

    await press("KeyN");
    await release("KeyN");

    assert.deepEqual(reported, []);
  });
});
