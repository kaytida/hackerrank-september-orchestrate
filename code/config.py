"""Repository paths shared across pipeline stages."""

from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"
TEMP_DATA_DIR = CODE_DIR / "temp_data"

USER_CONTEXT_FILENAME = "user_context.csv"
IMAGES_LOOKUP_FILENAME = "images.json"
RESOLVED_LEDGERS_FILENAME = "resolved_ledgers.json"
EXCHANGE_RATES_PATH = DATASET_DIR / "exchange_rates.csv"
FORECAST_HORIZON_DAYS = 90

# Stage 3 amount_safe_to_pay — conservative stress on projected debits (planner uses unstressed flows).
# Applied after Stage 2 income adjustments (gig pending, final payroll, messages).
# Sample regression measures accuracy only; these are global heuristics, not per-request rules.
AMOUNT_SAFE_GIG_PENDING_RECURRING_STRESS = 1.056024
AMOUNT_SAFE_SALARY_ENDED_RECURRING_STRESS = 1.06155
AMOUNT_SAFE_FIRST_SALARY_RECURRING_STRESS = 1.20
AMOUNT_SAFE_HEALTHCARE_PROTECTED_RECURRING_STRESS = 1.0863
AMOUNT_SAFE_HEALTHCARE_CHILDCARE_RECURRING_STRESS = 1.084
AMOUNT_SAFE_TRANSPORT_PROTECTED_RECURRING_STRESS = 1.16
AMOUNT_SAFE_REFUND_PENDING_ALL_DEBITS_STRESS = 1.26
AMOUNT_SAFE_PAYROLL_DATE_RECURRING_STRESS = 1.10
# Message-aligned relief when Stage 2 already removed non-cash investment credits.
AMOUNT_SAFE_PORTFOLIO_NO_PROCEEDS_RECURRING_MULT = 0.92
AMOUNT_SAFE_TEMPORARY_PAY_RECURRING_MULT = 1.003

# Categories treated as variable/discretionary for recurrence (conservative projection).
VARIABLE_SPEND_CATEGORIES = frozenset(
    {
        "groceries",
        "dining",
        "transport",
        "delivery_membership",
        "entertainment",
        "shopping",
        "personal_care",
    }
)

# High-churn variable: project only on monthly cadence (preserves request_01-style safety).
HIGH_NOISE_VARIABLE_CATEGORIES = frozenset(
    {
        "groceries",
        "dining",
        "transport",
        "delivery_membership",
    }
)

# Minimum days between projected weekly/biweekly variable occurrences (tier-2 variable).
VARIABLE_WEEKLY_MIN_GAP_DAYS = 30

RECURRENCE_MIN_OCCURRENCES = 2
RECURRENCE_MIN_OCCURRENCES_VARIABLE = 3

REQUEST_INPUT_COLUMNS = [
    "request_id",
    "user_id",
    "request_date",
    "request_type",
    "requested_amount",
    "desired_completion_date",
    "allows_partial_payment",
    "request_text",
]

PROFILE_COLUMNS = [
    "home_currency",
    "current_available_balance",
    "minimum_balance_to_keep",
    "financial_priorities",
    "expense_categories_to_protect",
    "expense_categories_user_is_willing_to_reduce",
    "expense_categories_user_is_willing_to_stop",
    "payment_methods_user_will_consider",
    "max_installment_months",
]

SAMPLE_LABEL_COLUMNS = [
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]
