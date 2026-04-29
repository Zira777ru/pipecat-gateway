import base64
import json
import requests
import os

def deploy():
    url = "http://localhost:8000/api/v1/services"
    token = "3|claude-api-token-igor-2026"
    
    with open("/home/igor/pipecat-gateway/docker-compose.yaml", "rb") as f:
        compose_raw = f.read()
        compose_b64 = base64.b64encode(compose_raw).decode("utf-8")
    
    payload = {
        "project_uuid": "yoo484ksc04cooosc0wk08g8",
        "environment_name": "production",
        "server_uuid": "f0kgss8ccgksokkscgc0sk4s",
        "docker_compose_raw": compose_b64
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, headers=headers, json=payload)
    print(json.dumps(response.json(), indent=2))

if __name__ == "__main__":
    deploy()
