/**
 * 交题页 → 追问页的一次性交接。
 *
 * `createSession` 已经把完整会话（含第一问）返回了，追问页再取一次只会多一次
 * 骨架屏闪烁。把这份响应放在内存里交过去，追问页首帧就是真内容；直接刷新
 * 或换设备进来时缓存是空的，仍然走正常的 GET。
 */
import type { SessionResponse } from "@/src/lib/api/types";

let handoff: SessionResponse | null = null;

export function handOffSession(session: SessionResponse): void {
  handoff = session;
}

export function adoptSession(sessionId: string): SessionResponse | null {
  if (handoff?.session_id !== sessionId) return null;
  const session = handoff;
  handoff = null;
  return session;
}