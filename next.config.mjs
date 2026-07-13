/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Don't advertise the framework in response headers.
  poweredByHeader: false,
  // Emit a self-contained server bundle (.next/standalone) so the frontend can
  // also be containerized; Vercel ignores this and deploys natively.
  output: "standalone",
};

export default nextConfig;
