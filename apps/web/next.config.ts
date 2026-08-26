import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Standalone output keeps the Cloud Run image small and avoids shipping node_modules.
  output: "standalone",
  // The BFF is a separate Cloud Run service. Same-origin /api/* keeps the browser
  // free of CORS preflights and keeps the API base URL out of the client bundle.
  async rewrites() {
    const api = process.env.NIGHTSHIFT_API_URL;
    return api ? [{ source: "/api/:path*", destination: `${api}/api/:path*` }] : [];
  },
};

export default config;
