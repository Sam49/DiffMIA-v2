import docx
import sys

def extract_text_from_docx(docx_path):
    doc = docx.Document(docx_path)
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    return '\n'.join(full_text)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_docx.py <docx_file>")
        sys.exit(1)

    docx_path = sys.argv[1]
    try:
        text = extract_text_from_docx(docx_path)
        print(text)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)