import type { Metadata } from "next";
import Link from "next/link";

import { SiteNav } from "@/components/site-nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "CineMind — explainable movie discovery",
  description:
    "Describe the movie you're in the mood for; CineMind explains why each pick fits.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="beam grain min-h-screen antialiased">
        <div className="relative z-10 flex min-h-screen flex-col">
          <SiteNav />
          <main className="flex-1">{children}</main>
          <footer className="border-t border-border/60 py-6 text-center text-xs text-muted-foreground">
            CineMind — every pick comes with its reasons. ·{" "}
            <Link
              href="http://localhost:8000/docs"
              target="_blank"
              className="underline-offset-4 hover:underline"
            >
              API docs
            </Link>
          </footer>
        </div>
        {/* Ambient art: projector glow + reel silhouette, behind content. */}
        <div
          aria-hidden
          className="pointer-events-none fixed inset-x-0 bottom-0 h-24 bg-gradient-to-t from-background to-transparent"
        />
        <div
          aria-hidden
          className="pointer-events-none fixed left-1/2 top-0 h-[420px] w-[820px] -translate-x-1/2 rounded-full bg-glow/10 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none fixed left-1/2 top-[-140px] h-[380px] w-[380px] -translate-x-1/2 rounded-full border border-neon/20"
        />
      </body>
    </html>
  );
}
