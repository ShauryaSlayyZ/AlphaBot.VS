import urllib.request
import json

try:
    response = urllib.request.urlopen("http://127.0.0.1:58628/json")
    data = json.loads(response.read().decode())
    print(json.dumps(data, indent=2))
except Exception as e:
    print("Error:", e)
