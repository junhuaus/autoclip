import { HttpResponse, delay, http } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { App } from "../src/App";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

describe("project list states", () => {
  it("shows loading and then a useful empty state", async () => {
    server.use(
      http.get("/api/v1/projects", async () => {
        await delay(80);
        return HttpResponse.json([]);
      }),
    );

    renderWithClient(<App />);

    expect(screen.getByText("正在加载项目…")).toBeInTheDocument();
    expect(await screen.findByText("还没有项目")).toBeInTheDocument();
    expect(screen.getByText("从上方输入本地视频路径开始。")).toBeInTheDocument();
  });

  it("renders only the stable safe API error and retry affordance", async () => {
    server.use(
      http.get("/api/v1/projects", () =>
        HttpResponse.json(
          {
            error: {
              schema_version: "1",
              code: "AUTHENTICATION_REQUIRED",
              message: "Valid Bearer authorization or signed media access is required",
              retryable: false,
              resource_id: null,
              correlation_id: "request-safe-123",
              details: [],
            },
          },
          { status: 401 },
        ),
      ),
    );

    renderWithClient(<App />);

    expect(await screen.findByText("Valid Bearer authorization or signed media access is required")).toBeInTheDocument();
    expect(screen.getByText(/AUTHENTICATION_REQUIRED/)).toHaveTextContent("request-safe-123");
    expect(screen.getByRole("button", { name: "重试" })).toBeEnabled();
  });

  it("keeps the optional Bearer token in memory while sending it to the API", async () => {
    const authorizations: Array<string | null> = [];
    server.use(
      http.get("/api/v1/projects", ({ request }) => {
        authorizations.push(request.headers.get("Authorization"));
        return HttpResponse.json([]);
      }),
    );
    window.localStorage.clear();
    window.sessionStorage.clear();
    const user = userEvent.setup();
    renderWithClient(<App />);

    await screen.findByText("还没有项目");
    await user.type(
      screen.getByLabelText(/本机 API Bearer token/),
      "temporary-browser-token",
    );
    await user.click(screen.getByRole("button", { name: "应用" }));

    await waitFor(() => expect(authorizations).toContain("Bearer temporary-browser-token"));
    expect(screen.getByText("已在内存中启用")).toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain("temporary-browser-token");
  });
});
