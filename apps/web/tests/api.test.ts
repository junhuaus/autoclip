import { describe, expect, it, vi } from "vitest";

import { LiveClipApiClient, signedUrlRefreshInterval } from "../src/api";

it("uses the caller-owned completion key and exact high-level body", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}", { status: 202 }));
  try {
    const api = new LiveClipApiClient("synthetic-token");
    const body = { input_path: "/synthetic.mp4", preset_id: "mini_lesson_v1", selection_policy: "manual" } as const;
    await api.completionPresets();
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/completion-presets");
    await api.createCompletionFromPreset(body, "caller-owned-key");
    const [url, init] = fetch.mock.calls[1];
    expect(url).toBe("/api/v1/completion-goals/from-preset");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify(body));
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("caller-owned-key");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer synthetic-token");
  } finally { fetch.mockRestore(); }
});

describe("signed media URL refresh", () => {
  it("refreshes before the earliest expiry and handles an already expired tab", () => {
    expect(
      signedUrlRefreshInterval(
        [
          "/api/v1/media/a?expires=200&signature=one",
          "/api/v1/media/b?expires=100&signature=two",
        ],
        0,
      ),
    ).toBe(85_000);
    expect(
      signedUrlRefreshInterval(
        ["/api/v1/media/a?expires=10&signature=expired"],
        20_000,
      ),
    ).toBe(5_000);
  });

  it("does not poll unsigned URLs and bounds long browser timers", () => {
    expect(signedUrlRefreshInterval(["/api/v1/media/a"], 0)).toBe(false);
    expect(
      signedUrlRefreshInterval(
        ["/api/v1/media/a?expires=9999999999&signature=test"],
        0,
      ),
    ).toBe(30 * 60_000);
  });
});
