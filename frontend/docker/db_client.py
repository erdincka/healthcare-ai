import asyncpg
import json
import random
import structlog
from datetime import datetime, timedelta
from typing import Tuple, List, Optional
from faker import Faker
from utils import to_str

logger = structlog.get_logger(__name__)
fake = Faker()

# Medical data lists for population
PRIMARY_DIAGNOSES = [
    'Acute infectious gastroenteritis', 'COPD Exacerbation', 'Influenza', 
    'Diverticulitis', 'Migraine', 'Anaphylaxis', 'Sinusitis', 
    'Bacterial Keratitis', 'Acute Myocardial Infarction', 'Otitis Media',
    'Muscle Strain', 'Pneumonia', 'Urinary Tract Infection', 'Pneumothorax',
    'Pulmonary Embolism', 'Heart failure', 'Viral Infection', 'Pyelonephritis',
    'Gout', 'Toxic megacolon', 'Eosinophilic esophagitis', 'Facet joint syndrome',
    'Hypertension', 'Diabetes Type 2', 'Asthma', 'Bronchitis', 'Cellulitis',
    'Gastritis', 'Kidney stones', 'Appendicitis', 'Allergic reaction',
    'Depression', 'Anxiety disorder', 'Back pain', 'Headache', 'Chest pain'
]

SECONDARY_DIAGNOSES = [
    'Dehydration', 'Electrolyte imbalance', 'Possible mild pneumonia',
    'Herniated Disc', 'Coronary Artery Disease', 'Elevated Blood Pressure',
    'Dental Abscess', 'Deformed Nasal Septum', 'Pleurisy', 'Hypertension',
    'Diabetes', 'Obesity', 'Sleep apnea', 'Osteoporosis', 'Arthritis',
    'GERD', 'Hypothyroidism', 'Anemia', 'Chronic kidney disease', None
]

RECOMMENDED_TESTS = [
    'CBC', 'Chest X-ray', 'CT scan', 'MRI', 'EKG', 'Echocardiogram',
    'Urinalysis', 'Blood cultures', 'Stool sample', 'Spirometry',
    'Endoscopy with biopsy', 'Ultrasound', 'Bone scan', 'Stress test',
    'Colonoscopy', 'Mammogram', 'Pap smear', 'Thyroid function test',
    'Liver function test', 'Kidney function test', 'Blood glucose test',
    'Hemoglobin A1C', 'Lipid panel', 'PSA test', 'Vitamin D test', ''
]

RECOMMENDED_TREATMENTS = [
    'Antibiotics', 'Pain management', 'Physical therapy', 'Rest and hydration',
    'Bronchodilators', 'Corticosteroids', 'Antihistamines', 'Insulin therapy',
    'Blood pressure medication', 'Antidepressants', 'Anti-inflammatory drugs',
    'Chemotherapy', 'Radiation therapy', 'Surgery', 'Lifestyle modifications',
    'Dietary changes', 'Exercise program', 'Counseling', 'Immunotherapy',
    'Oxygen therapy', 'Wound care', 'IV fluids', 'Monitoring'
]

FOLLOW_UP_OPTIONS = [
    'Regular monitoring of symptoms', 'Follow up in 1 week', 'Follow up in 2 weeks',
    'Follow up in 1 month', 'Follow up in 3 months', 'Refer to specialist',
    'Monitor vital signs', 'Lab work follow-up', 'Imaging follow-up',
    'Emergency follow-up if symptoms worsen', 'No follow-up needed',
    'Schedule routine check-up', 'Physical therapy follow-up'
]

SEVERITIES = ['Mild', 'Moderate', 'Severe', 'Critical']

async def check_database(connection_string: str) -> Tuple[bool, str]:
    """Check database connection and presence of 'triage' table."""
    if not connection_string:
        return False, "Database connection string is required."
    
    try:
        conn = await asyncpg.connect(dsn=connection_string)
        # Check database accessibility
        version = await conn.fetchval('SELECT version()')
        
        # Check if 'triage' table exists
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'triage'
            )
        """)
        
        await conn.close()
        
        if table_exists:
            return True, f"Database available: {version[:50]}... (Table 'triage' exists)"
        else:
            return True, f"Database available: {version[:50]}... (BUT Table 'triage' NOT found)"
            
    except Exception as e:
        logger.error("database_check_failed", error=str(e))
        return False, f"Database error: {str(e)}"

async def initialize_database(connection_string: str, num_records: int = 200) -> Tuple[bool, str]:
    """Create 'triage' table and populate it with sample data."""
    if not connection_string:
        return False, "Database connection string is required."
    
    try:
        conn = await asyncpg.connect(dsn=connection_string)
        
        logger.info("initializing_database", num_records=num_records)
        
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
            
            records.append((
                fake.name(),
                birth_date,
                visit_time,
                random.choice(SEVERITIES),
                random.choice(PRIMARY_DIAGNOSES),
                random.choice(SECONDARY_DIAGNOSES) or None,
                random.choice(RECOMMENDED_TESTS),
                random.choice(RECOMMENDED_TREATMENTS),
                random.choice(FOLLOW_UP_OPTIONS),
                None # medical_reasoning
            ))
            
        await conn.executemany("""
            INSERT INTO triage (
                patient_name, date_of_birth, visit_time, severity, 
                primary_diagnosis, secondary_diagnoses, recommended_tests, 
                recommended_treatment, follow_up, medical_reasoning
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """, records)
        
        await conn.close()
        return True, f"Successfully initialized database with {num_records} sample records."
        
    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))
        return False, f"Initialization error: {str(e)}"

async def save_diagnosis_to_db(json_data: str, connection_string: str) -> Tuple[bool, str]:
    """Save diagnosis data to PostgreSQL database using asyncpg."""
    if not json_data or json_data.strip() == "" or json_data in ["No JSON found", "Invalid JSON"] or json_data.startswith("Error:"):
        return False, "Please run 'Generate AI Analysis' successfully first."
    
    if not connection_string:
        return False, "Database connection string is not configured."

    try:
        # Robust JSON extraction
        clean_json = json_data.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[-1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[-1].split("```")[0].strip()
            
        diagnosis_data = json.loads(clean_json)
        conn = await asyncpg.connect(dsn=connection_string)
        
        sql = """
        INSERT INTO triage (
            patient_name, date_of_birth, visit_time, severity, 
            primary_diagnosis, secondary_diagnoses, recommended_tests, 
            recommended_treatment, follow_up, medical_reasoning
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """
        
        # Date/Time parsing
        dob_raw = diagnosis_data.get("date_of_birth")
        dob = None
        if dob_raw:
            try:
                dob = datetime.strptime(dob_raw, "%Y-%m-%d").date()
            except ValueError:
                logger.warning("invalid_dob_format", value=dob_raw)
        
        vt_raw = diagnosis_data.get("visit_time")
        vt = None
        if vt_raw:
            try:
                vt = datetime.strptime(vt_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try: 
                    vt = datetime.strptime(vt_raw, "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    logger.warning("invalid_visit_time_format", value=vt_raw)

        record_id = await conn.fetchval(sql, 
            to_str(diagnosis_data.get("patient_name")),
            dob,
            vt,
            to_str(diagnosis_data.get("severity")),
            to_str(diagnosis_data.get("primary_diagnosis")),
            to_str(diagnosis_data.get("secondary_diagnoses")),
            to_str(diagnosis_data.get("recommended_tests")),
            to_str(diagnosis_data.get("recommended_treatment")),
            to_str(diagnosis_data.get("follow_up")),
            to_str(diagnosis_data.get("medical_reasoning"))
        )
        
        await conn.close()
        return True, f"Saved successfully with ID: {record_id}"
    
    except json.JSONDecodeError as jde:
        logger.error("json_parsing_failed", error=str(jde), data_snippet=json_data[:100])
        return False, f"Data format error: AI results must be valid JSON. (Error: {str(jde)})"
    except Exception as e:
        logger.error("database_save_failed", error=str(e))
        return False, f"Database error: {str(e)}"
