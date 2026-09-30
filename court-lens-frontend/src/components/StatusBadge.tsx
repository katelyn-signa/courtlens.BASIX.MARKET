import type { ReactNode } from 'react';

export type Tone = 'success' | 'warning' | 'conflict' | 'info' | 'neutral';
const tones: Record<Tone, string> = {
  success: 'border-success/30 bg-success/10 text-success',
  warning: 'border-warning/30 bg-warning/10 text-warning',
  conflict: 'border-conflict/30 bg-conflict/10 text-conflict',
  info: 'border-info/30 bg-info/10 text-info',
  neutral: 'border-line bg-white text-charcoal'
};

export function StatusBadge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}
