# Rebuilds USER-MANUAL.pdf from USER-MANUAL.md (needs: pip install markdown playwright; playwright install chromium). Run from the project folder.
import markdown, re, sys
from playwright.sync_api import sync_playwright
src = open("USER-MANUAL.md", encoding="utf-8").read()
body = markdown.markdown(src, extensions=["tables", "fenced_code", "toc", "sane_lists"])
css = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1d2330; }
h1 { font-size: 26pt; margin: 0 0 8pt; color: #b3243a; }
h2 { font-size: 16pt; margin-top: 22pt; padding-bottom: 3pt; border-bottom: 2px solid #e3e6ee; color: #1d2330; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin-top: 14pt; color: #b3243a; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9.5pt; }
th, td { border: 1px solid #cfd4e0; padding: 4pt 6pt; vertical-align: top; text-align: left; }
th { background: #eef0f6; }
code { background: #eef0f6; padding: 1px 4px; border-radius: 3px; font-size: 9.5pt; }
pre { background: #f3f4f8; padding: 8pt; border-radius: 5px; overflow-wrap: anywhere; white-space: pre-wrap; }
hr { border: 0; border-top: 1px solid #e3e6ee; margin: 14pt 0; }
a { color: #1f5fbf; text-decoration: none; }
li { margin: 2pt 0; }
tr, li { page-break-inside: avoid; }
"""
html = f"<!doctype html><meta charset='utf-8'><style>{css}</style>{body}"
open("manual.tmp.html", "w", encoding="utf-8").write(html)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(__import__("pathlib").Path("manual.tmp.html").resolve().as_uri())
    pg.pdf(path="USER-MANUAL.pdf", format="A4", print_background=True, display_header_footer=True,
           header_template="<span></span>",
           footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#777'>Lazy Mixtape Maker - User Manual - page <span class='pageNumber'></span> of <span class='totalPages'></span></div>",
           margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
    b.close()
