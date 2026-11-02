/**
 * The signed-in account's own BYOK model configuration.
 */

import type {
  ModelSettings,
  ModelSettingsTestResult,
  SaveModelSettingsInput,
  TestModelSettingsInput,
} from "./types";
import { request } from "./http";

/**
 * The signed-in user's own model config. Never carries the key: only
 * `key_last4` and a masked status line. 401 means there is no session (or the
 * login ticket was replayed); 403 means this deployment has no account layer.
 */
export function getModelSettings(): Promise<ModelSettings> {
  return request<ModelSettings>("/api/v1/settings/model");
}

/**
 * Replace this user's provider/base URL/model/key. The API requires the key on
 * every save, so the page must ask for it again rather than reuse a hidden one.
 */
export function saveModelSettings(
  input: SaveModelSettingsInput,
): Promise<ModelSettings> {
  return request<ModelSettings>("/api/v1/settings/model", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

/**
 * Try a provider call. Omit `api_key` to test the key already stored for this
 * account. A provider/network rejection is HTTP 200 with `ok:false`; only a
 * malformed body (422) or a missing server master key (503) reject.
 */
export function testModelSettings(
  input: TestModelSettingsInput = {},
): Promise<ModelSettingsTestResult> {
  return request<ModelSettingsTestResult>("/api/v1/settings/model/test", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/** Remove this user's saved key and provider config (204). */
export function deleteModelSettings(): Promise<void> {
  return request<void>("/api/v1/settings/model", { method: "DELETE" });
}