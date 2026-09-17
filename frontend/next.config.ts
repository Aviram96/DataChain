import type { NextConfig } from "next";

const backendUrl =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

const polygonRpcUrl =
  process.env.NEXT_PUBLIC_POLYGON_RPC_URL?.replace(/\/$/, "") ??
  "https://polygon-amoy.drpc.org";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
      {
        source: "/amoy-rpc",
        destination: polygonRpcUrl,
      },
    ];
  },
};

export default nextConfig;
