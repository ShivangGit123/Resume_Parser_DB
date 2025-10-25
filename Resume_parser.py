import streamlit as st
import os
import json
import fitz  # PyMuPDF
import mysql.connector
from groq import Groq
from pydantic import BaseModel, Field
from typing import List, Optional

# --- 1. Pydantic Schema and Scoring Logic (From previous response) ---

GROQ_MODEL = "llama-3.1-8b-instant"

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


# --- 2. Utility Functions (Adapted for Streamlit) ---

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
    """
    Uses Groq's LLM to parse raw resume text into structured JSON.
    
    Correction: Replaces 'response_json_schema' with 'response_format' and 
    integrates schema instructions into the prompt.
    """
    
    # 1. Define the required JSON structure directly in the prompt
    JSON_SCHEMA_INSTRUCTIONS = """
    You must respond ONLY with a single JSON object that strictly adheres to the following structure:
    {
      "name": "string",
      "email": "string",
      "phone": "string (or null if not found)",
      "total_years_experience": "number (in years, e.g., 5.5. Use 0.0 if not found)",
      "highest_degree": "string (e.g., 'M.S. in CS', 'B.Tech in ECE')",
      "skills_list": "array of strings (e.g., ['Python', 'SQL', 'AWS'])"
    }
    """
    
    system_prompt = (
        "You are an expert resume parsing engine. Your task is to extract all requested fields "
        "from the provided resume text into a perfectly valid JSON object. "
        "Strictly adhere to the JSON format provided below. Do not include any text outside the JSON block."
    )
    
    user_prompt = f"{JSON_SCHEMA_INSTRUCTIONS}\n\n**Resume Text to Parse:**\n\n{resume_text}"

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model=GROQ_MODEL,
            # CORRECT ARGUMENT: Use response_format for JSON output
            response_format={"type": "json_object"} 
        )
        
        # The response content is a JSON string
        json_content = chat_completion.choices[0].message.content
        return json.loads(json_content)
        
    except Exception as e:
        # Note: If the LLM generates invalid JSON, json.loads() will raise an error here.
        st.error(f"Error during LLM parsing or JSON decoding: {e}")
        return None
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Parse the following resume text:\n\n{resume_text}"}
            ],
            model=GROQ_MODEL,
            response_format={"type": "json_object"},
            response_json_schema=ResumeData.model_json_schema()
        )
        
        json_content = chat_completion.choices[0].message.content
        return json.loads(json_content)
        
    except Exception as e:
        st.error(f"Error during LLM parsing: {e}")
        return None

def store_in_mysql(filename: str, parsed_data: ResumeData, job_description: str, score: float, db_config: dict):
    """Connects to MySQL and inserts the parsed data."""
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        sql = """
        INSERT INTO parsed_resumes 
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
        st.error(f"❌ **MySQL Database Error:** Could not save data. Please check connection details. Error: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
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
    db_host = st.text_input("Host", "localhost")
    db_user = st.text_input("User", "your_mysql_user") # CHANGE THIS
    db_password = st.text_input("Password", "your_mysql_password", type="password") # CHANGE THIS
    db_name = st.text_input("Database Name", "resume_parser_db")

    db_config = {
        "host": db_host,
        "user": db_user,
        "password": db_password,
        "database": db_name
    }
    
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
        "Python, Django, AWS, MySQL, PostgreSQL, REST API",
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
    else:
        # Use a Streamlit spinner for visual feedback
        with st.spinner('Parsing resume with Groq and calculating score...'):
            
            # Get Groq client
            groq_client = get_groq_client(groq_api_key)
            if not groq_client:
                st.stop()
            
            # 1. Extraction
            raw_text = extract_text_from_pdf(uploaded_file)
            
            # 2. LLM Parsing
            parsed_json = parse_resume_with_llm(groq_client, raw_text)
            
            if not parsed_json:
                st.error("LLM failed to produce valid data. Please try another resume.")
                st.stop()
            
            # 3. Validation and Scoring
            try:
                parsed_data = ResumeData.model_validate(parsed_json)
                final_score = calculate_resume_score(parsed_data, required_skills)
            except Exception as e:
                st.error(f"Data validation error: {e}")
                st.json(parsed_json) # Show the raw LLM output for debugging
                st.stop()
            
            # 4. Display Results
            st.success("✅ Analysis Complete!")
            
            score_col, name_col, email_col = st.columns(3)
            with score_col:
                st.metric(label="🎯 **Final Compatibility Score**", value=f"{final_score} / 100")
            with name_col:
                st.metric(label="👤 **Candidate Name**", value=parsed_data.name)
            with email_col:
                st.metric(label="📧 **Email**", value=parsed_data.email)

            st.markdown("### 📋 Extracted Details")
            
            # Display Extracted Fields in a table or structured format
            data_summary = {
                "Phone": parsed_data.phone or "N/A",
                "Years Experience": parsed_data.total_years_experience,
                "Highest Degree": parsed_data.highest_degree,
                "Skills Found": ", ".join(parsed_data.skills_list)
            }
            st.json(data_summary)
            
            # 5. Database Storage
            store_in_mysql(uploaded_file.name, parsed_data, job_description, final_score, db_config)

# --- Instructions to Run ---

st.sidebar.markdown("---")
st.sidebar.markdown("### How to Run This App")
st.sidebar.markdown(
    """
    1.  **Install Dependencies:** `pip install streamlit groq pydantic PyMuPDF mysql-connector-python`
    2.  **Set Up MySQL:** Execute the SQL code from the previous response to create the `parsed_resumes` table.
    3.  **Run:** `streamlit run app.py`
    """
)