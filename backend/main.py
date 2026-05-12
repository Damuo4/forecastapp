import os
import json
from collections import defaultdict
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from sec_client import SecEdgarClient, SecEdgarClientError

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@db:5432/appdb",
)
SEC_BASE_URL = os.getenv("SEC_BASE_URL", "https://data.sec.gov")
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "").strip()
SEC_PROOF_OF_LIFE_ENABLED = os.getenv("SEC_PROOF_OF_LIFE_ENABLED", "true").lower() == "true"

app = FastAPI(title="Forecast App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = create_engine(DATABASE_URL, future=True)

FRED_REQUIRED_SERIES = {
    "CPIAUCSL",
    "PPIACO",
    "FEDFUNDS",
    "DGS10",
    "HOUST",
    "TTLCONS",
    "INDPRO",
    "WPU1017",
    "WPU083",
}

COMTRADE_REQUIRED_MATERIALS = {
    "steel",
    "aluminum",
    "copper",
    "lumber",
    "cement",
}

SEC_COMPANY_UNIVERSE = [
    {"company_name": "Fastenal", "ticker": "FAST", "cik": "815556"},
    {"company_name": "W.W. Grainger", "ticker": "GWW", "cik": "277135"},
    {"company_name": "Builders FirstSource", "ticker": "BLDR", "cik": "1316835"},
    {"company_name": "Beacon Roofing Supply", "ticker": "BECN", "cik": "1124941"},
    {"company_name": "SiteOne Landscape Supply", "ticker": "SITE", "cik": "1650729"},
]

SUPPORTED_SCENARIOS = {
    "baseline",
    "demand_spike",
    "demand_drop",
    "supply_tightening",
    "overstock",
    "low_stock",
}

COMPANY_FINANCIAL_INDICATORS = [
    {
        "company_name": "Industrial Distribution Peer Basket",
        "period": "2026Q1",
        "revenue_yoy_percent": 2.9,
        "cogs_yoy_percent": 3.8,
        "inventory_yoy_percent": 5.6,
        "gross_margin_change_bps": -35,
        "inventory_turnover_change_percent": -2.1,
    }
]

SUPPLY_CHAIN_DISCLOSURE_INDICATORS = [
    {
        "period": "2026Q1",
        "supplier_disruption_mentions": 6,
        "cost_inflation_mentions": 8,
        "destocking_mentions": 2,
        "backlog_softening_mentions": 3,
        "overall_tone": "watch",
    }
]


def _month_string(value: date | None) -> str:
    if value is None:
        return "N/A"
    return value.strftime("%Y-%m")


def _trend_label(current: float, previous: float | None) -> str:
    if previous is None:
        return "flat"
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "flat"


def _is_old_period(value: date | None) -> bool:
    if value is None:
        return True
    today = date.today()
    month_gap = (today.year - value.year) * 12 + (today.month - value.month)
    return month_gap > 2


def _stock_status(available_units: float, latest_sales_units: float) -> str:
    if latest_sales_units <= 0:
        return "overstock_risk" if available_units > 0 else "normal"
    coverage_ratio = available_units / latest_sales_units
    if coverage_ratio < 0.8:
        return "low_stock"
    if coverage_ratio > 2.5:
        return "overstock_risk"
    return "normal"


def _inventory_coverage_months(available_units: float, latest_sales_units: float) -> float | str:
    if latest_sales_units <= 0:
        return "N/A"
    return round(available_units / latest_sales_units, 1)


def _normalized_scenario(value: str | None) -> str:
    scenario = (value or "baseline").strip().lower()
    return scenario if scenario in SUPPORTED_SCENARIOS else "baseline"


def _infer_material_from_text(value: str) -> str:
    normalized = value.lower()
    if "steel" in normalized:
        return "steel"
    if "copper" in normalized:
        return "copper"
    if "aluminum" in normalized:
        return "aluminum"
    if "lumber" in normalized or "wood" in normalized:
        return "lumber"
    if "cement" in normalized:
        return "cement"
    return "other"


def _cik_padded(cik: str) -> str:
    return str(cik).zfill(10)


def _build_sec_client() -> SecEdgarClient | None:
    if not SEC_USER_AGENT:
        return None
    return SecEdgarClient(base_url=SEC_BASE_URL, user_agent=SEC_USER_AGENT, timeout_seconds=20.0)


def _sec_fetch_submissions_for_universe() -> list[dict[str, object]]:
    client = _build_sec_client()
    if client is None:
        return []

    results: list[dict[str, object]] = []
    for company in SEC_COMPANY_UNIVERSE:
        cik10 = _cik_padded(company["cik"])
        try:
            payload = client.get_submissions(cik10)
            results.append(
                {
                    "company_name": company["company_name"],
                    "ticker": company["ticker"],
                    "cik": cik10,
                    "ok": True,
                    "payload": payload,
                    "error": None,
                }
            )
        except SecEdgarClientError as error:
            results.append(
                {
                    "company_name": company["company_name"],
                    "ticker": company["ticker"],
                    "cik": cik10,
                    "ok": False,
                    "payload": None,
                    "error": str(error),
                }
            )
    return results


def _fetch_macro_indicators_from_db() -> list[dict[str, object]]:
    query = text(
        """
        SELECT
            fs.code,
            fs.series_id,
            fs.name,
            fs.category,
            fs.unit,
            fs.source,
            mo.observation_date,
            mo.value
        FROM fred_series fs
        JOIN macro_observations mo ON mo.series_id = fs.id
        WHERE fs.is_active = TRUE
        ORDER BY fs.id, mo.observation_date DESC
        """
    )

    grouped_points: dict[str, list[dict[str, object]]] = defaultdict(list)

    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            for row in result.mappings():
                code = str(row["code"])
                if len(grouped_points[code]) < 2:
                    grouped_points[code].append(dict(row))
    except SQLAlchemyError:
        return []

    indicators: list[dict[str, object]] = []
    for code, points in grouped_points.items():
        latest = points[0]
        previous = points[1] if len(points) > 1 else None
        latest_value = float(latest["value"])
        previous_value = float(previous["value"]) if previous else None

        indicators.append(
            {
                "code": code,
                "series_id": str(latest["series_id"]),
                "name": str(latest["name"]),
                "category": str(latest["category"]),
                "value": latest_value,
                "latest_value": latest_value,
                "previous_value": previous_value if previous_value is not None else "N/A",
                "change_value": (
                    round(latest_value - previous_value, 4)
                    if previous_value is not None
                    else "N/A"
                ),
                "unit": str(latest["unit"]),
                "latest_date": latest["observation_date"].isoformat(),
                "trend": _trend_label(latest_value, previous_value),
                "source": str(latest["source"]),
                "as_of_month": _month_string(latest["observation_date"]),
            }
        )

    indicators.sort(key=lambda item: str(item["name"]))
    return indicators


def _fetch_trade_flows_from_db() -> list[dict[str, object]]:
    query = text(
        """
        WITH latest_period AS (
            SELECT MAX(period) AS period
            FROM trade_flows
        )
        SELECT
            m.material_code,
            m.material_name AS material,
            tf.hs_code,
            tf.reporter_country,
            tf.partner_country,
            tf.period,
            SUM(CASE WHEN tf.flow_type = 'import' THEN COALESCE(tf.trade_value_usd, 0) ELSE 0 END) AS import_value_usd,
            SUM(CASE WHEN tf.flow_type = 'export' THEN COALESCE(tf.trade_value_usd, 0) ELSE 0 END) AS export_value_usd,
            SUM(CASE WHEN tf.flow_type = 'import' AND tf.trade_value_usd IS NULL THEN 1 ELSE 0 END) AS missing_import_trade_count,
            SUM(CASE WHEN tf.flow_type = 'export' AND tf.trade_value_usd IS NULL THEN 1 ELSE 0 END) AS missing_export_trade_count,
            SUM(CASE WHEN tf.quantity IS NULL AND tf.net_weight_kg IS NULL THEN 1 ELSE 0 END) AS missing_quantity_count,
            SUM(CASE WHEN tf.quantity IS NULL AND tf.net_weight_kg IS NULL THEN 1 ELSE 0 END) AS unknown_unit_count
        FROM trade_flows tf
        JOIN materials m ON m.id = tf.material_id
        JOIN latest_period lp ON tf.period = lp.period
        GROUP BY
            m.material_code,
            m.material_name,
            tf.hs_code,
            tf.reporter_country,
            tf.partner_country,
            tf.period
        ORDER BY m.material_name
        """
    )

    items: list[dict[str, object]] = []
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            for row in result.mappings():
                import_value_usd = float(row["import_value_usd"] or 0)
                export_value_usd = float(row["export_value_usd"] or 0)
                period_value = row["period"]
                warnings: list[str] = []
                if int(row["missing_quantity_count"] or 0) > 0:
                    warnings.append("quantity_missing")
                if int(row["unknown_unit_count"] or 0) > 0:
                    warnings.append("unit_unknown")
                if int(row["missing_import_trade_count"] or 0) > 0:
                    warnings.append("import_value_missing")
                if int(row["missing_export_trade_count"] or 0) > 0:
                    warnings.append("export_value_missing")
                if _is_old_period(period_value):
                    warnings.append("stale_period")

                ratio = (
                    round(import_value_usd / export_value_usd, 4)
                    if export_value_usd > 0
                    else None
                )

                items.append(
                    {
                        "material_code": str(row["material_code"]),
                        "material": str(row["material"]),
                        "hs_code": str(row["hs_code"]),
                        "reporter_country": str(row["reporter_country"]),
                        "reporter": str(row["reporter_country"]),
                        "partner_country": str(row["partner_country"]),
                        "partner": str(row["partner_country"]),
                        "import_value_usd_millions": round(import_value_usd / 1_000_000, 3),
                        "export_value_usd_millions": round(export_value_usd / 1_000_000, 3),
                        "net_import_value_usd_millions": round(
                            (import_value_usd - export_value_usd) / 1_000_000, 3
                        ),
                        "import_value_usd": import_value_usd,
                        "export_value_usd": export_value_usd,
                        "net_import_value_usd": round(import_value_usd - export_value_usd, 2),
                        "import_export_ratio": ratio if ratio is not None else "N/A",
                        "source": "UN Comtrade",
                        "quality_warnings": warnings,
                        "has_warnings": len(warnings) > 0,
                        "latest_period": _month_string(period_value),
                        "as_of_month": _month_string(row["period"]),
                    }
                )
    except SQLAlchemyError:
        return []

    return items


def _fetch_inventory_operations_from_db() -> list[dict[str, object]]:
    query = text(
        """
        WITH latest_month_cte AS (
            SELECT MAX(snapshot_month) AS latest_month
            FROM inventory_snapshots
        ),
        inventory_latest AS (
            SELECT
                p.id AS product_id,
                p.product_name,
                p.product_category,
                lm.latest_month,
                SUM(i.on_hand_units) AS total_on_hand_units,
                SUM(i.available_units) AS total_available_units,
                SUM(i.inventory_value_usd) AS inventory_value_usd,
                AVG(i.average_unit_cost_usd) AS avg_unit_cost
            FROM products p
            JOIN latest_month_cte lm ON TRUE
            LEFT JOIN inventory_snapshots i
                ON i.product_id = p.id
               AND i.snapshot_month = lm.latest_month
            WHERE p.active = TRUE
            GROUP BY p.id, p.product_name, p.product_category, lm.latest_month
        ),
        sales_latest AS (
            SELECT
                s.product_id,
                SUM(s.units_sold) AS units_sold_latest_month,
                AVG(s.average_selling_price_usd) AS avg_selling_price
            FROM sales_orders s
            JOIN latest_month_cte lm ON s.order_month = lm.latest_month
            GROUP BY s.product_id
        ),
        sales_previous AS (
            SELECT
                s.product_id,
                SUM(s.units_sold) AS units_sold_previous_month
            FROM sales_orders s
            JOIN latest_month_cte lm ON s.order_month = (lm.latest_month - INTERVAL '1 month')
            GROUP BY s.product_id
        ),
        po_open AS (
            SELECT
                po.product_id,
                SUM(GREATEST(po.units_ordered - po.units_received, 0)) AS open_purchase_order_units
            FROM purchase_orders po
            WHERE po.status IN ('open', 'partial')
            GROUP BY po.product_id
        ),
        lead_latest AS (
            SELECT DISTINCT ON (sl.product_id)
                sl.product_id,
                sl.average_lead_time_days,
                sl.late_delivery_rate_percent
            FROM supplier_lead_times sl
            ORDER BY sl.product_id, sl.month DESC
        )
        SELECT
            il.product_id,
            il.product_name,
            il.product_category,
            il.latest_month,
            COALESCE(il.total_on_hand_units, 0) AS total_on_hand_units,
            COALESCE(il.total_available_units, 0) AS total_available_units,
            COALESCE(il.inventory_value_usd, 0) AS inventory_value_usd,
            COALESCE(sl.units_sold_latest_month, 0) AS units_sold_latest_month,
            COALESCE(sp.units_sold_previous_month, 0) AS units_sold_previous_month,
            COALESCE(po.open_purchase_order_units, 0) AS open_purchase_order_units,
            ll.average_lead_time_days,
            ll.late_delivery_rate_percent,
            il.avg_unit_cost,
            sl.avg_selling_price
        FROM inventory_latest il
        LEFT JOIN sales_latest sl ON sl.product_id = il.product_id
        LEFT JOIN sales_previous sp ON sp.product_id = il.product_id
        LEFT JOIN po_open po ON po.product_id = il.product_id
        LEFT JOIN lead_latest ll ON ll.product_id = il.product_id
        ORDER BY il.product_name
        """
    )

    rows: list[dict[str, object]] = []
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            for row in result.mappings():
                units_latest = float(row["units_sold_latest_month"] or 0)
                units_previous = float(row["units_sold_previous_month"] or 0)
                sales_mom_percent: float | str
                if units_previous <= 0:
                    sales_mom_percent = "N/A"
                else:
                    sales_mom_percent = round(
                        ((units_latest - units_previous) / units_previous) * 100, 2
                    )

                avg_cost = float(row["avg_unit_cost"] or 0)
                avg_sell = float(row["avg_selling_price"] or 0)
                est_margin: float | str
                if avg_sell > 0 and avg_cost > 0:
                    est_margin = round(((avg_sell - avg_cost) / avg_sell) * 100, 2)
                else:
                    est_margin = "N/A"

                available_units = float(row["total_available_units"] or 0)
                stock_status = _stock_status(available_units, units_latest)

                latest_month = row["latest_month"]
                material = _infer_material_from_text(str(row["product_category"]))
                rows.append(
                    {
                        "product_id": int(row["product_id"]),
                        "product_name": str(row["product_name"]),
                        "product_category": str(row["product_category"]),
                        "material": material,
                        "latest_month": _month_string(latest_month) if latest_month else "N/A",
                        "total_on_hand_units": round(float(row["total_on_hand_units"] or 0), 2),
                        "total_available_units": round(available_units, 2),
                        "inventory_value_usd": round(float(row["inventory_value_usd"] or 0), 2),
                        "units_sold_latest_month": round(units_latest, 2),
                        "units_sold_previous_month": round(units_previous, 2),
                        "sales_mom_percent": sales_mom_percent,
                        "open_purchase_order_units": round(
                            float(row["open_purchase_order_units"] or 0), 2
                        ),
                        "average_lead_time_days": round(
                            float(row["average_lead_time_days"] or 0), 2
                        ),
                        "late_delivery_rate_percent": round(
                            float(row["late_delivery_rate_percent"] or 0), 2
                        ),
                        "estimated_gross_margin_percent": est_margin,
                        "stock_status": stock_status,
                        "inventory_coverage_months": _inventory_coverage_months(
                            available_units, units_latest
                        ),
                    }
                )
    except SQLAlchemyError:
        return []

    return rows


def _aggregate_demand_signal(macro_items: list[dict[str, object]]) -> str:
    demand_rows = [
        item
        for item in macro_items
        if str(item.get("category")) in {"construction_demand", "industrial_demand"}
    ]
    up_count = sum(1 for item in demand_rows if item.get("trend") == "up")
    down_count = sum(1 for item in demand_rows if item.get("trend") == "down")
    if up_count > down_count:
        return "strong"
    if down_count > up_count:
        return "weak"
    return "neutral"


def _aggregate_cost_pressure_signal(macro_items: list[dict[str, object]]) -> str:
    pressure_rows = [
        item for item in macro_items if str(item.get("category")) == "materials_pressure"
    ]
    up_count = sum(1 for item in pressure_rows if item.get("trend") == "up")
    down_count = sum(1 for item in pressure_rows if item.get("trend") == "down")
    if up_count > down_count:
        return "rising"
    if down_count > up_count:
        return "falling"
    return "neutral"


def _trade_supply_signal_for_material(
    material: str, trade_items: list[dict[str, object]]
) -> tuple[str, bool]:
    target_rows = [
        item for item in trade_items if str(item.get("material_code")) == material
    ]
    if not target_rows:
        return ("neutral", False)

    row = target_rows[0]
    ratio = row.get("import_export_ratio")
    ratio_value = (
        float(ratio)
        if isinstance(ratio, (int, float))
        else None
        if ratio == "N/A"
        else None
    )
    net_import = float(row.get("net_import_value_usd", 0) or 0)

    if ratio_value is not None and ratio_value > 1.2 and net_import > 0:
        return ("tight", True)
    if (ratio_value is not None and ratio_value < 0.9) or net_import < 0:
        return ("loose", True)
    return ("neutral", True)


def _apply_inventory_scenario(
    inventory_rows: list[dict[str, object]], scenario: str
) -> list[dict[str, object]]:
    scenario_name = _normalized_scenario(scenario)
    if scenario_name == "baseline":
        return [dict(row) for row in inventory_rows]

    transformed: list[dict[str, object]] = []
    for row in inventory_rows:
        item = dict(row)
        sales_latest = float(item.get("units_sold_latest_month") or 0)
        available = float(item.get("total_available_units") or 0)
        on_hand = float(item.get("total_on_hand_units") or 0)
        lead_days = float(item.get("average_lead_time_days") or 0)
        late_rate = float(item.get("late_delivery_rate_percent") or 0)

        if scenario_name == "demand_spike":
            sales_latest *= 1.28
        elif scenario_name == "demand_drop":
            sales_latest *= 0.72
        elif scenario_name == "supply_tightening":
            lead_days *= 1.35
            late_rate = min(100.0, late_rate * 1.5)
        elif scenario_name == "overstock":
            available *= 2.2
            on_hand *= 2.0
        elif scenario_name == "low_stock":
            available *= 0.3
            on_hand *= 0.4

        item["units_sold_latest_month"] = round(sales_latest, 2)
        item["total_available_units"] = round(available, 2)
        item["total_on_hand_units"] = round(on_hand, 2)
        item["average_lead_time_days"] = round(lead_days, 2)
        item["late_delivery_rate_percent"] = round(late_rate, 2)
        item["stock_status"] = _stock_status(available, sales_latest)
        item["inventory_coverage_months"] = _inventory_coverage_months(available, sales_latest)
        item["scenario"] = scenario_name
        transformed.append(item)

    return transformed


def _recommendation_for_signals(
    inventory_signal: str,
    demand_signal: str,
    cost_pressure_signal: str,
) -> str:
    if inventory_signal == "low_stock" and demand_signal == "strong":
        return "buy_more"
    if inventory_signal == "low_stock" and cost_pressure_signal == "rising":
        return "buy_more"
    if inventory_signal == "overstock_risk" and demand_signal == "weak":
        return "buy_less"
    if inventory_signal == "overstock_risk" and cost_pressure_signal == "falling":
        return "buy_less"
    return "buy_same"


def _confidence_score(
    inventory_signal: str,
    demand_signal: str,
    cost_pressure_signal: str,
    has_trade_data: bool,
) -> float:
    score = 0.5
    if inventory_signal in {"low_stock", "overstock_risk"}:
        score += 0.1
    if demand_signal in {"strong", "weak"}:
        score += 0.1
    if cost_pressure_signal in {"rising", "falling"}:
        score += 0.1
    if has_trade_data:
        score += 0.1
    return min(0.9, round(score, 2))


def _persist_inventory_recommendations(items: list[dict[str, object]]) -> None:
    if not items:
        return

    insert_query = text(
        """
        INSERT INTO buy_recommendations (
            product_id,
            recommendation_month,
            recommendation,
            recommendation_label,
            confidence_score,
            confidence,
            demand_signal,
            cost_pressure_signal,
            trade_supply_signal,
            inventory_signal,
            rationale_json,
            source_notes_json,
            rationale,
            as_of_month
        )
        VALUES (
            :product_id,
            :recommendation_month,
            :recommendation,
            :recommendation,
            :confidence_score,
            :confidence_score,
            :demand_signal,
            :cost_pressure_signal,
            :trade_supply_signal,
            :inventory_signal,
            :rationale_json::jsonb,
            :source_notes_json::jsonb,
            :rationale_json::jsonb,
            :recommendation_month
        )
        ON CONFLICT (product_id, recommendation_month)
        DO UPDATE SET
            recommendation = EXCLUDED.recommendation,
            recommendation_label = EXCLUDED.recommendation_label,
            confidence_score = EXCLUDED.confidence_score,
            confidence = EXCLUDED.confidence,
            demand_signal = EXCLUDED.demand_signal,
            cost_pressure_signal = EXCLUDED.cost_pressure_signal,
            trade_supply_signal = EXCLUDED.trade_supply_signal,
            inventory_signal = EXCLUDED.inventory_signal,
            rationale_json = EXCLUDED.rationale_json,
            source_notes_json = EXCLUDED.source_notes_json,
            rationale = EXCLUDED.rationale,
            as_of_month = EXCLUDED.as_of_month
        """
    )

    try:
        with engine.begin() as conn:
            for item in items:
                recommendation_month = date.fromisoformat(str(item["latest_month"]) + "-01")
                conn.execute(
                    insert_query,
                    {
                        "product_id": int(item["product_id"]),
                        "recommendation_month": recommendation_month,
                        "recommendation": item["recommendation"],
                        "confidence_score": item["confidence_score"],
                        "demand_signal": item["demand_signal"],
                        "cost_pressure_signal": item["cost_pressure_signal"],
                        "trade_supply_signal": item["trade_supply_signal"],
                        "inventory_signal": item["inventory_signal"],
                        "rationale_json": json.dumps(item["rationale"]),
                        "source_notes_json": json.dumps(item["source_notes"]),
                    },
                )
    except SQLAlchemyError:
        return


def _build_inventory_recommendations(
    persist: bool = True, scenario: str = "baseline"
) -> list[dict[str, object]]:
    scenario_name = _normalized_scenario(scenario)
    macro_items = _fetch_macro_indicators_from_db()
    trade_items = _fetch_trade_flows_from_db()
    inventory_rows = _apply_inventory_scenario(
        _fetch_inventory_operations_from_db(), scenario_name
    )

    demand_signal = _aggregate_demand_signal(macro_items)
    cost_signal = _aggregate_cost_pressure_signal(macro_items)
    if scenario_name == "demand_spike":
        demand_signal = "strong"
    elif scenario_name == "demand_drop":
        demand_signal = "weak"
    if scenario_name == "supply_tightening":
        cost_signal = "rising"

    recommendations: list[dict[str, object]] = []
    for row in inventory_rows:
        material = str(row.get("material", "other"))
        trade_signal, has_trade_data = _trade_supply_signal_for_material(material, trade_items)
        if scenario_name == "supply_tightening":
            trade_signal = "tight"
        inventory_signal = str(row.get("stock_status", "normal"))
        recommendation = _recommendation_for_signals(
            inventory_signal=inventory_signal,
            demand_signal=demand_signal,
            cost_pressure_signal=cost_signal,
        )
        confidence = _confidence_score(
            inventory_signal=inventory_signal,
            demand_signal=demand_signal,
            cost_pressure_signal=cost_signal,
            has_trade_data=has_trade_data,
        )

        rationale = [
            f"Demand signal is {demand_signal}",
            f"Cost pressure is {cost_signal}",
            f"Trade supply is {trade_signal}",
            f"Inventory signal is {inventory_signal}",
        ]
        source_notes = ["FRED", "Synthetic Inventory Dataset"]
        if has_trade_data:
            source_notes.append("UN Comtrade")

        recommendations.append(
            {
                "product_id": int(row["product_id"]),
                "product_name": row["product_name"],
                "product_category": row["product_category"],
                "material": material,
                "latest_month": row["latest_month"],
                "recommendation": recommendation,
                "confidence_score": confidence,
                "demand_signal": demand_signal,
                "cost_pressure_signal": cost_signal,
                "trade_supply_signal": trade_signal,
                "inventory_signal": inventory_signal,
                "inventory_coverage_months": row.get("inventory_coverage_months", "N/A"),
                "rationale": rationale,
                "source_notes": source_notes,
                "scenario": scenario_name,
            }
        )

    if persist and scenario_name == "baseline":
        _persist_inventory_recommendations(recommendations)
    return recommendations


def _fetch_fred_preview_from_db(limit: int = 8) -> list[dict[str, object]]:
    query = text(
        """
        SELECT
            fs.source,
            fs.series_id,
            fs.name AS series_name,
            mo.observation_date,
            mo.value,
            fs.unit
        FROM macro_observations mo
        JOIN fred_series fs ON fs.id = mo.series_id
        ORDER BY mo.observation_date DESC, fs.series_id
        LIMIT :limit
        """
    )

    rows: list[dict[str, object]] = []
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"limit": limit})
            for row in result.mappings():
                rows.append(
                    {
                        "source": str(row["source"]),
                        "series_id": str(row["series_id"]),
                        "series_name": str(row["series_name"]),
                        "date": row["observation_date"].isoformat(),
                        "value": float(row["value"]),
                        "units": str(row["unit"]),
                    }
                )
    except SQLAlchemyError:
        return []

    return rows


def _fetch_comtrade_preview_from_db(limit: int = 8) -> list[dict[str, object]]:
    query = text(
        """
        SELECT
            tf.source,
            m.material_name,
            tf.hs_code,
            tf.reporter_country,
            tf.partner_country,
            tf.flow_type,
            tf.period,
            tf.trade_value_usd,
            tf.quantity,
            tf.net_weight_kg
        FROM trade_flows tf
        JOIN materials m ON m.id = tf.material_id
        ORDER BY tf.period DESC, m.material_name, tf.flow_type
        LIMIT :limit
        """
    )

    rows: list[dict[str, object]] = []
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"limit": limit})
            for row in result.mappings():
                quantity_value = (
                    float(row["quantity"])
                    if row["quantity"] is not None
                    else float(row["net_weight_kg"])
                    if row["net_weight_kg"] is not None
                    else None
                )
                unit = (
                    "reported_quantity"
                    if row["quantity"] is not None
                    else "kg"
                    if row["net_weight_kg"] is not None
                    else "unknown"
                )
                rows.append(
                    {
                        "source": str(row["source"]),
                        "material": str(row["material_name"]),
                        "hs_code": str(row["hs_code"]),
                        "reporter": str(row["reporter_country"]),
                        "partner": str(row["partner_country"]),
                        "flow_type": str(row["flow_type"]),
                        "period": _month_string(row["period"]),
                        "trade_value_usd": float(row["trade_value_usd"] or 0),
                        "quantity": quantity_value,
                        "unit": unit,
                    }
                )
    except SQLAlchemyError:
        return []

    return rows


def _fetch_data_source_status_from_db() -> dict[str, object]:
    status_payload: dict[str, object] = {
        "sources": [
            {
                "source_name": "FRED",
                "status": "unavailable",
                "latest_pull_timestamp": "N/A",
                "rows_returned": 0,
                "sample_series_material": "N/A",
            },
            {
                "source_name": "UN Comtrade",
                "status": "unavailable",
                "latest_pull_timestamp": "N/A",
                "rows_returned": 0,
                "sample_series_material": "N/A",
            },
        ],
        "data_freshness": {
            "latest_fred_date": "N/A",
            "latest_comtrade_period": "N/A",
        },
    }

    try:
        with engine.connect() as conn:
            fred_summary = conn.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS rows_returned,
                        MAX(mo.observation_date) AS latest_data_date,
                        MAX(mo.created_at) AS latest_pull_timestamp
                    FROM macro_observations mo
                    """
                )
            ).mappings().first()
            fred_sample = conn.execute(
                text(
                    """
                    SELECT fs.series_id
                    FROM macro_observations mo
                    JOIN fred_series fs ON fs.id = mo.series_id
                    ORDER BY mo.observation_date DESC
                    LIMIT 1
                    """
                )
            ).mappings().first()

            comtrade_summary = conn.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS rows_returned,
                        MAX(tf.period) AS latest_period,
                        MAX(tf.created_at) AS latest_pull_timestamp
                    FROM trade_flows tf
                    """
                )
            ).mappings().first()
            comtrade_sample = conn.execute(
                text(
                    """
                    SELECT m.material_name
                    FROM trade_flows tf
                    JOIN materials m ON m.id = tf.material_id
                    ORDER BY tf.period DESC
                    LIMIT 1
                    """
                )
            ).mappings().first()
    except SQLAlchemyError:
        return status_payload

    fred_rows = int((fred_summary or {}).get("rows_returned") or 0)
    fred_latest_date = (fred_summary or {}).get("latest_data_date")
    fred_latest_pull = (fred_summary or {}).get("latest_pull_timestamp")
    fred_sample_value = (fred_sample or {}).get("series_id")

    comtrade_rows = int((comtrade_summary or {}).get("rows_returned") or 0)
    comtrade_latest_period = (comtrade_summary or {}).get("latest_period")
    comtrade_latest_pull = (comtrade_summary or {}).get("latest_pull_timestamp")
    comtrade_sample_value = (comtrade_sample or {}).get("material_name")

    status_payload["sources"] = [
        {
            "source_name": "FRED",
            "status": "ok" if fred_rows > 0 else "empty",
            "latest_pull_timestamp": (
                fred_latest_pull.isoformat() if fred_latest_pull else "N/A"
            ),
            "rows_returned": fred_rows,
            "sample_series_material": str(fred_sample_value or "N/A"),
        },
        {
            "source_name": "UN Comtrade",
            "status": "ok" if comtrade_rows > 0 else "empty",
            "latest_pull_timestamp": (
                comtrade_latest_pull.isoformat() if comtrade_latest_pull else "N/A"
            ),
            "rows_returned": comtrade_rows,
            "sample_series_material": str(comtrade_sample_value or "N/A"),
        },
    ]
    status_payload["data_freshness"] = {
        "latest_fred_date": fred_latest_date.isoformat() if fred_latest_date else "N/A",
        "latest_comtrade_period": (
            _month_string(comtrade_latest_period) if comtrade_latest_period else "N/A"
        ),
    }

    return status_payload


def _sec_status_payload() -> dict[str, object]:
    if not SEC_USER_AGENT:
        return {
            "source": "SEC EDGAR",
            "status": "warning",
            "companies_checked": len(SEC_COMPANY_UNIVERSE),
            "companies_ok": 0,
            "companies_failed": len(SEC_COMPANY_UNIVERSE),
            "latest_successful_company": None,
            "message": "SEC_USER_AGENT is not configured.",
        }

    results = _sec_fetch_submissions_for_universe()
    checked = len(results)
    ok_rows = [item for item in results if item.get("ok")]
    failed_rows = [item for item in results if not item.get("ok")]

    status = "ok" if len(ok_rows) == checked else "warning" if ok_rows else "error"
    latest_successful_company = ok_rows[-1]["company_name"] if ok_rows else None
    message = (
        "SEC submissions endpoint reachable."
        if status == "ok"
        else "Some SEC company calls failed."
        if status == "warning"
        else "SEC submissions endpoint failed for all companies."
    )
    return {
        "source": "SEC EDGAR",
        "status": status,
        "companies_checked": checked,
        "companies_ok": len(ok_rows),
        "companies_failed": len(failed_rows),
        "latest_successful_company": latest_successful_company,
        "message": message,
    }


def _sec_company_preview_payload() -> list[dict[str, object]]:
    previews: list[dict[str, object]] = []
    for result in _sec_fetch_submissions_for_universe():
        payload = result.get("payload") or {}
        filings = ((payload.get("filings") or {}).get("recent") or {})
        forms = filings.get("form") or []
        dates = filings.get("filingDate") or []
        accessions = filings.get("accessionNumber") or []
        previews.append(
            {
                "company_name": result["company_name"],
                "ticker": result["ticker"],
                "cik": result["cik"],
                "sec_name": payload.get("name"),
                "sic": payload.get("sic"),
                "sic_description": payload.get("sicDescription"),
                "latest_filing_form": forms[0] if forms else None,
                "latest_filing_date": dates[0] if dates else None,
                "latest_accession_number": accessions[0] if accessions else None,
                "source": "SEC EDGAR",
            }
        )
    return previews


def _sec_company_facts_preview_payload() -> list[dict[str, object]]:
    client = _build_sec_client()
    if client is None:
        return []

    previews: list[dict[str, object]] = []
    for company in SEC_COMPANY_UNIVERSE:
        cik10 = _cik_padded(company["cik"])
        try:
            facts_payload = client.get_company_facts(cik10)
        except SecEdgarClientError:
            continue

        facts = (facts_payload.get("facts") or {}).get("us-gaap") or {}
        fact_names = list(facts.keys())
        previews.append(
            {
                "company_name": company["company_name"],
                "ticker": company["ticker"],
                "cik": cik10,
                "entity_name": facts_payload.get("entityName"),
                "available_taxonomies": list((facts_payload.get("facts") or {}).keys()),
                "number_of_us_gaap_facts": len(fact_names),
                "sample_fact_names": fact_names[:5],
            }
        )
    return previews


def _generate_data_quality_report() -> dict[str, object]:
    checks_by_source: dict[str, list[dict[str, str]]] = {
        "FRED": [],
        "UN Comtrade": [],
        "Synthetic Inventory Dataset": [],
    }

    try:
        with engine.connect() as conn:
            fred_rows = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS rows_returned
                    FROM macro_observations
                    """
                )
            ).scalar()
            fred_latest_date = conn.execute(
                text(
                    """
                    SELECT MAX(observation_date) AS latest_date
                    FROM macro_observations
                    """
                )
            ).scalar()
            fred_non_numeric_values = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS invalid_count
                    FROM macro_observations
                    WHERE value IS NULL
                    """
                )
            ).scalar()
            fred_present_series = conn.execute(
                text(
                    """
                    SELECT DISTINCT fs.series_id
                    FROM fred_series fs
                    JOIN macro_observations mo ON mo.series_id = fs.id
                    """
                )
            ).scalars().all()

            comtrade_rows = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS rows_returned
                    FROM trade_flows
                    """
                )
            ).scalar()
            comtrade_missing_period = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS missing_period
                    FROM trade_flows
                    WHERE period IS NULL
                    """
                )
            ).scalar()
            comtrade_missing_trade_value = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS missing_trade_value
                    FROM trade_flows
                    WHERE trade_value_usd IS NULL
                    """
                )
            ).scalar()
            comtrade_missing_qty_unit = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS missing_qty_unit
                    FROM trade_flows
                    WHERE quantity IS NULL AND net_weight_kg IS NULL
                    """
                )
            ).scalar()
            comtrade_flow_counts = conn.execute(
                text(
                    """
                    SELECT m.material_code, tf.flow_type, COUNT(*) AS row_count
                    FROM trade_flows tf
                    JOIN materials m ON m.id = tf.material_id
                    GROUP BY m.material_code, tf.flow_type
                    """
                )
            ).mappings().all()

            inventory_products_count = conn.execute(
                text("SELECT COUNT(*) FROM products WHERE active = TRUE")
            ).scalar()
            inventory_warehouses_count = conn.execute(
                text("SELECT COUNT(*) FROM warehouses WHERE active = TRUE")
            ).scalar()
            inventory_snapshots_count = conn.execute(
                text("SELECT COUNT(*) FROM inventory_snapshots")
            ).scalar()
            sales_orders_count = conn.execute(
                text("SELECT COUNT(*) FROM sales_orders")
            ).scalar()
            purchase_orders_count = conn.execute(
                text("SELECT COUNT(*) FROM purchase_orders")
            ).scalar()
            lead_times_count = conn.execute(
                text("SELECT COUNT(*) FROM supplier_lead_times")
            ).scalar()
            latest_inventory_month = conn.execute(
                text("SELECT MAX(snapshot_month) FROM inventory_snapshots")
            ).scalar()
    except SQLAlchemyError:
        return {
            "overall_status": "error",
            "sources": [
                {
                    "source_name": "FRED",
                    "status": "error",
                    "checks": [
                        {
                            "name": "db_query",
                            "status": "error",
                            "message": "Failed to query FRED quality checks",
                        }
                    ],
                },
                {
                    "source_name": "UN Comtrade",
                    "status": "error",
                    "checks": [
                        {
                            "name": "db_query",
                            "status": "error",
                            "message": "Failed to query Comtrade quality checks",
                        }
                    ],
                },
                {
                    "source_name": "Synthetic Inventory Dataset",
                    "status": "error",
                    "checks": [
                        {
                            "name": "db_query",
                            "status": "error",
                            "message": "Failed to query synthetic inventory quality checks",
                        }
                    ],
                },
            ],
        }

    fred_rows = int(fred_rows or 0)
    checks_by_source["FRED"].append(
        {
            "name": "rows_returned",
            "status": "ok" if fred_rows > 0 else "error",
            "message": f"{fred_rows} rows returned",
        }
    )
    checks_by_source["FRED"].append(
        {
            "name": "latest_observation_date",
            "status": "ok" if fred_latest_date else "error",
            "message": (
                f"Latest observation date {fred_latest_date.isoformat()}"
                if fred_latest_date
                else "Latest observation date missing"
            ),
        }
    )
    checks_by_source["FRED"].append(
        {
            "name": "numeric_values",
            "status": "ok" if int(fred_non_numeric_values or 0) == 0 else "error",
            "message": (
                "All values are numeric"
                if int(fred_non_numeric_values or 0) == 0
                else f"{int(fred_non_numeric_values)} rows have null values"
            ),
        }
    )
    present_series = {str(item) for item in fred_present_series}
    missing_series = sorted(FRED_REQUIRED_SERIES - present_series)
    checks_by_source["FRED"].append(
        {
            "name": "required_series_present",
            "status": "ok" if not missing_series else "warning",
            "message": (
                "All required configured series are present"
                if not missing_series
                else f"Missing series: {', '.join(missing_series)}"
            ),
        }
    )

    comtrade_rows = int(comtrade_rows or 0)
    checks_by_source["UN Comtrade"].append(
        {
            "name": "rows_returned",
            "status": "ok" if comtrade_rows > 0 else "error",
            "message": f"{comtrade_rows} rows returned",
        }
    )

    products_count = int(inventory_products_count or 0)
    warehouses_count = int(inventory_warehouses_count or 0)
    snapshots_count = int(inventory_snapshots_count or 0)
    sales_count = int(sales_orders_count or 0)
    po_count = int(purchase_orders_count or 0)
    lead_count = int(lead_times_count or 0)

    checks_by_source["Synthetic Inventory Dataset"].append(
        {
            "name": "products_seeded",
            "status": "ok" if products_count > 0 else "error",
            "message": f"{products_count} products seeded",
        }
    )
    checks_by_source["Synthetic Inventory Dataset"].append(
        {
            "name": "warehouses_seeded",
            "status": "ok" if warehouses_count > 0 else "error",
            "message": f"{warehouses_count} warehouses seeded",
        }
    )
    checks_by_source["Synthetic Inventory Dataset"].append(
        {
            "name": "inventory_snapshots_available",
            "status": "ok" if snapshots_count > 0 else "error",
            "message": f"{snapshots_count} inventory snapshots available",
        }
    )
    checks_by_source["Synthetic Inventory Dataset"].append(
        {
            "name": "sales_orders_available",
            "status": "ok" if sales_count > 0 else "error",
            "message": f"{sales_count} sales orders available",
        }
    )
    checks_by_source["Synthetic Inventory Dataset"].append(
        {
            "name": "purchase_orders_available",
            "status": "ok" if po_count > 0 else "error",
            "message": f"{po_count} purchase orders available",
        }
    )
    checks_by_source["Synthetic Inventory Dataset"].append(
        {
            "name": "lead_times_available",
            "status": "ok" if lead_count > 0 else "error",
            "message": f"{lead_count} supplier lead-time rows available",
        }
    )
    checks_by_source["Synthetic Inventory Dataset"].append(
        {
            "name": "latest_inventory_month_exists",
            "status": "ok" if latest_inventory_month else "error",
            "message": (
                f"Latest inventory month {latest_inventory_month.isoformat()}"
                if latest_inventory_month
                else "Latest inventory month missing"
            ),
        }
    )

    if SEC_PROOF_OF_LIFE_ENABLED:
        sec_checks: list[dict[str, str]] = []
        if not SEC_USER_AGENT:
            sec_checks.append(
                {
                    "name": "sec_user_agent_configured",
                    "status": "warning",
                    "message": "SEC_USER_AGENT is missing; SEC proof-of-life is disabled.",
                }
            )
        else:
            sec_checks.append(
                {
                    "name": "sec_user_agent_configured",
                    "status": "ok",
                    "message": "SEC_USER_AGENT is configured.",
                }
            )
            submissions = _sec_fetch_submissions_for_universe()
            ok_count = sum(1 for item in submissions if item.get("ok"))
            sec_checks.append(
                {
                    "name": "submissions_endpoint_reachable",
                    "status": "ok" if ok_count > 0 else "error",
                    "message": f"{ok_count} companies returned submissions.",
                }
            )
            sec_checks.append(
                {
                    "name": "at_least_one_company_has_filings",
                    "status": "ok" if ok_count > 0 else "error",
                    "message": (
                        "At least one company returned filings."
                        if ok_count > 0
                        else "No company returned filings."
                    ),
                }
            )
            facts_preview = _sec_company_facts_preview_payload()
            sec_checks.append(
                {
                    "name": "company_facts_endpoint_reachable",
                    "status": "ok" if len(facts_preview) > 0 else "warning",
                    "message": (
                        "Company facts endpoint reachable."
                        if len(facts_preview) > 0
                        else "Company facts endpoint not reachable for configured companies."
                    ),
                }
            )

        checks_by_source["SEC EDGAR"] = sec_checks

    material_flow_map: dict[str, set[str]] = defaultdict(set)
    for row in comtrade_flow_counts:
        material_flow_map[str(row["material_code"])].add(str(row["flow_type"]))

    missing_import = [
        code for code in COMTRADE_REQUIRED_MATERIALS if "import" not in material_flow_map[code]
    ]
    missing_export = [
        code for code in COMTRADE_REQUIRED_MATERIALS if "export" not in material_flow_map[code]
    ]
    checks_by_source["UN Comtrade"].append(
        {
            "name": "material_import_coverage",
            "status": "ok" if not missing_import else "error",
            "message": (
                "Each configured material has at least one import row"
                if not missing_import
                else f"Missing import rows for: {', '.join(sorted(missing_import))}"
            ),
        }
    )
    checks_by_source["UN Comtrade"].append(
        {
            "name": "material_export_coverage",
            "status": "ok" if not missing_export else "error",
            "message": (
                "Each configured material has at least one export row"
                if not missing_export
                else f"Missing export rows for: {', '.join(sorted(missing_export))}"
            ),
        }
    )
    checks_by_source["UN Comtrade"].append(
        {
            "name": "trade_value_numeric",
            "status": "ok" if int(comtrade_missing_trade_value or 0) == 0 else "warning",
            "message": (
                "Trade values are present"
                if int(comtrade_missing_trade_value or 0) == 0
                else f"{int(comtrade_missing_trade_value)} rows missing trade_value_usd"
            ),
        }
    )
    checks_by_source["UN Comtrade"].append(
        {
            "name": "period_exists",
            "status": "ok" if int(comtrade_missing_period or 0) == 0 else "error",
            "message": (
                "All trade rows have a period"
                if int(comtrade_missing_period or 0) == 0
                else f"{int(comtrade_missing_period)} rows missing period"
            ),
        }
    )
    checks_by_source["UN Comtrade"].append(
        {
            "name": "missing_quantity",
            "status": "warning" if int(comtrade_missing_qty_unit or 0) > 0 else "ok",
            "message": (
                "Some material rows are missing physical quantity; trade value is still available"
                if int(comtrade_missing_qty_unit or 0) > 0
                else "Quantity/unit present for all rows"
            ),
        }
    )

    source_statuses = []
    worst_status_rank = 0
    status_rank = {"ok": 0, "warning": 1, "error": 2}
    for source_name, checks in checks_by_source.items():
        source_state = "ok"
        for check in checks:
            if status_rank[check["status"]] > status_rank[source_state]:
                source_state = check["status"]
        worst_status_rank = max(worst_status_rank, status_rank[source_state])
        source_statuses.append(
            {"source_name": source_name, "status": source_state, "checks": checks}
        )

    inverse_rank = {0: "ok", 1: "warning", 2: "error"}
    return {"overall_status": inverse_rank[worst_status_rank], "sources": source_statuses}


def _build_recommendation() -> dict[str, object]:
    demand_index = 54.0
    cost_pressure_score = 47.0
    overstock_risk_score = 41.0
    recommendation_label = "buy_more"
    confidence = 0.69

    return {
        "as_of_month": "2026-04",
        "recommendation_label": recommendation_label,
        "confidence": confidence,
        "demand_index": demand_index,
        "material_cost_pressure_score": cost_pressure_score,
        "overstock_risk_score": overstock_risk_score,
        "rationale": [
            "Construction demand indicators are positive versus last month.",
            "Material cost pressure is easing, reducing purchase timing risk.",
            "Overstock risk remains moderate based on inventory/disclosure signals.",
        ],
    }


@app.get("/api/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello from FastAPI"}


@app.get("/api/health/db")
def db_health() -> dict[str, str]:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 'Postgres is connected' AS message;"))
        row = result.fetchone()

    message = row[0] if row else "Database check failed"
    return {"message": message}


@app.get("/api/dashboard/overview")
def dashboard_overview() -> dict[str, object]:
    recommendation = _build_recommendation()
    macro_items = _fetch_macro_indicators_from_db()
    trade_items = _fetch_trade_flows_from_db()
    return {
        "industry_focus": "Industrial Distribution / Building Materials",
        "as_of_month": recommendation["as_of_month"],
        "recommendation_label": recommendation["recommendation_label"],
        "confidence": recommendation["confidence"],
        "macro_indicator_count": len(macro_items),
        "trade_flow_count": len(trade_items),
        "company_indicator_count": len(COMPANY_FINANCIAL_INDICATORS),
    }


@app.get("/api/indicators/macro")
def macro_indicators() -> dict[str, object]:
    return {"items": _fetch_macro_indicators_from_db()}


@app.get("/api/indicators/trade-flows")
def trade_flow_indicators() -> dict[str, object]:
    return {"items": _fetch_trade_flows_from_db()}


@app.get("/api/indicators/inventory-operations")
def inventory_operations_indicators(scenario: str = "baseline") -> dict[str, object]:
    scenario_name = _normalized_scenario(scenario)
    base_rows = _fetch_inventory_operations_from_db()
    return {"items": _apply_inventory_scenario(base_rows, scenario_name), "scenario": scenario_name}


@app.get("/api/indicators/company-financials")
def company_financial_indicators() -> dict[str, object]:
    return {"items": COMPANY_FINANCIAL_INDICATORS}


@app.get("/api/indicators/supply-chain-disclosures")
def supply_chain_disclosures() -> dict[str, object]:
    return {"items": SUPPLY_CHAIN_DISCLOSURE_INDICATORS}


@app.get("/api/recommendations/current")
def current_recommendation(scenario: str = "baseline") -> dict[str, object]:
    scenario_name = _normalized_scenario(scenario)
    product_recommendations = _build_inventory_recommendations(
        persist=True, scenario=scenario_name
    )
    buy_more_count = sum(
        1
        for item in product_recommendations
        if item.get("recommendation") == "buy_more"
    )
    buy_less_count = sum(
        1
        for item in product_recommendations
        if item.get("recommendation") == "buy_less"
    )
    buy_same_count = sum(
        1
        for item in product_recommendations
        if item.get("recommendation") == "buy_same"
    )

    if buy_more_count > max(buy_less_count, buy_same_count):
        overall = "buy_more"
    elif buy_less_count > max(buy_more_count, buy_same_count):
        overall = "buy_less"
    else:
        overall = "buy_same"

    confidence = (
        round(
            sum(float(item.get("confidence_score", 0)) for item in product_recommendations)
            / len(product_recommendations),
            2,
        )
        if product_recommendations
        else 0.5
    )
    rationale = [
        f"Buy More: {buy_more_count} products",
        f"Buy Same: {buy_same_count} products",
        f"Buy Less: {buy_less_count} products",
    ]
    return {
        "overall_recommendation": overall,
        "confidence": confidence,
        "product_count": len(product_recommendations),
        "buy_more_count": buy_more_count,
        "buy_same_count": buy_same_count,
        "buy_less_count": buy_less_count,
        "rationale": rationale,
        "scenario": scenario_name,
    }


@app.get("/api/recommendations/inventory")
def inventory_recommendations(scenario: str = "baseline") -> dict[str, object]:
    scenario_name = _normalized_scenario(scenario)
    return {"items": _build_inventory_recommendations(persist=True, scenario=scenario_name), "scenario": scenario_name}


@app.get("/api/data-sources/status")
def data_sources_status() -> dict[str, object]:
    return _fetch_data_source_status_from_db()


@app.get("/api/debug/fred-preview")
def debug_fred_preview() -> dict[str, object]:
    return {"items": _fetch_fred_preview_from_db()}


@app.get("/api/debug/comtrade-preview")
def debug_comtrade_preview() -> dict[str, object]:
    return {"items": _fetch_comtrade_preview_from_db()}


@app.get("/api/sec/status")
def sec_status() -> dict[str, object]:
    return _sec_status_payload()


@app.get("/api/sec/company-preview")
def sec_company_preview() -> dict[str, object]:
    return {"items": _sec_company_preview_payload()}


@app.get("/api/sec/company-facts-preview")
def sec_company_facts_preview() -> dict[str, object]:
    return {"items": _sec_company_facts_preview_payload()}


@app.get("/api/data-quality")
def data_quality() -> dict[str, object]:
    return _generate_data_quality_report()

