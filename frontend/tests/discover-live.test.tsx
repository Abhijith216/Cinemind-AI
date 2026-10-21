import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import DiscoverPage from "@/app/page";

// Opt-in: runs the real UI handlers and API client against a running backend
// and seeded database. No fetch mocks, AI providers or database writes.
afterEach(cleanup);

it.skipIf(process.env.CINEMIND_LIVE_TESTS !== "1")(
  "submits Discover requests to the live catalog and renders results and empty states",
  async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    const input = screen.getByLabelText("What would you like to watch?");
    await user.type(input, "Interstellar{Enter}");
    const title = await screen.findByRole("heading", { name: "Interstellar" }, { timeout: 35_000 });
    const article = title.closest("article");
    expect(article).not.toBeNull();
    expect(within(article!).getByText("2014 · 169 min")).toBeTruthy();
    expect(within(article!).getByText("An exact match for the title you searched.")).toBeTruthy();
    expect(within(article!).getByRole("link", { name: /Explore Interstellar/ }).getAttribute("href"))
      .toMatch(/^\/movie\/[a-f0-9-]{36}$/);
    await user.clear(input);
    await user.type(input, "cozy comedy");
    await user.selectOptions(screen.getByLabelText("Genre"), "Comedy");
    await user.selectOptions(screen.getByLabelText("Maximum runtime"), "90");
    await user.click(screen.getByRole("button", { name: "Find movies" }));
    const resultTitle = await screen.findByRole("heading", { name: /movies to explore/ }, { timeout: 35_000 });
    const results = resultTitle.closest("section")!;
    const articles = within(results).getAllByRole("article");
    expect(articles.length).toBeGreaterThan(0);
    for (const card of articles) {
      const runtime = card.textContent?.match(/· (\d+) min/);
      expect(runtime).not.toBeNull();
      expect(Number(runtime![1])).toBeLessThanOrEqual(90);
    }
    await user.clear(input);
    await user.type(input, "zzzzunmatchablecatalogquery{Enter}");
    await screen.findByRole("heading", { name: "No matches this time" }, { timeout: 35_000 });
    expect(screen.queryByRole("alert")).toBeNull();
  },
  120_000,
);
