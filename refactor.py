import re

with open('web/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Find inline script block (not src-based)
# Match <script> tag WITHOUT src attribute
inline_pattern = re.compile(r'<script(?![^>]*\bsrc\b)[^>]*>(.*?)</script>', re.DOTALL)

js_blocks = []
def collect_and_replace(m):
    js_blocks.append(m.group(1))
    return ''

html_clean = inline_pattern.sub(collect_and_replace, html)

# Insert app.js reference before </body>
html_clean = html_clean.replace('</body>', '<script src="app.js"></script>\n</body>')

# Write clean HTML
with open('web/index.html', 'w', encoding='utf-8') as f:
    f.write(html_clean)

# Write app.js
with open('web/app.js', 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(js_blocks).strip())

print(f"Done. Extracted {len(js_blocks)} JS block(s)")
