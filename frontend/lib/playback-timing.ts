/** Diagnostic clocks for one Watch startup. Logs contain ids and durations only. */

const origins = new Map<string, number>();
const timingByRecord = new Map<string, string>();

export function beginPlaybackTiming(): string {
  const id = crypto.randomUUID();
  origins.set(id, performance.now());
  return id;
}

export function notePlaybackRecord(recordId: string, timingId: string): void {
  timingByRecord.set(recordId, timingId);
}

export function playbackTimingForRecord(recordId: string): string | undefined {
  return timingByRecord.get(recordId);
}

export function logPlaybackTiming(
  id: string,
  event: string,
  stepStartedAt?: number,
  fields?: Record<string, string | number | boolean>
): void {
  const now = performance.now();
  let origin = origins.get(id);
  if (origin === undefined) {
    origin = now;
    origins.set(id, origin);
  }
  console.info("[playback-timing]", {
    id,
    event,
    elapsedMs: Number((now - origin).toFixed(3)),
    stepMs:
      stepStartedAt === undefined
        ? 0
        : Number((now - stepStartedAt).toFixed(3)),
    ...fields,
  });
}
