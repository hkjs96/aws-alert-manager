import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // standalone: Docker/ECS 배포 시 STANDALONE=true 로 빌드
  // Amplify 배포 시에는 미설정 (Amplify 자체 SSR 런타임 사용)
  output: process.env.STANDALONE === "true" ? "standalone" : undefined,
  // NOTE: No /api/* rewrite. Backend calls go through the route handler
  // `app/api/[...path]/route.ts`, which injects the Google ID token as a
  // Bearer header (auth). A `beforeFiles` rewrite here would bypass both that
  // proxy and the next-auth handlers (`/api/auth/*`), breaking login.
};

export default nextConfig;
