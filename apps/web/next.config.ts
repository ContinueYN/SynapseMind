import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1"],
  // Docker 运行时（infra/Dockerfile.web）跑 .next/standalone/server.js，
  // 不用 `next start`；dev/build/test 行为不变。
  output: "standalone",
  // 默认仍是 .next；NEXT_DIST_DIR 用来跑第二份产物（并行验证、隔离缓存）
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
