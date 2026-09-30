import { NotConfiguredError } from './errors';
import type { AnyRecord } from '../types';

/**
 * BACKEND INTEGRATION POINT #3
 * Normalise backend payloads for the UI. Until the spec defines shapes, we only
 * accept a top-level array or object and refuse to guess anything else.
 */
export function toList(raw: unknown): AnyRecord[] {
  if (Array.isArray(raw)) return raw as AnyRecord[];
  throw new NotConfiguredError('List response adapter (expected a JSON array)');
}

export function isEmpty(raw: unknown): boolean {
  if (raw == null) return true;
  if (Array.isArray(raw)) return raw.length === 0;
  if (typeof raw === 'object') return Object.keys(raw as object).length === 0;
  return false;
}
