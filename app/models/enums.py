"""Enumerations partagees entre les modeles SQLModel."""

from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    WFM_ANALYST = "wfm_analyst"
    TEAM_LEAD = "team_lead"
    VIEWER = "viewer"


class Channel(str, Enum):
    VOICE = "voice"
    CHAT = "chat"
    EMAIL = "email"
    BACKOFFICE = "backoffice"


class EmployeeStatus(str, Enum):
    ACTIVE = "active"
    LEAVE = "leave"
    TERMINATED = "terminated"


class ForecastVersionType(str, Enum):
    LTF = "LTF"
    STF = "STF"


class ShrinkageType(str, Enum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"


class PeriodType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ConfigScope(str, Enum):
    GLOBAL = "global"
    CAMPAIGN = "campaign"
    SKILL = "skill"


class AbsenceType(str, Enum):
    """Motifs d'absence longue/courte ayant un impact sur le staffing."""
    MATERNITY = "maternity"
    AVAILABILITY = "availability"
    PAID_LEAVE = "paid_leave"
    UNPAID_LEAVE = "unpaid_leave"
