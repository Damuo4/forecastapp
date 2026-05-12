from fastapi.testclient import TestClient
from datetime import date

import main


client = TestClient(main.app)


def test_hello_returns_expected_message():
    response = client.get("/api/hello")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello from FastAPI"}


def test_db_health_returns_expected_message(monkeypatch):
    class FakeResult:
        def fetchone(self):
            return ("Postgres is connected",)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _query):
            return FakeResult()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(main, "engine", FakeEngine())

    response = client.get("/api/health/db")

    assert response.status_code == 200
    assert response.json() == {"message": "Postgres is connected"}


def test_dashboard_overview_returns_industry_payload(monkeypatch):
    monkeypatch.setattr(
        main,
        "_fetch_macro_indicators_from_db",
        lambda: [
            {
                "code": "housing_starts",
                "name": "Housing Starts",
                "category": "construction_demand",
                "value": 100.0,
                "unit": "index",
                "trend": "up",
                "source": "FRED",
                "as_of_month": "2026-04",
            }
        ],
    )
    monkeypatch.setattr(
        main,
        "_fetch_trade_flows_from_db",
        lambda: [
            {
                "material": "Steel products",
                "hs_code": "72",
                "reporter_country": "United States",
                "partner_country": "World",
                "import_value_usd_millions": 3.125,
                "export_value_usd_millions": 1.61,
                "net_import_value_usd_millions": 1.515,
                "as_of_month": "2026-03",
            }
        ],
    )

    response = client.get("/api/dashboard/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["industry_focus"] == "Industrial Distribution / Building Materials"
    assert payload["recommendation_label"] in {"buy_less", "buy_same", "buy_more"}
    assert payload["macro_indicator_count"] == 1
    assert payload["trade_flow_count"] == 1


def test_macro_indicators_returns_expected_shape(monkeypatch):
    class FakeMacroResult:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def __iter__(self):
            return iter(self.rows)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _query):
            return FakeMacroResult(
                [
                    {
                        "code": "housing_starts",
                        "series_id": "HOUST",
                        "name": "Housing Starts",
                        "category": "construction_demand",
                        "unit": "index",
                        "source": "FRED",
                        "observation_date": date(2026, 4, 1),
                        "value": 100.0,
                    },
                    {
                        "code": "housing_starts",
                        "series_id": "HOUST",
                        "name": "Housing Starts",
                        "category": "construction_demand",
                        "unit": "index",
                        "source": "FRED",
                        "observation_date": date(2026, 3, 1),
                        "value": 95.0,
                    },
                ]
            )

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(main, "engine", FakeEngine())

    response = client.get("/api/indicators/macro")

    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert len(payload["items"]) >= 1
    first = payload["items"][0]
    assert {"code", "name", "category", "value", "source"} <= set(first.keys())
    assert first["trend"] == "up"


def test_trade_flow_indicators_returns_expected_shape(monkeypatch):
    class FakeTradeResult:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def __iter__(self):
            return iter(self.rows)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _query):
            return FakeTradeResult(
                [
                    {
                        "material_code": "steel",
                        "material": "Steel products",
                        "hs_code": "72",
                        "reporter_country": "United States",
                        "partner_country": "World",
                        "period": date(2026, 3, 1),
                        "import_value_usd": 3_125_000,
                        "export_value_usd": 1_610_000,
                        "missing_import_trade_count": 0,
                        "missing_export_trade_count": 0,
                        "missing_quantity_count": 1,
                        "unknown_unit_count": 1,
                    }
                ]
            )

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(main, "engine", FakeEngine())

    response = client.get("/api/indicators/trade-flows")

    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert len(payload["items"]) >= 1
    first = payload["items"][0]
    assert {"material", "hs_code", "import_value_usd_millions"} <= set(first.keys())
    assert first["net_import_value_usd_millions"] == 1.515


def test_current_recommendation_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "_build_inventory_recommendations",
        lambda persist=True, scenario="baseline": [
            {
                "product_id": 1,
                "product_name": "Steel Beam Bundle 100",
                "product_category": "Steel products",
                "material": "steel",
                "latest_month": "2026-05",
                "recommendation": "buy_more",
                "confidence_score": 0.8,
                "demand_signal": "strong",
                "cost_pressure_signal": "rising",
                "trade_supply_signal": "tight",
                "inventory_signal": "low_stock",
                "rationale": ["Demand signal is strong"],
                "source_notes": ["FRED", "UN Comtrade", "Synthetic Inventory Dataset"],
            },
            {
                "product_id": 2,
                "product_name": "Copper Tube Set 50",
                "product_category": "Copper products",
                "material": "copper",
                "latest_month": "2026-05",
                "recommendation": "buy_same",
                "confidence_score": 0.6,
                "demand_signal": "strong",
                "cost_pressure_signal": "neutral",
                "trade_supply_signal": "neutral",
                "inventory_signal": "normal",
                "rationale": ["Inventory signal is normal"],
                "source_notes": ["FRED", "Synthetic Inventory Dataset"],
            },
        ],
    )

    response = client.get("/api/recommendations/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_recommendation"] in {"buy_less", "buy_same", "buy_more"}
    assert isinstance(payload["confidence"], float)
    assert payload["product_count"] == 2
    assert payload["buy_more_count"] == 1
    assert isinstance(payload["rationale"], list)
    assert payload["scenario"] == "baseline"


def test_inventory_recommendations_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "_build_inventory_recommendations",
        lambda persist=True, scenario="baseline": [
            {
                "product_id": 1,
                "product_name": "Steel Beam Bundle 100",
                "product_category": "Steel products",
                "material": "steel",
                "latest_month": "2026-05",
                "recommendation": "buy_more",
                "confidence_score": 0.8,
                "demand_signal": "strong",
                "cost_pressure_signal": "rising",
                "trade_supply_signal": "tight",
                "inventory_signal": "low_stock",
                "inventory_coverage_months": 0.8,
                "rationale": ["Demand signal is strong", "Inventory signal is low_stock"],
                "source_notes": ["FRED", "UN Comtrade", "Synthetic Inventory Dataset"],
            }
        ],
    )

    response = client.get("/api/recommendations/inventory")
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert len(payload["items"]) == 1
    first = payload["items"][0]
    assert first["recommendation"] in {"buy_less", "buy_same", "buy_more"}
    assert isinstance(first["confidence_score"], float)
    assert isinstance(first["rationale"], list)
    assert "inventory_coverage_months" in first


def test_inventory_operations_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "_fetch_inventory_operations_from_db",
        lambda: [
            {
                "product_name": "Steel Beam Bundle 100",
                "product_category": "Steel products",
                "latest_month": "2026-05",
                "total_on_hand_units": 2000.0,
                "total_available_units": 1500.0,
                "inventory_value_usd": 820000.0,
                "units_sold_latest_month": 1200.0,
                "units_sold_previous_month": 1150.0,
                "sales_mom_percent": 4.35,
                "open_purchase_order_units": 300.0,
                "average_lead_time_days": 33.4,
                "late_delivery_rate_percent": 9.2,
                "estimated_gross_margin_percent": 24.5,
                "stock_status": "normal",
                "inventory_coverage_months": 1.3,
            }
        ],
    )

    response = client.get("/api/indicators/inventory-operations")
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    first = payload["items"][0]
    assert first["product_name"] == "Steel Beam Bundle 100"
    assert "stock_status" in first
    assert "inventory_coverage_months" in first


def test_scenario_query_parameter_is_accepted(monkeypatch):
    monkeypatch.setattr(
        main,
        "_fetch_inventory_operations_from_db",
        lambda: [
            {
                "product_id": 1,
                "product_name": "Steel Beam Bundle 100",
                "product_category": "Steel products",
                "material": "steel",
                "latest_month": "2026-05",
                "total_on_hand_units": 2000.0,
                "total_available_units": 1500.0,
                "inventory_value_usd": 820000.0,
                "units_sold_latest_month": 1200.0,
                "units_sold_previous_month": 1150.0,
                "sales_mom_percent": 4.35,
                "open_purchase_order_units": 300.0,
                "average_lead_time_days": 33.4,
                "late_delivery_rate_percent": 9.2,
                "estimated_gross_margin_percent": 24.5,
                "stock_status": "normal",
                "inventory_coverage_months": 1.3,
            }
        ],
    )
    response = client.get("/api/indicators/inventory-operations?scenario=demand_drop")
    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "demand_drop"


def test_low_stock_scenario_produces_buy_more(monkeypatch):
    monkeypatch.setattr(
        main,
        "_fetch_inventory_operations_from_db",
        lambda: [
            {
                "product_id": 1,
                "product_name": "Steel Beam Bundle 100",
                "product_category": "Steel products",
                "material": "steel",
                "latest_month": "2026-05",
                "total_on_hand_units": 2000.0,
                "total_available_units": 1500.0,
                "inventory_value_usd": 820000.0,
                "units_sold_latest_month": 1200.0,
                "units_sold_previous_month": 1150.0,
                "sales_mom_percent": 4.35,
                "open_purchase_order_units": 300.0,
                "average_lead_time_days": 33.4,
                "late_delivery_rate_percent": 9.2,
                "estimated_gross_margin_percent": 24.5,
                "stock_status": "normal",
                "inventory_coverage_months": 1.3,
            }
        ],
    )
    monkeypatch.setattr(
        main,
        "_fetch_macro_indicators_from_db",
        lambda: [
            {"category": "construction_demand", "trend": "up"},
            {"category": "industrial_demand", "trend": "up"},
            {"category": "materials_pressure", "trend": "up"},
        ],
    )
    monkeypatch.setattr(main, "_fetch_trade_flows_from_db", lambda: [])
    response = client.get("/api/recommendations/inventory?scenario=low_stock")
    assert response.status_code == 200
    payload = response.json()
    assert any(item["recommendation"] == "buy_more" for item in payload["items"])


def test_overstock_scenario_produces_buy_less(monkeypatch):
    monkeypatch.setattr(
        main,
        "_fetch_inventory_operations_from_db",
        lambda: [
            {
                "product_id": 1,
                "product_name": "Steel Beam Bundle 100",
                "product_category": "Steel products",
                "material": "steel",
                "latest_month": "2026-05",
                "total_on_hand_units": 2000.0,
                "total_available_units": 1500.0,
                "inventory_value_usd": 820000.0,
                "units_sold_latest_month": 1200.0,
                "units_sold_previous_month": 1150.0,
                "sales_mom_percent": 4.35,
                "open_purchase_order_units": 300.0,
                "average_lead_time_days": 33.4,
                "late_delivery_rate_percent": 9.2,
                "estimated_gross_margin_percent": 24.5,
                "stock_status": "normal",
                "inventory_coverage_months": 1.3,
            }
        ],
    )
    monkeypatch.setattr(
        main,
        "_fetch_macro_indicators_from_db",
        lambda: [
            {"category": "construction_demand", "trend": "down"},
            {"category": "industrial_demand", "trend": "down"},
            {"category": "materials_pressure", "trend": "down"},
        ],
    )
    monkeypatch.setattr(main, "_fetch_trade_flows_from_db", lambda: [])
    response = client.get("/api/recommendations/inventory?scenario=overstock")
    assert response.status_code == 200
    payload = response.json()
    assert any(item["recommendation"] == "buy_less" for item in payload["items"])


def test_data_sources_status_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "_fetch_data_source_status_from_db",
        lambda: {
            "sources": [
                {
                    "source_name": "FRED",
                    "status": "ok",
                    "latest_pull_timestamp": "2026-05-12T00:00:00Z",
                    "rows_returned": 10,
                    "sample_series_material": "CPIAUCSL",
                }
            ],
            "data_freshness": {
                "latest_fred_date": "2026-03-01",
                "latest_comtrade_period": "2025-01",
            },
        },
    )

    response = client.get("/api/data-sources/status")
    assert response.status_code == 200
    payload = response.json()
    assert "sources" in payload
    assert "data_freshness" in payload
    assert payload["sources"][0]["source_name"] == "FRED"


def test_debug_fred_preview_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "_fetch_fred_preview_from_db",
        lambda: [
            {
                "source": "FRED",
                "series_id": "CPIAUCSL",
                "series_name": "CPI All Urban Consumers",
                "date": "2026-03-01",
                "value": 330.293,
                "units": "index",
            }
        ],
    )

    response = client.get("/api/debug/fred-preview")
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert payload["items"][0]["series_id"] == "CPIAUCSL"


def test_debug_comtrade_preview_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "_fetch_comtrade_preview_from_db",
        lambda: [
            {
                "source": "UN_COMTRADE",
                "material": "Steel products",
                "hs_code": "72",
                "reporter": "USA",
                "partner": "World",
                "flow_type": "import",
                "period": "2025-01",
                "trade_value_usd": 1234.5,
                "quantity": 10.0,
                "unit": "reported_quantity",
            }
        ],
    )

    response = client.get("/api/debug/comtrade-preview")
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert payload["items"][0]["material"] == "Steel products"


def test_data_quality_returns_overall_status(monkeypatch):
    monkeypatch.setattr(
        main,
        "_generate_data_quality_report",
        lambda: {
            "overall_status": "warning",
            "sources": [
                {
                    "source_name": "FRED",
                    "status": "ok",
                    "checks": [{"name": "rows_returned", "status": "ok", "message": "3919 rows returned"}],
                },
                {
                    "source_name": "UN Comtrade",
                    "status": "warning",
                    "checks": [
                        {
                            "name": "missing_quantity",
                            "status": "warning",
                            "message": "Some material rows are missing physical quantity; trade value is still available",
                        }
                    ],
                },
                {
                    "source_name": "Synthetic Inventory Dataset",
                    "status": "ok",
                    "checks": [
                        {
                            "name": "products_seeded",
                            "status": "ok",
                            "message": "5 products seeded",
                        }
                    ],
                },
            ],
        },
    )

    response = client.get("/api/data-quality")
    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "warning"
    assert len(payload["sources"]) == 3
    assert payload["sources"][0]["source_name"] == "FRED"
    assert payload["sources"][1]["source_name"] == "UN Comtrade"
    assert payload["sources"][1]["checks"][0]["status"] == "warning"
    assert payload["sources"][1]["checks"][0]["status"] != "error"
    assert payload["sources"][2]["source_name"] == "Synthetic Inventory Dataset"


def test_sec_status_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "_sec_status_payload",
        lambda: {
            "source": "SEC EDGAR",
            "status": "ok",
            "companies_checked": 5,
            "companies_ok": 5,
            "companies_failed": 0,
            "latest_successful_company": "Fastenal",
            "message": "SEC submissions endpoint reachable.",
        },
    )
    response = client.get("/api/sec/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "SEC EDGAR"
    assert payload["status"] in {"ok", "warning", "error"}


def test_sec_company_preview_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        main,
        "_sec_company_preview_payload",
        lambda: [
            {
                "company_name": "Fastenal",
                "ticker": "FAST",
                "cik": "0000815556",
                "sec_name": "FASTENAL CO",
                "sic": "5051",
                "sic_description": "Metals Service Centers",
                "latest_filing_form": "10-Q",
                "latest_filing_date": "2026-03-31",
                "latest_accession_number": "0000815556-26-000010",
                "source": "SEC EDGAR",
            }
        ],
    )
    response = client.get("/api/sec/company-preview")
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert payload["items"][0]["ticker"] == "FAST"


def test_sec_missing_user_agent_returns_warning(monkeypatch):
    monkeypatch.setattr(main, "SEC_USER_AGENT", "")
    response = client.get("/api/sec/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "warning"

