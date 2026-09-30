"use client";

import { Clapperboard, Film, LogOut, MessagesSquare, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Discover", icon: Sparkles },
  { href: "/chat", label: "Chat", icon: MessagesSquare },
  { href: "/profile", label: "My Taste", icon: Film },
] as const;

export function SiteNav() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <header className="sticky top-0 z-20 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <nav className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-primary/15 text-primary shadow-[0_0_18px_hsl(var(--glow)/0.35)]">
            <Clapperboard className="h-5 w-5" />
          </span>
          <span className="text-lg font-semibold tracking-tight">
            Cine
            <span className="text-primary">Mind</span>
          </span>
        </Link>

        <ul className="flex items-center gap-1">
          {LINKS.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm transition-colors",
                    active
                      ? "bg-primary/15 text-primary shadow-[inset_0_0_0_1px_hsl(var(--glow)/0.3)]"
                      : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="flex items-center gap-2">
          {user ? (
            <>
              <span
                className="hidden max-w-44 truncate rounded-lg bg-secondary/60 px-3 py-1.5 text-xs text-muted-foreground sm:block"
                title={user.email}
              >
                {user.email}
              </span>
              <button
                type="button"
                onClick={logout}
                aria-label="Sign out"
                title="Sign out"
                className="flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-secondary/70 hover:text-foreground"
              >
                <LogOut className="h-4 w-4" />
                <span className="hidden sm:inline">Sign out</span>
              </button>
            </>
          ) : (
            <Link
              href="/login"
              className="rounded-lg bg-primary/15 px-3.5 py-2 text-sm text-primary shadow-[inset_0_0_0_1px_hsl(var(--glow)/0.3)] transition-colors hover:bg-primary/25"
            >
              Sign in
            </Link>
          )}
        </div>
      </nav>
    </header>
  );
}
