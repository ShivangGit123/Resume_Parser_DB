import streamlit as st
import os
import json
import fitz 
import mysql.connector
from groq import Groq
from pydantic import BaseModel, Field
from typing import List, Optional

# --- 1. Pydantic Schema and Scoring Logic ---

GROQ_MODEL = "llama-3.1-8b-instant"
TABLE_NAME = "parsed_resumes"
LOGS_TABLE_NAME = "parsing_logs" # Added for completeness

class ResumeData(BaseModel):
    """Schema for structured data extraction from a resume."""
    name: str = Field(description="Full name of the candidate.")
    email: str = Field(description="Primary email address.")
    phone: Optional[str] = Field(description="Primary phone number, if available.")
    total_years_experience: float = Field(
        description="Total professional experience in years (e.g., 5.5). Default to 0.0 if not found."
    )
    highest_degree: str = Field(
        description="The highest academic degree achieved (e.g., 'M.S. in CS', 'B.Tech in ECE')."
    )
    skills_list: List[str] = Field(description="A list of technical and soft skills.")

def calculate_resume_score(parsed_data: ResumeData, required_skills: List[str]) -> float:
    """Calculates a numerical score based on predefined criteria."""
    
    score = 0.0
    
    # 1. Skill Match (40 points max)
    # Avoid DivisionByZeroError if no required skills are entered
    if required_skills:
        skill_points_per_match = 40 / len(required_skills)
        skill_match_score = 0
        
        parsed_skills_lower = [s.lower().strip() for s in parsed_data.skills_list]
        
        for skill in required_skills:
            if any(skill.lower() == s for s in parsed_skills_lower):
                skill_match_score += skill_points_per_match
                
        score += min(skill_match_score, 40)
    
    # 2. Experience Match (30 points max)
    target_experience = 5.0
    experience_weight = 30.0
    if parsed_data.total_years_experience >= target_experience:
        score += experience_weight
    else:
        score += (parsed_data.total_years_experience / target_experience) * (experience_weight * 0.8)

    # 3. Education Bonus (20 points max)
    education_score = 0
    if any(deg in parsed_data.highest_degree for deg in ['Master', 'M.S.', 'MS', 'MBA', 'PhD', 'Ph.D.']):
        education_score = 20
    elif 'Bachelor' in parsed_data.highest_degree or 'B.S.' in parsed_data.highest_degree or 'B.Tech' in parsed_data.highest_degree:
        education_score = 10
    score += education_score

    # 4. Data Quality/Completeness (10 points max)
    completeness_score = 0
    if parsed_data.name: completeness_score += 3
    if parsed_data.email: completeness_score += 3
    if parsed_data.phone: completeness_score += 2
    if parsed_data.total_years_experience > 0.0: completeness_score += 2
    score += completeness_score
    
    final_score = min(score, 100.0)
    return round(final_score, 2)


# --- 2. Utility Functions (Database & LLM) ---

@st.cache_data
def extract_text_from_pdf(uploaded_file):
    """Extracts text from a Streamlit uploaded PDF file."""
    try:
        # Read the file content into memory
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    except Exception as e:
        st.error(f"Error extracting text from PDF: {e}")
        return ""

@st.cache_resource
def get_groq_client(api_key):
    """Initializes and caches the Groq client."""
    if not api_key:
        return None
    try:
        return Groq(api_key=api_key)
    except Exception as e:
        st.error(f"Groq Client Error: {e}")
        return None

def parse_resume_with_llm(client: Groq, resume_text: str):
    """Uses Groq's LLM to parse raw resume text into structured JSON."""
    
    JSON_SCHEMA_INSTRUCTIONS = ResumeData.model_json_schema()
    
    system_prompt = (
        "You are an expert resume parsing engine. Your task is to extract all requested fields "
        "from the provided resume text into a perfectly valid JSON object that strictly adheres to the schema."
        "Do not include any text outside the JSON block."
    )
    
    # Use Pydantic's schema for better reliability
    user_prompt = f"Parse the following resume text into a JSON object strictly following this schema: {json.dumps(JSON_SCHEMA_INSTRUCTIONS)}\n\n**Resume Text to Parse:**\n\n{resume_text}"

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model=GROQ_MODEL,
            # Correct argument: Use response_format for JSON output
            response_format={"type": "json_object"} 
        )
        
        # The response content is a JSON string
        json_content = chat_completion.choices[0].message.content
        return json.loads(json_content)
        
    except Exception as e:
        st.error(f"Error during LLM parsing or JSON decoding. Raw Error: {e}")
        return None

# NEW FUNCTION: Initialize Database and Tables
@st.cache_resource
def initialize_database(db_config: dict):
    """Checks for the DB and table, creating them if they don't exist."""
    
    # 1. Connect without specifying the DB name (to create it if needed)
    try:
        # Temporarily remove 'database' key for initial connection
        temp_config = db_config.copy()
        db_name = temp_config.pop("database") 
        conn = mysql.connector.connect(**temp_config)
        cursor = conn.cursor()
        
        st.info(f"Checking for database: **{db_name}**...")
        
        # 2. Create Database if it doesn't exist
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        
        # 3. Switch to the newly created/existing database
        cursor.execute(f"USE {db_name}")
        
        # 4. Create the main table
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            filename VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL, 
            phone VARCHAR(50),
            total_years_experience DECIMAL(4, 2),
            highest_degree VARCHAR(100),
            skills JSON,
            job_description TEXT,
            score DECIMAL(5, 2),
            parsing_date DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        """
        cursor.execute(create_table_sql)

        st.success(f"Database **'{db_name}'** and table **'{TABLE_NAME}'** confirmed/created.")
        
    except mysql.connector.Error as err:
        st.error(f"❌ **FATAL DB Initialization Error:** Check Host/User/Password. Error: {err}")
        return False
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
    return True


def store_in_mysql(filename: str, parsed_data: ResumeData, job_description: str, score: float, db_config: dict):
    """Connects to MySQL and inserts the parsed data."""
    conn = None
    try:
        # Connect using the full config now that the DB/Table are confirmed
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        sql = f"""
        INSERT INTO {TABLE_NAME} 
        (filename, name, email, phone, total_years_experience, highest_degree, skills, job_description, score) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        data = (
            filename,
            parsed_data.name,
            parsed_data.email,
            parsed_data.phone,
            parsed_data.total_years_experience,
            parsed_data.highest_degree,
            json.dumps(parsed_data.skills_list),
            job_description,
            score
        )
        
        cursor.execute(sql, data)
        conn.commit()
        st.success(f"**✅ Database Save:** Data for **{filename}** stored with score **{score}**.")
        
    except mysql.connector.Error as err:
        st.error(f"❌ **MySQL Save Error:** Could not save data. Error: {err}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


# --- 3. Streamlit Interface ---

st.set_page_config(page_title="⚡ LLM Resume Scorer (Groq + MySQL)", layout="wide")

st.title("⚡ LLM-Powered Resume Scorer")
st.markdown("Upload a PDF resume and a job description to get an **instant, LLM-based compatibility score**.")

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("🔑 Configuration")
    groq_api_key = st.text_input("Groq API Key", type="password")
    
    st.subheader("⚙️ MySQL Database Settings")
    st.warning("Ensure the MySQL server is running and accessible.")
    db_host = st.text_input("Host", "localhost")
    db_user = st.text_input("User", "root") # Default MySQL User
    db_password = st.text_input("Password", type="password") # Must be provided
    db_name = st.text_input("Database Name", "resume_parser_db")

    db_config = {
        "host": db_host,
        "user": db_user,
        "password": db_password,
        "database": db_name
    }
    
    # Initialize the database immediately upon connecting/reloading
    if st.button("Initialize/Check Database Connection"):
        if initialize_database(db_config):
            st.success("Database connection successful and schema is ready!")
        else:
            st.error("Database initialization failed. Check credentials and server status.")

st.markdown("---")

# --- Main Content ---
col1, col2 = st.columns(2)

with col1:
    uploaded_file = st.file_uploader(
        "**Upload Resume (PDF only)**", 
        type=["pdf"], 
        help="Upload the candidate's PDF resume."
    )

with col2:
    job_description = st.text_area(
        "**Paste Target Job Description (JD)**", 
        height=200,
        value="Senior Python Developer with 5+ years of experience. Must have deep expertise in Python, Django, AWS, and MySQL. A Master's degree is highly preferred.",
        help="The scoring algorithm will compare the resume against this job description."
    )
    
    required_skills_input = st.text_input(
        "**Key Skills for Scoring (Comma-separated)**",
        "Python, Django, AWS, MySQL, REST API",
        help="These are the critical skills used to calculate the Skill Match score."
    )
    required_skills = [s.strip() for s in required_skills_input.split(',') if s.strip()]


st.markdown("---")

if st.button("🚀 **Analyze & Score Resume**", type="primary", use_container_width=True):
    if not groq_api_key:
        st.error("Please enter your Groq API Key in the sidebar to proceed.")
    elif not uploaded_file:
        st.warning("Please upload a PDF resume.")
    elif not required_skills:
        st.warning("Please specify at least one key skill for accurate scoring.")
    elif not initialize_database(db_config): # Check DB again before running the main logic
         st.error("Database connection failed. Cannot proceed with analysis.")
    else:
        # Use a Streamlit spinner for visual feedback
        with st.spinner('Parsing resume with Groq and calculating score...'):
            
            # 1. Get Groq client
            groq_client = get_groq_client(groq_api_key)
            if not groq_client:
                st.stop()
            
            # 2. Extraction
            raw_text = extract_text_from_pdf(uploaded_file)
            
            # 3. LLM Parsing
            parsed_json = parse_resume_with_llm(groq_client, raw_text)
            
            if not parsed_json:
                st.error("LLM failed to produce valid data. Please try another resume.")
                st.stop()
            
            # 4. Validation and Scoring
            try:
                parsed_data = ResumeData.model_validate(parsed_json)
                final_score = calculate_resume_score(parsed_data, required_skills)
            except Exception as e:
                st.error(f"Data validation error (Pydantic): The LLM output did not match the required schema. Error: {e}")
                st.json(parsed_json) # Show the raw LLM output for debugging
                st.stop()
            
            # 5. Display Results
            st.success("✅ Analysis Complete!")
            
            score_col, name_col, email_col = st.columns(3)
            with score_col:
                st.metric(label="🎯 **Final Compatibility Score**", value=f"{final_score} / 100")
            with name_col:
                st.metric(label="👤 **Candidate Name**", value=parsed_data.name)
            with email_col:
                st.metric(label="📧 **Email**", value=parsed_data.email)

            st.markdown("### 📋 Extracted Details")
            
            # Display Extracted Fields
            data_summary = {
                "Phone": parsed_data.phone or "N/A",
                "Years Experience": parsed_data.total_years_experience,
                "Highest Degree": parsed_data.highest_degree,
                "Skills Found": ", ".join(parsed_data.skills_list)
            }
            st.json(data_summary)
            
            # 6. Database Storage
            store_in_mysql(uploaded_file.name, parsed_data, job_description, final_score, db_config)

st.sidebar.markdown("---")
st.sidebar.markdown("### How to Run This App")
st.sidebar.markdown(
    """
    1. **Install Dependencies:** `pip install streamlit groq pydantic PyMuPDF mysql-connector-python`
    2. **Start MySQL Server:** Ensure your local or remote MySQL server is running.
    3. **Run:** `streamlit run app.py` (or whatever you name your file)
    """
)
