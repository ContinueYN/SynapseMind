/**
 * Account endpoints: the session cookie, one-time login tickets, and the
 * account's own identity.
 */

import type {
  AuthUser,
  LoginAccountInput,
  RegisterAccountInput,
} from "./types";
import { armLoginTicketBootstrap, request } from "./http";

/**
 * The account behind the session cookie; 401 logged out, 403 auth disabled.
 * After login this is the call that exchanges the one-time ticket.
 */
export function getMe(): Promise<AuthUser> {
  return request<AuthUser>("/api/v1/auth/me");
}

/**
 * Create an account; 409 means this email already has one. A successful
 * response hands out the one-time login ticket, so arm the bootstrap gate.
 */
export async function registerAccount(
  input: RegisterAccountInput,
): Promise<AuthUser> {
  const user = await request<AuthUser>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
  armLoginTicketBootstrap();
  return user;
}

/**
 * Exchange email/password for the one-time login ticket. The first protected
 * request turns that ticket into an ordinary session cookie.
 */
export async function loginAccount(input: LoginAccountInput): Promise<AuthUser> {
  const user = await request<AuthUser>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
  armLoginTicketBootstrap();
  return user;
}

/**
 * Revoke the server-side session and clear the cookie. Idempotent and safe to
 * call without a session; the response carries no account data.
 */
export async function logoutAccount(): Promise<void> {
  await request<null>("/api/v1/auth/logout", { method: "POST" });
}