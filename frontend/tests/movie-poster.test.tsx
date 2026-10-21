import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MoviePoster } from "@/components/movie-poster";

afterEach(cleanup);

describe("MoviePoster", () => {
  it("keeps a readable title visible while remote artwork loads or fails", () => {
    render(<MoviePoster title="Interstellar" posterUrl="https://image.tmdb.org/t/p/w500/example.jpg" />);
    const image = screen.getByAltText("Interstellar poster");
    expect(screen.getByText("Poster unavailable")).toBeTruthy();
    expect(image.className).toContain("opacity-0");

    fireEvent.load(image);
    expect(image.className).toContain("opacity-100");

    fireEvent.error(image);
    expect(screen.queryByAltText("Interstellar poster")).toBeNull();
    expect(screen.getByText("Interstellar")).toBeTruthy();
  });
});
