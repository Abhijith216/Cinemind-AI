import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MoviePage from "@/app/movie/[id]/page";
import MovieError from "@/app/movie/[id]/error";
import MovieNotFound from "@/app/movie/[id]/not-found";
import { api, ApiError } from "@/lib/api";

const navigation = vi.hoisted(() => ({ notFound: vi.fn(() => { throw new Error("NOT_FOUND"); }) }));
vi.mock("next/navigation", () => ({ notFound: navigation.notFound }));
vi.mock("@/components/movie-personalization", () => ({ MoviePersonalization: () => null }));
const id = "88752c4f-df2f-4fb4-8684-adc1463f141d";

beforeEach(() => vi.clearAllMocks());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Movie error routing", () => {
  it("rejects malformed links before requesting the backend", async () => {
    const request = vi.spyOn(api.movies, "get");
    await expect(MoviePage({ params: Promise.resolve({ id: "invalid" }) })).rejects.toThrow("NOT_FOUND");
    expect(request).not.toHaveBeenCalled();
  });

  it("routes a missing movie to the not-found page", async () => {
    vi.spyOn(api.movies, "get").mockRejectedValue(new ApiError(404, "movie not found"));
    await expect(MoviePage({ params: Promise.resolve({ id }) })).rejects.toThrow("NOT_FOUND");
    render(<MovieNotFound />);
    expect(screen.getByRole("heading", { name: "Movie not found" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to Discover" }).getAttribute("href")).toBe("/");
  });

  it("propagates temporary failures to the retry boundary", async () => {
    vi.spyOn(api.movies, "get").mockRejectedValue(new ApiError(503, "Catalog unavailable"));
    await expect(MoviePage({ params: Promise.resolve({ id }) })).rejects.toThrow("temporarily unavailable");
    expect(navigation.notFound).not.toHaveBeenCalled();
    render(<MovieError />);
    const retry = screen.getByRole("button", { name: "Retry" }) as HTMLButtonElement;
    expect(retry.type).toBe("submit");
    expect(retry.form?.method).toBe("get");
    expect(retry.form?.getAttribute("action")).toBeNull();
  });
});
