import requests

base_url = "http://localhost:8000/api/v1"

# The UI uses a fixed "admin" or just hits an endpoint to get an anonymous token, wait
# actually let's look at `frontend/src/api.ts` or `frontend/src/stores/auth.ts`
# But let's just try logging in with admin/admin
resp = requests.post(f"{base_url}/user/login", json={"username": "admin", "password": "password"})
if resp.status_code == 200:
    token = resp.json().get("token")
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{base_url}/industry/brain", headers=headers)
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)
else:
    # try registering
    requests.post(f"{base_url}/user/register", json={"username": "admin2", "password": "password", "nickname": "admin"})
    resp = requests.post(f"{base_url}/user/login", json={"username": "admin2", "password": "password"})
    if resp.status_code == 200:
        token = resp.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{base_url}/industry/brain", headers=headers)
        print("STATUS:", r.status_code)
        print("RESPONSE:", r.text)
    else:
        print("LOGIN FAILED:", resp.text)
