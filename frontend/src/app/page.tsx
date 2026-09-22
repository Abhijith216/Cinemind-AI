"use client";

import { motion } from "framer-motion";
import { useEffect, useState } from "react";

import type { HealthResponse } from "@/lib/api";

const SUGGESTIONS = [
  "Something like Interstellar but not about space, emotional, mind-blowing ending",
  "A cozy comfort movie with witty dialogue",
  "A mind-bending thriller that stays with you",
];

export default function HomePage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/api/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col items-center justify-center gap-8 px-6 py-16">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="text-center"
      >
        <h1 className="bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-5xl font-bold tracking-tight text-transparent">
          CineMind
        </h1>
        <p className="mt-3 text-muted-foreground">
          Describe the mood. Get recommendations — with the &ldquo;why&rdquo;
          spelled out.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.15 }}
        className="w-full rounded-2xl border border-border bg-card p-5 shadow-lg"
      >
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <span
              key={s}
              className="cursor-default rounded-full border border-border bg-secondary px-3 py-1 text-sm text-secondary-foreground/80"
            >
              {s}
            </span>
          ))}
        </div>
        <div className="mt-4 flex gap-2">
          <input
            className="h-11 flex-1 rounded-xl border border-input bg-background px-4 text-sm outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring"
            placeholder="Describe what you feel like watching…"
            aria-label="Movie request"
          />
          <button
            className="h-11 rounded-xl bg-primary px-5 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
            disabled
          >
            Find movies
          </button>
        </div>
      </motion.div>

      <p className="text-xs text-muted-foreground">
        Backend:{" "}
        {health ? (
          <span className={health.database === "up" ? "text-emerald-400" : "text-amber-400"}>
            {health.status} · v{health.version} · db {health.database}
          </span>
        ) : (
          <span className="text-muted-foreground">offline (start the FastAPI server)</span>
        )}
      </p>

      <p className="text-center text-sm text-muted-foreground">
        Chat UI, movie cards, explanation panel, and taste evolution chart land
        in module 9. This page verifies the scaffold end-to-end.
      </p>
    </main>
  );
}
