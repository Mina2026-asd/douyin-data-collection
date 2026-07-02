#!/usr/bin/env python3
"""
抖音数据采集脚本 —— GitHub Actions 专用

功能：
  1. 读取 GitHub Secrets 中的 Cookie
  2. 使用 Playwright 访问 3 个抖音账号主页
  3. 调用抖音 API 获取最新视频数据
  4. 调用飞书 Open API 写入多维表

环境变量（从 GitHub Secrets 注入）：
  DOUYIN_COOKIES    - 抖音 Cookie JSON 数组
  FEISHU_APP_ID     - 飞书应用 App ID
  FEISHU_APP_SECRET - 飞书应用 App Secret
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

# ============================================================
# 配置
# ============================================================
CST = timezone(timedelta(hours=8))

# 飞书多维表
FEISHU_APP_TOKEN = "USO1bXpU1a9pScsRhrgchbc5n9g"
FEISHU_TABLE_ID = "tblOFknpGbLMwb1V"
FEISHU_BASE_URL = "https://maiyamedia.feishu.cn/base/USO1bXpU1a9pScsRhrgchbc5n9g"

# 账号列表
ACCOUNTS = [
    {
        "name": "记忆星球",
        "douyin_id": "30547611923",
        "sec_uid": "MS4wLjABAAAAH6AtfrwGrticYZW_gVTTM_lcxUD3jpTbLN_NzbtZq0_zQl9QnKtIQjM1w_IELWRv",
    },
    {
        "name": "麦猫",
        "douyin_id": "37681695466",
        "sec_uid": "MS4wLjABAAAAeukEzrESuE95O5MDDmBmll-DNQ8Do9WW5fnoD4aA8KM",
    },
    {
        "name": "高山流水",
        "douyin_id": "50448224245",
        "sec_uid": "MS4wLjABAAAAIA3cQS5umafsQuijQUb7BvIBRjYcaPOOZgw4xsEhOLFYtx4xT8s1fKohsJNpcrmt",
    },
]

# 日志
LOG_FILE = "/tmp/collect_log.txt"
RESULT_FILE = "/tmp/collect_result.json"

log_lines = []


def log(msg):
    line = f"[{datetime.now(CST).strftime('%H:%M:%S')}] {msg}"
    print(line)
    log_lines.append(line)


# ============================================================
# 飞书 API
# ============================================================
class FeishuAPI:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.token = None
        self.client = httpx.Client(timeout=30)

    def get_token(self):
        """获取 tenant_access_token"""
        resp = self.client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"获取飞书 Token 失败: {data}")
        self.token = data["tenant_access_token"]
        log(f"✓ 飞书 Token 获取成功")
        return self.token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def list_records(self, page_token=None):
        """列出多维表现有记录"""
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = self.client.get(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}"
            f"/tables/{FEISHU_TABLE_ID}/records",
            headers=self._headers(),
            params=params,
        )
        return resp.json()

    def batch_create_records(self, records):
        """批量创建记录（每批最多 500 条）"""
        resp = self.client.post(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}"
            f"/tables/{FEISHU_TABLE_ID}/records/batch_create",
            headers=self._headers(),
            json={"records": records},
        )
        return resp.json()


# ============================================================
# 抖音数据采集
# ============================================================
def load_cookies():
    """从环境变量加载 Cookie"""
    raw = os.environ.get("DOUYIN_COOKIES", "")
    if not raw:
        raise Exception("环境变量 DOUYIN_COOKIES 为空，请先配置 GitHub Secrets")
    cookies = json.loads(raw)
    log(f"✓ 加载了 {len(cookies)} 个 Cookie")
    return cookies


def fetch_user_videos(cookies, sec_uid, max_count=10):
    """
    通过抖音 Web API 获取用户视频列表
    使用 httpx 模拟浏览器请求
    """
    # 构建 Cookie 字符串
    cookie_str = "; ".join(
        f"{c['name']}={c['value']}" for c in cookies
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
        "Cookie": cookie_str,
    }

    videos = []
    max_cursor = 0
    has_more = True

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        while has_more and len(videos) < max_count:
            params = {
                "sec_user_id": sec_uid,
                "count": min(30, max_count - len(videos) + 5),
                "max_cursor": max_cursor,
                "aid": "1128",
                "app_name": "douyin_web",
                "channel": "channel_pc_web",
                "device_platform": "webapp",
                "pc_client_type": "1",
                "version_code": "170400",
                "version_name": "17.4.0",
                "cookie_enabled": "true",
                "screen_width": "1280",
                "screen_height": "800",
                "browser_language": "zh-CN",
                "browser_platform": "Win32",
                "browser_name": "Chrome",
                "browser_version": "120.0.0.0",
                "browser_online": "true",
                "engine_name": "Blink",
                "engine_version": "120.0.0.0",
                "os_name": "Windows",
                "os_version": "10",
                "cpu_core_num": "8",
                "device_memory": "8",
                "platform": "PC",
                "downlink": "10",
                "effective_type": "4g",
                "round_trip_time": "100",
            }

            resp = client.get(
                "https://www.douyin.com/aweme/v1/web/aweme/post/",
                params=params,
                headers=headers,
            )

            if resp.status_code != 200:
                log(f"  API 请求失败: HTTP {resp.status_code}")
                break

            data = resp.json()
            aweme_list = data.get("aweme_list", [])

            if not aweme_list:
                break

            for aweme in aweme_list:
                stat = aweme.get("statistics", {})
                videos.append({
                    "aweme_id": aweme.get("aweme_id", ""),
                    "title": aweme.get("desc", ""),
                    "create_time": aweme.get("create_time", 0),
                    "video_url": f"https://www.douyin.com/video/{aweme.get('aweme_id', '')}",
                    "digg_count": stat.get("digg_count", 0),
                    "comment_count": stat.get("comment_count", 0),
                    "collect_count": stat.get("collect_count", 0),
                    "share_count": stat.get("share_count", 0),
                    "play_count": stat.get("play_count", 0),
                })

            max_cursor = data.get("max_cursor", 0)
            has_more = data.get("has_more", 0) == 1

            # 速率限制
            time.sleep(0.5)

    return videos[:max_count]


def collect_all():
    """采集所有账号数据"""
    cookies = load_cookies()
    all_data = []

    for acc in ACCOUNTS:
        log(f"采集账号「{acc['name']}」({acc['douyin_id']})...")
        try:
            videos = fetch_user_videos(cookies, acc["sec_uid"], max_count=10)
            log(f"  ✓ 获取到 {len(videos)} 个视频")
            for v in videos:
                v["account_name"] = acc["name"]
                v["sec_uid"] = acc["sec_uid"]
            all_data.extend(videos)
        except Exception as e:
            log(f"  ✗ 失败: {e}")
            traceback.print_exc()

    log(f"总计采集 {len(all_data)} 条视频数据")
    return all_data


# ============================================================
# 数据去重与写入飞书
# ============================================================
def build_records(videos):
    """将视频数据转为飞书多维表记录格式"""
    now = datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    records = []
    for v in videos:
        create_ts = v.get("create_time", 0)
        if create_ts:
            create_time = datetime.fromtimestamp(create_ts, CST).strftime(
                "%Y-%m-%dT%H:%M:%S+08:00"
            )
        else:
            create_time = ""

        # 视频链接使用 link 类型
        video_url = v.get("video_url", "")
        link_field = {
            "link": video_url,
            "text": v.get("title", "")[:50] or "查看视频",
        }

        records.append({
            "fields": {
                "账号名称": v.get("account_name", ""),
                "账号ID": v.get("sec_uid", ""),
                "视频标题": v.get("title", ""),
                "视频链接": link_field,
                "发布时间": create_time,
                "浏览量": v.get("play_count", 0),
                "点赞数": v.get("digg_count", 0),
                "评论数": v.get("comment_count", 0),
                "收藏数": v.get("collect_count", 0),
                "分享数": v.get("share_count", 0),
                "采集时间": now,
            }
        })
    return records


def get_existing_video_links(api):
    """获取表中已有的视频链接，用于去重"""
    existing = set()
    page_token = None
    while True:
        data = api.list_records(page_token)
        if data.get("code") != 0:
            log(f"获取已有记录失败: {data}")
            break
        items = data.get("data", {}).get("items", [])
        for item in items:
            link_field = item.get("fields", {}).get("视频链接", {})
            if isinstance(link_field, dict):
                link = link_field.get("link", "")
            else:
                link = str(link_field) if link_field else ""
            if link:
                existing.add(link)
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")
    log(f"多维表中已有 {len(existing)} 条记录")
    return existing


def sync_to_feishu(api, records):
    """去重后写入飞书多维表"""
    existing = get_existing_video_links(api)
    new_records = []

    for r in records:
        link = ""
        link_field = r["fields"].get("视频链接", {})
        if isinstance(link_field, dict):
            link = link_field.get("link", "")
        if link and link not in existing:
            new_records.append(r)

    if not new_records:
        log("没有新数据，跳过写入")
        return {"inserted": 0, "skipped": len(records)}

    # 批量写入（每批 500 条）
    total = len(new_records)
    inserted = 0
    batch_size = 500

    for i in range(0, total, batch_size):
        batch = new_records[i : i + batch_size]
        resp = api.batch_create_records(batch)
        if resp.get("code") == 0:
            count = len(resp.get("data", {}).get("records", []))
            inserted += count
            log(f"  写入批次 {i // batch_size + 1}: {count} 条")
        else:
            log(f"  写入失败: {resp}")

    log(f"✓ 写入完成: 新增 {inserted} 条, 跳过 {len(records) - inserted} 条（已存在）")
    return {"inserted": inserted, "skipped": len(records) - inserted}


# ============================================================
# 主流程
# ============================================================
def main():
    log("=" * 60)
    log("抖音数据采集 → 飞书多维表 (GitHub Actions)")
    log("=" * 60)

    # 1. 采集抖音数据
    log("步骤 1/3: 采集抖音数据")
    videos = collect_all()

    if not videos:
        log("✗ 未采集到任何数据")
        save_result({"status": "empty", "videos": []})
        return

    # 2. 连接飞书
    log("步骤 2/3: 连接飞书")
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        log("⚠ 未配置飞书应用凭证，仅保存采集结果到文件")
        save_result({"status": "no_auth", "videos": videos})
        return

    api = FeishuAPI(app_id, app_secret)
    api.get_token()

    # 3. 写入多维表
    log("步骤 3/3: 写入飞书多维表")
    records = build_records(videos)
    result = sync_to_feishu(api, records)

    # 保存结果
    save_result({
        "status": "success",
        "total_videos": len(videos),
        "inserted": result["inserted"],
        "skipped": result["skipped"],
        "accounts": [a["name"] for a in ACCOUNTS],
        "videos": [
            {
                "account": v["account_name"],
                "title": v["title"][:40],
                "url": v["video_url"],
                "likes": v["digg_count"],
            }
            for v in videos[:5]
        ],
    })

    log("=" * 60)
    log("✓ 全部完成")
    log("=" * 60)


def save_result(data):
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))


if __name__ == "__main__":
    main()
