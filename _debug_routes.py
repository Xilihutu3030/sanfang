# -*- coding: utf-8 -*-
"""Quick debug: test if /system route is registered"""
import sys, os
sys.path.insert(0, r'g:\三防指挥系统')
os.chdir(r'g:\三防指挥系统')

from app import app

print("Registered routes:")
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    print(f"  {rule.rule:40s} -> {rule.endpoint}")

print()
# Test with test client
with app.test_client() as c:
    r1 = c.get('/')
    print(f"GET /        -> {r1.status_code}")
    r2 = c.get('/system')
    print(f"GET /system  -> {r2.status_code}")
    r3 = c.get('/favicon.png')
    print(f"GET /favicon -> {r3.status_code}")
