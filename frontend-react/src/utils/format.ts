import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { format } from 'date-fns';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Parse ISO, timestamp, or space-separated "YYYY-MM-DD HH:MM(:SS)" safely across Chrome/Firefox/Safari. */
export function safeParseDate(value?: string | number | Date | null): Date | null {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value;
  if (typeof value === 'number') {
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }
  const str = String(value).trim();
  if (!str) return null;
  // Safari/WebKit returns Invalid Date for "YYYY-MM-DD HH:mm:ss" with space separator
  const normalized = /^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(str) ? str.replace(/\s+/, 'T') : str;
  const d = new Date(normalized);
  return isNaN(d.getTime()) ? null : d;
}

export function safeFormatDate(
  value?: string | number | Date | null,
  pattern: string = 'dd/MM/yyyy HH:mm',
  fallback: string = '—'
): string {
  const d = safeParseDate(value);
  if (!d) return typeof value === 'string' && value.trim() ? value.trim() : fallback;
  try {
    return format(d, pattern);
  } catch {
    return fallback;
  }
}

/** Return today's date in Vietnam timezone (UTC+7) as YYYY-MM-DD (avoids UTC yesterday bug 00:00–06:59 VN). */
export function getVnTodayStr(offsetDays: number = 0): string {
  const now = new Date();
  const vnMs = now.getTime() + 7 * 60 * 60 * 1000 + offsetDays * 86400 * 1000;
  return new Date(vnMs).toISOString().slice(0, 10);
}

/** Sanitize external URLs so only http(s) links are clickable; returns null for plain text or unsafe schemes. */
export function toSafeHttpUrl(raw?: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) {
    try {
      const u = new URL(trimmed);
      if (u.protocol === 'http:' || u.protocol === 'https:') return u.href;
    } catch {
      return null;
    }
  }
  // Allow domain-like strings starting with www. or known social domains
  if (/^(www\.|fb\.com|facebook\.com|m\.me|zalo\.me|tiktok\.com|pancake\.vn|pages\.fm)/i.test(trimmed)) {
    try {
      return new URL(`https://${trimmed}`).href;
    } catch {
      return null;
    }
  }
  return null;
}

/** Safe clipboard copy with execCommand fallback; never throws unhandled rejections. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fallback below
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
