/**
 * Shared HTTP transport for the API client.
 *
 * This module owns the base URL, `ApiError`, the auth/session error helpers and
 * the one-time-login-ticket bootstrap queue. Feature modules import `request`
 * from here; only the public helpers are re-exported by `@/src/lib/api`, so the
 * transport itself stays an internal detail.
 */

// `??` (not `||`) matters: an explicitly empty value means same-origin, which
// is what the nginx deployment relies on. Unset still falls back to local dev.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * The server rejected a write because the session changed after it was read.
 * The caller must reload before offering the action again; retrying the same
 * body could apply it on top of a state the user never saw.
 */
export function isSessionConflict(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 409;
}

/**
 * `/auth/me` (or a gated session route) says there is no valid session. The web
 * client never stores a token: the only credential is the HttpOnly cookie, so
 * the fix is always to send the user to `/login`.
 */
export function isUnauthorized(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 401;
}

/**
 * The server rejects a login ticket it has already exchanged: replaying the
 * one-time ticket is the session-theft signal, not an ordinary expired login.
 * The caller must drop account state and send the user back through
 * `/login?reason=session_reused`.
 */
export const SESSION_REUSED_EVENT = "synapse:session-reused";

const SESSION_REUSED_DETAIL = "会话被复用";

export function isSessionReused(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 401 &&
    error.message.includes(SESSION_REUSED_DETAIL)
  );
}

function notifySessionReused() {
  // The event lets the account chip clear itself immediately. Login and
  // settings pages render their own notice; this is only a UI hint.
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(SESSION_REUSED_EVENT));
}

/**
 * `/auth/me` answers 403 only when this deployment runs with `SYNAPSE_AUTH=off`.
 * That is not a failed login: there is no account layer at all, so the UI must
 * render no prompt and leave the local single-user flow untouched.
 */
export function isAuthDisabled(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 403;
}

/**
 * Login and register hand out a one-time ticket, not a long-lived cookie that
 * rotates per request. The first authenticated request exchanges that ticket
 * for an ordinary session cookie; from then on the cookie is stable and every
 * later request just carries it.
 *
 * Only the short window between login and that first exchange needs any
 * coordination: if two protected requests left at once, both would present the
 * same ticket and the server would read the second one as a replay. So we set
 * `bootstrapPending` after a successful login/register and serialize just the
 * calls that can spend the ticket (`/auth/me`, `/sessions...`, `/settings...`).
 * Public calls are never serialized, and once the ticket is spent every call
 * runs normally and in parallel again.
 *
 * The flag is cleared as soon as any protected-path response arrives, including
 * an error response: the response proves the ticket has been presented and
 * consumed (or rejected). A transport failure before any response deliberately
 * leaves it set, because the request never reached the server and a retry may
 * still consume the same valid ticket.
 *
 * `bootstrapEpoch` guards the re-login case: a response belonging to an older
 * login must not clear the gate that a newer login just armed.
 */
let bootstrapPending = false;
let bootstrapEpoch = 0;
let bootstrapQueue: Promise<unknown> = Promise.resolve();

const BOOTSTRAP_PATHS = ["/api/v1/auth/me", "/api/v1/sessions", "/api/v1/settings"];

function canSpendLoginTicket(path: string): boolean {
  const pathname = path.split("?")[0];
  return BOOTSTRAP_PATHS.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * Arm the gate after a successful login/register. Exported for `api/auth.ts`
 * only; it is intentionally absent from the public barrel.
 */
export function armLoginTicketBootstrap(): void {
  bootstrapPending = true;
  bootstrapEpoch += 1;
}

function settleBootstrap(epoch: number): void {
  if (epoch === bootstrapEpoch) bootstrapPending = false;
}

function serializeBootstrap<T>(task: () => Promise<T>): Promise<T> {
  // The rejection handler is the same task on purpose: a failed request must not
  // reject the chain and silently skip every later call. `current` still rejects
  // for the caller, so error values are preserved.
  const current = bootstrapQueue.then(task, task);
  bootstrapQueue = current.then(
    () => undefined,
    () => undefined,
  );
  return current;
}

async function performRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const epochWhenSent = canSpendLoginTicket(path) ? bootstrapEpoch : null;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      // The session cookie (or the one-time login ticket on the first call after
      // login) is HttpOnly and SameSite=Lax. Sending it on every call keeps the
      // API useful behind nginx (API_BASE = "") as well as in the local split
      // (web :3000, api :8000, same site "localhost").
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    // No response means the ticket may not have been spent; leave the gate
    // armed so a retry can still exchange it.
    throw new ApiError(
      0,
      `连不上诊断服务（${API_BASE}），请确认 FastAPI 已启动。`,
    );
  }

  // Any protected-path response proves the ticket (if one was pending) has been
  // presented, so the gate can open. Success and error statuses both count.
  if (epochWhenSent !== null) settleBootstrap(epochWhenSent);

  // 204/205 have no body by definition; parsing "" would still work, but the
  // explicit branch keeps `logoutAccount` (and any future DELETE) honest.
  if (response.status === 204 || response.status === 205) {
    return undefined as T;
  }

  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }

  if (!response.ok) {
    const detail =
      body &&
      typeof body === "object" &&
      "detail" in body &&
      typeof body.detail === "string"
        ? body.detail
        : `请求失败（HTTP ${response.status}）`;
    if (response.status === 401 && detail.includes(SESSION_REUSED_DETAIL)) {
      notifySessionReused();
    }
    throw new ApiError(response.status, detail);
  }
  return body as T;
}

/**
 * Typed JSON request over the shared transport.
 *
 * Only the login-ticket bootstrap window is serialized; everything else goes
 * straight to fetch so ordinary calls can overlap again. Not re-exported from
 * the public barrel: feature modules are the only callers.
 */
export function request<T>(path: string, init?: RequestInit): Promise<T> {
  const task = () => performRequest<T>(path, init);
  return bootstrapPending && canSpendLoginTicket(path)
    ? serializeBootstrap(task)
    : task();
}