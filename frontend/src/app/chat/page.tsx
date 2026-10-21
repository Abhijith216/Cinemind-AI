"use client";

import { useEffect, useRef, useState } from "react";
import { SendHorizontal, Sparkles } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";

import {
  MovieCardRow,
  type MatchedAttributeGroup,
  type MovieCardData,
} from "@/components/movie-card-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError, type ChatTurnResponse, type IntegrationStatus, type ChatSessionSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

type Role = "user" | "assistant";

interface ChatEntry {
  role: Role;
  text: string;
  /** Quick replies for the NEXT user turn (clarifying questions). */
  suggestions?: string[];
  movies?: MovieCardData[];
  /** This assistant bubble is a failure — offer a retry of retryText. */
  failed?: boolean;
  retryText?: string;
  /** Search ran but returned nothing (not a clarifying turn). */
  noResults?: boolean;
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
    runtime: item.movie.runtime,
    overview: item.movie.overview,
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

/**
 * One honest, actionable message per failure mode — LLM slowness, rate
 * limits, and a dead backend read differently, and none of them crash.
 */
function describeChatError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return "You're sending messages faster than our API budget allows. Give it about a minute, then try again.";
    }
    if (error.status === 503 || error.status === 502 || error.status === 504) {
      return error.message || "Chat is temporarily unavailable. Please try again.";
    }
    if (error.status === 404) {
      return "This conversation expired on the server. Send any message to start a fresh one.";
    }
    return `Something went wrong (${error.status}). ${error.message}`;
  }
  if (
    error instanceof DOMException &&
    (error.name === "TimeoutError" || error.name === "AbortError")
  ) {
    return "That took too long — deep dives can be slow, but this timed out. Try rephrasing, or send it again.";
  }
  return "Chat couldn’t connect. Please try again in a moment.";
}

export default function ChatPage() {
  const { hydrated, user } = useAuth();
  const [entries, setEntries] = useState<ChatEntry[]>([OPENING]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const sending = useRef(false);
  const [restoring, setRestoring] = useState(true);
  const [integrations, setIntegrations] = useState<IntegrationStatus | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [savedChats, setSavedChats] = useState<ChatSessionSummary[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [managementError, setManagementError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [managing, setManaging] = useState(false);
  const managementController = useRef<AbortController | null>(null);

  useEffect(() => {
    setHistoryOpen(false); setSavedChats([]); setManagementError(null); setManaging(false); setHistoryLoading(false); setConfirmDelete(false);
    return () => managementController.current?.abort();
  }, [user?.id]);

  async function loadHistory(offset = 0) {
    if (!user || historyLoading) return;
    const controller = new AbortController();
    managementController.current?.abort(); managementController.current = controller;
    setHistoryLoading(true); setManagementError(null);
    try {
      const page = await api.chat.history(offset, controller.signal);
      if (!controller.signal.aborted) { setSavedChats((current) => offset ? [...current, ...page.items] : page.items); setHistoryTotal(page.total); }
    } catch { if (!controller.signal.aborted) setManagementError("Couldn’t load saved chats. Close and reopen history to try again."); }
    finally { if (!controller.signal.aborted) setHistoryLoading(false); }
  }

  async function openChat(id: string) {
    const controller = new AbortController();
    managementController.current?.abort(); managementController.current = controller;
    setHistoryLoading(false);
    setManaging(true); setManagementError(null);
    try {
      const chat = await api.chat.getSession(id, controller.signal);
      if (!controller.signal.aborted) {
        setSessionId(chat.id); setEntries(chat.messages.length ? chat.messages.map((message) => ({ role: message.role, text: message.content, movies: message.results.map(rankedToCard) })) : [OPENING]);
        try { window.sessionStorage.setItem(SESSION_STORAGE_KEY, chat.id); } catch {}
        setHistoryOpen(false); setConfirmDelete(false); setError(null);
      }
    } catch { if (!controller.signal.aborted) setManagementError("Couldn’t open that conversation. Try another chat or reload history."); }
    finally { if (!controller.signal.aborted) setManaging(false); }
  }

  async function deleteCurrentChat() {
    if (!sessionId) return;
    const controller = new AbortController();
    managementController.current?.abort(); managementController.current = controller;
    setManaging(true); setManagementError(null);
    try {
      await api.chat.remove(sessionId, controller.signal);
      if (!controller.signal.aborted) { setSavedChats((current) => current.filter((chat) => chat.id !== sessionId)); setHistoryTotal((total) => Math.max(0, total - 1)); setConfirmDelete(false); newChat(); }
    } catch { if (!controller.signal.aborted) setManagementError("Couldn’t delete this conversation. Please try again."); }
    finally { if (!controller.signal.aborted) setManaging(false); }
  }

  // Resume the same conversation after a reload (backend keeps the history).
  useEffect(() => {
    if (!hydrated) return;
    const abort = new AbortController();
    void api.integrations().then((status) => {
      if (!abort.signal.aborted) setIntegrations(status);
    }).catch(() => {});
    async function restore() {
      setRestoring(true);
      setSessionId(null);
      setEntries([OPENING]);
      try {
        const saved = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
        if (!saved) return;
        const conversation = await api.chat.getSession(saved, abort.signal);
        if (abort.signal.aborted) return;
        setSessionId(conversation.id);
        setEntries(conversation.messages.length ? conversation.messages.map((message) => ({
          role: message.role,
          text: message.content,
          movies: (message.results ?? []).map(rankedToCard),
        })) : [OPENING]);
      } catch (failure) {
        if (abort.signal.aborted) return;
        if (failure instanceof ApiError && [401, 404, 422].includes(failure.status)) {
          try { window.sessionStorage.removeItem(SESSION_STORAGE_KEY); } catch {}
          setSessionId(null);
          setError("Your previous conversation is unavailable. Start a new chat below.");
        } else {
          setError("Couldn’t restore your previous conversation. You can start a new chat below.");
        }
      } finally {
        if (!abort.signal.aborted) setRestoring(false);
      }
    }
    void restore();
    return () => abort.abort();
  }, [hydrated, user?.id]);

  useEffect(() => {
    const conversation = conversationRef.current;
    conversation?.scrollTo?.({
      top: conversation.scrollHeight,
      behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  }, [entries, pending]);

  async function send(text: string, retry = false): Promise<void> {
    const trimmed = text.trim();
    if (trimmed.length === 0 || sending.current || restoring || integrations?.chat_configured === false) return;
    sending.current = true;
    setPending(true);
    setHistoryOpen(false); setConfirmDelete(false);
    setError(null);
    setInput("");
    setEntries((prev) => [
      ...(retry && prev.at(-1)?.failed ? prev.slice(0, -2) : prev),
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
        try { window.sessionStorage.setItem(SESSION_STORAGE_KEY, turn.session_id); } catch {}
      }
      setEntries((prev) => {
        const next = [...prev];
        const isClarifying =
          turn.results.length === 0 && turn.asked_clarifying_question;
        next[next.length - 1] = {
          role: "assistant",
          text: turn.reply,
          suggestions: isClarifying ? quickRepliesFor(turn) : [],
          movies: turn.results.map(rankedToCard),
          // A searched turn that found nothing is its own honest state.
          noResults: turn.results.length === 0 && !isClarifying,
        };
        return next;
      });
    } catch (err) {
      if (err instanceof ApiError && [404, 409].includes(err.status)) {
        setSessionId(null);
        try { window.sessionStorage.removeItem(SESSION_STORAGE_KEY); } catch {}
      }
      setEntries((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          text: describeChatError(err),
          failed: true,
          retryText: trimmed,
          suggestions: [],
          movies: [],
        };
        return next;
      });
    } finally {
      setPending(false);
      sending.current = false;
      inputRef.current?.focus();
    }
  }

  const last = entries.length - 1;
  const unavailable = integrations?.chat_configured === false;
  const busy = pending || restoring || managing || !hydrated;

  function newChat() {
    managementController.current?.abort(); setHistoryLoading(false); setManaging(false); setHistoryOpen(false);
    setConfirmDelete(false);
    setSessionId(null); setEntries([OPENING]); setError(null); setInput("");
    try { window.sessionStorage.removeItem(SESSION_STORAGE_KEY); } catch {}
    inputRef.current?.focus();
  }

  return (
    <div className="cinema-shell flex h-[calc(100dvh-4.75rem)] min-h-0 max-w-6xl flex-col pt-4 sm:pt-6 [@media(max-height:650px)]:pt-2">
      <header className="flex shrink-0 flex-col justify-between gap-3 pb-4 sm:flex-row sm:items-end [@media(max-height:650px)]:pb-2">
        <div>
        <p className="cinema-eyebrow mb-3 [@media(max-height:650px)]:hidden">The conversation</p>
        <h1 className="cinema-display text-4xl sm:text-5xl [@media(max-height:650px)]:text-2xl">Talk your way to a film.</h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground [@media(max-height:650px)]:hidden">
          Describe what you want to watch — a vibe, a movie you loved, an ending you need.
        </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={newChat} disabled={busy} className="rounded-full">New chat</Button>
          {user && <Button variant="outline" disabled={busy || historyLoading} aria-expanded={historyOpen} onClick={() => { setHistoryOpen(!historyOpen); if (!historyOpen) void loadHistory(); }}>Saved chats</Button>}
          {sessionId && <Button variant="ghost" disabled={busy || historyLoading} onClick={() => setConfirmDelete(true)}>Delete chat</Button>}
        </div>
      </header>
      {historyOpen && <section aria-label="Saved conversations" className="mb-3 max-h-[20dvh] shrink-0 overflow-y-auto rounded-xl border border-border p-3">
        <p className="mb-2 text-xs text-muted-foreground">Chats stay saved until you delete them. New chat keeps previous conversations.</p>
        {historyLoading && <p role="status">Loading conversations…</p>}
        {!historyLoading && savedChats.length === 0 && <p className="text-sm">No saved conversations yet.</p>}
        <ul className="space-y-1">{savedChats.map((chat) => <li key={chat.id}><button type="button" disabled={busy || historyLoading} className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => void openChat(chat.id)}>{chat.title}<span className="ml-2 text-xs text-muted-foreground"> · {new Date(chat.updated_at).toLocaleDateString()}</span></button></li>)}</ul>
        {savedChats.length < historyTotal && <Button type="button" variant="outline" disabled={busy || historyLoading} onClick={() => void loadHistory(savedChats.length)}>Load older chats</Button>}
      </section>}
      {confirmDelete && <div className="mb-3 shrink-0 rounded-xl border border-border p-3"><p className="mb-2 text-sm">Permanently delete this conversation and its messages?</p><div className="flex gap-2"><Button type="button" disabled={busy} onClick={() => void deleteCurrentChat()}>Confirm deletion</Button><Button type="button" variant="outline" disabled={busy} onClick={() => setConfirmDelete(false)}>Cancel</Button></div></div>}
      {managementError && <p role="alert" className="mb-2 shrink-0 text-sm text-rose-300">{managementError}</p>}

      {unavailable && <p role="status" className="mb-3 rounded-lg border border-amber-500/30 p-3 text-sm text-amber-200">
        AI chat is not connected yet. <Link href="/" className="underline">Explore movies in Discover</Link> while it is being set up.
      </p>}
      {restoring && <p role="status" className="py-2 text-sm text-muted-foreground">Loading your conversation…</p>}

      <div ref={conversationRef} role="log" aria-label="Movie conversation" aria-live="polite" tabIndex={0} className="cinema-surface min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain rounded-[1.5rem] p-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-8">
        {entries.map((entry, index) => (
          <div key={index} className="space-y-2">
            {entry.text && <div
              role={entry.failed ? "alert" : undefined}
              className={cn(
                cnBubble(entry.role),
                entry.failed && "border-rose-500/30 text-rose-200",
              )}
            >
              {entry.text}
            </div>}

            {/* Retry affordance on failed turns (latest only). */}
            {entry.failed && index === last && entry.retryText && (
              <div className="mr-auto">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void send(entry.retryText ?? "", true)}
                  disabled={pending}
                >
                  Try again
                </Button>
              </div>
            )}

            {/* Honest empty state: the search ran and found nothing. */}
            {entry.role === "assistant" && entry.noResults && (
              <p className="mr-auto rounded-lg border border-dashed border-border/60 px-4 py-3 text-sm text-muted-foreground">
                Nothing in the catalog matched that. Try broadening the mood or
                dropping a filter.
              </p>
            )}

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
      </div>

      {error && (
        <p className="max-h-20 shrink-0 overflow-y-auto pt-2 text-sm text-rose-400" role="alert">
          {error}
        </p>
      )}

      <form
        className="flex shrink-0 gap-2 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
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
          disabled={busy || unavailable}
          maxLength={2000}
          className="h-12 flex-1 rounded-xl"
          aria-label="Chat message"
        />
        <Button
          type="submit"
          disabled={busy || unavailable || input.trim().length === 0}
          aria-label="Send message"
          className="h-12 rounded-xl px-5"
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
    ? "ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-primary/15 px-5 py-3 text-sm leading-relaxed ring-1 ring-primary/30"
    : "mr-auto w-fit max-w-[85%] rounded-2xl rounded-bl-sm bg-[#211b1d] px-5 py-3 text-sm leading-relaxed ring-1 ring-border/60";
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
