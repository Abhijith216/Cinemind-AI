import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import ProfilePage from "@/app/profile/page";
import TasteEvolutionPage from "@/app/taste-evolution/page";

const owner = "f728f15c-30ee-4bdd-8c18-79c708b37500";
const movie = { id: "88752c4f-df2f-4fb4-8684-adc1463f141d", tmdb_id: 1, title: "Arrival", release_year: 2016, runtime: 116, genres: ["Science Fiction"], keywords: ["time"], poster_path: null, overview: "A linguist makes first contact.", vote_average: 8 };
const auth = vi.hoisted(() => ({ user: null as { id: string } | null, hydrated: true }));
vi.mock("@/components/auth-provider", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({ usePathname: () => "/profile" }));
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => { auth.user = { id: owner }; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("explains My Taste to signed-out visitors without requesting private records", () => {
  auth.user = null;
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<ProfilePage />);
  expect(screen.getByRole("heading", { name: "Your movie taste, in one place" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Sign in or register" }).getAttribute("href")).toBe("/login?next=%2Fprofile");
  expect(fetch).not.toHaveBeenCalled();
});

it("searches a movie, saves a score, refreshes preferences, and edits the saved rating", async () => {
  let saved: number | null = null;
  const writes: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url.endsWith("/taste-dashboard")) return json({
      profile: saved ? { user_id: owner, likes: saved >= 7 ? ["Science Fiction", "time"] : [], dislikes: saved <= 4 ? ["Science Fiction"] : [], favorite_themes: saved >= 7 ? ["time"] : [] } : null,
      total_ratings: saved ? 1 : 0, average_score: saved,
      ratings: saved ? [{ id: "r", movie, score: saved, rated_at: "2026-10-21T12:00:00Z" }] : [], recommendations: [],
    });
    if (url.endsWith("/api/search/discover")) return json({ results: [{ movie }] });
    if (url.includes("/api/ratings/")) return json(saved ? { score: saved } : null);
    if (url.endsWith("/api/ratings")) {
      const data = JSON.parse(init.body as string); writes.push(data); saved = data.score;
      return json({ score: saved, created: writes.length === 1 });
    }
    throw new Error("Unexpected request");
  }));
  const user = userEvent.setup(); render(<ProfilePage />);
  await screen.findByRole("region", { name: "Your rating summary" });
  await user.type(screen.getByRole("textbox", { name: "Movie title" }), "Arrival{Enter}");
  await user.click(await screen.findByRole("button", { name: "Rate Arrival" }));
  await waitFor(() => expect((screen.getByLabelText("Your rating") as HTMLSelectElement).disabled).toBe(false));
  await user.selectOptions(screen.getByLabelText("Your rating"), "9");
  await user.click(screen.getByRole("button", { name: "Save rating" }));
  const preferences = await screen.findByRole("region", { name: "Your preferences" });
  await within(preferences).findByText("Science Fiction");
  await screen.findByRole("button", { name: "Edit rating for Arrival" });
  expect(writes[0]).toEqual({ user_id: owner, movie_id: movie.id, score: 9 });
  await user.click(screen.getByRole("button", { name: "Edit rating for Arrival" }));
  await user.selectOptions(screen.getByLabelText("Your rating"), "3");
  await user.click(screen.getByRole("button", { name: "Save rating" }));
  await waitFor(() => expect(within(screen.getByRole("region", { name: "Your preferences" })).queryByText("time")).toBeNull());
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual({ user_id: owner, movie_id: movie.id, score: 3 });
});

it("shows a retry when the profile cannot load", async () => {
  let tries = 0;
  vi.stubGlobal("fetch", vi.fn(async () => ++tries === 1 ? json({ detail: "Unavailable" }, 503)
    : json({ profile: null, total_ratings: 0, average_score: null, ratings: [], recommendations: [] })));
  const user = userEvent.setup(); render(<ProfilePage />);
  await screen.findByRole("alert");
  await user.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByRole("region", { name: "Your rating summary" });
  expect(screen.queryByRole("alert")).toBeNull();
});

it("shows the factual reason and matched taste attributes for a recommendation", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({
    profile: { user_id: owner, likes: ["Science Fiction", "time"], dislikes: [], favorite_themes: ["time"] },
    total_ratings: 1, average_score: 7, ratings: [],
    recommendations: [{ ...movie, explanation: "Arrival shares Science Fiction and time with your favorites.", preference_score: 0.25,
      matched_attributes: { genres: ["Science Fiction"], themes: ["time"], personality_traits: [], intent_matches: [], loved_movie_overlaps: [] } }],
  })));
  const user = userEvent.setup(); render(<ProfilePage />);
  const suggestions = await screen.findByRole("region", { name: "Movies for your taste" });
  await within(suggestions).findByText("Arrival shares Science Fiction and time with your favorites.");
  expect(within(suggestions).queryByText("No explanation available yet.")).toBeNull();
  await user.click(within(suggestions).getByRole("button", { name: "Why this?" }));
  expect(within(suggestions).getByText("Genres you enjoy")).toBeTruthy();
  expect(within(suggestions).getByText("time")).toBeTruthy();
});

it("shows the first month of taste without requiring a job or another user's id", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    expect(url).toContain(`/api/users/${owner}/taste-evolution`);
    return json([{ user_id: owner, month: "2026-10", dominant_genres: ["Science Fiction"], dominant_themes: ["time"] }]);
  }));
  render(<TasteEvolutionPage />);
  const months = await screen.findByRole("list", { name: "Monthly taste history" });
  expect(within(months).getByRole("heading", { name: "October 2026" })).toBeTruthy();
  expect(within(months).getByText("Science Fiction")).toBeTruthy();
});

it("removes a rating only after confirmation and refreshes taste", async () => {
  let removed = false;
  const remove = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    if (init.method === "DELETE") { remove(); removed = true; return new Response(null, { status: 204 }); }
    return json({ profile: { likes: removed ? [] : ["Science Fiction"], dislikes: [], favorite_themes: [] }, total_ratings: removed ? 0 : 1, average_score: removed ? null : 9, ratings: removed ? [] : [{ id: "rating", movie, score: 9, rated_at: "2026-10-21T12:00:00Z" }], recommendations: [] });
  }));
  const user = userEvent.setup(); render(<ProfilePage />);
  await user.click(await screen.findByRole("button", { name: "Remove rating for Arrival" }));
  expect(remove).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Confirm removal" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Remove rating for Arrival" })).toBeNull());
  expect(remove).toHaveBeenCalledOnce();
});

it("loads ratings beyond the first fifty", async () => {
  const rows = Array.from({ length: 52 }, (_, i) => ({ id: `r${i}`, movie: { ...movie, id: `${movie.id}-${i}`, title: `Film ${i}` }, score: 7, rated_at: "2026-10-21T12:00:00Z" }));
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes("/ratings/history?offset=50&limit=50")
    ? json({ items: rows.slice(50), total: 52, offset: 50, limit: 50 })
    : json({ profile: null, total_ratings: 52, average_score: 7, ratings: rows.slice(0, 50), recommendations: [] })));
  const user = userEvent.setup(); render(<ProfilePage />);
  await user.click(await screen.findByRole("button", { name: "Load older ratings" }));
  await screen.findByRole("link", { name: "Film 51" });
  expect(screen.queryByRole("button", { name: "Load older ratings" })).toBeNull();
});
