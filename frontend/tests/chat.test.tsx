import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage from "@/app/chat/page";

const auth = vi.hoisted(() => ({ hydrated: true, user: null as { id: string } | null }));
vi.mock("@/components/auth-provider", () => ({ useAuth: () => auth }));

const sessionId = "f728f15c-30ee-4bdd-8c18-79c708b37500";
const movie = {
  id: "88752c4f-df2f-4fb4-8684-adc1463f141d", title: "Interstellar", tmdb_id: 157336,
  release_year: 2014, runtime: 169, overview: "Explorers travel beyond the stars.",
  vote_average: 8.1, poster_path: null,
};
const turn = {
  session_id: sessionId, reply: "Here is a movie with themes you asked for.",
  asked_clarifying_question: false, intent: { genres_include: ["Science Fiction"] },
  results: [{ movie, final_score: 1, explanation: "Science Fiction matches your request.",
    matched_attributes: { genres: ["Science Fiction"], themes: [], personality_traits: [],
      intent_matches: [], loved_movie_overlaps: [] } }],
};
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
const messageCalls: RequestInit[] = [];

function setupFetch(send: (init: RequestInit) => Promise<Response> = async () => response(turn),
  restored?: unknown, configured = true) {
  const mock = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url.endsWith("/api/integrations")) return response({ chat_configured: configured, tmdb_configured: true });
    if (url.includes("/api/chat/sessions/")) return restored
      ? response(restored) : response({ detail: "Chat session not found" }, 404);
    if (url.endsWith("/api/chat/message")) { messageCalls.push(init); return send(init); }
    throw new Error(`Unexpected test request: ${url}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

async function ready() {
  const input = screen.getByLabelText("Chat message") as HTMLInputElement;
  await waitFor(() => expect(input.disabled).toBe(false));
  return input;
}

beforeEach(() => { auth.user = null; window.sessionStorage.clear(); messageCalls.length = 0; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("AI chat", () => {
  it("deletes a conversation after confirmation and clears the browser selection", async () => {
    window.sessionStorage.setItem("cinemind.chat.session_id", sessionId);
    const remove = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      if (url.endsWith("/api/integrations")) return response({ chat_configured: true, tmdb_configured: true });
      if (init.method === "DELETE") { remove(); return new Response(null, { status: 204 }); }
      return response({ id: sessionId, messages: [{ role: "assistant", content: "Saved conversation", results: [] }] });
    }));
    const user = userEvent.setup(); render(<ChatPage />);
    await ready();
    await user.click(await screen.findByRole("button", { name: "Delete chat" }));
    expect(remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm deletion" }));
    await waitFor(() => expect(window.sessionStorage.getItem("cinemind.chat.session_id")).toBeNull());
    expect(remove).toHaveBeenCalledOnce();
    expect(screen.queryByText("Saved conversation")).toBeNull();
  });

  it("opens an account conversation from saved history", async () => {
    auth.user = { id: "owner" };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/api/integrations")) return response({ chat_configured: true, tmdb_configured: true });
      if (url.includes("/api/chat/sessions?")) return response({ items: [{ id: sessionId, title: "Comedy conversation", updated_at: "2026-10-21T12:00:00Z" }], total: 1, offset: 0, limit: 20 });
      return response({ id: sessionId, messages: [{ role: "assistant", content: "Your restored reply", results: [] }] });
    }));
    const user = userEvent.setup(); render(<ChatPage />);
    await ready(); await user.click(screen.getByRole("button", { name: "Saved chats" }));
    await user.click(await screen.findByRole("button", { name: /Comedy conversation/ }));
    await screen.findByText("Your restored reply");
    expect(window.sessionStorage.getItem("cinemind.chat.session_id")).toBe(sessionId);
  });

  it("clears an interrupted history refresh when starting a new chat", async () => {
    auth.user = { id: "owner" };
    let loads = 0;
    const page = { items: [{ id: sessionId, title: "Saved request", updated_at: "2026-10-21T12:00:00Z" }], total: 1 };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      if (url.endsWith("/api/integrations")) return response({ chat_configured: true, tmdb_configured: true });
      if (url.includes("/api/chat/sessions?")) {
        loads++;
        if (loads === 2) return new Promise<Response>((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
        return response(page);
      }
      return response({ id: sessionId, messages: [{ role: "assistant", content: "Restored", results: [] }] });
    }));
    const user = userEvent.setup(); render(<ChatPage />);
    await ready(); await user.click(screen.getByRole("button", { name: "Saved chats" }));
    await user.click(await screen.findByRole("button", { name: /Saved request/ }));
    await screen.findByText("Restored");
    await user.click(screen.getByRole("button", { name: "Saved chats" }));
    expect((screen.getByRole("button", { name: /Saved request/ }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect((screen.getByRole("button", { name: "Saved chats" }) as HTMLButtonElement).disabled).toBe(false);
    await user.click(screen.getByRole("button", { name: "Saved chats" }));
    await user.click(await screen.findByRole("button", { name: /Saved request/ }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Delete chat" }) as HTMLButtonElement).disabled).toBe(false));
  });
  it("shows a greeting response without a provider error or an empty-results notice", async () => {
    setupFetch(async () => response({ ...turn,
      reply: "Hey! What kind of movie are you in the mood for?",
      asked_clarifying_question: true, intent: null, results: [],
    }));
    const user = userEvent.setup();
    render(<ChatPage />);
    await user.type(await ready(), "hey{Enter}");
    await screen.findByText("Hey! What kind of movie are you in the mood for?");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/Nothing in the catalog matched/)).toBeNull();
  });

  it("reports the server's database outage without blaming the language model", async () => {
    setupFetch(async () => response({ detail: "The movie catalog is temporarily unavailable. Please try again shortly." }, 503));
    const user = userEvent.setup();
    render(<ChatPage />);
    await user.type(await ready(), "a comedy{Enter}");
    expect((await screen.findByRole("alert")).textContent).toContain("movie catalog");
    expect(screen.queryByText(/Your message is safe/)).toBeNull();
  });

  it("submits once, renders a movie card/link, and sends follow-ups in the same session", async () => {
    setupFetch();
    const user = userEvent.setup();
    render(<ChatPage />);
    const input = await ready();
    await user.type(input, "science fiction");
    await user.dblClick(screen.getByRole("button", { name: "Send message" }));
    await screen.findByRole("link", { name: "Interstellar" });
    expect(messageCalls).toHaveLength(1);
    expect(window.sessionStorage.getItem("cinemind.chat.session_id")).toBe(sessionId);
    await user.type(input, "under two hours{Enter}");
    await waitFor(() => expect(messageCalls).toHaveLength(2));
    expect(JSON.parse(messageCalls[1]!.body as string).session_id).toBe(sessionId);
    await waitFor(() => expect(input.disabled).toBe(false));
  });

  it("restores conversation text and movie cards after a reload", async () => {
    window.sessionStorage.setItem("cinemind.chat.session_id", sessionId);
    setupFetch(undefined, { id: sessionId, messages: [
      { id: "1", role: "user", content: "science fiction", results: [] },
      { id: "2", role: "assistant", content: turn.reply, results: turn.results },
    ] });
    const user = userEvent.setup();
    render(<ChatPage />);
    await ready();
    expect(screen.getByRole("link", { name: "Interstellar" })).toBeTruthy();
    expect(messageCalls).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(window.sessionStorage.getItem("cinemind.chat.session_id")).toBeNull();
    expect(screen.queryByRole("link", { name: "Interstellar" })).toBeNull();
  });

  it("clears an expired session so the next send starts a new conversation", async () => {
    window.sessionStorage.setItem("cinemind.chat.session_id", sessionId);
    setupFetch();
    const user = userEvent.setup();
    render(<ChatPage />);
    const input = await ready();
    expect(window.sessionStorage.getItem("cinemind.chat.session_id")).toBeNull();
    await user.type(input, "a comedy{Enter}");
    await screen.findByRole("link", { name: "Interstellar" });
    expect(JSON.parse(messageCalls[0]!.body as string).session_id).toBeUndefined();
  });

  it("retries a failed turn without duplicating the user message", async () => {
    let attempts = 0;
    setupFetch(async () => ++attempts === 1
      ? response({ detail: "Provider unavailable" }, 503) : response(turn));
    const user = userEvent.setup();
    render(<ChatPage />);
    await user.type(await ready(), "A cozy film request{Enter}");
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("link", { name: "Interstellar" });
    expect(within(screen.getByRole("log")).getAllByText("A cozy film request")).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("offers clickable clarification replies", async () => {
    let attempts = 0;
    setupFetch(async () => ++attempts === 1 ? response({ ...turn,
      reply: "Would you like something mind-bending or heartfelt?", results: [],
      asked_clarifying_question: true,
    }) : response(turn));
    const user = userEvent.setup();
    render(<ChatPage />);
    await user.type(await ready(), "surprise me{Enter}");
    await user.click(await screen.findByRole("button", { name: "mind-bending thriller" }));
    await screen.findByRole("link", { name: "Interstellar" });
    expect(JSON.parse(messageCalls[1]!.body as string).message).toBe("mind-bending thriller");
  });

  it("shows configuration truthfully and disables AI requests until connected", async () => {
    setupFetch(undefined, undefined, false);
    render(<ChatPage />);
    await screen.findByText(/AI chat is not connected yet/);
    expect((screen.getByLabelText("Chat message") as HTMLInputElement).disabled).toBe(true);
    expect(messageCalls).toHaveLength(0);
    expect(screen.getByRole("link", { name: /Explore movies in Discover/ })).toBeTruthy();
  });
});
