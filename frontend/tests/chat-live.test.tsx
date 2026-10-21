import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import ChatPage from "@/app/chat/page";
import { AuthProvider } from "@/components/auth-provider";
import { api } from "@/lib/api";

afterEach(cleanup);

// Opt-in: makes real provider calls. Requires a running configured backend.
it.skipIf(process.env.CINEMIND_LIVE_AI !== "1")(
  "uses real AI/catalog services and restores recommendations on reload",
  async () => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    const user = userEvent.setup();
    const view = render(<AuthProvider><ChatPage /></AuthProvider>);
    const input = screen.getByLabelText("Chat message") as HTMLInputElement;
    await waitFor(() => expect(input.disabled).toBe(false), { timeout: 10_000 });
    await user.type(input, "A comedy about friendship, no horror, at most 90 minutes{Enter}");
    const movies = await screen.findByRole("list", { name: "Recommended movies" }, { timeout: 70_000 });
    const cards = within(movies).getAllByRole("listitem");
    expect(cards.length).toBeGreaterThan(0);
    for (const card of cards) {
      const runtime = card.textContent?.match(/· (\d+) min/);
      expect(runtime).not.toBeNull();
      expect(Number(runtime![1])).toBeLessThanOrEqual(90);
    }
    const title = within(cards[0]!).getByRole("heading").textContent!;
    const saved = window.sessionStorage.getItem("cinemind.chat.session_id");
    expect(saved).toMatch(/^[a-f0-9-]{36}$/);
    await waitFor(() => expect(input.disabled).toBe(false));
    await user.type(input, "At most 80 minutes; keep all my other constraints{Enter}");
    await waitFor(() => expect(screen.getAllByRole("list", { name: "Recommended movies" })).toHaveLength(2), { timeout: 70_000 });
    const transcript = await api.chat.getSession(saved!);
    const last = transcript.messages.filter((message) => message.role === "assistant").at(-1)!;
    expect(last.intent?.runtime_max).toBeLessThanOrEqual(80);
    expect(last.intent?.genres_exclude).toContain("Horror");
    expect(last.intent?.genres_include).toContain("Comedy");
    expect(last.results.length).toBeGreaterThan(0);
    for (const result of last.results) {
      expect(result.movie.runtime).toBeLessThanOrEqual(80);
      expect(result.movie.genres).not.toContain("Horror");
    }
    view.unmount();
    render(<AuthProvider><ChatPage /></AuthProvider>);
    await screen.findAllByRole("heading", { name: title }, { timeout: 45_000 });
    expect(screen.queryByRole("alert")).toBeNull();
  },
  180_000,
);
