import os
import subprocess

print("=== Mount points ===")
res = subprocess.run(["mount"], capture_output=True, text=True)
for line in res.stdout.splitlines():
    if any(k in line for k in ["/mnt", "/media", "drvfs", "cgroup", "sd", "workspace"]):
        print(line)

print("\n=== /mnt contents ===")
if os.path.exists("/mnt"):
    print(os.listdir("/mnt"))

print("\n=== /media contents ===")
if os.path.exists("/media"):
    print(os.listdir("/media"))

print("\n=== /workspace contents ===")
if os.path.exists("/workspace"):
    print(os.listdir("/workspace"))
    if os.path.exists("/workspace/tutorials"):
        print("tutorials:", os.listdir("/workspace/tutorials"))
