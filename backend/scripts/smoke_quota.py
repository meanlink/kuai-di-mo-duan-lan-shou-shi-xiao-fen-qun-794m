"""名额台账冒烟验证：设置名额、幂等更新、权限与入参校验。

先启动 docker compose 栈，再在宿主机运行：
    python backend/scripts/smoke_quota.py
或在容器内运行：
    docker compose exec backend python -m scripts.smoke_quota
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = os.getenv('BASE_URL', 'http://127.0.0.1:19243')
PASSWORD = 'Pickup1044!'


def call(method, path, token=None, data=None):
    request = urllib.request.Request(BASE + path, method=method)
    request.add_header('Accept', 'application/json')
    if token:
        request.add_header('Authorization', f'Bearer {token}')
    body = None
    if data is not None:
        request.add_header('Content-Type', 'application/json')
        body = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(request, body) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def check(label, condition, detail=''):
    print(f'{"PASS" if condition else "FAIL"} {label} {detail if not condition else ""}'.rstrip())
    if not condition:
        raise SystemExit(1)


def main():
    _, admin = call('POST', '/auth/login', data={'username': 'admin', 'password': PASSWORD})
    _, analyst = call('POST', '/auth/login', data={'username': 'analyst', 'password': PASSWORD})
    admin_token, analyst_token = admin['token'], analyst['token']

    plan = {'region': '上城片区', 'business_date': '2026-12-10', 'shift': 'afternoon', 'capacity': 3}
    status, quota = call('PUT', '/shift-quotas', admin_token, plan)
    check('主管设置名额', status == 200 and quota['capacity'] == 3 and quota['available'] == 3, quota)

    status, again = call('PUT', '/shift-quotas', admin_token, {**plan, 'capacity': 5})
    check('重复设置幂等更新', status == 200 and again['capacity'] == 5 and again['id'] == quota['id'], again)

    region = urllib.parse.quote(plan['region'])
    status, ledger = call('GET', f'/shift-quotas?start=2026-12-10&end=2026-12-10&region={region}', admin_token)
    row = next((item for item in ledger.get('quotas', []) if item['id'] == quota['id']), None)
    check('台账可查还可派人数', status == 200 and row is not None and row['available'] == 5, ledger)

    status, _ = call('PUT', '/shift-quotas', analyst_token, plan)
    check('非主管不能设置名额', status == 403)

    status, _ = call('PUT', '/shift-quotas', admin_token, {**plan, 'region': '不存在片区'})
    check('未知片区被拒绝', status == 422)

    status, _ = call('PUT', '/shift-quotas', admin_token, {**plan, 'capacity': 61})
    check('名额上限校验', status == 422)

    print('名额台账冒烟验证通过。占用、改期与实到结算请按 README 演示剧本走支援与补派全流程核对。')


if __name__ == '__main__':
    main()
