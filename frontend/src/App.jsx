import { useEffect, useState } from "react";

const fallbackSummary = {
  industry_focus: "Industrial Distribution / Building Materials",
  as_of_month: "N/A",
};

const titleCase = (value) =>
  String(value ?? "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

const formatConfidence = (value) => `${Math.round((Number(value) || 0) * 100)}%`;
const formatPercent = (value) =>
  typeof value === "number" ? `${value.toFixed(1)}%` : String(value ?? "N/A");
const asNumber = (value) => (typeof value === "number" ? value : Number(value) || 0);
const formatUnits = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return n.toLocaleString();
  if (Math.abs(n) >= 1_000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return Number.isInteger(n) ? n.toString() : n.toFixed(1);
};
const formatCoverage = (value) =>
  typeof value === "number" ? `${value.toFixed(1)} months` : String(value ?? "N/A");

const formatCompactUsd = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  if (Math.abs(n) >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  return `$${n.toFixed(1)}`;
};

const scenarioHelpText = {
  baseline: "Uses current stored data without simulation.",
  demand_spike:
    "This simulates a demand surge to test whether the system recommends buying more.",
  demand_drop:
    "This simulates weaker demand to test whether the system recommends buying less or staying steady.",
  supply_tightening:
    "This simulates longer lead times and delivery delays to test supply risk response.",
  overstock:
    "This simulates excess available inventory to test whether the system recommends buying less.",
  low_stock:
    "This simulates reduced available inventory to test whether the system recommends buying more.",
};

function App() {
  const [summary, setSummary] = useState(fallbackSummary);
  const [message, setMessage] = useState("Loading...");
  const [dbMessage, setDbMessage] = useState("Checking DB...");
  const [dashboardError, setDashboardError] = useState("");
  const [validationError, setValidationError] = useState("");

  const [currentRecommendation, setCurrentRecommendation] = useState(null);
  const [inventoryRecommendations, setInventoryRecommendations] = useState([]);
  const [inventoryOperations, setInventoryOperations] = useState([]);
  const [macroIndicators, setMacroIndicators] = useState([]);
  const [tradeFlows, setTradeFlows] = useState([]);
  const [sourceStatus, setSourceStatus] = useState([]);
  const [sourceFreshness, setSourceFreshness] = useState({
    latest_fred_date: "N/A",
    latest_comtrade_period: "N/A",
  });
  const [dataQuality, setDataQuality] = useState({ overall_status: "warning", sources: [] });
  const [fredPreview, setFredPreview] = useState([]);
  const [comtradePreview, setComtradePreview] = useState([]);
  const [secStatus, setSecStatus] = useState(null);
  const [secCompanyPreview, setSecCompanyPreview] = useState([]);
  const [secFactsPreview, setSecFactsPreview] = useState([]);
  const [scenario, setScenario] = useState("baseline");

  useEffect(() => {
    fetch("/api/hello")
      .then((res) => res.json())
      .then((data) => setMessage(data.message))
      .catch(() => setMessage("Failed to reach backend"));
    fetch("/api/health/db")
      .then((res) => res.json())
      .then((data) => setDbMessage(data.message))
      .catch(() => setDbMessage("Failed to connect to DB"));

    Promise.all([
      fetch("/api/dashboard/overview").then((res) => res.json()),
      fetch("/api/indicators/macro").then((res) => res.json()),
      fetch("/api/indicators/trade-flows").then((res) => res.json()),
      fetch("/api/data-sources/status").then((res) => res.json()),
      fetch("/api/data-quality").then((res) => res.json()),
      fetch("/api/debug/fred-preview").then((res) => res.json()),
      fetch("/api/debug/comtrade-preview").then((res) => res.json()),
      fetch("/api/sec/status").then((res) => res.json()),
      fetch("/api/sec/company-preview").then((res) => res.json()),
      fetch("/api/sec/company-facts-preview").then((res) => res.json()),
    ])
      .then(
        ([
          summaryPayload,
          macroPayload,
          tradePayload,
          sourcePayload,
          qualityPayload,
          fredPreviewPayload,
          comtradePreviewPayload,
          secStatusPayload,
          secCompanyPayload,
          secFactsPayload,
        ]) => {
          setSummary(summaryPayload ?? fallbackSummary);
          setMacroIndicators(macroPayload.items ?? []);
          setTradeFlows(tradePayload.items ?? []);
          setSourceStatus(sourcePayload.sources ?? []);
          setSourceFreshness(
            sourcePayload.data_freshness ?? {
              latest_fred_date: "N/A",
              latest_comtrade_period: "N/A",
            },
          );
          setDataQuality(qualityPayload ?? { overall_status: "warning", sources: [] });
          setFredPreview(fredPreviewPayload.items ?? []);
          setComtradePreview(comtradePreviewPayload.items ?? []);
          setSecStatus(secStatusPayload ?? null);
          setSecCompanyPreview(secCompanyPayload.items ?? []);
          setSecFactsPreview(secFactsPayload.items ?? []);
        },
      )
      .catch(() => {
        setDashboardError("Could not load dashboard indicators.");
        setValidationError("Could not load data source validation previews.");
      });
  }, []);

  useEffect(() => {
    Promise.all([
      fetch(`/api/recommendations/current?scenario=${scenario}`).then((res) => res.json()),
      fetch(`/api/recommendations/inventory?scenario=${scenario}`).then((res) => res.json()),
      fetch(`/api/indicators/inventory-operations?scenario=${scenario}`).then((res) =>
        res.json(),
      ),
    ])
      .then(([currentPayload, inventoryRecPayload, inventoryOpsPayload]) => {
        setCurrentRecommendation(currentPayload ?? null);
        setInventoryRecommendations(inventoryRecPayload.items ?? []);
        setInventoryOperations(inventoryOpsPayload.items ?? []);
      })
      .catch(() => {
        setDashboardError("Unable to load recommendations.");
      });
  }, [scenario]);

  const apiHealthy = !message.toLowerCase().includes("failed");
  const dbHealthy = !dbMessage.toLowerCase().includes("failed");
  const readiness = Object.fromEntries(sourceStatus.map((item) => [item.source_name, item.status]));

  const macroUp = macroIndicators.filter((item) => item.trend === "up").length;
  const macroDown = macroIndicators.filter((item) => item.trend === "down").length;
  const macroFlat = macroIndicators.filter((item) => item.trend === "flat").length;
  const totalNetImportUsd = tradeFlows.reduce(
    (sum, item) => sum + asNumber(item.net_import_value_usd),
    0,
  );
  const urgentProduct =
    [...inventoryRecommendations]
      .filter((item) => item.recommendation !== "buy_same")
      .sort((a, b) => asNumber(b.confidence_score) - asNumber(a.confidence_score))[0] || null;
  const lowStockBuyMoreCount = inventoryRecommendations.filter(
    (item) =>
      item.recommendation === "buy_more" && item.inventory_signal === "low_stock",
  ).length;
  const strongDemandBuyMoreCount = inventoryRecommendations.filter(
    (item) => item.recommendation === "buy_more" && item.demand_signal === "strong",
  ).length;
  const overstockBuyLessCount = inventoryRecommendations.filter(
    (item) =>
      item.recommendation === "buy_less" && item.inventory_signal === "overstock_risk",
  ).length;
  const mainDriver =
    lowStockBuyMoreCount >= strongDemandBuyMoreCount &&
    lowStockBuyMoreCount >= overstockBuyLessCount &&
    lowStockBuyMoreCount > 0
      ? "Inventory risk"
      : strongDemandBuyMoreCount >= overstockBuyLessCount && strongDemandBuyMoreCount > 0
      ? "Demand strength"
      : overstockBuyLessCount > 0
      ? "Overstock risk"
      : "Balanced signals";

  return (
    <main className="app-shell">
      <section className="dashboard">
        <header className="dashboard-header">
          <p className="eyebrow">MVP Decision Dashboard</p>
          <h1>Industrial Distribution Inventory Decision Dashboard</h1>
          <p className="status-line">
            Combines macro, trade, and inventory signals to support monthly purchasing
            decisions.
          </p>
        </header>

        {dashboardError ? <p className="error-line">{dashboardError}</p> : null}
        {!dashboardError && !currentRecommendation ? (
          <p className="status-line">Loading dashboard data...</p>
        ) : null}

        <section className="table-card">
          <h2>Executive Summary</h2>
          <p className="status-line">As of month: {summary.as_of_month}</p>
          <p className="status-line">
            Recommendation is based on current inventory coverage, recent sales, macro demand
            signals, material cost pressure, and trade supply conditions.
          </p>
          <section className="metrics-grid">
            <article className="metric-card">
              <p className="health-label">Overall Recommendation</p>
              <p className={`health-badge badge-${currentRecommendation?.overall_recommendation}`}>
                {titleCase(currentRecommendation?.overall_recommendation ?? "buy_same")}
              </p>
            </article>
            <article className="metric-card">
              <p className="health-label">Confidence</p>
              <p className="metric-value">{formatConfidence(currentRecommendation?.confidence)}</p>
            </article>
            <article className="metric-card">
              <p className="health-label">Buy More</p>
              <p className="metric-value">{currentRecommendation?.buy_more_count ?? 0}</p>
            </article>
            <article className="metric-card">
              <p className="health-label">Buy Same</p>
              <p className="metric-value">{currentRecommendation?.buy_same_count ?? 0}</p>
            </article>
            <article className="metric-card">
              <p className="health-label">Buy Less</p>
              <p className="metric-value">{currentRecommendation?.buy_less_count ?? 0}</p>
            </article>
            <article className="metric-card">
              <p className="health-label">Most Urgent Product</p>
              <p className="metric-value">
                {urgentProduct
                  ? `${urgentProduct.product_name} (${titleCase(
                      urgentProduct.recommendation,
                    )})`
                  : "No urgent action"}
              </p>
            </article>
            <article className="metric-card">
              <p className="health-label">Main Driver</p>
              <p className="metric-value">{mainDriver}</p>
            </article>
          </section>
          <h3>Data Readiness</h3>
          <section className="source-status-grid">
            <article className="source-status-card">
              <p className="health-label">FRED</p>
              <p className={`health-badge ${readiness.FRED === "ok" ? "good" : "warn"}`}>
                FRED {titleCase(readiness.FRED ?? "unknown")}
              </p>
            </article>
            <article className="source-status-card">
              <p className="health-label">UN Comtrade</p>
              <p className={`health-badge ${readiness["UN Comtrade"] === "ok" ? "good" : "warn"}`}>
                UN Comtrade {titleCase(readiness["UN Comtrade"] ?? "unknown")}
              </p>
            </article>
            <article className="source-status-card">
              <p className="health-label">Synthetic Inventory</p>
              <p
                className={`health-badge ${
                  dataQuality.sources.find(
                    (item) => item.source_name === "Synthetic Inventory Dataset",
                  )?.status === "ok"
                    ? "good"
                    : "warn"
                }`}
              >
                Synthetic Inventory{" "}
                {titleCase(
                  dataQuality.sources.find(
                    (item) => item.source_name === "Synthetic Inventory Dataset",
                  )?.status ?? "unknown",
                )}
              </p>
            </article>
          </section>
        </section>

        <section className="table-card">
          <h2>Scenario</h2>
          <label className="health-label" htmlFor="scenario-select">
            Scenario
          </label>
          <select
            id="scenario-select"
            value={scenario}
            onChange={(event) => setScenario(event.target.value)}
          >
            <option value="baseline">Baseline</option>
            <option value="demand_spike">Demand Spike</option>
            <option value="demand_drop">Demand Drop</option>
            <option value="supply_tightening">Supply Tightening</option>
            <option value="overstock">Overstock</option>
            <option value="low_stock">Low Stock</option>
          </select>
          <p className="status-line">
            Scenario: {titleCase(scenario)}. {scenarioHelpText[scenario]}
          </p>
          {scenario !== "baseline" ? (
            <p className="health-badge warn">Simulated Scenario</p>
          ) : null}
        </section>

        <section className="table-card">
          <h2>Product Inventory Recommendations</h2>
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Product</th>
                <th>Why</th>
                <th>Confidence</th>
                <th>Inventory Coverage</th>
                <th>Demand</th>
                <th>Cost Pressure</th>
                <th>Trade Supply</th>
                <th>Stock Status</th>
              </tr>
            </thead>
            <tbody>
              {inventoryRecommendations.length === 0 ? (
                <tr>
                  <td colSpan={9}>No inventory records available.</td>
                </tr>
              ) : (
                inventoryRecommendations.map((item) => (
                  <tr key={item.product_name}>
                  <td>
                    <span className={`health-badge badge-${item.recommendation}`}>
                      {titleCase(item.recommendation)}
                    </span>
                  </td>
                  <td>
                    {item.product_name}
                    <div className="subtle-line">{item.product_category}</div>
                  </td>
                  <td>
                    {(item.rationale ?? []).slice(0, 2).join("; ")}
                    <details>
                      <summary>Details</summary>
                      <p className="status-line">
                        Full rationale: {(item.rationale ?? []).join("; ") || "N/A"}
                      </p>
                      <p className="status-line">
                        Sources: {(item.source_notes ?? []).join(", ") || "N/A"}
                      </p>
                    </details>
                  </td>
                  <td>{formatConfidence(item.confidence_score)}</td>
                  <td>{formatCoverage(item.inventory_coverage_months)}</td>
                  <td>
                    <span className={`health-badge signal-${item.demand_signal}`}>
                      {titleCase(item.demand_signal)}
                    </span>
                  </td>
                  <td>
                    <span className={`health-badge signal-${item.cost_pressure_signal}`}>
                      {titleCase(item.cost_pressure_signal)}
                    </span>
                  </td>
                  <td>
                    <span className={`health-badge signal-${item.trade_supply_signal}`}>
                      {titleCase(item.trade_supply_signal)}
                    </span>
                  </td>
                  <td>
                    <span className={`health-badge stock-${item.inventory_signal}`}>
                      {titleCase(item.inventory_signal)}
                    </span>
                  </td>
                </tr>
                ))
              )}
            </tbody>
          </table>
        </section>

        <section className="table-card">
          <h2>Inventory Snapshot</h2>
          <p className="status-line">
            Current synthetic internal inventory view used to test purchasing decision logic.
          </p>
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>Category</th>
                <th>Latest Month</th>
                <th>On Hand Units</th>
                <th>Available Units</th>
                <th>Latest Sales Units</th>
                <th>Sales MoM %</th>
                <th>Inventory Coverage</th>
                <th>Open PO Units</th>
                <th>Avg Lead Time</th>
                <th>Late Delivery %</th>
                <th>Est. Gross Margin</th>
                <th>Stock Status</th>
              </tr>
            </thead>
            <tbody>
              {inventoryOperations.length === 0 ? (
                <tr>
                  <td colSpan={13}>No inventory records available.</td>
                </tr>
              ) : (
                inventoryOperations.map((item) => (
                  <tr key={`${item.product_name}-${item.latest_month}`}>
                  <td>{item.product_name}</td>
                  <td>{item.product_category}</td>
                  <td>{item.latest_month}</td>
                  <td>{formatUnits(item.total_on_hand_units)}</td>
                  <td>{formatUnits(item.total_available_units)}</td>
                  <td>{formatUnits(item.units_sold_latest_month)}</td>
                  <td>{formatPercent(item.sales_mom_percent)}</td>
                  <td>{formatCoverage(item.inventory_coverage_months)}</td>
                  <td>{formatUnits(item.open_purchase_order_units)}</td>
                  <td>
                    {typeof item.average_lead_time_days === "number"
                      ? `${item.average_lead_time_days.toFixed(1)} days`
                      : "N/A"}
                  </td>
                  <td>{formatPercent(item.late_delivery_rate_percent)}</td>
                  <td>{formatPercent(item.estimated_gross_margin_percent)}</td>
                  <td><span className={`health-badge stock-${item.stock_status}`}>{titleCase(item.stock_status)}</span></td>
                </tr>
                ))
              )}
            </tbody>
          </table>
        </section>

        <section className="table-card">
          <h2>Market Signals</h2>
          <section className="source-status-grid">
            <article className="source-status-card">
              <h3>Macro Signal Summary</h3>
              <p className="status-line">Up: {macroUp}</p>
              <p className="status-line">Down: {macroDown}</p>
              <p className="status-line">Flat: {macroFlat}</p>
              <p className="status-line">
                Macro read:{" "}
                {macroUp > macroDown
                  ? "Construction demand is rising and industrial activity is supportive."
                  : macroDown > macroUp
                  ? "Construction and industrial demand are softening."
                  : "Demand signals are mixed."}
              </p>
            </article>
            <article className="source-status-card">
              <h3>Trade Flow Summary</h3>
              <p className="status-line">Total Net Imports: {formatCompactUsd(totalNetImportUsd)}</p>
              <p className="status-line">Materials Tracked: {tradeFlows.length}</p>
              <p className="status-line">
                Trade read:{" "}
                {totalNetImportUsd > 0
                  ? "The material basket is net import dependent."
                  : "The material basket is not strongly import dependent."}
              </p>
              <p className="status-line">
                Data limitation:{" "}
                {tradeFlows.some((row) => (row.quality_warnings ?? []).length > 0)
                  ? "Comtrade quantity coverage is incomplete for some materials, but trade value is available."
                  : "Comtrade quantity and trade value coverage are complete for tracked materials."}
              </p>
            </article>
          </section>
          {macroIndicators.length === 0 ? <p className="status-line">No macro indicators available.</p> : null}
          {tradeFlows.length === 0 ? <p className="status-line">No trade flow records available.</p> : null}
        </section>

        <section className="table-card">
          <h2>Data Quality & Developer Diagnostics</h2>
          {validationError ? <p className="error-line">{validationError}</p> : null}
          <details>
            <summary>Show diagnostics</summary>
            <p className="status-line">
              These diagnostics are for development and data validation, not end-user purchasing
              decisions.
            </p>
            <p className="status-line">API: {apiHealthy ? "Healthy" : "Degraded"} ({message})</p>
            <p className="status-line">DB: {dbHealthy ? "Connected" : "Disconnected"} ({dbMessage})</p>
            <p className="status-line">Latest FRED date: {sourceFreshness.latest_fred_date}</p>
            <p className="status-line">Latest Comtrade period: {sourceFreshness.latest_comtrade_period}</p>
            <h3>Quality Checks</h3>
            <ul>
              {dataQuality.sources.map((source) =>
                (source.checks ?? []).map((check) => (
                  <li key={`${source.source_name}-${check.name}`}>
                    <strong>{source.source_name}</strong> {check.name}: [{check.status}] {check.message}
                  </li>
                )),
              )}
            </ul>
            <h3>Detailed Validation Tables</h3>
            <details>
              <summary>Show detailed validation tables</summary>
              <h4>Macro Detail</h4>
              <table>
                <thead>
                  <tr><th>Metric</th><th>Category</th><th>Latest</th><th>Trend</th></tr>
                </thead>
                <tbody>
                  {macroIndicators.map((item) => (
                    <tr key={item.code}>
                      <td>{item.name}</td>
                      <td>{item.category}</td>
                      <td>{item.latest_value ?? item.value}</td>
                      <td>{titleCase(item.trend)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h4>Trade Detail</h4>
              <table>
                <thead>
                  <tr><th>Material</th><th>Import</th><th>Export</th><th>Net</th><th>Warnings</th></tr>
                </thead>
                <tbody>
                  {tradeFlows.map((item) => (
                    <tr key={`${item.material}-${item.latest_period}`}>
                      <td>{item.material}</td>
                      <td>{formatCompactUsd(item.import_value_usd)}</td>
                      <td>{formatCompactUsd(item.export_value_usd)}</td>
                      <td>{formatCompactUsd(item.net_import_value_usd)}</td>
                      <td>{(item.quality_warnings ?? []).join(", ") || "none"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
            <h3>Raw JSON</h3>
            <pre>{JSON.stringify({ sourceStatus, sourceFreshness, dataQuality, fredPreview, comtradePreview }, null, 2)}</pre>
            <h3>SEC EDGAR Proof of Life (experimental)</h3>
            <p className="status-line">
              Status: {titleCase(secStatus?.status ?? "unknown")} | Checked:{" "}
              {secStatus?.companies_checked ?? 0} | OK: {secStatus?.companies_ok ?? 0} |
              Failed: {secStatus?.companies_failed ?? 0}
            </p>
            <p className="status-line">{secStatus?.message ?? "No SEC status available."}</p>
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Ticker</th>
                  <th>CIK</th>
                  <th>SIC</th>
                  <th>Latest Filing Form</th>
                  <th>Latest Filing Date</th>
                </tr>
              </thead>
              <tbody>
                {secCompanyPreview.map((row) => (
                  <tr key={row.cik}>
                    <td>{row.company_name}</td>
                    <td>{row.ticker}</td>
                    <td>{row.cik}</td>
                    <td>{row.sic_description ?? row.sic ?? "N/A"}</td>
                    <td>{row.latest_filing_form ?? "N/A"}</td>
                    <td>{row.latest_filing_date ?? "N/A"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Entity Name</th>
                  <th>US-GAAP Fact Count</th>
                  <th>Sample Facts</th>
                </tr>
              </thead>
              <tbody>
                {secFactsPreview.map((row) => (
                  <tr key={`${row.cik}-facts`}>
                    <td>{row.company_name}</td>
                    <td>{row.entity_name ?? "N/A"}</td>
                    <td>{row.number_of_us_gaap_facts ?? 0}</td>
                    <td>{(row.sample_fact_names ?? []).slice(0, 3).join(", ") || "N/A"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </section>
      </section>
    </main>
  );
}

export default App;

