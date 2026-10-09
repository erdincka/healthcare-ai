import random
from datetime import datetime, timedelta

import asyncpg
import structlog
from faker import Faker

from llm_output import LlmOutputError, parse_triage_output
from utils import format_exception_details

logger = structlog.get_logger(__name__)
fake = Faker()

# Medical data lists for population
PRIMARY_DIAGNOSES = [
    "Acute infectious gastroenteritis",
    "COPD Exacerbation",
    "Influenza",
    "Diverticulitis",
    "Migraine",
    "Anaphylaxis",
    "Sinusitis",
    "Bacterial Keratitis",
    "Acute Myocardial Infarction",
    "Otitis Media",
    "Muscle Strain",
    "Pneumonia",
    "Urinary Tract Infection",
    "Pneumothorax",
    "Pulmonary Embolism",
    "Heart failure",
    "Viral Infection",
    "Pyelonephritis",
    "Gout",
    "Toxic megacolon",
    "Eosinophilic esophagitis",
    "Facet joint syndrome",
    "Hypertension",
    "Diabetes Type 2",
    "Asthma",
    "Bronchitis",
    "Cellulitis",
    "Gastritis",
    "Kidney stones",
    "Appendicitis",
    "Allergic reaction",
    "Depression",
    "Anxiety disorder",
    "Back pain",
    "Headache",
    "Chest pain",
]

SECONDARY_DIAGNOSES = [
    "Dehydration",
    "Electrolyte imbalance",
    "Possible mild pneumonia",
    "Herniated Disc",
    "Coronary Artery Disease",
    "Elevated Blood Pressure",
    "Dental Abscess",
    "Deformed Nasal Septum",
    "Pleurisy",
    "Hypertension",
    "Diabetes",
    "Obesity",
    "Sleep apnea",
    "Osteoporosis",
    "Arthritis",
    "GERD",
    "Hypothyroidism",
    "Anemia",
    "Chronic kidney disease",
    None,
]

RECOMMENDED_TESTS = [
    "CBC",
    "Chest X-ray",
    "CT scan",
    "MRI",
    "EKG",
    "Echocardiogram",
    "Urinalysis",
    "Blood cultures",
    "Stool sample",
    "Spirometry",
    "Endoscopy with biopsy",
    "Ultrasound",
    "Bone scan",
    "Stress test",
    "Colonoscopy",
    "Mammogram",
    "Pap smear",
    "Thyroid function test",
    "Liver function test",
    "Kidney function test",
    "Blood glucose test",
    "Hemoglobin A1C",
    "Lipid panel",
    "PSA test",
    "Vitamin D test",
    "",
]

RECOMMENDED_TREATMENTS = [
    "Antibiotics",
    "Pain management",
    "Physical therapy",
    "Rest and hydration",
    "Bronchodilators",
    "Corticosteroids",
    "Antihistamines",
    "Insulin therapy",
    "Blood pressure medication",
    "Antidepressants",
    "Anti-inflammatory drugs",
    "Chemotherapy",
    "Radiation therapy",
    "Surgery",
    "Lifestyle modifications",
    "Dietary changes",
    "Exercise program",
    "Counseling",
    "Immunotherapy",
    "Oxygen therapy",
    "Wound care",
    "IV fluids",
    "Monitoring",
]

FOLLOW_UP_OPTIONS = [
    "Regular monitoring of symptoms",
    "Follow up in 1 week",
    "Follow up in 2 weeks",
    "Follow up in 1 month",
    "Follow up in 3 months",
    "Refer to specialist",
    "Monitor vital signs",
    "Lab work follow-up",
    "Imaging follow-up",
    "Emergency follow-up if symptoms worsen",
    "No follow-up needed",
    "Schedule routine check-up",
    "Physical therapy follow-up",
]

SEVERITIES = ["Mild", "Moderate", "Severe", "Critical"]


async def check_database(connection_string: str) -> tuple[bool, str]:
    """Check database connection and presence of 'triage' table."""
    if not connection_string:
        return False, "Database connection string is required."

    try:
        conn = await asyncpg.connect(dsn=connection_string)
        try:
            # Check database accessibility
            version = await conn.fetchval("SELECT version()")

            # Check if 'triage' table exists
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'triage'
                )
            """)
        finally:
            await conn.close()

        if table_exists:
            return (
                True,
                f"Database available: {version[:50]}... (Table 'triage' exists)",
            )
        else:
            return (
                True,
                f"Database available: {version[:50]}... (BUT Table 'triage' NOT found)",
            )

    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("database_check_failed", error=err_detail, exc_info=True)
        return False, f"Database error: {err_detail}"


async def initialize_database(connection_string: str, num_records: int = 200) -> tuple[bool, str]:
    """Create 'triage' table and populate it with sample data."""
    if not connection_string:
        return False, "Database connection string is required."

    try:
        logger.info("initializing_database", num_records=num_records)
        conn = await asyncpg.connect(dsn=connection_string)
        try:
            await _create_and_populate(conn, num_records)
        finally:
            await conn.close()
        return (
            True,
            f"Successfully initialized database with {num_records} sample records.",
        )

    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("database_initialization_failed", error=err_detail, exc_info=True)
        return False, f"Initialization error: {err_detail}"


INSERT_TRIAGE_SQL = """
    INSERT INTO triage (
        patient_name, date_of_birth, visit_time, severity,
        primary_diagnosis, secondary_diagnoses, recommended_tests,
        recommended_treatment, follow_up, medical_reasoning
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    RETURNING id
"""


async def _create_and_populate(conn: asyncpg.Connection, num_records: int) -> None:
    """Create the ``triage`` table if needed and insert ``num_records`` sample rows."""
    # Create table
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS triage (
            id SERIAL PRIMARY KEY,
            patient_name TEXT,
            date_of_birth DATE,
            visit_time TIMESTAMP,
            severity TEXT,
            primary_diagnosis TEXT,
            secondary_diagnoses TEXT,
            recommended_tests TEXT,
            recommended_treatment TEXT,
            follow_up TEXT,
            medical_reasoning TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Populate with sample data
    records = []
    for _ in range(num_records):
        start_date = datetime.now() - timedelta(days=365)
        visit_time = fake.date_time_between(start_date=start_date, end_date=datetime.now())
        birth_date = fake.date_of_birth(minimum_age=18, maximum_age=90)

        records.append(
            (
                fake.name(),
                birth_date,
                visit_time,
                random.choice(SEVERITIES),
                random.choice(PRIMARY_DIAGNOSES),
                random.choice(SECONDARY_DIAGNOSES) or None,
                random.choice(RECOMMENDED_TESTS),
                random.choice(RECOMMENDED_TREATMENTS),
                random.choice(FOLLOW_UP_OPTIONS),
                None,  # medical_reasoning
            )
        )

    await conn.executemany(INSERT_TRIAGE_SQL, records)


async def save_diagnosis_to_db(json_data: str, connection_string: str) -> tuple[bool, str]:
    """Validate a triage record and insert it into the ``triage`` table.

    Args:
        json_data: The analysis as shown in the UI: pretty-printed JSON from the
            model, or raw model output pasted by the user.
        connection_string: PostgreSQL DSN.

    Returns:
        ``(ok, message)`` for the status box.
    """
    if not json_data or not json_data.strip():
        return False, "Please run 'Generate AI Analysis' successfully first."

    if not connection_string:
        return False, "Database connection string is not configured."

    try:
        result = parse_triage_output(json_data)
    except LlmOutputError as exc:
        logger.warning("triage_record_invalid", error=str(exc), length=len(json_data))
        return False, f"Cannot save: {exc}"

    try:
        conn = await asyncpg.connect(dsn=connection_string)
        try:
            record_id = await conn.fetchval(INSERT_TRIAGE_SQL, *result.to_db_row())
        finally:
            await conn.close()
    except Exception as e:
        err_detail = format_exception_details(e)
        logger.error("database_save_failed", error=err_detail, exc_info=True)
        return False, f"Database error: {err_detail}"

    logger.info("triage_saved", record_id=record_id, severity=result.severity.value)
    return True, f"Saved successfully with ID: {record_id}"
