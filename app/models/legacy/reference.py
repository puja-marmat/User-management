"""Reference tables U01 only reads (site list, sub-division tower scope, meter look-ups).

Generated from the `sav_uat` schema script (2026-10-15) and checked by
`tests/test_legacy_models.py` (contract) and `tests/integration/test_legacy_schema.py`
(live INFORMATION_SCHEMA). Table and column names are the legacy names; never emit DDL
for these tables (they are outside Alembic's target metadata).
"""

from datetime import datetime
from decimal import Decimal
import uuid

from sqlalchemy import Integer, SmallInteger
from sqlalchemy.dialects.mssql import BIT, DATETIME, DECIMAL, NVARCHAR, TINYINT, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import LegacyBase


class Site(LegacyBase):
    __tablename__ = "Sites"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column("Name", NVARCHAR(60), nullable=False)
    address: Mapped[str] = mapped_column("Address", NVARCHAR(500), nullable=False)
    head_office: Mapped[str | None] = mapped_column("HeadOffice", NVARCHAR(500), nullable=True)
    phone: Mapped[str | None] = mapped_column("Phone", NVARCHAR(30), nullable=True)
    wire_break_mobile_no: Mapped[str | None] = mapped_column(
        "WireBreakMobileNo", NVARCHAR(30), nullable=True
    )
    service_tax_no: Mapped[str | None] = mapped_column("ServiceTaxNo", NVARCHAR(60), nullable=True)
    faulty_meter_interval: Mapped[int | None] = mapped_column(
        "FaultyMeterInterval", Integer(), nullable=True
    )
    principal_unit: Mapped[int] = mapped_column("PrincipalUnit", Integer(), nullable=False)
    principal_dg_unit: Mapped[int] = mapped_column("PrincipalDGUnit", Integer(), nullable=False)
    dashboard_column: Mapped[int] = mapped_column("DashboardColumn", Integer(), nullable=False)
    logo_name: Mapped[str | None] = mapped_column("LogoName", NVARCHAR(100), nullable=True)
    bill_generation_status_id: Mapped[int] = mapped_column(
        "BillGenerationStatusId", Integer(), nullable=False
    )
    charge_deduction_status_id: Mapped[int] = mapped_column(
        "ChargeDeductionStatusId", Integer(), nullable=False
    )
    alert_sms_status_id: Mapped[int] = mapped_column("AlertSMSStatusId", Integer(), nullable=False)
    alert_email_status_id: Mapped[int] = mapped_column(
        "AlertEmailStatusId", Integer(), nullable=False
    )
    site_status_id: Mapped[int] = mapped_column("SiteStatusId", Integer(), nullable=False)
    allow_disconnect_status_id: Mapped[int] = mapped_column(
        "AllowDisconnectStatusId", Integer(), nullable=False
    )
    unit_type: Mapped[int] = mapped_column("UnitType", Integer(), nullable=False)
    approve_meter_bill_in_hours: Mapped[int | None] = mapped_column(
        "ApproveMeterBillInHours", Integer(), nullable=True
    )
    generate_recharge_company_copy: Mapped[bool] = mapped_column(
        "GenerateRechargeCompanyCopy", BIT(), nullable=False
    )
    bill_prefix: Mapped[str | None] = mapped_column("BillPrefix", NVARCHAR(20), nullable=True)
    billing_max_decimal: Mapped[int] = mapped_column("BillingMaxDecimal", Integer(), nullable=False)
    sms_limit: Mapped[int | None] = mapped_column("SMSLimit", Integer(), nullable=True)
    sms_sent: Mapped[int | None] = mapped_column("SMSSent", Integer(), nullable=True)
    interest_monthly_rate: Mapped[Decimal] = mapped_column(
        "InterestMonthlyRate", DECIMAL(18, 2), nullable=False
    )
    apply_interest_rate_status_id: Mapped[int] = mapped_column(
        "ApplyInterestRateStatusId", Integer(), nullable=False
    )
    gst_amount: Mapped[Decimal] = mapped_column("GSTAmount", DECIMAL(18, 2), nullable=False)
    temp_credit_threshold: Mapped[int | None] = mapped_column(
        "TempCreditThreshold", Integer(), nullable=True
    )
    temp_credit_monthly_change_limit: Mapped[int | None] = mapped_column(
        "TempCreditMonthlyChangeLimit", Integer(), nullable=True
    )
    auto_send_meter_bills_upon_auto_approval: Mapped[bool | None] = mapped_column(
        "AutoSendMeterBillsUponAutoApproval", BIT(), nullable=True
    )
    assign_top_priority_to_faulty_interval: Mapped[bool | None] = mapped_column(
        "AssignTopPriorityToFaultyInterval", BIT(), nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        "CreatedByUserId", Integer(), nullable=True
    )
    created_date: Mapped[datetime] = mapped_column("CreatedDate", DATETIME(), nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        "UpdatedByUserId", Integer(), nullable=True
    )
    updated_date: Mapped[datetime | None] = mapped_column("UpdatedDate", DATETIME(), nullable=True)
    guid: Mapped[uuid.UUID] = mapped_column(
        "Guid", UNIQUEIDENTIFIER(as_uuid=True), nullable=False, default=uuid.uuid4
    )


class Tower(LegacyBase):
    __tablename__ = "Towers"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
    name: Mapped[str | None] = mapped_column("Name", NVARCHAR(100), nullable=True)
    imei: Mapped[str | None] = mapped_column("IMEI", NVARCHAR(20), nullable=True)
    status_id: Mapped[int] = mapped_column("StatusId", Integer(), nullable=False)
    tower_number: Mapped[int | None] = mapped_column("TowerNumber", SmallInteger(), nullable=True)
    last_data_received_on: Mapped[datetime | None] = mapped_column(
        "LastDataReceivedOn", DATETIME(), nullable=True
    )
    wire_break: Mapped[int] = mapped_column("WireBreak", Integer(), nullable=False)
    wire_break_flag_reset_on: Mapped[datetime | None] = mapped_column(
        "WireBreakFlagResetOn", DATETIME(), nullable=True
    )
    primary_phone: Mapped[str | None] = mapped_column("PrimaryPhone", NVARCHAR(50), nullable=True)
    primary_phone_operator: Mapped[str | None] = mapped_column(
        "PrimaryPhoneOperator", NVARCHAR(50), nullable=True
    )
    secondary_phone: Mapped[str | None] = mapped_column(
        "SecondaryPhone", NVARCHAR(50), nullable=True
    )
    secondary_phone_operator: Mapped[str | None] = mapped_column(
        "SecondaryPhoneOperator", NVARCHAR(50), nullable=True
    )
    gateway_no: Mapped[str | None] = mapped_column("GatewayNo", NVARCHAR(), nullable=True)
    user_id: Mapped[int | None] = mapped_column("UserId", Integer(), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        "CreatedByUserId", Integer(), nullable=True
    )
    created_date: Mapped[datetime] = mapped_column("CreatedDate", DATETIME(), nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        "UpdatedByUserId", Integer(), nullable=True
    )
    updated_date: Mapped[datetime | None] = mapped_column("UpdatedDate", DATETIME(), nullable=True)
    guid: Mapped[uuid.UUID] = mapped_column(
        "Guid", UNIQUEIDENTIFIER(as_uuid=True), nullable=False, default=uuid.uuid4
    )


class Meter(LegacyBase):
    __tablename__ = "Meters"
    id: Mapped[int] = mapped_column("Id", Integer(), primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column("SiteId", Integer(), nullable=False)
    meter_type_id: Mapped[int] = mapped_column("MeterTypeId", Integer(), nullable=False)
    tower_id: Mapped[int | None] = mapped_column("TowerId", Integer(), nullable=True)
    meter_no: Mapped[str] = mapped_column("MeterNo", NVARCHAR(9), nullable=False)
    master_meter_grid: Mapped[str | None] = mapped_column(
        "MasterMeterGrid", NVARCHAR(9), nullable=True
    )
    master_meter_dg: Mapped[str | None] = mapped_column("MasterMeterDG", NVARCHAR(9), nullable=True)
    remarks: Mapped[str | None] = mapped_column("Remarks", NVARCHAR(50), nullable=True)
    ctf_factor: Mapped[Decimal] = mapped_column("CTFFactor", DECIMAL(18, 3), nullable=False)
    load_senction_main: Mapped[Decimal] = mapped_column(
        "LoadSenctionMain", DECIMAL(18, 3), nullable=False
    )
    load_senction_dg: Mapped[Decimal] = mapped_column(
        "LoadSenctionDG", DECIMAL(18, 3), nullable=False
    )
    water_charges: Mapped[Decimal] = mapped_column("WaterCharges", DECIMAL(18, 3), nullable=False)
    free_units_main: Mapped[Decimal] = mapped_column(
        "FreeUnitsMain", DECIMAL(18, 3), nullable=False
    )
    free_units_dg: Mapped[Decimal] = mapped_column("FreeUnitsDG", DECIMAL(18, 3), nullable=False)
    sms_warning_amount: Mapped[Decimal] = mapped_column(
        "SMSWarningAmount", DECIMAL(18, 3), nullable=False
    )
    sms_warning1_amount: Mapped[Decimal] = mapped_column(
        "SMSWarning1Amount", DECIMAL(18, 3), nullable=False
    )
    credit_limit: Mapped[int] = mapped_column("CreditLimit", Integer(), nullable=False)
    dg_phase: Mapped[int] = mapped_column("DGPhase", TINYINT(), nullable=False)
    bill_generation_status_id: Mapped[int] = mapped_column(
        "BillGenerationStatusId", Integer(), nullable=False
    )
    charge_deduction_status_id: Mapped[int] = mapped_column(
        "ChargeDeductionStatusId", Integer(), nullable=False
    )
    status_id: Mapped[int] = mapped_column("StatusId", Integer(), nullable=False)
    possession_date: Mapped[datetime] = mapped_column("PossessionDate", DATETIME(), nullable=False)
    field_connected_disconnected: Mapped[int] = mapped_column(
        "FieldConnectedDisconnected", Integer(), nullable=False
    )
    is_disconnected_by_admin: Mapped[bool] = mapped_column(
        "IsDisconnectedByAdmin", BIT(), nullable=False
    )
    unit_name: Mapped[str | None] = mapped_column("UnitName", NVARCHAR(), nullable=True)
    unit_address: Mapped[str | None] = mapped_column("UnitAddress", NVARCHAR(), nullable=True)
    unit_area: Mapped[Decimal] = mapped_column("UnitArea", DECIMAL(18, 3), nullable=False)
    billing_address: Mapped[str | None] = mapped_column("BillingAddress", NVARCHAR(), nullable=True)
    user_id: Mapped[int | None] = mapped_column("UserId", Integer(), nullable=True)
    tenant_user_id: Mapped[int | None] = mapped_column("TenantUserId", Integer(), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(
        "FirmwareVersion", NVARCHAR(20), nullable=True
    )
    status_remark: Mapped[str | None] = mapped_column("StatusRemark", NVARCHAR(100), nullable=True)
    billing_date: Mapped[datetime | None] = mapped_column("BillingDate", DATETIME(), nullable=True)
    visible_on_dashboard: Mapped[bool] = mapped_column("VisibleOnDashboard", BIT(), nullable=False)
    temp_credit_till_date: Mapped[datetime | None] = mapped_column(
        "TempCreditTillDate", DATETIME(), nullable=True
    )
    charge1: Mapped[Decimal | None] = mapped_column("Charge1", DECIMAL(18, 3), nullable=True)
    charge2: Mapped[Decimal | None] = mapped_column("Charge2", DECIMAL(18, 3), nullable=True)
    is_vacant: Mapped[bool] = mapped_column("IsVacant", BIT(), nullable=False)
    is_meter_reset_for_billing_period: Mapped[bool] = mapped_column(
        "IsMeterResetForBillingPeriod", BIT(), nullable=False
    )
    last_meter_reset_on: Mapped[datetime | None] = mapped_column(
        "LastMeterResetOn", DATETIME(), nullable=True
    )
    threshold_value: Mapped[Decimal] = mapped_column(
        "ThresholdValue", DECIMAL(18, 2), nullable=False
    )
    is_installed: Mapped[bool] = mapped_column("IsInstalled", BIT(), nullable=False)
    gstin: Mapped[str | None] = mapped_column("GSTIN", NVARCHAR(), nullable=True)
    meter_ratio: Mapped[Decimal] = mapped_column("MeterRatio", DECIMAL(18, 2), nullable=False)
    meter_serial_no: Mapped[str | None] = mapped_column("MeterSerialNo", NVARCHAR(), nullable=True)
    is_dlms_meter: Mapped[int] = mapped_column("IsDlmsMeter", Integer(), nullable=False)
    is_master_reset: Mapped[int] = mapped_column("IsMasterReset", Integer(), nullable=False)
    master_reset_on: Mapped[datetime | None] = mapped_column(
        "MasterResetOn", DATETIME(), nullable=True
    )
    default_address: Mapped[int] = mapped_column("DefaultAddress", Integer(), nullable=False)
    meter_load_type_id: Mapped[int] = mapped_column("MeterLoadTypeId", Integer(), nullable=False)
    meter_status: Mapped[int] = mapped_column("MeterStatus", Integer(), nullable=False)
    solar_meter_no: Mapped[str | None] = mapped_column("SolarMeterNo", NVARCHAR(), nullable=True)
    custom_bill_setup_id: Mapped[int | None] = mapped_column(
        "CustomBillSetupId", Integer(), nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        "CreatedByUserId", Integer(), nullable=True
    )
    created_date: Mapped[datetime] = mapped_column("CreatedDate", DATETIME(), nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        "UpdatedByUserId", Integer(), nullable=True
    )
    updated_date: Mapped[datetime | None] = mapped_column("UpdatedDate", DATETIME(), nullable=True)
    guid: Mapped[uuid.UUID] = mapped_column(
        "Guid", UNIQUEIDENTIFIER(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    meter_prefix: Mapped[str | None] = mapped_column("MeterPrefix", NVARCHAR(20), nullable=True)
