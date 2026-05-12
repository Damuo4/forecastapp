import os
import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text


@dataclass(frozen=True)
class ProductSeed:
    material_code: str
    sku: str
    product_name: str
    product_category: str
    hs_code: str
    unit_of_measure: str
    base_demand_units: int
    base_cost_usd: float
    base_sell_usd: float
    supplier_name: str
    lead_time_days: int


PRODUCTS: list[ProductSeed] = [
    ProductSeed("steel", "STL-BEAM-100", "Steel Beam Bundle 100", "Steel products", "72", "bundle", 820, 415.0, 560.0, "Great Lakes Steel Co", 36),
    ProductSeed("copper", "CPR-TUBE-50", "Copper Tube Set 50", "Copper products", "74", "set", 700, 385.0, 535.0, "Copper Ridge Metals", 33),
    ProductSeed("aluminum", "ALM-SHEET-200", "Aluminum Sheet Pack 200", "Aluminum products", "76", "pack", 760, 295.0, 430.0, "North Aluminum Works", 31),
    ProductSeed("lumber", "LMB-2X4-STD", "Lumber 2x4 Standard Lot", "Lumber and wood products", "44", "lot", 940, 120.0, 210.0, "Pine Valley Timber", 25),
    ProductSeed("cement", "CMT-PORT-90", "Portland Cement Pallet 90", "Cement", "2523", "pallet", 680, 92.0, 155.0, "Atlas Cement Supply", 22),
]

WAREHOUSES = [
    ("Northeast Distribution Center", "Northeast", "US"),
    ("Midwest Distribution Center", "Midwest", "US"),
    ("Southern Distribution Center", "South", "US"),
]

REGION_FACTORS = {
    "Northeast": 1.06,
    "Midwest": 1.0,
    "South": 1.12,
}


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def month_shift(value: date, delta_months: int) -> date:
    month_index = value.year * 12 + (value.month - 1) + delta_months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def generate_months_back(month_count: int) -> list[date]:
    start = month_start(date.today().year, date.today().month)
    return [month_shift(start, -offset) for offset in range(month_count - 1, -1, -1)]


def upsert_product(conn: Any, product: ProductSeed) -> int:
    result = conn.execute(
        text(
            """
            INSERT INTO products (material_id, sku, product_name, product_category, hs_code, unit_of_measure, active)
            VALUES (
                (SELECT id FROM materials WHERE material_code = :material_code LIMIT 1),
                :sku, :product_name, :product_category, :hs_code, :unit_of_measure, TRUE
            )
            ON CONFLICT (sku) DO UPDATE
                SET material_id = EXCLUDED.material_id,
                    product_name = EXCLUDED.product_name,
                    product_category = EXCLUDED.product_category,
                    hs_code = EXCLUDED.hs_code,
                    unit_of_measure = EXCLUDED.unit_of_measure,
                    active = TRUE,
                    updated_at = NOW()
            RETURNING id
            """
        ),
        {
            "material_code": product.material_code,
            "sku": product.sku,
            "product_name": product.product_name,
            "product_category": product.product_category,
            "hs_code": product.hs_code,
            "unit_of_measure": product.unit_of_measure,
        },
    )
    return int(result.scalar_one())


def upsert_warehouse(conn: Any, warehouse_name: str, region: str, country: str) -> int:
    result = conn.execute(
        text(
            """
            INSERT INTO warehouses (warehouse_name, region, country, active)
            VALUES (:warehouse_name, :region, :country, TRUE)
            ON CONFLICT (warehouse_name) DO UPDATE
                SET region = EXCLUDED.region,
                    country = EXCLUDED.country,
                    active = TRUE,
                    updated_at = NOW()
            RETURNING id
            """
        ),
        {
            "warehouse_name": warehouse_name,
            "region": region,
            "country": country,
        },
    )
    return int(result.scalar_one())


def run() -> None:
    database_url = get_required_env("DATABASE_URL")
    months = generate_months_back(int(os.getenv("INVENTORY_SEED_MONTHS", "24")))
    rng = random.Random(42)

    engine = create_engine(database_url, future=True)
    product_ids: dict[str, int] = {}
    warehouse_ids: dict[str, tuple[int, str]] = {}

    with engine.begin() as conn:
        for product in PRODUCTS:
            product_ids[product.sku] = upsert_product(conn, product)

        for warehouse_name, region, country in WAREHOUSES:
            warehouse_id = upsert_warehouse(conn, warehouse_name, region, country)
            warehouse_ids[warehouse_name] = (warehouse_id, region)

        inventory_rows = 0
        sales_rows = 0
        purchase_rows = 0
        lead_rows = 0

        for product in PRODUCTS:
            product_id = product_ids[product.sku]
            for month in months:
                seasonality = 1.0 + 0.12 * ((month.month % 6) / 5.0)
                lead_time_value = max(
                    8.0,
                    product.lead_time_days + rng.uniform(-4.0, 6.0),
                )
                late_rate = max(1.0, min(30.0, 8.0 + rng.uniform(-3.0, 8.0)))

                conn.execute(
                    text(
                        """
                        INSERT INTO supplier_lead_times (
                            product_id, supplier_name, month, average_lead_time_days, late_delivery_rate_percent
                        )
                        VALUES (:product_id, :supplier_name, :month, :average_lead_time_days, :late_delivery_rate_percent)
                        ON CONFLICT (product_id, supplier_name, month) DO UPDATE
                            SET average_lead_time_days = EXCLUDED.average_lead_time_days,
                                late_delivery_rate_percent = EXCLUDED.late_delivery_rate_percent
                        """
                    ),
                    {
                        "product_id": product_id,
                        "supplier_name": product.supplier_name,
                        "month": month,
                        "average_lead_time_days": Decimal(f"{lead_time_value:.2f}"),
                        "late_delivery_rate_percent": Decimal(f"{late_rate:.2f}"),
                    },
                )
                lead_rows += 1

                for warehouse_name, (warehouse_id, region) in warehouse_ids.items():
                    region_factor = REGION_FACTORS[region]
                    demand_noise = rng.uniform(0.88, 1.15)
                    units_sold = max(
                        80.0,
                        product.base_demand_units * region_factor * seasonality * demand_noise,
                    )
                    sell_price = max(15.0, product.base_sell_usd * rng.uniform(0.95, 1.07))
                    unit_cost = max(8.0, product.base_cost_usd * rng.uniform(0.94, 1.08))

                    on_hand_units = units_sold * rng.uniform(1.6, 2.8)
                    reserved_units = on_hand_units * rng.uniform(0.08, 0.2)
                    available_units = max(0.0, on_hand_units - reserved_units)
                    inventory_value = on_hand_units * unit_cost
                    revenue = units_sold * sell_price

                    conn.execute(
                        text(
                            """
                            INSERT INTO inventory_snapshots (
                                product_id, warehouse_id, snapshot_month, on_hand_units, reserved_units,
                                available_units, inventory_value_usd, average_unit_cost_usd
                            )
                            VALUES (
                                :product_id, :warehouse_id, :snapshot_month, :on_hand_units, :reserved_units,
                                :available_units, :inventory_value_usd, :average_unit_cost_usd
                            )
                            ON CONFLICT (product_id, warehouse_id, snapshot_month) DO UPDATE
                                SET on_hand_units = EXCLUDED.on_hand_units,
                                    reserved_units = EXCLUDED.reserved_units,
                                    available_units = EXCLUDED.available_units,
                                    inventory_value_usd = EXCLUDED.inventory_value_usd,
                                    average_unit_cost_usd = EXCLUDED.average_unit_cost_usd
                            """
                        ),
                        {
                            "product_id": product_id,
                            "warehouse_id": warehouse_id,
                            "snapshot_month": month,
                            "on_hand_units": Decimal(f"{on_hand_units:.2f}"),
                            "reserved_units": Decimal(f"{reserved_units:.2f}"),
                            "available_units": Decimal(f"{available_units:.2f}"),
                            "inventory_value_usd": Decimal(f"{inventory_value:.2f}"),
                            "average_unit_cost_usd": Decimal(f"{unit_cost:.4f}"),
                        },
                    )
                    inventory_rows += 1

                    conn.execute(
                        text(
                            """
                            INSERT INTO sales_orders (
                                product_id, warehouse_id, order_month, units_sold, revenue_usd, average_selling_price_usd
                            )
                            VALUES (
                                :product_id, :warehouse_id, :order_month, :units_sold, :revenue_usd, :average_selling_price_usd
                            )
                            ON CONFLICT (product_id, warehouse_id, order_month) DO UPDATE
                                SET units_sold = EXCLUDED.units_sold,
                                    revenue_usd = EXCLUDED.revenue_usd,
                                    average_selling_price_usd = EXCLUDED.average_selling_price_usd
                            """
                        ),
                        {
                            "product_id": product_id,
                            "warehouse_id": warehouse_id,
                            "order_month": month,
                            "units_sold": Decimal(f"{units_sold:.2f}"),
                            "revenue_usd": Decimal(f"{revenue:.2f}"),
                            "average_selling_price_usd": Decimal(f"{sell_price:.4f}"),
                        },
                    )
                    sales_rows += 1

                    units_ordered = units_sold * rng.uniform(0.95, 1.25)
                    expected_receipt = month_shift(month, 1)
                    months_from_now = (
                        (date.today().year - month.year) * 12 + (date.today().month - month.month)
                    )
                    if months_from_now <= 1:
                        received_ratio = rng.uniform(0.2, 0.8)
                        po_status = "open" if received_ratio < 0.45 else "partial"
                    else:
                        received_ratio = rng.uniform(0.88, 1.0)
                        po_status = "received"

                    units_received = units_ordered * received_ratio
                    conn.execute(
                        text(
                            """
                            INSERT INTO purchase_orders (
                                product_id, warehouse_id, supplier_name, order_month, expected_receipt_month,
                                units_ordered, units_received, unit_cost_usd, status
                            )
                            VALUES (
                                :product_id, :warehouse_id, :supplier_name, :order_month, :expected_receipt_month,
                                :units_ordered, :units_received, :unit_cost_usd, :status
                            )
                            ON CONFLICT (product_id, warehouse_id, supplier_name, order_month, expected_receipt_month)
                            DO UPDATE SET
                                units_ordered = EXCLUDED.units_ordered,
                                units_received = EXCLUDED.units_received,
                                unit_cost_usd = EXCLUDED.unit_cost_usd,
                                status = EXCLUDED.status
                            """
                        ),
                        {
                            "product_id": product_id,
                            "warehouse_id": warehouse_id,
                            "supplier_name": product.supplier_name,
                            "order_month": month,
                            "expected_receipt_month": expected_receipt,
                            "units_ordered": Decimal(f"{units_ordered:.2f}"),
                            "units_received": Decimal(f"{units_received:.2f}"),
                            "unit_cost_usd": Decimal(f"{unit_cost:.4f}"),
                            "status": po_status,
                        },
                    )
                    purchase_rows += 1

        print(f"Seed complete. inventory_snapshots upserted: {inventory_rows}")
        print(f"Seed complete. sales_orders upserted: {sales_rows}")
        print(f"Seed complete. purchase_orders upserted: {purchase_rows}")
        print(f"Seed complete. supplier_lead_times upserted: {lead_rows}")


if __name__ == "__main__":
    run()
