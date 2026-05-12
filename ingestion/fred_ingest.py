import os
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import create_engine, text

FRED_BASE_URL = "https://api.stlouisfed.org/fred"

SERIES_CATALOG = [
    {
        "series_id": "CPIAUCSL",
        "code": "cpi_all_items",
        "name": "CPI All Urban Consumers",
        "category": "inflation",
        "unit": "index",
    },
    {
        "series_id": "PPIACO",
        "code": "ppi_all_commodities",
        "name": "Producer Price Index: All Commodities",
        "category": "inflation",
        "unit": "index",
    },
    {
        "series_id": "FEDFUNDS",
        "code": "federal_funds_rate",
        "name": "Federal Funds Effective Rate",
        "category": "rates",
        "unit": "percent",
    },
    {
        "series_id": "DGS10",
        "code": "us_10y_treasury_rate",
        "name": "10-Year Treasury Constant Maturity Rate",
        "category": "rates",
        "unit": "percent",
    },
    {
        "series_id": "HOUST",
        "code": "housing_starts",
        "name": "Housing Starts: Total New Privately Owned Housing Units Started",
        "category": "construction_demand",
        "unit": "thousands_of_units",
    },
    {
        "series_id": "TTLCONS",
        "code": "construction_spending_total",
        "name": "Total Construction Spending",
        "category": "construction_demand",
        "unit": "million_usd",
    },
    {
        "series_id": "INDPRO",
        "code": "industrial_production_index",
        "name": "Industrial Production Index",
        "category": "industrial_demand",
        "unit": "index",
    },
    {
        "series_id": "WPU1017",
        "code": "ppi_steel_mill_products",
        "name": "PPI: Steel Mill Products",
        "category": "materials_pressure",
        "unit": "index",
    },
    {
        "series_id": "WPU083",
        "code": "ppi_lumber_products",
        "name": "PPI: Lumber and Wood Products",
        "category": "materials_pressure",
        "unit": "index",
    },
]


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def fetch_observations(
    client: httpx.Client, api_key: str, series_id: str, observation_start: str
) -> list[dict[str, Any]]:
    response = client.get(
        f"{FRED_BASE_URL}/series/observations",
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": observation_start,
        },
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("observations", [])


def upsert_series(conn: Any, series: dict[str, str]) -> int:
    result = conn.execute(
        text(
            """
            INSERT INTO fred_series (series_id, code, name, category, unit, frequency, source, is_active)
            VALUES (:series_id, :code, :name, :category, :unit, 'monthly', 'FRED', TRUE)
            ON CONFLICT (series_id) DO UPDATE
                SET code = EXCLUDED.code,
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    unit = EXCLUDED.unit,
                    is_active = TRUE
            RETURNING id
            """
        ),
        series,
    )
    return int(result.scalar_one())


def upsert_observations(conn: Any, fred_series_id: int, observations: list[dict[str, Any]]) -> int:
    inserted = 0
    for point in observations:
        raw_value = point.get("value")
        if raw_value in (None, "."):
            continue

        try:
            numeric_value = Decimal(str(raw_value))
        except (InvalidOperation, ValueError):
            continue

        conn.execute(
            text(
                """
                INSERT INTO macro_observations (series_id, observation_date, value)
                VALUES (:series_id, :observation_date, :value)
                ON CONFLICT (series_id, observation_date) DO UPDATE
                    SET value = EXCLUDED.value
                """
            ),
            {
                "series_id": fred_series_id,
                "observation_date": point.get("date"),
                "value": numeric_value,
            },
        )
        inserted += 1

    return inserted


def run() -> None:
    fred_api_key = get_required_env("FRED_API_KEY")
    database_url = get_required_env("DATABASE_URL")
    observation_start = os.getenv("FRED_OBSERVATION_START", "2015-01-01")

    engine = create_engine(database_url, future=True)

    total_upserted = 0
    with httpx.Client(timeout=30.0) as client:
        with engine.begin() as conn:
            for series in SERIES_CATALOG:
                fred_series_id = upsert_series(conn, series)
                observations = fetch_observations(
                    client=client,
                    api_key=fred_api_key,
                    series_id=series["series_id"],
                    observation_start=observation_start,
                )
                upserted = upsert_observations(conn, fred_series_id, observations)
                total_upserted += upserted
                print(
                    f"Series {series['series_id']} ({series['code']}): "
                    f"{upserted} observations upserted"
                )

    print(f"Done. Total macro observations upserted: {total_upserted}")


if __name__ == "__main__":
    run()
