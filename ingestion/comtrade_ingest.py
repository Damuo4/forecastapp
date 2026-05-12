import os
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import create_engine, text

COMTRADE_BASE_URL = "https://comtradeapi.un.org/data/v1"

MATERIALS_CATALOG = [
    {
        "material_code": "steel",
        "material_name": "Steel products",
        "material_group": "metals",
        "default_hs_code": "72",
        "cmd_code": "72",
    },
    {
        "material_code": "copper",
        "material_name": "Copper and articles",
        "material_group": "metals",
        "default_hs_code": "74",
        "cmd_code": "74",
    },
    {
        "material_code": "aluminum",
        "material_name": "Aluminum and articles",
        "material_group": "metals",
        "default_hs_code": "76",
        "cmd_code": "76",
    },
    {
        "material_code": "lumber",
        "material_name": "Lumber and wood products",
        "material_group": "wood",
        "default_hs_code": "44",
        "cmd_code": "44",
    },
    {
        "material_code": "cement",
        "material_name": "Cement",
        "material_group": "construction_materials",
        "default_hs_code": "2523",
        "cmd_code": "2523",
    },
]

FLOW_CODE_TO_TYPE = {
    "M": "import",
    "X": "export",
}


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_numeric(value: Any) -> Decimal | None:
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_period_to_date(period: str) -> date:
    cleaned = str(period).strip()
    if len(cleaned) == 6:
        return date(int(cleaned[0:4]), int(cleaned[4:6]), 1)
    if len(cleaned) == 4:
        return date(int(cleaned), 1, 1)
    raise ValueError(f"Unsupported period format: {period}")


def upsert_material(conn: Any, material: dict[str, str]) -> int:
    result = conn.execute(
        text(
            """
            INSERT INTO materials (material_code, material_name, material_group, default_hs_code, is_active)
            VALUES (:material_code, :material_name, :material_group, :default_hs_code, TRUE)
            ON CONFLICT (material_code) DO UPDATE
                SET material_name = EXCLUDED.material_name,
                    material_group = EXCLUDED.material_group,
                    default_hs_code = EXCLUDED.default_hs_code,
                    is_active = TRUE
            RETURNING id
            """
        ),
        {
            "material_code": material["material_code"],
            "material_name": material["material_name"],
            "material_group": material["material_group"],
            "default_hs_code": material["default_hs_code"],
        },
    )
    return int(result.scalar_one())


def fetch_comtrade_rows(
    client: httpx.Client,
    api_key: str,
    reporter_code: str,
    partner_code: str,
    periods: str,
    cmd_code: str,
) -> list[dict[str, Any]]:
    response = client.get(
        f"{COMTRADE_BASE_URL}/get/C/A/HS",
        headers={"Ocp-Apim-Subscription-Key": api_key},
        params={
            "reporterCode": reporter_code,
            "partnerCode": partner_code,
            "period": periods,
            "flowCode": "M,X",
            "cmdCode": cmd_code,
            "includeDesc": "true",
        },
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("data", [])


def upsert_trade_rows(conn: Any, material_id: int, rows: list[dict[str, Any]]) -> int:
    upserted = 0
    for row in rows:
        flow_code = str(row.get("flowCode", "")).strip()
        flow_type = FLOW_CODE_TO_TYPE.get(flow_code)
        if flow_type is None:
            continue

        period_value = row.get("period")
        if period_value in (None, ""):
            continue

        try:
            period_date = parse_period_to_date(str(period_value))
        except ValueError:
            continue

        reporter_country = (
            row.get("reporterDesc")
            or row.get("reporterISO")
            or str(row.get("reporterCode", "Unknown"))
        )
        partner_country = (
            row.get("partnerDesc")
            or row.get("partnerISO")
            or str(row.get("partnerCode", "Unknown"))
        )

        trade_value = parse_numeric(
            row.get("primaryValue")
            or row.get("tradeValue")
            or row.get("fobvalue")
            or row.get("cifvalue")
        )
        net_weight = parse_numeric(row.get("netWgt") or row.get("netWeight"))
        quantity = parse_numeric(row.get("qty") or row.get("quantity"))
        hs_code = str(row.get("cmdCode") or row.get("classificationCode") or "")

        conn.execute(
            text(
                """
                INSERT INTO trade_flows (
                    material_id,
                    reporter_country,
                    partner_country,
                    flow_type,
                    period,
                    trade_value_usd,
                    net_weight_kg,
                    quantity,
                    hs_code,
                    source
                )
                VALUES (
                    :material_id,
                    :reporter_country,
                    :partner_country,
                    :flow_type,
                    :period,
                    :trade_value_usd,
                    :net_weight_kg,
                    :quantity,
                    :hs_code,
                    'UN_COMTRADE'
                )
                ON CONFLICT (material_id, reporter_country, partner_country, flow_type, period, hs_code)
                DO UPDATE SET
                    trade_value_usd = EXCLUDED.trade_value_usd,
                    net_weight_kg = EXCLUDED.net_weight_kg,
                    quantity = EXCLUDED.quantity
                """
            ),
            {
                "material_id": material_id,
                "reporter_country": str(reporter_country),
                "partner_country": str(partner_country),
                "flow_type": flow_type,
                "period": period_date,
                "trade_value_usd": trade_value,
                "net_weight_kg": net_weight,
                "quantity": quantity,
                "hs_code": hs_code,
            },
        )
        upserted += 1

    return upserted


def run() -> None:
    api_key = get_required_env("COMTRADE_API_KEY")
    database_url = get_required_env("DATABASE_URL")

    reporter_code = os.getenv("COMTRADE_REPORTER_CODE", "842")
    partner_code = os.getenv("COMTRADE_PARTNER_CODE", "0")
    periods = os.getenv("COMTRADE_PERIODS", "2023,2024,2025")

    engine = create_engine(database_url, future=True)
    total_upserted = 0

    with httpx.Client() as client:
        with engine.begin() as conn:
            for material in MATERIALS_CATALOG:
                material_id = upsert_material(conn, material)
                rows = fetch_comtrade_rows(
                    client=client,
                    api_key=api_key,
                    reporter_code=reporter_code,
                    partner_code=partner_code,
                    periods=periods,
                    cmd_code=material["cmd_code"],
                )
                upserted = upsert_trade_rows(conn, material_id, rows)
                total_upserted += upserted
                print(
                    f"Material {material['material_code']} ({material['cmd_code']}): "
                    f"{upserted} trade rows upserted"
                )

    print(f"Done. Total trade rows upserted: {total_upserted}")


if __name__ == "__main__":
    run()
