"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Gate for member-only pages (/profile, /taste-evolution).
 *
 * While the stored token is being validated we show a spinner (no flicker of
 * the sign-in prompt on reload). Signed-out visitors get an in-place sign-in
 * prompt with a link that preserves the current page via ?next=.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, hydrated } = useAuth();
  const pathname = usePathname();

  if (!hydrated) {
    return (
      <div
        className="flex items-center justify-center gap-2 py-24 text-sm text-muted-foreground"
        role="status"
      >
        <Loader2 className="size-4 animate-spin" />
        Checking your session…
      </div>
    );
  }

  if (!user) {
    return (
      <div className="cinema-shell flex min-h-[calc(100dvh-11rem)] items-center justify-center py-16">
        <Card className="cinema-surface w-full max-w-2xl rounded-[1.75rem] p-5 text-center sm:p-10">
          <CardHeader>
            <p className="cinema-eyebrow mb-4">My Taste</p>
            <CardTitle className="cinema-display text-4xl sm:text-5xl">Your movie taste, in one place</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-muted-foreground">
            <p>
              Turn the films you’ve seen into a profile that helps you find your next favorite.
            </p>
            <ol className="mx-auto max-w-md space-y-3 py-4 text-left leading-relaxed">
              <li><span className="font-medium text-foreground">1. Rate movies you’ve watched.</span> Search a title and give it 1–10.</li>
              <li><span className="font-medium text-foreground">2. Discover your patterns.</span> See your likes, favorite themes, and how they change over time.</li>
              <li><span className="font-medium text-foreground">3. Find more your kind of film.</span> Get suggestions based on your ratings.</li>
            </ol>
            <p className="text-xs">Sign in to save your scores and keep your profile private.</p>
            <Link
              href={`/login?next=${encodeURIComponent(pathname)}`}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary font-medium text-primary-foreground shadow-[0_0_24px_hsl(var(--glow)/0.25)] transition-colors hover:bg-primary/90"
            >
              Sign in or register
            </Link>
            <Link href="/" className="inline-block text-primary underline-offset-4 hover:underline">Keep exploring movies</Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <>{children}</>;
}
