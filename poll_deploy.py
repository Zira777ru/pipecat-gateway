import requests
import time
import sys

def poll_deployment():
    deploy_uuid = "z8c80ck80c4s4k4o88kwkk4c"
    token = "3|claude-api-token-igor-2026"
    url = f"http://localhost:8000/api/v1/deployments/{deploy_uuid}"
    
    headers = {
        "Authorization": f"Bearer {token}"
    }

    print(f"Polling deployment {deploy_uuid}...")
    while True:
        try:
            resp = requests.get(url, headers=headers)
            status = resp.json().get("status")
            print(f"Status: {status}")
            if status in ["finished", "failed", "error"]:
                break
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(10)

if __name__ == "__main__":
    poll_deployment()
