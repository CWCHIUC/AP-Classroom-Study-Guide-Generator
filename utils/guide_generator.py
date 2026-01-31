import os
import pandas as pd
import fitz  # PyMuPDF
import google.generativeai as genai
from fpdf import FPDF
import re
import io
import requests
import urllib.parse
from PIL import Image

# --- Configuration & Colors ---
# Modern Color Palette
COLOR_PRIMARY = (41, 128, 185)      # Strong Blue (Headers)
COLOR_SECONDARY = (52, 73, 94)      # Dark Blue-Grey (Subheaders)
COLOR_ACCENT = (231, 76, 60)        # Red (Important/Tips)
COLOR_TEXT = (44, 62, 80)           # Dark Grey (Body Text)
COLOR_LIGHT_BG = (245, 247, 250)    # Very Light Grey (Backgrounds)
COLOR_CODE_BG = (240, 240, 240)     # Light Grey (Code Blocks)
COLOR_BOX_DEF = (232, 246, 243)     # Mint Green (Definitions)
COLOR_BOX_TIP = (253, 237, 236)     # Light Red (Tips)

def get_weak_topics_and_subject(student_id, csv_stream):
    """Finds topics where a student scored below 70%."""
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
        return "Error: API key was not provided."
    if not weak_topics or not ced_text:
        return "Could not generate study guide due to missing topics or course material."

    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return f"Failed to configure AI: {e}"

    # --- Dynamic Prompt Logic ---
    is_cs = "Computer Science" in subject or "CS" in subject
    
    if is_cs:
        example_req = "code-based or pseudocode example"
        frq_req = "Code Analysis Challenge"
    else:
        example_req = "practical application or case study"
        frq_req = "Critical Thinking or Data Analysis Challenge"

    prompt = (
        f"You are an expert {subject} tutor and curriculum designer. Your task is to create a concise, high-impact "
        f"study guide for a student weak in: {', '.join(weak_topics)}.\n\n"
        "**GOAL:** Synthesize the provided Course and Exam Description (CED) content into a clear, digestible narrative. "
        "Do NOT list every single 'Essential Knowledge' point or 'Learning Objective' individually. Instead, group them "
        "to explain the core concepts of the topic efficiently.\n\n"
        "**STUDY GUIDE STRUCTURE (for each topic):**\n\n"
        "**1. **Topic Overview:**\n"
        "* A brief, engaging introduction (2-3 sentences) with a compelling real-world analogy to frame the topic.\n\n"
        "**2. **Core Concepts & Essential Knowledge (Synthesized):**\n"
        "* **The Big Picture:** Weave the 'Essential Knowledge' points together into a cohesive explanation of the topic. "
        "Focus on the *relationships* between concepts rather than isolated facts.\n"
        "* **Key Examples:** Provide 1-2 strong examples (one everyday analogy, one {example_req}) that illustrate the *main* ideas.\n"
        "* **Common Pitfalls:** Briefly address the single most critical misconception students have about this topic.\n\n"
        "**3. **Achieving Mastery (Skills Focus):**\n"
        "* Focus on the *skills* required by the Learning Objectives. How should a student approach problems in this topic?\n"
        "* **Strategy:** Provide a general strategy or framework for answering questions related to these objectives.\n"
        "* **Application:** Walk through *one* illustrative scenario that demonstrates how to apply these skills.\n\n"
        "**4. **Practice:**\n"
        "* **2 Multiple-Choice Questions:** Exam-style with distractors.\n"
        "* **1 Short-Answer Question:** Application-based.\n"
        f"* **1 {frq_req}:** A slightly more complex problem to test synthesis.\n\n"
        "**FORMATTING RULES:**\n"
        "* **Definitions:** [[BOX: Key Definition | The term is...]]\n"
        "* **Tips:** [[BOX: Exam Tip | Remember that...]]\n"
        "* **Math:** Use LaTeX ($...$ or $$...$$). NO backticks for math.\n"
        "* **Code:** Use ```...```.\n"
        "* **Headers:** ### for Main, #### for Sub.\n"
        "* **No Preamble.** Start immediately with '### TOPIC...'\n\n"
        "--- CED Content ---\n"
        f"{ced_text}\n"
        "--- End CED ---\n"
    )

    try:
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return f"An error occurred: {e}"

def sanitize_for_fpdf(text):
    """Sanitizes text for FPDF (Latin-1)."""
    replacements = {
        '’': "'", '‘': "'", '“': '"', '”': '"', '—': '--', '…': '...',
        '–': '-', '•': '*'
    }
    for uni_char, ascii_char in replacements.items():
        text = text.replace(uni_char, ascii_char)
    return text.encode('latin-1', 'replace').decode('latin-1')

class ModernPDF(FPDF):
    def __init__(self, subject="Study Guide", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subject = subject
        self.set_auto_page_break(auto=True, margin=25)
        self.line_height = 6
        
        # Font Loading
        font_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'fonts', 'dejavu-sans')
        self.main_font = 'Helvetica'
        try:
            regular = os.path.join(font_dir, 'DejaVuSans.ttf')
            bold = os.path.join(font_dir, 'DejaVuSans-Bold.ttf')
            italic = os.path.join(font_dir, 'DejaVuSans-Oblique.ttf')
            if os.path.exists(regular) and os.path.exists(bold):
                self.add_font('DejaVu', '', regular, uni=True)
                self.add_font('DejaVu', 'B', bold, uni=True)
                if os.path.exists(italic): self.add_font('DejaVu', 'I', italic, uni=True)
                self.main_font = 'DejaVu'
        except Exception:
            self.main_font = 'Helvetica'

    def _safe_text(self, text):
        return sanitize_for_fpdf(text) if self.main_font == 'Helvetica' else text

    def header(self):
        # Only draw the big banner on the first page
        if self.page_no() == 1:
            self.set_fill_color(*COLOR_PRIMARY)
            self.rect(0, 0, 215.9, 35, 'F') # Full width banner
            
            self.set_y(10)
            self.set_font(self.main_font, 'B', 24)
            self.set_text_color(255, 255, 255)
            self.cell(0, 10, self._safe_text(f"{self.subject} Guide"), 0, 1, 'C')
            
            self.set_font(self.main_font, '', 10)
            self.cell(0, 6, "Personalized Mastery Plan", 0, 1, 'C')
            self.ln(20) # Space after header
        else:
            # Minimal header for subsequent pages
            self.set_y(10)
            self.set_font(self.main_font, 'I', 8)
            self.set_text_color(128)
            self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 205.9, self.get_y())
        self.set_font(self.main_font, 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, self._safe_text(f'Page {self.page_no()}'), 0, 0, 'R')

    def write_h1(self, text):
        self.ln(5)
        self.set_font(self.main_font, 'B', 18)
        self.set_text_color(*COLOR_PRIMARY)
        # Add a small underline accent
        self.cell(0, 8, self._safe_text(text.upper()), 0, 1, 'L')
        self.set_draw_color(*COLOR_PRIMARY)
        self.set_line_width(0.5)
        self.line(self.get_x(), self.get_y(), self.get_x() + 190, self.get_y())
        self.ln(6)

    def write_h2(self, text):
        self.ln(4)
        self.set_font(self.main_font, 'B', 14)
        self.set_text_color(*COLOR_SECONDARY)
        self.multi_cell(0, 8, self._safe_text(text), 0, 'L')
        self.ln(2)

    def write_body(self, text):
        self.write_styled_text(text)
        self.ln(self.line_height)

    def write_bullet(self, text):
        # FIX: Explicitly reset font to main_font to avoid Courier issues
        self.set_font(self.main_font, '', 11)
        self.set_text_color(*COLOR_PRIMARY)
        
        # Safe bullet handling
        bullet = "•"
        if self.main_font == 'Helvetica':
            bullet = "*" # Fallback for standard fonts
            
        self.cell(6, self.line_height, bullet, 0, 0) 
        self.set_text_color(*COLOR_TEXT)
        self.write_styled_text(text)
        self.ln(self.line_height)

    def draw_code_block(self, text):
        self.ln(2)
        self.set_font('Courier', '', 9)
        self.set_fill_color(*COLOR_CODE_BG)
        self.set_text_color(50, 50, 50)
        
        # Calculate height needed
        lines = text.split('\n')
        num_lines = len(lines)
        height = num_lines * 5 + 6
        
        # Draw background rect
        x = self.get_x()
        y = self.get_y()
        
        # Check page break
        if y + height > 260:
            self.add_page()
            y = self.get_y()

        self.rect(x, y, 170, height, 'F')
        
        # "Code" Label
        self.set_font('Helvetica', 'B', 6)
        self.set_text_color(150)
        self.set_xy(x + 160, y + 1)
        self.cell(8, 4, "CODE", 0, 0, 'R')
        
        # Write Code
        self.set_xy(x + 2, y + 3)
        self.set_font('Courier', '', 9)
        self.set_text_color(50, 50, 50)
        safe_code = sanitize_for_fpdf(text)
        self.multi_cell(166, 5, safe_code, 0, 'L')
        
        self.set_y(y + height + 4)
        self.set_font(self.main_font, '', 11) # Reset font

    def draw_callout_box(self, title, text):
        """Draws a styled box with a colored left border."""
        self.ln(4)
        
        # Determine colors based on title
        if "Tip" in title or "Warning" in title:
            bg_color = COLOR_BOX_TIP
            border_color = COLOR_ACCENT
            icon = "!"
        else:
            bg_color = COLOR_BOX_DEF
            border_color = (26, 188, 156) # Teal
            icon = "i"

        self.set_fill_color(*bg_color)
        self.set_draw_color(*border_color)
        self.set_line_width(0.8)
        
        # Calculate height
        self.set_font(self.main_font, '', 10)
        # Simulate height calculation
        lines = self.multi_cell(160, 6, self._safe_text(text), split_only=True)
        h = len(lines) * 6 + 12
        
        # Check page break
        if self.get_y() + h > 260:
            self.add_page()

        x = self.get_x()
        y = self.get_y()
        
        # Draw Background
        self.rect(x, y, 170, h, 'F')
        
        # Draw Left Accent Border
        self.set_fill_color(*border_color)
        self.rect(x, y, 2, h, 'F')
        
        # Title
        self.set_xy(x + 6, y + 3)
        self.set_font(self.main_font, 'B', 10)
        self.set_text_color(*border_color)
        self.cell(0, 6, self._safe_text(title.upper()), 0, 1)
        
        # Body
        self.set_xy(x + 6, y + 9)
        self.set_font(self.main_font, '', 10)
        self.set_text_color(*COLOR_TEXT)
        self.multi_cell(160, 6, self._safe_text(text), 0, 'L')
        
        self.set_y(y + h + 4)

    def render_latex(self, formula, dpi=300):
        """Renders LaTeX via Codecogs."""
        clean_formula = formula.strip()
        if not clean_formula: return None
        encoded = urllib.parse.quote(f"\\dpi{{{dpi}}} \\bg_white {clean_formula}") # Add white bg
        url = f"https://latex.codecogs.com/png.latex?{encoded}"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r.content
        except:
            return None

    def draw_latex_formula(self, formula):
        """Draws centered block LaTeX."""
        dpi = 300
        img_data = self.render_latex(formula, dpi)
        if img_data:
            try:
                img = Image.open(io.BytesIO(img_data))
                w_mm = (img.size[0] / dpi) * 25.4
                h_mm = (img.size[1] / dpi) * 25.4
                
                # Center it
                x = (210 - w_mm) / 2
                
                self.ln(2)
                if self.get_y() + h_mm > 260: self.add_page()
                
                self.image(io.BytesIO(img_data), x=x, w=w_mm, h=h_mm, type='PNG')
                self.ln(h_mm + 4)
            except:
                self.set_font('Courier', '', 10)
                self.cell(0, 5, f"[Formula: {formula}]", 0, 1)
        else:
            self.set_font('Courier', '', 10)
            self.cell(0, 5, f"[Formula: {formula}]", 0, 1)

    def _write_sub_segment(self, text):
        """Handles inline code and math."""
        # Split by code (`...`) and math ($...$)
        parts = re.split(r'(`.*?`|\$.*?\$)', text)
        for part in parts:
            if not part: continue
            
            if part.startswith('`') and part.endswith('`'):
                # Inline Code Style
                self.set_font('Courier', '', 10)
                self.set_fill_color(240, 240, 240)
                self.set_text_color(199, 37, 78) # Reddish code color
                content = sanitize_for_fpdf(part[1:-1])
                width = self.get_string_width(content) + 2
                self.cell(width, self.line_height, content, 0, 0, fill=True)
                # Reset
                self.set_font(self.main_font, '', 11) # Or Bold if parent was bold (simplified here)
                self.set_text_color(*COLOR_TEXT)
                
            elif part.startswith('$') and part.endswith('$'):
                # Inline Math
                formula = part[1:-1]
                img_data = self.render_latex(formula, 200)
                if img_data:
                    try:
                        img = Image.open(io.BytesIO(img_data))
                        w = (img.size[0] / 200) * 25.4
                        h = (img.size[1] / 200) * 25.4
                        y = self.get_y() + (self.line_height - h)/2 + 1
                        self.image(io.BytesIO(img_data), x=self.get_x(), y=y, w=w, h=h)
                        self.set_x(self.get_x() + w + 1)
                    except:
                        self.write(self.line_height, f" {formula} ")
                else:
                    self.write(self.line_height, f" {formula} ")
            else:
                self.write(self.line_height, self._safe_text(part))

    def write_styled_text(self, text):
        """Handles Bold (**text**) and calls sub_segment for code/math."""
        self.set_font(self.main_font, '', 11)
        self.set_text_color(*COLOR_TEXT)
        
        segments = re.split(r'(\*\*.*?\*\*)', text)
        for i, seg in enumerate(segments):
            if not seg: continue
            if i % 2 == 1: # Bold
                self.set_font(self.main_font, 'B', 11)
                self._write_sub_segment(seg[2:-2])
                self.set_font(self.main_font, '', 11)
            else:
                self._write_sub_segment(seg)

def create_pdf_from_text(text_content, subject="Study Guide"):
    """Creates the PDF."""
    pdf = ModernPDF(subject=subject, orientation='P', unit='mm', format='Letter')
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)
    pdf.add_page()

    chunks = re.split(r'(```.*?```|\$\$.*?\$\$|\[\[BOX:.*?\]\])', text_content, flags=re.DOTALL)

    for chunk in chunks:
        if not chunk.strip(): continue

        if chunk.startswith('[[BOX:'):
            content = chunk[6:-2]
            if '|' in content:
                title, body = content.split('|', 1)
                pdf.draw_callout_box(title.strip(), body.strip())
            else:
                pdf.draw_callout_box("Note", content.strip())

        elif chunk.startswith('```'):
            pdf.draw_code_block(chunk[3:-3].strip())
            
        elif chunk.startswith('$$'):
            pdf.draw_latex_formula(chunk[2:-2].strip())
            
        else:
            for line in chunk.split('\n'):
                s_line = line.strip()
                if s_line.startswith('### '):
                    pdf.write_h1(s_line[4:])
                elif s_line.startswith('#### '):
                    pdf.write_h2(s_line[5:])
                elif s_line.startswith('* '):
                    pdf.write_bullet(s_line[2:])
                elif s_line:
                    pdf.write_body(s_line)
                else:
                    # Smart spacing
                    if pdf.get_y() < 240: pdf.ln(2)

    return pdf.output()