import type { NextConfig } from "next";

const API_GATEWAY_URL = process.env.API_GATEWAY_URL;

const nextConfig: NextConfig = {
  // standalone: Docker/ECS 배포 시 STANDALONE=true 로 빌드
  // Amplify 배포 시에는 미설정 (Amplify 자체 SSR 런타임 사용)
  output: process.env.STANDALONE === "true" ? "standalone" : undefined,
  // When API_GATEWAY_URL is set, proxy all /api/* requests to the real backend.
  // In development (no env var), requests fall through to the local mock route handlers.
  async rewrites() {
    if (!API_GATEWAY_URL) return [];
    return {
      beforeFiles: [
        {
          source: "/api/:path*",
          destination: `${API_GATEWAY_URL}/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
