import re

with open('handlers.py', 'r', encoding='utf-8') as f:
    data = f.read()

data = re.sub(r'\"type\":\s*\"listitem\",\s*', '', data)

with open('handlers.py', 'w', encoding='utf-8') as f:
    f.write(data)
