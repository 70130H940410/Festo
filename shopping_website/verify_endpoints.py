import urllib.request

try:
    resp = urllib.request.urlopen("http://localhost:5000/manager/orders")
    print("GET /manager/orders code:", resp.getcode())
except Exception as e:
    print("GET /manager/orders error:", e)

try:
    resp = urllib.request.urlopen("http://localhost:5000/factory/api/mes_alerts")
    print("GET /factory/api/mes_alerts code:", resp.getcode(), resp.read()[:200])
except Exception as e:
    print("GET /factory/api/mes_alerts error:", e)
