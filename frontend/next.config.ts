import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker/production deploys run the small standalone server bundle.
  // (No effect on `next dev`; `npm start` also still works locally.)
  output: "standalone",
  // TMDb posters are served from image.tmdb.org
  images: {
    remotePatterns: [{ protocol: "https", hostname: "image.tmdb.org" }],
  },
};

export default nextConfig;
