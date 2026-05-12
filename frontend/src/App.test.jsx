import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import App from "./App";

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("renders scenario UX and recommendation table", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/hello")) return { json: async () => ({ message: "Hello from FastAPI" }) };
      if (url.includes("/api/health/db")) return { json: async () => ({ message: "Postgres is connected" }) };
      if (url.includes("/api/dashboard/overview")) return { json: async () => ({ as_of_month: "2026-05" }) };
      if (url.includes("/api/indicators/macro")) return { json: async () => ({ items: [{ code: "housing_starts", name: "Housing Starts", category: "construction_demand", value: 100, trend: "up" }] }) };
      if (url.includes("/api/indicators/trade-flows")) return { json: async () => ({ items: [{ material: "Steel products", latest_period: "2026-03", import_value_usd: 1_000_000, export_value_usd: 500_000, net_import_value_usd: 500_000, quality_warnings: [] }] }) };
      if (url.includes("/api/data-sources/status")) return { json: async () => ({ sources: [{ source_name: "FRED", status: "ok" }, { source_name: "UN Comtrade", status: "ok" }], data_freshness: { latest_fred_date: "2026-05-01", latest_comtrade_period: "2026-03" } }) };
      if (url.includes("/api/data-quality")) return { json: async () => ({ overall_status: "warning", sources: [{ source_name: "Synthetic Inventory Dataset", status: "ok", checks: [{ name: "products_seeded", status: "ok", message: "5 products seeded" }] }] }) };
      if (url.includes("/api/debug/fred-preview")) return { json: async () => ({ items: [] }) };
      if (url.includes("/api/debug/comtrade-preview")) return { json: async () => ({ items: [] }) };
      if (url.includes("/api/sec/status")) return { json: async () => ({ source: "SEC EDGAR", status: "warning", companies_checked: 5, companies_ok: 0, companies_failed: 5, message: "SEC_USER_AGENT is not configured." }) };
      if (url.includes("/api/sec/company-preview")) return { json: async () => ({ items: [] }) };
      if (url.includes("/api/sec/company-facts-preview")) return { json: async () => ({ items: [] }) };

      if (url.includes("/api/recommendations/current?scenario=demand_spike")) {
        return { json: async () => ({ overall_recommendation: "buy_more", confidence: 0.8, buy_more_count: 2, buy_same_count: 0, buy_less_count: 0 }) };
      }
      if (url.includes("/api/recommendations/inventory?scenario=demand_spike")) {
        return {
          json: async () => ({
            items: [{
              product_name: "Steel Beam Bundle 100",
              product_category: "Steel products",
              latest_month: "2026-05",
              recommendation: "buy_more",
              confidence_score: 0.8,
              demand_signal: "strong",
              cost_pressure_signal: "rising",
              trade_supply_signal: "tight",
              inventory_signal: "low_stock",
              inventory_coverage_months: 0.8,
              rationale: ["Demand signal is strong"],
            }],
          }),
        };
      }
      if (url.includes("/api/indicators/inventory-operations?scenario=demand_spike")) {
        return { json: async () => ({ items: [{ product_name: "Steel Beam Bundle 100", product_category: "Steel products", latest_month: "2026-05", total_on_hand_units: 2100, total_available_units: 1000, units_sold_latest_month: 1300, sales_mom_percent: 20, inventory_coverage_months: 0.8, open_purchase_order_units: 420, average_lead_time_days: 34.2, late_delivery_rate_percent: 11.4, estimated_gross_margin_percent: 23.8, stock_status: "low_stock" }] }) };
      }

      if (url.includes("/api/recommendations/current?scenario=baseline")) {
        return { json: async () => ({ overall_recommendation: "buy_same", confidence: 0.6, buy_more_count: 0, buy_same_count: 1, buy_less_count: 0 }) };
      }
      if (url.includes("/api/recommendations/inventory?scenario=baseline")) {
        return {
          json: async () => ({
            items: [{
              product_name: "Steel Beam Bundle 100",
              product_category: "Steel products",
              latest_month: "2026-05",
              recommendation: "buy_same",
              confidence_score: 0.6,
              demand_signal: "neutral",
              cost_pressure_signal: "neutral",
              trade_supply_signal: "neutral",
              inventory_signal: "normal",
              inventory_coverage_months: 2.2,
              rationale: ["Balanced signals"],
            }],
          }),
        };
      }
      if (url.includes("/api/indicators/inventory-operations?scenario=baseline")) {
        return { json: async () => ({ items: [{ product_name: "Steel Beam Bundle 100", product_category: "Steel products", latest_month: "2026-05", total_on_hand_units: 2100, total_available_units: 1560, units_sold_latest_month: 700, sales_mom_percent: 5.4, inventory_coverage_months: 2.2, open_purchase_order_units: 420, average_lead_time_days: 34.2, late_delivery_rate_percent: 11.4, estimated_gross_margin_percent: 23.8, stock_status: "normal" }] }) };
      }

      return { json: async () => ({}) };
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Executive Summary")).toBeInTheDocument();
      expect(screen.getByText("Product Inventory Recommendations")).toBeInTheDocument();
      expect(screen.getByLabelText("Scenario")).toBeInTheDocument();
      expect(screen.getByText("Data Quality & Developer Diagnostics")).toBeInTheDocument();
      expect(screen.getByText("Action")).toBeInTheDocument();
      expect(screen.getByText("Why")).toBeInTheDocument();
      expect(screen.getAllByText("Inventory Coverage").length).toBeGreaterThan(0);
    });

    fireEvent.change(screen.getByLabelText("Scenario"), {
      target: { value: "demand_spike" },
    });

    await waitFor(() => {
      expect(screen.getByText("Simulated Scenario")).toBeInTheDocument();
      expect(screen.getByText("Strong")).toBeInTheDocument();
      expect(screen.getAllByText("Low Stock").length).toBeGreaterThan(0);
    });
  });

  test("renders collapsed diagnostics on failures", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("request failed"));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("Unable to load recommendations.")).toBeInTheDocument();
      expect(screen.getByText("Show diagnostics")).toBeInTheDocument();
    });
  });
});
