import uuid
from sqlalchemy import String, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class HSNCode(Base):
    """HSN code to GST rate mapping for automatic tax calculation."""

    __tablename__ = "hsn_codes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    hsn_code: Mapped[str] = mapped_column(
        String(10), nullable=False, unique=True, index=True
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    gst_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # For goods: CGST = SGST = gst_rate / 2, IGST = gst_rate
    is_service: Mapped[bool] = mapped_column(default=False)
    chapter: Mapped[str | None] = mapped_column(String(4), nullable=True)
