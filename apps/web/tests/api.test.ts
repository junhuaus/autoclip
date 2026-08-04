import { describe, expect, it } from "vitest";

import { signedUrlRefreshInterval } from "../src/api";

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
