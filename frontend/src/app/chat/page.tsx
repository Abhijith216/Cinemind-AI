"use client";

import { useEffect, useRef, useState } from "react";
import { SendHorizontal, Sparkles } from "lucide-react";

import {
  MovieCardRow,
  type MatchedAttributeGroup,
  type MovieCardData,
} from "@/components/movie-card-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError, type ChatTurnResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type Role = "user" | "assistant";

interface ChatEntry {
  role: Role;
  text: string;
  /** Quick replies for the NEXT user turn (clarifying questions). */
  suggestions?: string[];
  movies?: MovieCardData[];
}

const OPENING: ChatEntry = {
  role: "assistant",
  text: "What are you in the mood for tonight? Describe it however you like — a vibe, a movie you loved, an ending you need.",
};

const SESSION_STORAGE_KEY = "cinemind.chat.session_id";

/** ChatMovieOut's flat explanation → MovieCard's structured groups. */
function toMatchedGroups(item: ChatTurnResponse["results"][number]): MatchedAttributeGroup[] {
  const attrs = item.matched_attributes;
  const groups: MatchedAttributeGroup[] = [];
  if (attrs.genres.length > 0) {
    groups.push({ label: "Genres", kind: "genre", items: attrs.genres });
  }
  if (attrs.themes.length > 0) {
    groups.push({ label: "Themes", kind: "theme", items: attrs.themes });
  }
  if (attrs.personality_traits.length > 0) {
    groups.push({ label: "Personality", kind: "trait", items: attrs.personality_traits });
  }
  if (attrs.intent_matches.length > 0) {
    groups.push({ label: "Intent", kind: "intent", items: attrs.intent_matches });
  }
  if (attrs.loved_movie_overlaps.length > 0) {
    groups.push({
      label: "Your favorites",
      kind: "loved",
      items: attrs.loved_movie_overlaps.map((overlap) =>
        overlap.detail ? `${overlap.label} — ${overlap.detail}` : overlap.label,
      ),
    });
  }
  return groups;
}

function rankedToCard(item: ChatTurnResponse["results"][number]): MovieCardData {
  return {
    movieId: item.movie.id,
    title: item.movie.title,
    year: item.movie.release_year ?? null,
    rating: item.movie.vote_average ?? null,
    posterUrl: item.movie.poster_path
      ? `https://image.tmdb.org/t/p/w500${item.movie.poster_path}`
      : null,
    explanation: item.explanation.length > 0 ? item.explanation : null,
    matched: toMatchedGroups(item),
  };
}

/**
 * Quick-reply chips for a clarifying turn: known question shapes first
 * (deterministic, user-voice), then themes the model echoed back.
 */
function quickRepliesFor(turn: ChatTurnResponse): string[] {
  const reply = turn.reply.toLowerCase();
  if (reply.includes("mind-bending") || reply.includes("heartfelt") || reply.includes("light and funny")) {
    return ["mind-bending thriller", "something heartfelt", "light and funny"];
  }
  if (reply.includes("how much time")) {
    return ["about two hours", "under 90 minutes", "a long epic"];
  }
  const intent = turn.intent as Record<string, unknown> | null;
  if (intent && Array.isArray(intent["themes"])) {
    const themes = intent["themes"].map(String).filter((t) => t.length > 0);
    if (themes.length > 0) return themes.slice(0, 3);
  }
  const quoted = [...turn.reply.matchAll(/"([^"]+)"/g)].map(
    (match) => match[1]?.trim() ?? "",
  );
  return quoted.filter((s) => s.length > 0).slice(0, 3);
}

export default function ChatPage() {
  const [entries, setEntries] = useState<ChatEntry[]>([OPENING]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollBottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Resume the same conversation after a reload (backend keeps the history).
  useEffect(() => {
    const saved = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (saved) setSessionId(saved);
  }, []);

  useEffect(() => {
    scrollBottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries, pending]);

  async function send(text: string): Promise<void> {
    const trimmed = text.trim();
    if (trimmed.length === 0 || pending) return;
    setPending(true);
    setError(null);
    setInput("");
    setEntries((prev) => [
      ...prev,
      { role: "user", text: trimmed },
      { role: "assistant", text: "" }, // placeholder replaced by the response
    ]);
    try {
      const turn = await api.chat.sendMessage({
        message: trimmed,
        session_id: sessionId ?? undefined,
      });
      if (sessionId === null && turn.session_id) {
        setSessionId(turn.session_id);
        window.sessionStorage.setItem(SESSION_STORAGE_KEY, turn.session_id);
      }
      setEntries((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          text: turn.reply,
          suggestions: turn.results.length === 0 ? quickRepliesFor(turn) : [],
          movies: turn.results.map(rankedToCard),
        };
        return next;
      });
    } catch (err) {
      setEntries((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          text:
            err instanceof ApiError
              ? `Something went wrong (${err.status}). ${err.message}`
              : "Something went wrong. Please try again.",
          suggestions: [],
          movies: [],
        };
        return next;
      });
      setError(
        err instanceof ApiError ? `Request failed with status ${err.status}` : "Request failed",
      );
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  }

  const last = entries.length - 1;

  return (
    <div className="mx-auto flex h-[calc(100dvh-4rem)] w-full max-w-4xl flex-col px-4">
      <header className="pt-6 pb-2">
        <h1 className="text-2xl font-semibold tracking-tight">Chat with CineMind</h1>
        <p className="text-sm text-muted-foreground">
          Describe what you want to watch — a vibe, a movie you loved, an ending you need.
        </p>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto rounded-lg border border-border/60 bg-card/30 p-4">
        {entries.map((entry, index) => (
          <div key={index} className="space-y-2">
            <div className={cnBubble(entry.role)}>{entry.text}</div>

            {/* Recommendations from a search turn render under the reply. */}
            {entry.role === "assistant" && entry.movies && entry.movies.length > 0 && (
              <MovieCardRow movies={entry.movies} />
            )}

            {/* Quick replies only on the latest assistant turn, never mid-send. */}
            {entry.role === "assistant" && index === last && !pending &&
              entry.suggestions && entry.suggestions.length > 0 && (
                <div className="flex flex-wrap gap-2" aria-label="Suggested replies">
                  {entry.suggestions.map((suggestion) => (
                    <Button
                      key={suggestion}
                      variant="outline"
                      size="sm"
                      onClick={() => void send(suggestion)}
                      className="border-violet-500/40 text-violet-300 hover:bg-violet-500/10 hover:text-violet-200"
                    >
                      {suggestion}
                    </Button>
                  ))}
                </div>
              )}
          </div>
        ))}
        {pending && <TypingIndicator />}
        <div ref={scrollBottomRef} />
      </div>

      {error && (
        <p className="pt-2 text-sm text-rose-400" role="alert">
          {error}
        </p>
      )}

      <form
        className="flex gap-2 py-4"
        onSubmit={(event) => {
          event.preventDefault();
          void send(input);
        }}
      >
        <Input
          ref={inputRef}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="e.g. something like Interstellar but not about space, emotional, mind-blowing ending"
          disabled={pending}
          className="flex-1"
          aria-label="Chat message"
        />
        <Button
          type="submit"
          disabled={pending || input.trim().length === 0}
          aria-label="Send message"
        >
          <SendHorizontal className="size-4" />
          Send
        </Button>
      </form>
    </div>
  );
}

function cnBubble(role: Role): string {
  return role === "user"
    ? "ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-sm bg-amber-500/15 px-4 py-2 text-sm ring-1 ring-amber-500/30"
    : "mr-auto w-fit max-w-[80%] rounded-2xl rounded-bl-sm bg-card px-4 py-2 text-sm ring-1 ring-border/60";
}

function TypingIndicator(): React.JSX.Element {
  return (
    <div
      className="mr-auto flex items-center gap-2 rounded-2xl bg-card px-4 py-3 ring-1 ring-border/60"
      aria-label="CineMind is thinking"
    >
      <Sparkles className="size-4 animate-pulse text-amber-300" />
      <span className="flex gap-1">
        <Dot delay="0ms" />
        <Dot delay="150ms" />
        <Dot delay="300ms" />
      </span>
    </div>
  );
}

function Dot({ delay }: { delay: string }): React.JSX.Element {
  return (
    <span
      className="size-1.5 animate-bounce rounded-full bg-amber-300/70"
      style={{ animationDelay: delay }}
    />
  );
}
