#!/usr/bin/env python
"""
Quick test of running API endpoints
"""
import requests
import time
import sys

print("=" * 70)
print("API ENDPOINT CONNECTIVITY TEST")
print("=" * 70)

BASE_URLS = {
    "main": "http://localhost:8000",
    "api": "http://localhost:8001",
}

endpoints = {
    "main": [
        ("GET", "/health"),
        ("GET", "/api/live-metrics"),
        ("GET", "/api/timeline"),
    ],
    "api": [
        ("GET", "/"),
        ("GET", "/metrics"),
        ("GET", "/session/status"),
    ],
}

print("\n[CHECKING MAIN SERVER (port 8000)]")
try:
    resp = requests.get("http://localhost:8000/health", timeout=2)
    print(f"  ✓ Server is running")
    print(f"    Status: {resp.status_code}")
    print(f"    Response: {resp.json()}")
except Exception as e:
    print(f"  ✗ Server not responding: {e}")
    print("    Start with: uvicorn main:app --host 0.0.0.0 --port 8000 --reload")

print("\n[CHECKING API SERVER (port 8001)]")
try:
    resp = requests.get("http://localhost:8001/", timeout=2)
    print(f"  ✓ Server is running")
    print(f"    Status: {resp.status_code}")
    print(f"    Response: {resp.json()}")
except Exception as e:
    print(f"  ✗ Server not responding: {e}")
    print("    Start with: cd classroom-dashboard/model1 && uvicorn api_server:app --host 0.0.0.0 --port 8001 --reload")

print("\n[SAMPLE ENDPOINT TESTS]")

# Test main server endpoints
print("\n► main.py endpoints:")
for method, endpoint in endpoints["main"]:
    try:
        url = BASE_URLS["main"] + endpoint
        if method == "GET":
            resp = requests.get(url, timeout=2)
        else:
            resp = requests.post(url, timeout=2)
        print(f"  ✓ {method:4s} {endpoint:30s} → {resp.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  ✗ {method:4s} {endpoint:30s} → SERVER NOT RUNNING")
    except Exception as e:
        print(f"  ✗ {method:4s} {endpoint:30s} → {str(e)[:40]}")

# Test api server endpoints
print("\n► api_server.py endpoints:")
for method, endpoint in endpoints["api"]:
    try:
        url = BASE_URLS["api"] + endpoint
        if method == "GET":
            resp = requests.get(url, timeout=2)
        else:
            resp = requests.post(url, timeout=2)
        print(f"  ✓ {method:4s} {endpoint:30s} → {resp.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"  ✗ {method:4s} {endpoint:30s} → SERVER NOT RUNNING")
    except Exception as e:
        print(f"  ✗ {method:4s} {endpoint:30s} → {str(e)[:40]}")

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)
