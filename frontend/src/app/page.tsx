"use client";

import { motion } from "framer-motion";
import { Clapperboard, Compass, MessageSquareText } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, type HealthResponse } from "@/lib/api";

const SUGGESTIONS = [
  "Something like Interstellar but not about space",
  "A cozy comfort movie with witty dialogue",
  "Mind-bending, emotional, under two hours",
];

export default function DiscoverPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-16">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="text-center"
      >
        <Badge variant="accent" className="mb-4">
          <Clapperboard className="mr-1.5 h-3 w-3" /> now screening
        </Badge>
        <h1 className="bg-gradient-to-r from-marquee via-primary to-neon bg-clip-text text-5xl font-bold tracking-tight text-transparent">
          Describe the mood.
        </h1>
        <p className="mt-3 text-lg text-muted-foreground">
          CineMind finds the movie — and spells out exactly{" "}
          <span className="text-primary">why</span> each pick fits.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.15 }}
        className="mt-10"
      >
        <Card className="border-border/80 bg-card/80 shadow-[0_0_40px_hsl(var(--glow)/0.08)] backdrop-blur-sm">
          <CardContent className="p-5">
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <Badge key={suggestion} variant="outline" className="normal-case">
                  {suggestion}
                </Badge>
              ))}
            </div>
            <div className="mt-4 flex gap-2">
              <Input
                placeholder="Describe what you feel like watching…"
                aria-label="Movie request"
              />
              <Button disabled>Find movies</Button>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.3 }}
        className="mt-12 grid gap-4 sm:grid-cols-2"
      >
        <Card className="bg-card/60">
          <CardContent className="flex items-start gap-3 p-5">
            <MessageSquareText className="mt-0.5 h-5 w-5 text-neon" />
            <div>
              <p className="text-sm font-medium">Prefer a conversation?</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Chat, refine, and narrow it down turn by turn.
              </p>
              <Link
                href="/chat"
                className="mt-2 inline-block text-sm text-primary underline-offset-4 hover:underline"
              >
                Open the chat →
              </Link>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/60">
          <CardContent className="flex items-start gap-3 p-5">
            <Compass className="mt-0.5 h-5 w-5 text-neon" />
            <div>
              <p className="text-sm font-medium">Your taste, mapped.</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Ratings build a profile — and a chart of how it evolves.
              </p>
              <Link
                href="/profile"
                className="mt-2 inline-block text-sm text-primary underline-offset-4 hover:underline"
              >
                See My Taste →
              </Link>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <p className="mt-12 text-center text-xs text-muted-foreground">
        Backend:{" "}
        {health ? (
          <span
            className={
              health.database === "up" ? "text-emerald-400" : "text-amber-400"
            }
          >
            {health.status} · v{health.version} · db {health.database}
          </span>
        ) : (
          <span>offline (start the FastAPI server)</span>
        )}
      </p>
    </div>
  );
}
