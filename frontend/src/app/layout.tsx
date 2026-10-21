import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import Link from "next/link";

import { AuthProvider } from "@/components/auth-provider";
import { SiteNav } from "@/components/site-nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "CineMind — movie discovery with reasons",
  description: "Find a film that fits the moment. CineMind explains why every pick belongs.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`dark ${GeistSans.variable}`}>
      <body className="beam grain min-h-screen antialiased">
        <div className="relative z-10 flex min-h-screen flex-col">
          <AuthProvider>
            <SiteNav />
            <main className="w-full max-w-full flex-1 overflow-x-clip">{children}</main>
          </AuthProvider>
          <footer className="border-t cinema-rule py-10 text-sm text-muted-foreground">
            <div className="cinema-shell flex flex-col justify-between gap-6 sm:flex-row sm:items-start">
              <div>
                <p className="font-semibold tracking-tight text-foreground">Cine<span className="text-primary">Mind</span></p>
                <p className="mt-2 max-w-xs text-xs leading-relaxed">Find a film that fits. Know why it belongs.</p>
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs">
                <Link href="/" className="hover:text-foreground">Discover</Link>
                <Link href="/chat" className="hover:text-foreground">Chat</Link>
                <Link href="/profile" className="hover:text-foreground">My Taste</Link>
                <Link href="https://www.themoviedb.org/" target="_blank" rel="noreferrer" className="hover:text-foreground">Movie data from TMDB</Link>
              </div>
            </div>
            <p className="cinema-shell mt-7 text-[11px]">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
          </footer>
        </div>
      </body>
    </html>
  );
}
