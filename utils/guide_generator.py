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
        "* **IMPORTANT: Do not write any conversational introduction, preamble, or self-introduction. The output must begin *immediately* with the first topic's main title (e.g., '### TOPIC 3.6: CONDITIONALS').**\n"
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

COLOR_PRIMARY = (44, 62, 80)    # Dark Blue/Gray
COLOR_SECONDARY = (52, 152, 219) # Bright Blue
COLOR_BODY = (51, 51, 51)       # Dark Gray for text
COLOR_LIGHT_GRAY = (240, 240, 240) # For code block background
TEXT = (71, 71, 212) 

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # No custom fonts needed, we'll use built-in Helvetica
        self.set_auto_page_break(auto=True, margin=25)

    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(*COLOR_SECONDARY)
        self.cell(0, 10, 'Personalized Study Guide', 0, 1, 'L')
        # Add a line break and a horizontal line
        self.ln(5)
        self.set_draw_color(*COLOR_SECONDARY)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def write_h1(self, text):
        self.set_font('Helvetica', 'B', 20) # Using Helvetica Bold for main titles
        self.set_text_color(*COLOR_PRIMARY)
        self.multi_cell(0, 10, text, 0, 'L')
        self.ln(6)

    def write_h2(self, text):
        self.set_font('Helvetica', 'B', 16) # Using Helvetica Bold for sub-titles
        self.set_text_color(*COLOR_PRIMARY)
        self.multi_cell(0, 8, text, 0, 'L')
        self.ln(4)

    def write_body(self, text):
    # Use the new styled text writer instead of the simple multi_cell
        self.write_styled_text(text)

    def write_bullet(self, text):
        self.set_font('Helvetica', '', 11)
        self.set_text_color(*COLOR_BODY)
        self.cell(5, 6, "*", 0, 0)
        # The rest of the line is now handled by the styled writer
        self.write_styled_text(text)

    def draw_code_block(self, text):
        self.set_font('Courier', '', 10)
        self.set_fill_color(*COLOR_LIGHT_GRAY)
        self.set_text_color(*COLOR_BODY)
        # This is the key change: We let multi_cell handle the drawing.
        # The 'fill=True' parameter makes it draw the background, which
        # correctly splits across pages with the text.
        self.multi_cell(
            w=0,
            h=5,
            text=text,
            border=0,
            align='L',
            fill=True
        )
        self.ln(5) # Add some space after the block

    # This is a new method to be added to the PDF class
    def write_styled_text(self, text):
        """Parses a line for bold and inline code and writes it with appropriate styling."""
        self.set_font('Helvetica', '', 11)
        self.set_text_color(*COLOR_BODY)
        
        # Split the text by bold and inline code markers
        segments = re.split(r'(\*\*.*?\*\*|`.*?`)', text)
        
        for segment in segments:
            if segment.startswith('**') and segment.endswith('**'):
                # It's a bold segment
                self.set_font('Helvetica', 'B', 11)
                self.write(6, segment[2:-2])
                self.set_font('Helvetica', '', 11) # Reset to regular
            elif segment.startswith('`') and segment.endswith('`'):
                # It's an inline code segment
                self.set_font('Courier', '', 10)
                self.set_text_color(*COLOR_SECONDARY) # Use accent color
                self.write(6, segment[1:-1])
                self.set_font('Helvetica', '', 11) # Reset font
                self.set_text_color(*COLOR_BODY)   # Reset color
            else:
                # It's a regular segment
                self.write(6, segment)
        self.ln(6)

def create_pdf_from_text(text_content):
    """Creates a beautifully designed PDF from text content."""
    pdf = PDF('P', 'mm', 'Letter')
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)
    pdf.add_page()

    lines = text_content.split('\n')
    in_code_block = False
    code_block_text = []

    for line in lines:
        sanitized_line = sanitize_for_fpdf(line)
        if sanitized_line.strip().startswith('```'):
            in_code_block = not in_code_block
            if not in_code_block:
                pdf.draw_code_block("\n".join(code_block_text))
                code_block_text = []
            continue

        if in_code_block:
            code_block_text.append(sanitized_line)
            continue

        stripped_line = sanitized_line.strip()
        if stripped_line.startswith('### '):
            pdf.write_h1(stripped_line.lstrip('# ').strip())
        elif stripped_line.startswith('#### '):
            pdf.write_h2(stripped_line.lstrip('# ').strip())
        elif stripped_line.startswith('* '):
            pdf.write_bullet(stripped_line[2:])
        elif stripped_line:
            pdf.write_body(stripped_line)
        else:
            pdf.ln(3) # Keep small line breaks for spacing

    return pdf.output()
