from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)
r = client.get("/api/cases")
print(f"Status: {r.status_code}")
data = r.json()
cases = data.get("cases", [])
print(f"Cases: {len(cases)}")
for c in cases[:5]:
    src = c.get("source", "?")
    print(f"  {c['id']} ({src})")
print(f"Total: {data.get('total', 0)}")
