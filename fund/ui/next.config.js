/** @type {import('next').NextConfig} */
const nextConfig = {
  // The UI is local-only — no need for production telemetry.
  experimental: {
    typedRoutes: false,
  },
};

module.exports = nextConfig;
