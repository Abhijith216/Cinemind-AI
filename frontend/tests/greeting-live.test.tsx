import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import ChatPage from "@/app/chat/page";
import { AuthProvider } from "@/components/auth-provider";

afterEach(cleanup);

// Uses real HTTP handlers and stored history; the greeting needs no AI call.
it.skipIf(process.env.CINEMIND_LIVE_TESTS !== "1")(
  "answers hey and restores the greeting after reload",
  async () => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    const user = userEvent.setup();
    const view = render(<AuthProvider><ChatPage /></AuthProvider>);
    const input = screen.getByLabelText("Chat message") as HTMLInputElement;
    await waitFor(() => expect(input.disabled).toBe(false), { timeout: 10_000 });
    await user.type(input, "hey{Enter}");
    const reply = await screen.findByText(/Hey! What kind of movie/, {}, { timeout: 65_000 });
    const text = reply.textContent!;
    expect(screen.queryByRole("alert")).toBeNull();
    expect(window.sessionStorage.getItem("cinemind.chat.session_id")).toMatch(/^[a-f0-9-]{36}$/);
    view.unmount();
    render(<AuthProvider><ChatPage /></AuthProvider>);
    await screen.findByText(text, {}, { timeout: 45_000 });
    expect(screen.queryByRole("alert")).toBeNull();
  },
  120_000,
);
