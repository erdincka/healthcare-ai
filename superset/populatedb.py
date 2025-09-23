import pymysql
import random
from datetime import datetime, timedelta
from faker import Faker

# Initialize Faker
fake = Faker()

# Database connection parameters
DB_CONFIG = {
    'host': '10.0.31.73',
    'user': 'root',
    'password': 'Compaq1!',
    'database': 'triageai',
    'charset': 'utf8mb4'
}

# Medical data lists
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

def generate_patient_data():
    """Generate random patient data"""
    
    # Generate random visit date within the last 12 months
    start_date = datetime.now() - timedelta(days=365)
    end_date = datetime.now()
    visit_date = fake.date_time_between(start_date=start_date, end_date=end_date)
    
    # Generate random birth date (ages 18-90)
    birth_date = fake.date_of_birth(minimum_age=18, maximum_age=90)
    
    # Generate patient data
    patient_data = {
        'patient_name': fake.name(),
        'date_of_birth': birth_date,
        'visit_time': visit_date,
        'severity': random.choice(SEVERITIES),
        'primary_diagnosis': random.choice(PRIMARY_DIAGNOSES),
        'secondary_diagnoses': random.choice(SECONDARY_DIAGNOSES),
        'recommended_tests': random.choice(RECOMMENDED_TESTS),
        'recommended_treatment': random.choice(RECOMMENDED_TREATMENTS),
        'follow_up': random.choice(FOLLOW_UP_OPTIONS),
        'medical_reasoning': None  # As per your original data
    }
    
    return patient_data

def create_table_if_not_exists(cursor):
    """Create the triage table if it doesn't exist"""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS triage (
        id INT AUTO_INCREMENT PRIMARY KEY,
        patient_name VARCHAR(255),
        date_of_birth DATE,
        visit_time DATETIME,
        severity VARCHAR(50),
        primary_diagnosis VARCHAR(255),
        secondary_diagnoses VARCHAR(255),
        recommended_tests VARCHAR(255),
        recommended_treatment TEXT,
        follow_up TEXT,
        medical_reasoning TEXT
    )
    """
    cursor.execute(create_table_query)

def insert_patient_records(num_records=200):
    """Insert patient records into the database"""
    
    try:
        # Connect to database
        connection = pymysql.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        print(f"Connected to database: {DB_CONFIG['database']}")
        
        # Create table if it doesn't exist
        create_table_if_not_exists(cursor)
        
        # Insert query
        insert_query = """
        INSERT INTO triage (
            patient_name, date_of_birth, visit_time, severity, 
            primary_diagnosis, secondary_diagnoses, recommended_tests, 
            recommended_treatment, follow_up, medical_reasoning
        ) VALUES (
            %(patient_name)s, %(date_of_birth)s, %(visit_time)s, %(severity)s,
            %(primary_diagnosis)s, %(secondary_diagnoses)s, %(recommended_tests)s,
            %(recommended_treatment)s, %(follow_up)s, %(medical_reasoning)s
        )
        """
        
        # Generate and insert records
        records_inserted = 0
        for i in range(num_records):
            try:
                patient_data = generate_patient_data()
                cursor.execute(insert_query, patient_data)
                records_inserted += 1
                
                if records_inserted % 50 == 0:
                    print(f"Inserted {records_inserted} records...")
                    
            except Exception as e:
                print(f"Error inserting record {i+1}: {e}")
        
        # Commit changes
        connection.commit()
        print(f"\nSuccessfully inserted {records_inserted} patient records!")
        
        # Show sample of inserted data
        cursor.execute("SELECT COUNT(*) FROM triage")
        total_count = cursor.fetchone()[0]
        print(f"Total records in triage table: {total_count}")
        
        # Show severity distribution
        cursor.execute("""
            SELECT severity, COUNT(*) as count 
            FROM triage 
            GROUP BY severity 
            ORDER BY count DESC
        """)
        severity_counts = cursor.fetchall()
        print("\nSeverity distribution:")
        for severity, count in severity_counts:
            print(f"  {severity}: {count}")
            
    except pymysql.Error as e:
        print(f"Database error: {e}")
        
    except Exception as e:
        print(f"Error: {e}")
        
    finally:
        if 'connection' in locals():
            cursor.close()
            connection.close()
            print("\nDatabase connection closed.")

if __name__ == "__main__":
    print("Generating 200 dummy medical records...")
    print("=" * 50)
    
    # Install required packages if needed
    try:
        import pymysql
        import faker
    except ImportError:
        print("Required packages not found. Install with:")
        print("pip install pymysql faker")
        exit(1)
    
    insert_patient_records(200)
    
    print("\nScript completed successfully!")
    print("You can now use this data in Apache Superset for your dashboard.")
