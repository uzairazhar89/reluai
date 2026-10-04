import type { NextConfig } from "next";

// In production nginx routes /api/* to the API container, so Next.js never sees those
// requests. In local development (`pnpm dev`) the rewrite below does the same job; set
// LOCAL_API_PROXY=1 at build time to keep it in a local production build (`pnpm start`,
// Playwright). Release images never set it.
const apiOrigin = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  experimental: {
    // Regenerated (ISR) pages live in memory instead of being written back into .next, so
    // the container can run with a read-only root filesystem.
    isrFlushToDisk: false,
  },
  async rewrites() {
    if (process.env.NODE_ENV === "production" && process.env.LOCAL_API_PROXY !== "1") return [];
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
