import urllib.request, json
TOKEN='8146945075:AAHh3vmKX3GaV5nMC5QKjI_8u-qE2imCY24'

# Send msg
payload={'chat_id': '7693936576', 'text': 'test msg'}
req=urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/sendMessage', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
res = urllib.request.urlopen(req)
data = json.loads(res.read().decode())
msg_id = data['result']['message_id']
print(f"Sent: {msg_id}")

# Edit it
payload2={'chat_id': '7693936576', 'message_id': msg_id, 'rich_message': {'blocks': [
    {"type": "heading", "text": "🛡️ Управление Ролями", "size": 2},
    {"type": "paragraph", "text": "📊 Статистика группы:"}
]}}
req2=urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/editMessageText', data=json.dumps(payload2).encode('utf-8'), headers={'Content-Type': 'application/json'})
try:
    res2=urllib.request.urlopen(req2)
    print("Edit success:", res2.read().decode())
except Exception as e:
    print("Edit error:", e.read().decode())
