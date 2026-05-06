import type { NextConfig } from "next";

const API_GATEWAY_URL = process.env.API_GATEWAY_URL;

const nextConfig: NextConfig = {
  output: "standalone",
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
