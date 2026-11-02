import Link from "next/link";

import { Plane } from "@/components/ui/Plane";

/**
 * The one honest state for a gated page: the API said 401, so the page cannot
 * load. This is not a failed diagnosis and not an empty session; it only means
 * the cookie is missing or expired.
 */
export function SignInRequired({ next }: { next: string }) {
  return (
    <section className="sm-state">
      <Plane>
        <p className="sm-kicker">请先登录</p>
        <h1 className="sm-h1">这个页面需要账号。</h1>
        <p className="sm-p">
          会话接口在开启登录的部署里需要一个 HttpOnly cookie。登录后会回到这里，
          当前地址不会丢。
        </p>
        <p style={{ marginTop: 26 }}>
          <Link className="sm-cta" href={`/login?next=${encodeURIComponent(next)}`}>
            去登录
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </Link>
        </p>
      </Plane>
    </section>
  );
}