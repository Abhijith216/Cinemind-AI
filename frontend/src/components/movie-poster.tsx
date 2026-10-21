"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

export function MoviePoster({ title, posterUrl, eager = false, className }: {
  title: string;
  posterUrl?: string | null;
  eager?: boolean;
  className?: string;
}) {
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = Boolean(posterUrl && loadedUrl === posterUrl && failedUrl !== posterUrl);

  return (
    <div className={cn("relative overflow-hidden bg-gradient-to-br from-[#483027] via-[#2a2023] to-[#17121a]", className)}>
      <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center" aria-hidden="true">
        <span className="max-w-full text-2xl font-semibold leading-tight tracking-tight text-foreground/85">{title}</span>
        <span className="mt-4 text-[10px] uppercase tracking-[.18em] text-foreground/50">Poster unavailable</span>
      </div>
      {posterUrl && failedUrl !== posterUrl && (
        // eslint-disable-next-line @next/next/no-img-element -- TMDb posters are displayed directly and can fail independently.
        <img
          src={posterUrl}
          alt={`${title} poster`}
          loading={eager ? "eager" : "lazy"}
          onLoad={() => setLoadedUrl(posterUrl)}
          onError={() => setFailedUrl(posterUrl)}
          className={cn("absolute inset-0 h-full w-full object-cover transition-opacity duration-300", showImage ? "opacity-100" : "opacity-0")}
        />
      )}
    </div>
  );
}
