"use client";

import { Clapperboard, Film, LogOut, MessagesSquare, Sparkles, UserRound } from "lucide-react";
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
    <header className="sticky top-0 z-50 px-3 pt-3 sm:px-6">
      <nav className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between gap-2 rounded-full border border-border/80 bg-[#100e0f]/90 px-3 shadow-[0_16px_50px_rgba(0,0,0,.4)] backdrop-blur-xl sm:gap-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-primary text-primary-foreground">
            <Clapperboard className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className="hidden text-lg font-semibold tracking-tight sm:inline">
            Cine
            <span className="text-primary">Mind</span>
          </span>
        </Link>

        <ul className="flex items-center gap-0.5 sm:gap-1">
          {LINKS.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  aria-label={label}
                  className={cn(
                    "flex items-center gap-2 rounded-full px-2.5 py-2 text-sm transition-colors sm:px-4",
                    active
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  <span className="hidden sm:inline">{label}</span>
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="flex items-center gap-2">
          {user ? (
            <>
              <span
                className="hidden max-w-36 truncate text-xs text-muted-foreground lg:block"
                title={user.email}
              >
                {user.email}
              </span>
              <button
                type="button"
                onClick={logout}
                aria-label="Sign out"
                title="Sign out"
                className="flex items-center gap-1.5 rounded-full px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <LogOut className="h-4 w-4" />
                <span className="hidden sm:inline">Sign out</span>
              </button>
            </>
          ) : (
            <Link
              href="/login"
              className="grid size-9 shrink-0 place-items-center rounded-full bg-primary text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:h-auto sm:w-auto sm:px-3.5 sm:py-2"
            >
              <UserRound className="size-4 sm:hidden" aria-hidden="true" />
              <span className="hidden sm:inline">Sign in</span>
            </Link>
          )}
        </div>
      </nav>
    </header>
  );
}
