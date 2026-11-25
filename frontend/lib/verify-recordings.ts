/** 24-hour local time, so 16:30 is not shown as 4:30 PM. */

const localDateTime: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
};

const localDate: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
};

const localTime: Intl.DateTimeFormatOptions = {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
};

export type LocalWindowParts = {
  date: string;
  time: string;
};

/** Same local clock as formatLocalWindow, split for the player overlay. */
export function formatLocalWindowParts(
  startedAt: string,
  endedAt?: string
): LocalWindowParts {
  const start = new Date(startedAt);
  const startDate = start.toLocaleDateString(undefined, localDate);
  const startTime = start.toLocaleTimeString(undefined, localTime);
  if (!endedAt) {
    return { date: startDate, time: startTime };
  }
  const end = new Date(endedAt);
  const endTime = end.toLocaleTimeString(undefined, localTime);
  const date =
    start.toDateString() === end.toDateString()
      ? startDate
      : `${startDate} – ${end.toLocaleDateString(undefined, localDate)}`;
  return { date, time: `${startTime} – ${endTime}` };
}

export function missingRecordingMessage(
  startedAt: string,
  endedAt: string
): string {
  return `No recorded video is available for ${formatLocalWindow(startedAt, endedAt)}. Playback continues with the next available segment.`;
}

export function formatLocalWindow(startedAt: string, endedAt?: string): string {
  const start = new Date(startedAt);
  const startText = start.toLocaleString(undefined, localDateTime);
  if (!endedAt) {
    return startText;
  }
  const end = new Date(endedAt);
  const endText =
    start.toDateString() === end.toDateString()
      ? end.toLocaleTimeString(undefined, localTime)
      : end.toLocaleString(undefined, localDateTime);
  return `${startText} – ${endText}`;
}
