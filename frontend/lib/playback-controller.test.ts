import assert from "node:assert/strict";
import test from "node:test";

import {
  openPlayback,
  reducePlayback,
  type MediaSlice,
  type PlaybackEffect,
  type PlaybackEvent,
  type PlaybackMachine,
} from "./playback-controller.ts";

function minute(id: string, cid: string, offset = 0, end = 60): MediaSlice {
  return { id, cid, offsetSeconds: offset, endSeconds: end };
}

function sameCidMinutes(): MediaSlice[] {
  return [minute("a", "same"), minute("b", "same"), minute("c", "same")];
}

function differentCidMinutes(): MediaSlice[] {
  return [minute("a", "cid-a"), minute("b", "cid-b"), minute("c", "cid-c")];
}

function playToEnd(
  state: PlaybackMachine,
  slices: MediaSlice[],
  effects: PlaybackEffect[]
) {
  let current = state;
  const step = (event: PlaybackEvent) => {
    const result = reducePlayback(current, event, slices);
    current = result.state;
    effects.push(result.effect);
    return result;
  };
  return {
    get state() {
      return current;
    },
    step,
  };
}

function shownIndexes(effects: PlaybackEffect[]): number[] {
  return effects.flatMap((effect) =>
    effect.type === "show" ? [effect.index] : []
  );
}

test("three slices that share a CID each play for a minute", () => {
  const slices = sameCidMinutes();
  const opened = openPlayback(slices, 0);
  const effects = [opened.effect];
  const player = playToEnd(opened.state, slices, effects);
  player.step({ type: "positioned", command: 1, currentTime: 0 });
  player.step({
    type: "time",
    command: player.state.command,
    currentTime: 59.95,
  });
  assert.equal(player.state.index, 1);
  assert.equal(player.state.phase, "transitioning");
  assert.equal(player.state.elapsed, 60);
  player.step({
    type: "time",
    command: player.state.command,
    currentTime: 59.95,
  });
  player.step({
    type: "ended",
    command: player.state.command,
    currentTime: 59.95,
  });
  assert.equal(player.state.index, 1);
  assert.equal(player.state.elapsed, 60);
  player.step({
    type: "positioned",
    command: player.state.command,
    currentTime: 0,
  });
  assert.equal(player.state.phase, "playing");
  assert.equal(player.state.elapsed, 60);
  player.step({
    type: "time",
    command: player.state.command,
    currentTime: 59.95,
  });
  assert.equal(player.state.index, 2);
  assert.equal(player.state.elapsed, 120);
  player.step({
    type: "positioned",
    command: player.state.command,
    currentTime: 0,
  });
  player.step({
    type: "time",
    command: player.state.command,
    currentTime: 59.95,
  });
  assert.equal(player.state.phase, "ended");
  assert.equal(player.state.elapsed, 180);
  assert.deepEqual(shownIndexes(effects), [0, 1, 2]);
});

test("three slices with different CIDs play in order", () => {
  const slices = differentCidMinutes();
  const opened = openPlayback(slices, 0);
  const effects = [opened.effect];
  const player = playToEnd(opened.state, slices, effects);
  player.step({ type: "positioned", command: 1, currentTime: 0 });
  player.step({ type: "time", command: player.state.command, currentTime: 60 });
  player.step({
    type: "positioned",
    command: player.state.command,
    currentTime: 0,
  });
  player.step({ type: "time", command: player.state.command, currentTime: 60 });
  player.step({
    type: "positioned",
    command: player.state.command,
    currentTime: 0,
  });
  player.step({
    type: "ended",
    command: player.state.command,
    currentTime: 60,
  });
  assert.equal(player.state.phase, "ended");
  assert.deepEqual(shownIndexes(effects), [0, 1, 2]);
});

test("a boundary does not add a minute until the next slice is positioned", () => {
  const slices = sameCidMinutes();
  const opened = openPlayback(slices, 0);
  let state = opened.state;
  state = reducePlayback(
    state,
    { type: "positioned", command: 1, currentTime: 0 },
    slices
  ).state;
  const boundary = reducePlayback(
    state,
    { type: "time", command: state.command, currentTime: 60 },
    slices
  );
  assert.equal(boundary.state.elapsed, 60);
  assert.notEqual(boundary.state.elapsed, 120);
  const stale = reducePlayback(
    boundary.state,
    { type: "time", command: boundary.state.command, currentTime: 60 },
    slices
  );
  assert.equal(stale.state.index, 1);
  assert.equal(stale.state.elapsed, 60);
  const ready = reducePlayback(
    stale.state,
    { type: "positioned", command: stale.state.command, currentTime: 0 },
    slices
  );
  assert.equal(ready.state.phase, "playing");
  assert.equal(ready.state.elapsed, 60);
});

test("repeated seeks inside one slice stick", () => {
  const slices = sameCidMinutes();
  let state = reducePlayback(
    openPlayback(slices, 0).state,
    { type: "positioned", command: 1, currentTime: 0 },
    slices
  ).state;
  for (const target of [20, 5, 40, 10]) {
    const sought = reducePlayback(
      state,
      { type: "seek", seconds: target },
      slices
    );
    assert.equal(sought.state.phase, "transitioning");
    assert.equal(sought.state.elapsed, target);
    assert.equal(sought.state.index, 0);
    assert.equal(sought.effect.type, "show");
    const parked = reducePlayback(
      sought.state,
      {
        type: "positioned",
        command: sought.state.command,
        currentTime: target,
      },
      slices
    );
    state = parked.state;
    assert.equal(state.phase, "playing");
    assert.equal(state.targetMediaTime, target);
    assert.equal(state.elapsed, target);
  }
});

test("seeking across slices works while playing and while paused", () => {
  const slices = differentCidMinutes();
  let state = reducePlayback(
    openPlayback(slices, 0).state,
    { type: "positioned", command: 1, currentTime: 0 },
    slices
  ).state;
  state = reducePlayback(
    state,
    { type: "time", command: state.command, currentTime: 10 },
    slices
  ).state;
  assert.equal(state.phase, "playing");
  const playing = reducePlayback(state, { type: "seek", seconds: 70 }, slices);
  assert.equal(playing.state.index, 1);
  assert.equal(playing.state.targetMediaTime, 10);
  assert.equal(playing.state.playWhenReady, true);
  state = reducePlayback(
    playing.state,
    { type: "positioned", command: playing.state.command, currentTime: 10 },
    slices
  ).state;
  assert.equal(state.phase, "playing");
  state = reducePlayback(state, { type: "toggle" }, slices).state;
  assert.equal(state.phase, "paused");
  const paused = reducePlayback(state, { type: "seek", seconds: 130 }, slices);
  assert.equal(paused.state.index, 2);
  assert.equal(paused.state.playWhenReady, false);
  state = reducePlayback(
    paused.state,
    { type: "positioned", command: paused.state.command, currentTime: 10 },
    slices
  ).state;
  assert.equal(state.phase, "paused");
  assert.equal(state.elapsed, 130);
});

test("a range that starts and ends inside segments keeps those offsets", () => {
  const slices = [
    minute("first", "cid-a", 15, 60),
    minute("second", "cid-b", 0, 45),
  ];
  const opened = openPlayback(slices, 0);
  assert.equal(opened.state.targetMediaTime, 15);
  assert.equal(opened.state.elapsed, 0);
  let state = reducePlayback(
    opened.state,
    { type: "positioned", command: 1, currentTime: 15 },
    slices
  ).state;
  const boundary = reducePlayback(
    state,
    { type: "time", command: state.command, currentTime: 60 },
    slices
  );
  assert.equal(boundary.state.index, 1);
  assert.equal(boundary.state.targetMediaTime, 0);
  assert.equal(boundary.state.elapsed, 45);
  state = reducePlayback(
    boundary.state,
    { type: "positioned", command: boundary.state.command, currentTime: 0 },
    slices
  ).state;
  assert.equal(state.elapsed, 45);
});

test("verification that has not finished leaves the player loading", () => {
  const slices = differentCidMinutes();
  const opened = openPlayback(slices, 0);
  assert.equal(opened.state.phase, "loading");
  const ignored = reducePlayback(
    opened.state,
    { type: "time", command: 1, currentTime: 60 },
    slices
  );
  assert.equal(ignored.state.phase, "loading");
  assert.equal(ignored.state.elapsed, 0);
  assert.equal(ignored.state.index, 0);
});

test("a failed slice is not played and another slice can be opened", () => {
  const slices = sameCidMinutes();
  const state = reducePlayback(
    openPlayback(slices, 0).state,
    { type: "positioned", command: 1, currentTime: 0 },
    slices
  ).state;
  const boundary = reducePlayback(
    state,
    { type: "ended", command: state.command, currentTime: 60 },
    slices
  );
  const failed = reducePlayback(
    boundary.state,
    { type: "load-failed", command: boundary.state.command, index: 1 },
    slices
  );
  assert.equal(failed.state.phase, "blocked");
  assert.equal(failed.state.index, 1);
  assert.equal(failed.effect.type, "pause");
  const elsewhere = reducePlayback(
    failed.state,
    { type: "seek", seconds: 120 },
    slices
  );
  assert.equal(elsewhere.state.index, 2);
  assert.equal(elsewhere.state.phase, "transitioning");
  assert.equal(elsewhere.effect.type, "show");
});

test("a newer seek wins and a cancelled command cannot position the player", () => {
  const slices = sameCidMinutes();
  let state = reducePlayback(
    openPlayback(slices, 0).state,
    { type: "positioned", command: 1, currentTime: 0 },
    slices
  ).state;
  const first = reducePlayback(state, { type: "seek", seconds: 20 }, slices);
  const second = reducePlayback(
    first.state,
    { type: "seek", seconds: 5 },
    slices
  );
  const stale = reducePlayback(
    second.state,
    { type: "positioned", command: first.state.command, currentTime: 20 },
    slices
  );
  assert.equal(stale.state.targetMediaTime, 5);
  assert.equal(stale.state.elapsed, 5);
  assert.equal(stale.state.phase, "transitioning");
  state = reducePlayback(
    stale.state,
    { type: "positioned", command: second.state.command, currentTime: 5 },
    slices
  ).state;
  assert.equal(state.phase, "playing");
  assert.equal(state.elapsed, 5);
  const cancelled = reducePlayback(state, { type: "cancel" }, slices);
  const late = reducePlayback(
    cancelled.state,
    { type: "positioned", command: state.command, currentTime: 5 },
    slices
  );
  assert.equal(late.state.command, cancelled.state.command);
  assert.equal(late.state.phase, "loading");
});

test("a rejected play leaves the slice paused instead of transitioning", () => {
  const slices = differentCidMinutes();
  let state = reducePlayback(
    openPlayback(slices, 0).state,
    { type: "positioned", command: 1, currentTime: 0 },
    slices
  ).state;
  assert.equal(state.phase, "playing");
  state = reducePlayback(
    state,
    { type: "play-rejected", command: state.command },
    slices
  ).state;
  assert.equal(state.phase, "paused");
  assert.equal(state.index, 0);
  const resumed = reducePlayback(state, { type: "toggle" }, slices);
  assert.equal(resumed.state.phase, "playing");
  assert.equal(resumed.effect.type, "play");
});
