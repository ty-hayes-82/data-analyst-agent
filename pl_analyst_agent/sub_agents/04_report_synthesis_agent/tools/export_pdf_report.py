# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Convert Markdown reports to PDF format."""

from pathlib import Path
import sys


def markdown_to_pdf(markdown_file: Path, output_pdf: Path = None) -> Path:
    """
    Convert a Markdown file to PDF.
    
    Args:
        markdown_file: Path to the input markdown file
        output_pdf: Optional path for output PDF. If None, replaces .md with .pdf
        
    Returns:
        Path to the generated PDF file
        
    Raises:
        ImportError: If required dependencies are not installed
        FileNotFoundError: If markdown file does not exist
    """
    if not markdown_file.exists():
        raise FileNotFoundError(f"Markdown file not found: {markdown_file}")
    
    if output_pdf is None:
        output_pdf = markdown_file.with_suffix('.pdf')
    
    try:
        import markdown2
        from weasyprint import HTML, CSS
    except ImportError as e:
        print("ERROR: Missing required dependencies for PDF export.")
        print("Install with: pip install markdown2 weasyprint")
        print(f"Details: {e}")
        raise
    
    # Read markdown content
    markdown_content = markdown_file.read_text(encoding="utf-8")
    
    # Convert markdown to HTML
    html_content = markdown2.markdown(
        markdown_content,
        extras=["tables", "fenced-code-blocks", "header-ids"]
    )
    
    # Add basic styling
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{
                size: letter;
                margin: 1in;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                font-size: 11pt;
                line-height: 1.6;
                color: #333;
            }}
            h1 {{
                font-size: 20pt;
                color: #1a1a1a;
                border-bottom: 2px solid #4285f4;
                padding-bottom: 0.3em;
                margin-top: 0;
            }}
            h2 {{
                font-size: 16pt;
                color: #1a1a1a;
                margin-top: 1.5em;
                border-bottom: 1px solid #ddd;
                padding-bottom: 0.2em;
            }}
            h3 {{
                font-size: 13pt;
                color: #333;
                margin-top: 1.2em;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 1em 0;
                font-size: 10pt;
            }}
            th, td {{
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }}
            th {{
                background-color: #f4f4f4;
                font-weight: bold;
            }}
            tr:nth-child(even) {{
                background-color: #fafafa;
            }}
            code {{
                background-color: #f4f4f4;
                padding: 2px 4px;
                border-radius: 3px;
                font-family: "Courier New", monospace;
                font-size: 9pt;
            }}
            pre {{
                background-color: #f4f4f4;
                padding: 10px;
                border-radius: 5px;
                overflow-x: auto;
            }}
            ul, ol {{
                margin: 0.5em 0;
                padding-left: 2em;
            }}
            li {{
                margin: 0.3em 0;
            }}
            hr {{
                border: none;
                border-top: 1px solid #ddd;
                margin: 2em 0;
            }}
            .footer {{
                margin-top: 2em;
                padding-top: 1em;
                border-top: 1px solid #ddd;
                font-size: 9pt;
                color: #666;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """
    
    # Convert HTML to PDF
    HTML(string=html_template).write_pdf(output_pdf)
    
    return output_pdf


def main():
    """Command-line interface for PDF export."""
    if len(sys.argv) < 2:
        print("Usage: python -m pl_analyst_agent.sub_agents.report_synthesis_agent.tools.export_pdf_report <markdown_file> [output_pdf]")
        print("\nExamples:")
        print("  python -m pl_analyst_agent.sub_agents.report_synthesis_agent.tools.export_pdf_report outputs/cost_center_067.md")
        print("  python -m pl_analyst_agent.sub_agents.report_synthesis_agent.tools.export_pdf_report outputs/cost_center_067.md outputs/report.pdf")
        sys.exit(1)
    
    markdown_file = Path(sys.argv[1])
    output_pdf = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    
    try:
        result = markdown_to_pdf(markdown_file, output_pdf)
        print(f"Successfully generated PDF: {result}")
    except Exception as e:
        print(f"ERROR: Failed to generate PDF: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()





