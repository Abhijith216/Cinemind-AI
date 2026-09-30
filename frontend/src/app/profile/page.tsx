"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Film,
  Loader2,
  MessageCircleHeart,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { RequireAuth } from "@/components/require-auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api, ApiError, type TasteProfileOut } from "@/lib/api";

function ProfileContent() {
  const { user } = useAuth();
  const [profile, setProfile] = useState<TasteProfileOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!user) return;
    setLoading(true);
    setError(null);
    api.users
      .tasteProfile(user.id)
      .then(setProfile)
      .catch((err: unknown) => {
        setError(
          err instanceof ApiError
            ? err.status === 404
              ? "no profile yet"
              : `${err.status}: ${err.message}`
            : "Couldn't reach the backend. Is it running on :8000?",
        );
      })
      .finally(() => setLoading(false));
  }, [user]);

  useEffect(load, [load]);

  if (loading) {
    return (
      <div
        className="flex items-center justify-center gap-2 py-24 text-sm text-muted-foreground"
        role="status"
      >
        <Loader2 className="size-4 animate-spin" />
        Loading your taste profile…
      </div>
    );
  }

  if (error && error !== "no profile yet") {
    return (
      <Card className="border-rose-500/30 bg-card/60 text-center">
        <CardHeader>
          <CardTitle className="text-lg">Couldn't load your taste profile</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-rose-400" role="alert">
            {error}
          </p>
          <Button variant="outline" onClick={load}>
            <RefreshCw className="size-4" /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!profile) {
    // Backend said "no taste profile yet" — the new-user empty state.
    return (
      <Card className="border-dashed bg-card/50 text-center">
        <CardHeader>
          <CardTitle className="flex items-center justify-center gap-2 text-lg">
            <Film className="h-5 w-5 text-primary" />
            No taste profile yet
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            Your profile builds itself as you rate movies — likes, dislikes, and
            the themes you keep coming back to. Rate a few and this page comes
            alive.
          </p>
          <Link
            href="/chat"
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-primary px-5 font-medium text-primary-foreground shadow-[0_0_24px_hsl(var(--glow)/0.25)] transition-colors hover:bg-primary/90"
          >
            Find your first movie in Chat
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-6 md:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Sparkles className="h-5 w-5 text-primary" /> You like
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {profile.likes.length === 0 ? (
            <span className="text-sm text-muted-foreground">Nothing yet.</span>
          ) : (
            profile.likes.map((tag) => <Badge key={tag}>{tag}</Badge>)
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <MessageCircleHeart className="h-5 w-5 text-violet-300" /> Favorite themes
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {profile.favorite_themes.length === 0 ? (
            <span className="text-sm text-muted-foreground">Nothing yet.</span>
          ) : (
            profile.favorite_themes.map((tag) => (
              <Badge key={tag} variant="accent">
                {tag}
              </Badge>
            ))
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Avoid</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {profile.dislikes.length === 0 ? (
            <span className="text-sm text-muted-foreground">Nothing yet.</span>
          ) : (
            profile.dislikes.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <RequireAuth>
      <div className="mx-auto w-full max-w-4xl px-4 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">My Taste</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            What your ratings say you love — and what to avoid.{" "}
            <Link
              href="/taste-evolution"
              className="text-primary underline-offset-4 hover:underline"
            >
              How it evolves →
            </Link>
          </p>
        </header>
        <ProfileContent />
      </div>
    </RequireAuth>
  );
}
