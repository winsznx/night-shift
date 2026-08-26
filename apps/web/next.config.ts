import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Standalone output keeps the Cloud Run image small and avoids shipping node_modules.
  output: "standalone",
  // The same-origin /api/* proxy lives in src/app/api/[...path]/route.ts, not here.
  // rewrites() is evaluated at build time, so a container built without the API URL
  // shipped with no proxy at all and browser-side calls 404'd on the deployed site.
};

export default config;
