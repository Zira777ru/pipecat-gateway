import requests
import json

def configure_app():
    app_uuid = "gg08gkw88sg4gks080ggg0cs"
    token = "3|claude-api-token-igor-2026"
    url = f"http://localhost:8000/api/v1/applications/{app_uuid}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Set FQDN
    fqdn_payload = {
        "fqdn": "https://voice.coscore.us"
    }
    requests.patch(url, headers=headers, json=fqdn_payload)

    # Set Env Var
    env_url = f"{url}/envs"
    env_payload = {
        "key": "GOOGLE_API_KEY",
        "value": "REDACTED",
        "is_public": False
    }
    requests.post(env_url, headers=headers, json=env_payload)

    # Deploy
    deploy_url = f"{url}/start"
    resp = requests.post(deploy_url, headers=headers)
    print(json.dumps(resp.json(), indent=2))

if __name__ == "__main__":
    configure_app()
