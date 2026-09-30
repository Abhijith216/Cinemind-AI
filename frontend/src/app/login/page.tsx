"use client";

import { Suspense, useState } from "react";
import { Clapperboard, Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Wrong email or password.";
    if (error.status === 409) return "That email already has an account — sign in instead.";
    if (error.status === 422) return "Please enter a valid email and a password of at least 8 characters.";
    return error.message;
  }
  if (
    error instanceof DOMException &&
    (error.name === "TimeoutError" || error.name === "AbortError")
  ) {
    return "The backend didn't respond in time. Is it running on :8000?";
  }
  return "Couldn't reach the backend. Is it running on :8000?";
}

function LoginForm() {
  const { login, register } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextParam = searchParams.get("next") ?? "/profile";

  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password);
      router.push(nextParam.startsWith("/") ? nextParam : "/profile");
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-md px-4 py-16">
      <Card className="border-border/80 bg-card/70 backdrop-blur-sm">
        <CardHeader className="items-center text-center">
          <span className="mx-auto mb-2 grid h-12 w-12 place-items-center rounded-xl bg-primary/15 text-primary shadow-[0_0_24px_hsl(var(--glow)/0.35)]">
            <Clapperboard className="h-6 w-6" />
          </span>
          <CardTitle className="text-xl">
            {mode === "login" ? "Welcome back" : "Create your account"}
          </CardTitle>
          <CardDescription>
            {mode === "login"
              ? "Sign in to see your taste profile and evolution."
              : "One account for ratings, taste profile, and recommendations."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div
            className="mb-5 grid grid-cols-2 gap-1 rounded-lg bg-secondary/60 p-1"
            role="tablist"
            aria-label="Sign in or register"
          >
            {(["login", "register"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={mode === value}
                onClick={() => {
                  setMode(value);
                  setError(null);
                }}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  mode === value
                    ? "bg-primary/15 text-primary shadow-[inset_0_0_0_1px_hsl(var(--glow)/0.3)]"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {value === "login" ? "Sign in" : "Register"}
                </button>
            ))}
          </div>

          <form onSubmit={(event) => void submit(event)} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-sm text-muted-foreground">
                Email
              </label>
              <Input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                disabled={pending}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="password" className="text-sm text-muted-foreground">
                Password
              </label>
              <Input
                id="password"
                type="password"
                required
                minLength={8}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="At least 8 characters"
                disabled={pending}
              />
            </div>

            {error && (
              <p className="text-sm text-rose-400" role="alert">
                {error}
              </p>
            )}

            <Button type="submit" className="w-full" disabled={pending}>
              {pending && <Loader2 className="size-4 animate-spin" />}
              {mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
