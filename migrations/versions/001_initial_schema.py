"""Initial schema: all tables

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("state_code", sa.String(2), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("credit_limit", sa.Float, nullable=False, server_default="50000"),
        sa.Column("current_balance", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
    op.create_index("ix_customers_phone", "customers", ["phone"])

    op.create_table(
        "products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("unit", sa.String(50), nullable=False, server_default="piece"),
        sa.Column("hsn_code", sa.String(10), nullable=True),
        sa.Column("default_price", sa.Float, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.create_index("ix_products_hsn_code", "products", ["hsn_code"])

    op.create_table(
        "product_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "alias", name="uq_tenant_alias"),
    )
    op.create_index("ix_product_aliases_tenant_id", "product_aliases", ["tenant_id"])
    op.create_index("ix_product_aliases_product_id", "product_aliases", ["product_id"])
    op.create_index("ix_product_aliases_alias", "product_aliases", ["alias"])

    op.create_table(
        "inventory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Integer, nullable=False, server_default="10"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "product_id", name="uq_tenant_product_inventory"),
    )
    op.create_index("ix_inventory_tenant_id", "inventory", ["tenant_id"])
    op.create_index("ix_inventory_product_id", "inventory", ["product_id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("whatsapp_message_id", sa.String(255), nullable=True, unique=True),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_whatsapp_message_id", "orders", ["whatsapp_message_id"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("raw_product_name", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit", sa.String(50), nullable=False, server_default="piece"),
        sa.Column("unit_price", sa.Float, nullable=False),
        sa.Column("total_price", sa.Float, nullable=False),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("invoice_number", sa.String(50), nullable=False, unique=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("invoice_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("subtotal", sa.Float, nullable=False, server_default="0"),
        sa.Column("cgst_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("sgst_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("igst_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_tax", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("amount_paid", sa.Float, nullable=False, server_default="0"),
        sa.Column("amount_due", sa.Float, nullable=False, server_default="0"),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column("seller_gstin", sa.String(15), nullable=True),
        sa.Column("buyer_gstin", sa.String(15), nullable=True),
        sa.Column("place_of_supply", sa.String(2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"])
    op.create_index("ix_invoices_invoice_number", "invoices", ["invoice_number"])
    op.create_index("ix_invoices_customer_id", "invoices", ["customer_id"])
    op.create_index("ix_invoices_order_id", "invoices", ["order_id"])

    op.create_table(
        "invoice_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("product_id", sa.String(36), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("hsn_code", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("unit_price", sa.Float, nullable=False),
        sa.Column("subtotal", sa.Float, nullable=False),
        sa.Column("gst_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("cgst_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("sgst_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("igst_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("cgst_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("sgst_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("igst_amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_price", sa.Float, nullable=False),
    )
    op.create_index("ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("method", sa.String(20), nullable=False, server_default="cash"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reference_id", sa.String(255), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("payment_date", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"])
    op.create_index("ix_payments_customer_id", "payments", ["customer_id"])
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])

    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("entry_type", sa.String(30), nullable=False),
        sa.Column("reference_id", sa.String(36), nullable=True),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("balance_after", sa.Float, nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_credit_ledger_tenant_id", "credit_ledger", ["tenant_id"])
    op.create_index("ix_credit_ledger_customer_id", "credit_ledger", ["customer_id"])

    op.create_table(
        "hsn_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("hsn_code", sa.String(10), nullable=False, unique=True),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("gst_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_service", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("chapter", sa.String(4), nullable=True),
    )
    op.create_index("ix_hsn_codes_hsn_code", "hsn_codes", ["hsn_code"])


def downgrade() -> None:
    op.drop_table("hsn_codes")
    op.drop_table("credit_ledger")
    op.drop_table("payments")
    op.drop_table("invoice_items")
    op.drop_table("invoices")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("inventory")
    op.drop_table("product_aliases")
    op.drop_table("products")
    op.drop_table("customers")
