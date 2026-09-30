export interface UploadRules { maxBytes?: number; allowed: string[] }

export function uploadRules(): UploadRules {
  const mb = Number(import.meta.env.VITE_MAX_UPLOAD_MB);
  const allowed = (import.meta.env.VITE_ALLOWED_FILE_TYPES ?? '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
  return { maxBytes: Number.isFinite(mb) && mb > 0 ? mb * 1024 * 1024 : undefined, allowed };
}

/** Returns an error message, or null when the file passes. Limits come from env (backend spec). */
export function validateFile(file: File, rules: UploadRules): string | null {
  if (rules.allowed.length === 0 || rules.maxBytes === undefined) return 'Upload limits are not configured.';
  const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase();
  if (!rules.allowed.includes(ext) && !rules.allowed.includes(file.type.toLowerCase())) return `File type not allowed. Allowed: ${rules.allowed.join(', ')}`;
  if (file.size > rules.maxBytes) return `File is larger than ${Math.round(rules.maxBytes / 1048576)} MB.`;
  if (file.size === 0) return 'File is empty.';
  return null;
}
