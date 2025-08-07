# utils/guide_generator.py
import os
import pandas as pd
import fitz  # PyMuPDF
import google.generativeai as genai
from fpdf import FPDF
import re
import io

def get_weak_topics_and_subject(student_id, csv_stream):
    """
    Finds topics where a student scored below 70% and identifies the course subject from a CSV stream.
    Returns a tuple: (list_of_weak_topics, subject_string).
    """
    try:
        csv_stream.seek(0)
        df = pd.read_csv(csv_stream)
    
        subject = "General Studies"
        if "Subject" in df.columns and not df["Subject"].empty:
            subject = df["Subject"].dropna().iloc[0] if not df["Subject"].dropna().empty else "General Studies"

        df_filtered = df[df["Assessment Name"].str.contains("Quiz|Assessment", case=False, na=False)].copy()
        df_filtered.loc[:, "Percent Correct"] = pd.to_numeric(
            df_filtered["Percent Correct (teacher scored)"].astype(str).str.replace('%', '', regex=False),
            errors='coerce'
        )
        df_filtered.dropna(subset=["Percent Correct"], inplace=True)
        student_data = df_filtered[df_filtered["External Student ID"] == student_id]
        weak_assessments = student_data[student_data["Percent Correct"] < 70]
    
        return weak_assessments["Assessment Name"].tolist(), subject
    except Exception as e:
        print(f"Error getting weak topics for student {student_id}: {e}")
        return [], "General Studies"

def extract_text_from_pdf(pdf_stream):
    """Extracts all text from a given PDF file stream."""
    text = ""
    try:
        with fitz.open(stream=pdf_stream.read(), filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
    return text

def create_study_guide_text(weak_topics, ced_text, api_key, subject):
    """Generates study guide content using the Gemini API. (This function's logic is unchanged)"""
    # ... (The entire Gemini prompt and API call logic remains the same)
    if not api_key:
        return "Error: API key was not provided to the generation function."
  
    if not weak_topics or not ced_text:
        return "Could not generate study guide due to missing topics or course material."

    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return f"Failed to configure the AI model client: {e}"

    prompt = (
        f"You are an expert {subject} tutor and curriculum designer. Your task is to create a rigorous, detailed, "
        f"and personalized study guide for a high school student who has demonstrated weakness in the following topics: {', '.join(weak_topics)}.\n\n"
        "This study guide must be more than a simple summary. It should be a comprehensive learning tool that leaves the student with no questions. "
        "For each topic, you will not only directly address the 'Learning Objectives' and 'Essential Knowledge' from the provided CED excerpts "
        "but also provide the necessary context, real-world analogies, and detailed examples to ensure a deep and lasting understanding.\n\n"
        "**STUDY GUIDE STRUCTURE (for each topic):**\n\n"
        "**1. **Topic Overview:**\n"
        "* Start with a concise, engaging introduction that explains the real-world relevance of the topic. Why should the student care about this concept? "
        "Use a compelling analogy to frame the topic (e.g., \"Think of an algorithm as a recipe for a computer...\").\n\n"
        "**2. **Deconstructing the Essential Knowledge:**\n"
        "* For each 'Essential Knowledge' point from the CED, do not simply restate it. Instead, do the following:\n"
        "    * **Elaborate and Explain:** Break down the concept into simple, easy-to-understand terms. Define all key vocabulary.\n"
        "    * **Provide Concrete Examples:** Use at least two distinct and clear examples to illustrate the concept. One example should be a simple, "
        "everyday analogy, and the other should be a code-based or pseudocode example relevant to the course.\n"
        "    * **Address Common Misconceptions:** Explicitly state and correct common misunderstandings students have about the topic. For example, "
        "when discussing binary, address the misconception that it's just about ones and zeros without understanding place value.\n\n"
        "**3. **Mastering the Learning Objectives:**\n"
        "* For each 'Learning Objective' from the CED, create a section that actively helps the student achieve that objective.\n"
        "    * **Actionable Guidance:** Provide step-by-step instructions or thought processes that a student can follow to demonstrate mastery. "
        "For example, if the objective is to \"Explain how an algorithm works,\" your guide should provide a framework for how to articulate that explanation.\n"
        "    * **Illustrative Scenarios:** Present a novel scenario or problem and walk the student through how the learning objective applies to it.\n\n"
        "**4. **Practice Makes Perfect:**\n"
        "* Create a set of five practice questions for each topic. These questions should be varied in format and increase in difficulty:\n"
        "    * **Two Multiple-Choice Questions:** These should mirror the style of the AP exam, with plausible distractors.\n"
        "    * **Two Short-Answer Questions:** One should require a definition or explanation in their own words, and the other should ask them to apply a concept to a given situation.\n"
        "    * **One AP-Style Free-Response Question (FRQ) or Code Analysis Challenge:** This should be a more complex problem that requires the student to synthesize "
        "multiple concepts within the topic. Provide a detailed walkthrough of the solution, explaining the reasoning at each step.\n\n"
        "**CONTENT CONSTRAINTS:**\n\n"
        "* You must base your core content **ONLY** on the provided excerpts from the official Course and Exam Description (CED).\n"
        "* Use markdown for formatting. Use `###` for main topic titles, `####` for sub-headings. Use `**text**` for bold. Use `*` for bullet points. Use triple backticks (```) for code blocks.\n"
        "* **IMPORTANT:** Use only standard ASCII characters. For example, instead of '≠', use '!='. Do not use non-standard symbols.\n\n"
        "--- Course and Exam Description (CED) Content ---\n"
        f"{ced_text}\n"
        "--- End of CED Content ---\n\n"
        "Generate the study guide now."
    )

    try:
        model = genai.GenerativeModel('gemini-2.5-pro')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return f"An error occurred while generating the study guide: {e}"

def sanitize_for_fpdf(text):
    # ... (This function is unchanged)
    replacements = {
        '≠': '!=', '≤': '<=', '≥': '>=', '→': '->', '•': '*', '’': "'",
        '‘': "'", '“': '"', '”': '"', '—': '--', '…': '...'
    }
    for uni_char, ascii_char in replacements.items():
        text = text.replace(uni_char, ascii_char)
    return text.encode('latin-1', 'replace').decode('latin-1')

class PDF(FPDF):
    # ... (This class is unchanged)
    def header(self):
        self.set_font('Helvetica', 'B', 15)
        self.cell(0, 10, 'Personalized Study Guide', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def write_markdown_line(self, text, size=11):
        self.set_font('Helvetica', '', size)
        segments = re.split(r'(\*\*.*?\*\*)', text)
        for segment in segments:
            sanitized_segment = sanitize_for_fpdf(segment)
            if sanitized_segment.startswith('**') and sanitized_segment.endswith('**'):
                self.set_font('Helvetica', 'B', size)
                self.write(5, sanitized_segment[2:-2])
                self.set_font('Helvetica', '', size)
            else:
                self.write(5, sanitized_segment)
        self.ln()

def create_pdf_from_text(text_content):
    """Creates a PDF from text content and returns it as a byte string."""
    pdf = PDF()
    pdf.add_page()
    
    lines = text_content.split('\n')
    # ... (The PDF generation logic is unchanged)
    in_code_block = False
    code_block_text = []

    for line in lines:
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            if not in_code_block:
                pdf.set_font('Courier', '', 10)
                pdf.set_fill_color(240, 240, 240)
                text_to_write = "\n".join(code_block_text)
                sanitized_code = sanitize_for_fpdf(text_to_write)
                pdf.multi_cell(0, 5, sanitized_code, border=0, fill=True, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(5)
                code_block_text = []
            continue

        if in_code_block:
            code_block_text.append(line)
            continue

        stripped_line = line.strip()
        if stripped_line.startswith('### '):
            pdf.set_font('Helvetica', 'B', 16)
            title = sanitize_for_fpdf(stripped_line.lstrip('# ').strip())
            pdf.multi_cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
        elif stripped_line.startswith('#### '):
            pdf.set_font('Helvetica', 'B', 14)
            title = sanitize_for_fpdf(stripped_line.lstrip('# ').strip())
            pdf.multi_cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
        elif stripped_line.startswith('* '):
            pdf.set_x(pdf.l_margin + 5)
            pdf.cell(5, 5, sanitize_for_fpdf("•"))
            pdf.set_x(pdf.l_margin + 10)
            pdf.write_markdown_line(stripped_line[2:])
        elif stripped_line:
            pdf.write_markdown_line(stripped_line)
        else:
            pdf.ln(3)

    # --- THE FIX IS HERE ---
    # The modern fpdf2 `output()` method directly returns bytes by default.
    # The redundant .encode() call has been removed.
    return pdf.output()