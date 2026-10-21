import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import ProfilePage from "@/app/profile/page";
import TasteEvolutionPage from "@/app/taste-evolution/page";
import { AuthProvider } from "@/components/auth-provider";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({ usePathname: () => "/profile" }));
afterEach(cleanup);

it.skipIf(process.env.CINEMIND_LIVE_TASTE !== "1")(
  "saves and edits real ratings, updates recommendations/timeline, and restores the account",
  async () => {
    const qa = JSON.parse(readFileSync(resolve(process.cwd(), "../tmp/taste-qa.json"), "utf8")) as { user_id: string; token: string };
    window.localStorage.clear(); window.sessionStorage.clear();
    window.localStorage.setItem("cinemind.token", qa.token);
    const user = userEvent.setup();
    const view = render(<AuthProvider><ProfilePage /></AuthProvider>);
    await screen.findByRole("region", { name: "Your rating summary" }, { timeout: 60_000 });
    await user.type(screen.getByRole("textbox", { name: "Movie title" }), "Interstellar{Enter}");
    await user.click(await screen.findByRole("button", { name: "Rate Interstellar" }, { timeout: 45_000 }));
    await waitFor(() => expect((screen.getByLabelText("Your rating") as HTMLSelectElement).disabled).toBe(false), { timeout: 45_000 });
    await user.selectOptions(screen.getByLabelText("Your rating"), "9");
    await user.click(screen.getByRole("button", { name: "Save rating" }));
    await screen.findByRole("button", { name: "Edit rating for Interstellar" }, { timeout: 70_000 });
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Your recent ratings" })).getByText("9/10")).toBeTruthy(), { timeout: 70_000 });
    const dashboard = await api.users.tasteDashboard(qa.user_id);
    expect(dashboard.total_ratings).toBe(1);
    expect(dashboard.profile?.likes).toContain("Science Fiction");
    expect(dashboard.recommendations.length).toBeGreaterThan(0);
    expect(dashboard.recommendations.some((movie) => movie.title === "Interstellar")).toBe(false);
    expect(dashboard.ratings[0]!.score).toBe(9);
    view.unmount();
    const timeline = render(<AuthProvider><TasteEvolutionPage /></AuthProvider>);
    const months = await screen.findByRole("list", { name: "Monthly taste history" }, { timeout: 60_000 });
    expect(within(months).getByText(/science fiction/)).toBeTruthy();
    timeline.unmount();
    const restored = render(<AuthProvider><ProfilePage /></AuthProvider>);
    await user.click(await screen.findByRole("button", { name: "Edit rating for Interstellar" }, { timeout: 60_000 }));
    expect((screen.getByLabelText("Your rating") as HTMLSelectElement).value).toBe("9");
    await user.selectOptions(screen.getByLabelText("Your rating"), "3");
    await user.click(screen.getByRole("button", { name: "Save rating" }));
    // Wait for the refreshed history, not the always-present 3/10 select option.
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Your recent ratings" })).getByText("3/10")).toBeTruthy(), { timeout: 70_000 });
    const edited = await api.users.tasteDashboard(qa.user_id);
    expect(edited.total_ratings).toBe(1);
    expect(edited.ratings[0]!.score).toBe(3);
    expect(edited.profile?.likes).toEqual([]);
    expect(edited.profile?.dislikes).toContain("Science Fiction");
    expect(await api.users.tasteEvolution(qa.user_id)).toEqual([]);
    expect(screen.queryByRole("alert")).toBeNull();
    restored.unmount();
  },
  300_000,
);
