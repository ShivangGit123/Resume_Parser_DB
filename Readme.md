# 📄 Resume_Parser_DB

## 🌟 Project Title: Automated Resume Parser and Database System

This project implements a system to efficiently parse unstructured resume documents (PDFs, DOCXs) and store the extracted candidate data into a structured relational database (MySQL). The primary goal is to transform raw application files into readily queryable data, significantly accelerating the candidate screening process.

---

## 🚀 Features

* **Document Processing:** Handles parsing of common resume formats (`.pdf`, `.docx`).
* **Structured Data Extraction:** Accurately pulls key candidate details (Name, Contact, Experience, Education, Skills).
* **MySQL Integration:** Stores all parsed information in a robust, normalized MySQL database schema.
* **Data Quality:** Implements necessary constraints (`PRIMARY KEY`, `UNIQUE`) to ensure data integrity and prevent duplicate candidate entries.
* **Audit Logging:** Includes a dedicated table to log the outcome of every parsing operation.

---

## ⚙️ Technology Stack

| Category | Technology | Role in Project |
| :--- | :--- | :--- |
| **Database** | MySQL (or MariaDB) | Central storage for all structured candidate data. |
| **Development** | Python (3.x) | Core language used for the parsing logic (NLP, document handling). |
| **Data Interaction** | SQL | Used for creating the schema, inserting data, and running retrieval queries. |
| **Tools** | MySQL Workbench | Used for database management, query execution, and visual data inspection. |

---

## 📦 Database Setup (SQL)

### 1. Schema Overview

The database is named `resume_parser_db` and contains the following two primary tables:

#### A. `parsed_resumes` (Candidate Data)

| Column Name | Data Type | Description |
| :--- | :--- | :--- |
| `id` | `INT` | Unique Primary Key |
| `name` | `VARCHAR` | Candidate's Full Name |
| `email` | `VARCHAR` | Unique Contact Email |
| `phone` | `VARCHAR` | Contact Phone Number |
| `total_years_experience` | `DECIMAL(4, 2)` | Total work experience (e.g., 2.50) |
| `highest_degree` | `VARCHAR` | Highest qualification obtained |
| `skills` | `JSON` | List of extracted skills |
| `filename` | `VARCHAR` | Original uploaded file name |
| `parsing_date` | `DATETIME` | Timestamp of parsing |

#### B. `parsing_logs` (Audit Log)

Stores records of every file parsing attempt.

### 2. Execution Script

To set up the database, simply run the content of the `database_setup.sql` file (or the SQL code provided previously) in your MySQL Workbench:

```sql
-- Ensure you have the provided database creation script.
-- Example of execution:
SOURCE database_setup.sql;

-- Or execute these commands directly in Workbench:
CREATE DATABASE resume_parser_db;
USE resume_parser_db;
-- ... followed by CREATE TABLE and INSERT statements.

-- Example Query to verify data after setup:
SELECT * FROM parsed_resumes;
