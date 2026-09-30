export type Role = 'LAWYER' | 'GUARDIAN';

export interface Session {
  role: Role;
  displayName?: string;
}

/** Backend records are rendered generically until the API spec fixes their shape. */
export type AnyRecord = Record<string, unknown>;
