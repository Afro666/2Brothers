function parseDate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

/** ISO week label for a calendar date, computed with UTC dates. */
export function isoWeekOf(date: string): string {
  const value = parseDate(date);
  const weekday = value.getUTCDay() || 7;
  value.setUTCDate(value.getUTCDate() + 4 - weekday);
  const year = value.getUTCFullYear();
  const yearStart = new Date(Date.UTC(year, 0, 1));
  const week = Math.ceil(((value.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return `${year}-W${String(week).padStart(2, "0")}`;
}

/** Seven dates in an ISO week, Monday first, using UTC date math. */
export function weekDates(week: string): string[] {
  const match = /^(\d{4})-W(\d{2})$/.exec(week);
  if (!match) throw new Error(`Invalid ISO week: ${week}`);
  const year = Number(match[1]);
  const weekNumber = Number(match[2]);
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const mondayOffset = (jan4.getUTCDay() + 6) % 7;
  const monday = new Date(Date.UTC(year, 0, 4 - mondayOffset + (weekNumber - 1) * 7));
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(monday);
    date.setUTCDate(monday.getUTCDate() + index);
    return date.toISOString().slice(0, 10);
  });
}

/** The ISO week `weeks` weeks after `week` (negative goes back). */
export function shiftWeek(week: string, weeks: number): string {
  const monday = new Date(`${weekDates(week)[0]}T12:00:00Z`);
  monday.setUTCDate(monday.getUTCDate() + weeks * 7);
  return isoWeekOf(monday.toISOString().slice(0, 10));
}

const ISO_WEEK = /^(\d{4})-W(0[1-9]|[1-4]\d|5[0-3])$/;

export function isValidWeek(week: string): boolean {
  const match = ISO_WEEK.exec(week);
  if (!match) return false;
  // A year has 53 ISO weeks only when its Thursday falls in week 53.
  return weekDates(week)[3].slice(0, 4) === match[1];
}

/** "Week 47, 16 to 22 Nov 2026"; a week across New Year names both years. */
export function weekLabel(week: string): string {
  return `Week ${Number(week.slice(6))}, ${weekRangeLabel(week)}`;
}

const MONTHS = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });

function monthName(month: number): string {
  return MONTHS.format(new Date(Date.UTC(2000, month - 1, 1)));
}

/**
 * "16 to 22 Nov 2026", or "16 Nov to 22 Nov 2026" across a month end. A week
 * that crosses New Year names both years.
 */
export function weekRangeLabel(week: string): string {
  const dates = weekDates(week);
  const [firstYear, firstMonth, firstDay] = dates[0].split("-").map(Number);
  const [lastYear, lastMonth, lastDay] = dates[6].split("-").map(Number);
  if (firstYear !== lastYear) {
    return `${firstDay} ${monthName(firstMonth)} ${firstYear} to ${lastDay} ${monthName(lastMonth)} ${lastYear}`;
  }
  if (firstMonth === lastMonth) return `${firstDay} to ${lastDay} ${monthName(lastMonth)} ${lastYear}`;
  return `${firstDay} ${monthName(firstMonth)} to ${lastDay} ${monthName(lastMonth)} ${lastYear}`;
}
