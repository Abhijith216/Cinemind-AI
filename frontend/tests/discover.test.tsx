import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import DiscoverPage from "@/app/page";

const movie = {
  id: "f728f15c-30ee-4bdd-8c18-79c708b37500", tmdb_id: 157336,
  title: "Interstellar", release_year: 2014, runtime: 169, vote_average: 8.1,
  poster_path: null, genres: ["Science Fiction"], keywords: ["space travel"],
};
const body = (results: unknown[] = [{
  movie, explanation: "An exact match for the title you searched.", matched_terms: ["Science Fiction"],
}]) => ({ query: "Interstellar", results, search_mode: "catalog", notice: "Starter catalog" });
const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "Content-Type": "application/json" },
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Discover search", () => {
  it("enables search only for nonblank input and fills suggestions", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    const submit = screen.getByRole("button", { name: "Find movies" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    const input = screen.getByLabelText("What would you like to watch?") as HTMLInputElement;
    await user.type(input, "   ");
    expect(submit.disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: /Something like Interstellar/ }));
    expect(input.value).toBe("Something like Interstellar but not about space");
    expect(document.activeElement).toBe(input);
    expect(submit.disabled).toBe(false);
  });

  it("submits on Enter and renders real API results and detail links", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(body()));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(screen.getByLabelText("What would you like to watch?"), "Interstellar{Enter}");
    await screen.findByRole("heading", { name: "Interstellar" });
    expect(fetchMock.mock.calls[0]![0]).toBe("http://localhost:8000/api/search/discover");
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body)).toEqual({
      query: "Interstellar", limit: 12, filters: { genres: [], max_runtime: null },
    });
    expect(screen.getByText("An exact match for the title you searched.")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Explore Interstellar/ }).getAttribute("href"))
      .toBe(`/movie/${movie.id}`);
    await user.click(screen.getByRole("button", { name: "Why this?" }));
    expect(screen.getByText("Science Fiction", { selector: "span" })).toBeTruthy();
  });

  it("passes genre/runtime filters and prevents duplicate in-flight submissions", async () => {
    let finish!: (response: Response) => void;
    const fetchMock = vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.selectOptions(screen.getByLabelText("Genre"), "Science Fiction");
    await user.selectOptions(screen.getByLabelText("Maximum runtime"), "120");
    await user.type(screen.getByLabelText("What would you like to watch?"), "space");
    await user.dblClick(screen.getByRole("button", { name: "Find movies" }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((screen.getByRole("button", { name: "Finding movies…" }) as HTMLButtonElement).disabled).toBe(true);
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body).filters)
      .toEqual({ genres: ["Science Fiction"], max_runtime: 120 });
    await act(async () => finish(reply(body())));
    await screen.findByRole("heading", { name: "Interstellar" });
  });

  it("shows an empty state and lets the user clear restrictive filters", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(body([]))));
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.selectOptions(screen.getByLabelText("Genre"), "Comedy");
    await user.selectOptions(screen.getByLabelText("Maximum runtime"), "90");
    await user.type(screen.getByLabelText("What would you like to watch?"), "unknown film{Enter}");
    await screen.findByRole("heading", { name: "No matches this time" });
    await user.click(screen.getByRole("button", { name: "Adjust search" }));
    expect((screen.getByLabelText("Genre") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Maximum runtime") as HTMLSelectElement).value).toBe("");
  });

  it("displays API errors and retries the original request successfully", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(reply({ detail: "The movie catalog is temporarily unavailable." }, 503))
      .mockResolvedValueOnce(reply(body()));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(screen.getByLabelText("What would you like to watch?"), "Interstellar{Enter}");
    expect((await screen.findByRole("alert")).textContent).toContain("temporarily unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("heading", { name: "Interstellar" });
    expect(fetchMock.mock.calls[0]![1].body).toBe(fetchMock.mock.calls[1]![1].body);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("recovers from a network failure and re-enables submission", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(screen.getByLabelText("What would you like to watch?"), "Interstellar{Enter}");
    await screen.findByRole("alert");
    await waitFor(() => expect((screen.getByRole("button", { name: "Find movies" }) as HTMLButtonElement).disabled).toBe(false));
  });
});
