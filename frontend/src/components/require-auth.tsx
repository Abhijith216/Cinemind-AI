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
      <div className="mx-auto w-full max-w-md px-4 py-20">
        <Card className="border-dashed bg-card/50 text-center">
          <CardHeader>
            <CardTitle className="text-lg">This page is for members</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-muted-foreground">
            <p>
              Sign in to see the taste profile and evolution built from{" "}
              <span className="text-foreground">your</span> ratings.
            </p>
            <Link
              href={`/login?next=${encodeURIComponent(pathname)}`}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary font-medium text-primary-foreground shadow-[0_0_24px_hsl(var(--glow)/0.25)] transition-colors hover:bg-primary/90"
            >
              Sign in or register
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <>{children}</>;
}
