"""
One-time script to get your Strava refresh token.
Run this once, paste the token into .env, then use training_agent.py normally.
"""
import os
import webbrowser
from urllib.parse import urlparse, parse_qs
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REDIRECT_URI = "http://localhost"

auth_url = (
    f"https://www.strava.com/oauth/authorize"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}"
    f"&response_type=code"
    f"&scope=activity:read_all"
)

print("Opening Strava authorization in your browser...")
webbrowser.open(auth_url)

print("\nAfter authorizing, you'll be redirected to a localhost URL.")
redirected = input("Paste the full redirect URL here: ").strip()

code = parse_qs(urlparse(redirected).query)["code"][0]

response = requests.post("https://www.strava.com/oauth/token", data={
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code": code,
    "grant_type": "authorization_code",
})
response.raise_for_status()
tokens = response.json()

print(f"\nSuccess! Add this to your .env file:")
print(f"STRAVA_REFRESH_TOKEN={tokens['refresh_token']}")
