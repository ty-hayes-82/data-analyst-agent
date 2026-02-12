# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Pydantic models for structured responses from Order Dispatch Revenue queries.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class TopShipper(BaseModel):
    """Individual shipper with metrics."""
    shipper_code: str = Field(description="Shipper code identifier")
    shipper_name: str = Field(description="Shipper company name")
    total_loaded_miles: float = Field(description="Total loaded miles for this shipper")
    total_revenue: float = Field(description="Total revenue from this shipper")
    order_count: int = Field(description="Number of orders for this shipper")
    avg_revenue_per_order: float = Field(description="Average revenue per order")
    percent_of_total_miles: float = Field(description="Percentage of total miles")


class TopShippersByMilesResponse(BaseModel):
    """Structured response for top shippers by miles query."""
    success: bool = Field(description="Whether the query succeeded")
    period_start: str = Field(description="Start date of the period (YYYY-MM-DD)")
    period_end: str = Field(description="End date of the period (YYYY-MM-DD)")
    cost_center: str = Field(description="Cost center code")
    total_miles: float = Field(description="Total loaded miles for all shippers in period")
    total_revenue: float = Field(description="Total revenue for all orders in period")
    total_orders: int = Field(description="Total number of orders in period")
    top_shippers: List[TopShipper] = Field(description="List of top shippers ranked by miles")
    error_message: Optional[str] = Field(default=None, description="Error message if query failed")


class MonthlyAggregate(BaseModel):
    """Monthly aggregate metrics for a cost center."""
    month: str = Field(description="Month in YYYY-MM format")
    cost_center: str = Field(description="Cost center code")
    cost_center_name: str = Field(description="Cost center name")
    total_loaded_miles: float = Field(description="Total loaded miles for the month")
    total_empty_miles: float = Field(description="Total empty miles for the month")
    total_order_miles: float = Field(description="Total order miles for the month")
    total_stops: int = Field(description="Total number of stops for the month")
    total_revenue: float = Field(description="Total revenue for the month")
    total_lh_revenue: float = Field(description="Total line haul revenue for the month")
    total_fuel_revenue: float = Field(description="Total fuel surcharge revenue for the month")
    total_accessorial_revenue: float = Field(description="Total accessorial revenue for the month")
    order_count: int = Field(description="Number of orders for the month")
    avg_revenue_per_order: float = Field(description="Average revenue per order")


class MonthlyAggregatesResponse(BaseModel):
    """Structured response for monthly aggregates by cost center query."""
    success: bool = Field(description="Whether the query succeeded")
    period_start: str = Field(description="Start date of the period (YYYY-MM-DD)")
    period_end: str = Field(description="End date of the period (YYYY-MM-DD)")
    cost_centers: List[str] = Field(description="List of cost center codes included")
    monthly_data: List[MonthlyAggregate] = Field(description="Monthly aggregate data")
    grand_totals: dict = Field(description="Grand totals across all months and cost centers")
    error_message: Optional[str] = Field(default=None, description="Error message if query failed")

