/**
 * Session management utilities for AlphaBot conversational state.
 *
 * Session ID is persisted in localStorage so conversations survive
 * page refreshes. The actual state lives server-side, keyed by session_id.
 * Phase 3 will migrate ownership to user_id after authentication is added.
 */

const SESSION_KEY = 'alphabot_session_id';
const API_BASE = '/api';

export interface ConversationContext {
  session_id: string;
  active_metric: string | null;
  active_filters: Array<{ column: string; value: string }>;
  active_timeframe: { type: string; value: string } | null;
  comparison_entities: string[];
  active_operation: string | null;
  active_comparison: { type: string } | null;
  last_query: string | null;
  has_context: boolean;
  snapshot?: any | null;
}

/**
 * Returns an existing session ID from localStorage, or creates a new session
 * on the backend and stores the ID. Safe to call on every page mount.
 */
export async function getOrCreateSessionId(): Promise<string> {
  if (typeof window === 'undefined') return '';

  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) {
    // Ping the backend to ensure it's alive (recreates expired sessions)
    try {
      await fetch(`${API_BASE}/session/${existing}`);
    } catch {
      // Network error — still use the stored ID, backend will recreate on next query
    }
    return existing;
  }

  // No stored session — create a new one
  try {
    const res = await fetch(`${API_BASE}/session`, { method: 'POST' });
    const data = await res.json();
    const sessionId: string = data.session_id;
    localStorage.setItem(SESSION_KEY, sessionId);
    return sessionId;
  } catch {
    // Fallback: generate a client-side ID if the backend is temporarily unavailable
    const fallback = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem(SESSION_KEY, fallback);
    return fallback;
  }
}

/** Returns the stored session ID synchronously (null if not yet set). */
export function getStoredSessionId(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(SESSION_KEY);
}

/**
 * Fetches the current conversation context for a session from the backend.
 * Used on page mount to rehydrate context after a refresh.
 */
export async function fetchSessionContext(sessionId: string): Promise<ConversationContext | null> {
  try {
    const res = await fetch(`${API_BASE}/session/${sessionId}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Clears conversation state on the backend and removes the session ID
 * from localStorage. Call this when the user explicitly resets the conversation.
 */
export async function clearSession(sessionId: string): Promise<void> {
  localStorage.removeItem(SESSION_KEY);
  try {
    await fetch(`${API_BASE}/session/${sessionId}`, { method: 'DELETE' });
  } catch {
    // Best-effort — don't block the user if the network call fails
  }
}
