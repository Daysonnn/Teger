import urllib.request, json
TOKEN='8146945075:AAHh3vmKX3GaV5nMC5QKjI_8u-qE2imCY24'
payload={'chat_id': '7693936576', 'rich_message': {'blocks': [
    {"type": "heading", "text": "👥 Сбор: майн", "size": 2},
    {"type": "paragraph", "text": "Организатор: @dayyson\nМест: 1/2"},
    {"type": "list", "items": [
        {
            "blocks": [{"type": "paragraph", "text": "dayyson (Организатор)"}],
            "has_checkbox": True,
            "is_checked": True
        },
        {
            "blocks": [{"type": "paragraph", "text": "Свободный слот"}],
            "has_checkbox": True,
            "is_checked": False
        }
    ]}
]}}
req=urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/sendRichMessage', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
try:
    res=urllib.request.urlopen(req)
    print(res.read().decode())
except Exception as e:
    print(e.read().decode())
