import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // TMDb posters are served from image.tmdb.org
  images: {
    remotePatterns: [{ protocol: "https", hostname: "image.tmdb.org" }],
  },
};

export default nextConfig;
