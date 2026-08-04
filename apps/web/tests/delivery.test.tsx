import { HttpResponse, http } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { LiveClipApiClient } from "../src/api";
import { DeliveryPanel } from "../src/ProjectWorkspace";
import { project, succeededDelivery } from "./fixtures";
import { server } from "./server";
import { renderWithClient } from "./test-utils";

it("shows an empty delivery state, creates a ZIP version and exposes its signed download", async () => {
  let created = false;
  let requestBody: unknown = null;
  server.use(
    http.get("/api/v1/projects/project-1/deliveries", () =>
      HttpResponse.json(created ? [succeededDelivery] : []),
    ),
    http.post("/api/v1/projects/project-1/deliveries", async ({ request }) => {
      requestBody = await request.json();
      created = true;
      return HttpResponse.json(
        {
          resource_type: "delivery",
          resource_id: "delivery-1",
          task_id: "task-delivery-1",
          status: "queued",
          status_url: "/api/v1/deliveries/delivery-1",
        },
        { status: 202 },
      );
    }),
    http.get("/api/v1/deliveries/delivery-1", () => HttpResponse.json(succeededDelivery)),
  );

  const user = userEvent.setup();
  renderWithClient(
    <DeliveryPanel
      api={new LiveClipApiClient()}
      project={{ ...project, status: "ready_for_delivery" }}
      approvedCount={1}
    />,
  );

  expect(await screen.findByText("还没有交付版本")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "创建新交付版本" }));

  await waitFor(() => expect(requestBody).toEqual({ include_zip: true }));
  const download = await screen.findByRole("link", { name: "下载 ZIP" });
  expect(download).toHaveAttribute(
    "href",
    "/api/v1/deliveries/delivery-1/download?expires=9999999999&signature=signed",
  );
  expect(screen.getByText("v001")).toBeInTheDocument();
  expect(screen.getAllByText("成功").length).toBeGreaterThan(0);
});

it("allows the configured delivery workflow to omit the ZIP", async () => {
  let requestBody: unknown = null;
  server.use(
    http.get("/api/v1/projects/project-1/deliveries", () => HttpResponse.json([])),
    http.post("/api/v1/projects/project-1/deliveries", async ({ request }) => {
      requestBody = await request.json();
      return HttpResponse.json(
        {
          resource_type: "delivery",
          resource_id: "delivery-no-zip",
          task_id: "task-delivery-no-zip",
          status: "queued",
          status_url: "/api/v1/deliveries/delivery-no-zip",
        },
        { status: 202 },
      );
    }),
    http.get("/api/v1/deliveries/delivery-no-zip", () =>
      HttpResponse.json({
        delivery: {
          ...succeededDelivery.delivery,
          delivery_id: "delivery-no-zip",
          task_id: "task-delivery-no-zip",
          include_zip: false,
          zip_asset_id: null,
        },
        download_url: null,
      }),
    ),
  );

  const user = userEvent.setup();
  renderWithClient(
    <DeliveryPanel
      api={new LiveClipApiClient()}
      project={{ ...project, status: "ready_for_delivery" }}
      approvedCount={1}
    />,
  );

  await screen.findByText("还没有交付版本");
  await user.click(screen.getByRole("checkbox", { name: "创建 delivery.zip" }));
  const createButton = screen.getByRole("button", { name: "创建无 ZIP 交付版本" });
  expect(createButton).toBeEnabled();
  await user.click(createButton);
  await waitFor(() => expect(requestBody).toEqual({ include_zip: false }));
});

it("offers a new immutable delivery attempt after the previous version failed", async () => {
  let retried = false;
  const failedDelivery = {
    delivery: {
      ...succeededDelivery.delivery,
      status: "failed" as const,
      manifest_asset_id: null,
      zip_asset_id: null,
      error_code: "DELIVERY_IO_TEMPORARY",
      safe_error_message: "交付写入失败，请重试。",
    },
    download_url: null,
  };
  server.use(
    http.get("/api/v1/projects/project-1/deliveries", () =>
      HttpResponse.json([failedDelivery]),
    ),
    http.post("/api/v1/projects/project-1/deliveries", () => {
      retried = true;
      return HttpResponse.json(
        {
          resource_type: "delivery",
          resource_id: "delivery-2",
          task_id: "task-delivery-2",
          status: "queued",
          status_url: "/api/v1/deliveries/delivery-2",
        },
        { status: 202 },
      );
    }),
    http.get("/api/v1/deliveries/delivery-2", () =>
      HttpResponse.json({
        delivery: {
          ...succeededDelivery.delivery,
          delivery_id: "delivery-2",
          task_id: "task-delivery-2",
          version: 2,
          delivery_version: "v002",
        },
        download_url: "/api/v1/deliveries/delivery-2/download?expires=9999999999&signature=signed",
      }),
    ),
  );

  const user = userEvent.setup();
  renderWithClient(
    <DeliveryPanel
      api={new LiveClipApiClient()}
      project={{ ...project, status: "failed" }}
      approvedCount={1}
    />,
  );

  expect(await screen.findByText("交付写入失败，请重试。")).toBeInTheDocument();
  const retryButton = screen.getByRole("button", { name: "重试为新交付版本" });
  expect(retryButton).toBeEnabled();
  await user.click(retryButton);
  await waitFor(() => expect(retried).toBe(true));
});
