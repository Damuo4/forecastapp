import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import App from "./App";

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("renders API and database messages after successful fetches", async () => {
    vi.spyOn(global, "fetch")
      .mockResolvedValueOnce({
        json: async () => ({ message: "Hello from FastAPI" }),
      })
      .mockResolvedValueOnce({
        json: async () => ({ message: "Postgres is connected" }),
      });

    render(<App />);

    expect(screen.getByText("Forecast App")).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByText("API says: Hello from FastAPI"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("DB says: Postgres is connected"),
      ).toBeInTheDocument();
    });
  });

  test("shows fallback messages when fetch requests fail", async () => {
    vi.spyOn(global, "fetch")
      .mockRejectedValueOnce(new Error("hello failed"))
      .mockRejectedValueOnce(new Error("db failed"));

    render(<App />);

    await waitFor(() => {
      expect(
        screen.getByText("API says: Failed to reach backend"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("DB says: Failed to connect to DB"),
      ).toBeInTheDocument();
    });
  });
});
