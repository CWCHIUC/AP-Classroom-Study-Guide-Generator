# utils/guide_generator.py
import os
import pandas as pd
import fitz  # PyMuPDF
import google.generativeai as genai
from fpdf import FPDF
import re
import io

# --- Imports for Online LaTeX Rendering & Image Sizing ---
import requests
import urllib.parse
from PIL import Image

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
    """Generates study guide content using the Gemini API."""
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
        "* **MATHEMATICAL NOTATION:** All mathematical expressions, variables, and formulas MUST be formatted using standard LaTeX. Use single dollar signs for inline math (e.g., the formula is $v = \\Delta x / \\Delta t$) and double dollar signs for block-level equations (e.g., $$\\sum_{i=1}^{n} F_i = ma$$). **Crucially, do NOT wrap LaTeX expressions in backticks (`).**\n"
        "* You must base your core content **ONLY** on the provided excerpts from the official Course and Exam Description (CED).\n"
        "* Use markdown for formatting. Use `###` for main topic titles, `####` for sub-headings. Use `**text**` for bold. Use `*` for bullet points. Use triple backticks (```) for code blocks.\n"
        "* **IMPORTANT:** Use only standard ASCII characters outside of LaTeX. For example, instead of '≠', use '!='. Do not use non-standard symbols.\n\n"
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
    replacements = {
        '’': "'", '‘': "'", '“': '"', '”': '"', '—': '--', '…': '...'
    }
    for uni_char, ascii_char in replacements.items():
        text = text.replace(uni_char, ascii_char)
    return text.encode('latin-1', 'replace').decode('latin-1')

COLOR_PRIMARY = (44, 62, 80)
COLOR_SECONDARY = (52, 152, 219)
COLOR_BODY = (51, 51, 51)
COLOR_LIGHT_GRAY = (240, 240, 240)

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_auto_page_break(auto=True, margin=25)
        self.line_height = 6

    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(*COLOR_SECONDARY)
        self.cell(0, 10, 'Personalized Study Guide', 0, 1, 'L')
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
        self.set_font('Helvetica', 'B', 20)
        self.set_text_color(*COLOR_PRIMARY)
        self.multi_cell(0, 10, text, 0, 'L')
        self.ln(6)

    def write_h2(self, text):
        self.set_font('Helvetica', 'B', 16)
        self.set_text_color(*COLOR_PRIMARY)
        self.multi_cell(0, 8, text, 0, 'L')
        self.ln(4)

    def write_body(self, text):
        self.write_styled_text(text)
        self.ln(self.line_height)

    def write_bullet(self, text):
        self.cell(5, self.line_height, "*", 0, 0)
        self.write_styled_text(text)
        self.ln(self.line_height)

    def draw_code_block(self, text):
        self.set_font('Courier', '', 10)
        self.set_fill_color(*COLOR_LIGHT_GRAY)
        self.set_text_color(*COLOR_BODY)
        self.multi_cell(w=0, h=5, text=text, border=0, align='L', fill=True)
        self.ln(5)

    def render_latex(self, formula, dpi=300):
        """Renders a LaTeX formula to an in-memory image using the Codecogs API."""
        clean_formula = formula.strip()
        if not clean_formula:
            return None

        encoded_formula = urllib.parse.quote(f"\\dpi{{{dpi}}} {clean_formula}")
        url = f"https://latex.codecogs.com/png.latex?{encoded_formula}"

        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            print(f"Failed to render LaTeX formula via API: {e}")
            return None

    def draw_latex_formula(self, formula, is_display=True):
        """Draws a block-level LaTeX formula, correctly sized and centered."""
        dpi = 300
        img_data = self.render_latex(formula, dpi=dpi)
        
        if img_data:
            try:
                img = Image.open(io.BytesIO(img_data))
                img_width_px, _ = img.size
                img_width_mm = (img_width_px / dpi) * 25.4
                
                available_width = self.w - self.l_margin - self.r_margin
                if img_width_mm > available_width:
                    img_width_mm = available_width
                
                x_pos = self.l_margin + (available_width - img_width_mm) / 2
                
                self.ln(2)
                self.image(io.BytesIO(img_data), x=x_pos, w=img_width_mm, h=0, type='PNG')
                self.ln(2)
            except Exception as e:
                print(f"Error placing block image: {e}")
                self.set_font('Courier', '', 10)
                self.set_text_color(255, 0, 0)
                self.multi_cell(0, 5, f"[LaTeX Error: {formula}]")
        else:
            self.set_font('Courier', '', 10)
            self.set_text_color(255, 0, 0)
            self.multi_cell(0, 5, f"[LaTeX Error: {formula}]")

    def _write_sub_segment(self, text):
        """Processes a segment of text for math and code tags."""
        sub_segments = re.split(r'(`.*?`|\$.*?\$)', text)
        for segment in sub_segments:
            if not segment: continue

            if segment.startswith('`') and segment.endswith('`'):
                original_font_family = self.font_family
                original_font_style = self.font_style
                original_font_size = self.font_size_pt
                
                self.set_font('Courier', '', 10)
                self.set_text_color(*COLOR_SECONDARY)
                self.write(self.line_height, sanitize_for_fpdf(segment[1:-1]))
                self.set_font(original_font_family, original_font_style, original_font_size)
                self.set_text_color(*COLOR_BODY)

            elif segment.startswith('$') and segment.endswith('$'):
                formula = segment[1:-1]
                dpi = 300
                img_data = self.render_latex(formula, dpi=dpi)
                if img_data:
                    try:
                        img = Image.open(io.BytesIO(img_data))
                        img_width_px, img_height_px = img.size
                        
                        img_width_mm = (img_width_px / dpi) * 25.4
                        img_height_mm = (img_height_px / dpi) * 25.4
                        
                        space_width_mm = 1.5
                        
                        if self.get_x() + space_width_mm + img_width_mm > self.w - self.r_margin:
                            self.ln(self.line_height)
                            
                        y_pos = self.get_y() + (self.line_height / 2) - (img_height_mm / 2)
                        current_x = self.get_x()
                        
                        self.image(io.BytesIO(img_data), x=current_x + space_width_mm, y=y_pos, w=img_width_mm, h=img_height_mm, type='PNG')
                        self.set_x(current_x + space_width_mm + img_width_mm)
                        
                    except Exception as e:
                        print(f"Error placing inline image: {e}")
                        self.write(self.line_height, " [Math Error] ")
                else:
                    self.write(self.line_height, f" [ {formula} ] ")
            else:
                self.write(self.line_height, sanitize_for_fpdf(segment))

    def write_styled_text(self, text):
        """Parses a line for bold, code, and LaTeX and writes it with appropriate styling."""
        self.set_font('Helvetica', '', 11)
        self.set_text_color(*COLOR_BODY)
        
        # First, split the text by bold markers
        segments = re.split(r'(\*\*.*?\*\*)', text)
        
        for i, segment in enumerate(segments):
            if not segment: continue
            
            is_bold_content = (i % 2 == 1)
            
            if is_bold_content:
                self.set_font('Helvetica', 'B', 11)
                # Process the content inside the **...**
                self._write_sub_segment(segment[2:-2])
                self.set_font('Helvetica', '', 11) # Reset to normal
            else:
                # This is a normal, non-bold segment
                self._write_sub_segment(segment)

def create_pdf_from_text(text_content):
    """Creates a beautifully designed PDF from text content using a robust block parser."""
    pdf = PDF('P', 'mm', 'Letter')
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)
    pdf.add_page()

    chunks = re.split(r'(```.*?```|\$\$.*?\$\$)', text_content, flags=re.DOTALL)

    for chunk in chunks:
        if not chunk.strip():
            continue

        if chunk.startswith('```'):
            code_content = chunk[3:-3].strip()
            pdf.draw_code_block(sanitize_for_fpdf(code_content))
        elif chunk.startswith('$$'):
            math_content = chunk[2:-2].strip()
            pdf.draw_latex_formula(math_content, is_display=True)
        else:
            for line in chunk.split('\n'):
                stripped_line = line.strip()
                if stripped_line.startswith('### '):
                    pdf.write_h1(sanitize_for_fpdf(stripped_line.lstrip('# ').strip()))
                elif stripped_line.startswith('#### '):
                    pdf.write_h2(sanitize_for_fpdf(stripped_line.lstrip('# ').strip()))
                elif stripped_line.startswith('* '):
                    pdf.write_bullet(stripped_line[2:])
                elif stripped_line:
                    pdf.write_body(stripped_line)
                else:
                    if pdf.get_y() > pdf.t_margin + 15:
                        pdf.ln(3)

    return pdf.output()