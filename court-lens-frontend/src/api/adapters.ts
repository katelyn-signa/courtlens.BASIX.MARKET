import { NotConfiguredError } from './errors';
import type { AnyRecord } from '../types';

/**
 * CourtLens v1 list endpoints return { items, total, limit, offset }.
 * Keep the UI-facing contract as an array so existing resource pages remain simple.
 */
export function toList(raw: unknown): AnyRecord[] {
  if (Array.isArray(raw)) return raw as AnyRecord[];
  if (isPage(raw)) return raw.items as AnyRecord[];
  throw new NotConfiguredError('List response adapter (expected a JSON array or Page response)');
}

export function isPage(raw: unknown): raw is { items: unknown[]; total: number; limit: number; offset: number } {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return false;
  const value = raw as Record<string, unknown>;
  return Array.isArray(value.items)
    && typeof value.total === 'number'
    && typeof value.limit === 'number'
    && typeof value.offset === 'number';
}

export function isEmpty(raw: unknown): boolean {
  if (raw == null) return true;
  if (Array.isArray(raw)) return raw.length === 0;
  if (isPage(raw)) return raw.items.length === 0;
  if (typeof raw === 'object') return Object.keys(raw as object).length === 0;
  return false;
}
