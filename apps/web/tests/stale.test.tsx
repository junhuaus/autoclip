import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { ClipCard } from "../src/ProjectWorkspace";
import { clipSummary } from "./fixtures";

it("makes a stale proxy unmistakable and does not play it as current media", () => {
  render(
    <ClipCard
      item={{
        clip: { ...clipSummary.clip, proxy_status: "stale", proxy_asset_id: null },
        proxy_media_url: null,
        download_video_url: null,
        download_subtitle_url: null,
      }}
      onOpen={() => undefined}
    />,
  );

  expect(screen.getByText("旧母版已失效")).toBeInTheDocument();
  expect(screen.getByText(/旧母版不能用于交付/)).toBeInTheDocument();
  expect(screen.getByText("母版已失效")).toHaveAttribute("data-status", "stale");
  expect(screen.queryByRole("video")).not.toBeInTheDocument();
});
