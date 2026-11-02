#!/usr/bin/env python3
"""
github_discovery.py - Autonomous GitHub Topics & Repository Discovery Engine for Russian Whitelists (БС) & Bypass
Searches GitHub for repositories tagged with russia, whitelist, vless, xray, antizapret, etc.
Extracts, validates, and dynamically registers new subscription sources.
Persists discovered sources to discovered_sources.json and triggers verification engine.
"""

import os
import sys
import time
import json
import re
import base64
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# Add script directory to sys.path to import whitelist_engine helpers
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from whitelist_engine import (
    SOURCES,
    WORK_DIR,
    LOCAL_PROXY,
    fetch_url,
    decode_subscription_payload,
    WhitelistMatcher,
    run_harvest_and_test
)

DISCOVERED_FILE = os.path.join(WORK_DIR, "discovered_sources.json")
EXCLUDED_REPOS = {
    "u23jd9/russia-whitelist-vpn",
    "u23jd9/freesota"
}

SEARCH_QUERIES = [
    "topic:russia topic:whitelist",
    "topic:vless topic:whitelist",
    "topic:xray topic:whitelist",
    "topic:russia-whitelist",
    "topic:whitelist-vpn",
    "topic:vless-configs",
    "topic:vless-subscription",
    "\"белые списки\" vless in:description,readme",
    "\"белый список\" vless in:description,readme",
    "\"белые списки\" xray in:description,readme",
    "russia whitelist vless in:description,readme",
    "russia whitelist xray in:description,readme",
    "russia mobile whitelist in:description,readme",
    "antizapret vless in:description,readme"
]

def load_discovered_sources():
    if os.path.exists(DISCOVERED_FILE):
        try:
            with open(DISCOVERED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Failed to read {DISCOVERED_FILE}: {e}")
    return []

def save_discovered_sources(sources):
    with open(DISCOVERED_FILE, "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2, ensure_ascii=False)
    print(f"[✓] Saved {len(sources)} discovered sources to {DISCOVERED_FILE}")

def get_known_urls():
    known = {s["url"] for s in SOURCES}
    for d in load_discovered_sources():
        if "url" in d:
            known.add(d["url"])
    return known

def search_github_repositories():
    """
    Executes gh search repos across all target queries and topics.
    Returns list of unique repo objects.
    """
    all_repos = {}
    print("[*] Searching GitHub topics and keywords for Russian whitelist repositories...")

    for q in SEARCH_QUERIES:
        cmd = [
            "gh", "search", "repos", q,
            "--limit", "30",
            "--json", "fullName,description,url,stargazersCount,updatedAt,defaultBranch"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if res.returncode == 0 and res.stdout.strip():
                items = json.loads(res.stdout)
                added = 0
                for item in items:
                    fn = item.get("fullName", "")
                    if fn and fn.lower() not in EXCLUDED_REPOS:
                        if fn not in all_repos:
                            all_repos[fn] = item
                            added += 1
                print(f"  -> '{q}': found {len(items)} repos ({added} new)")
            else:
                print(f"  -> '{q}': 0 repos")
        except Exception as e:
            print(f"  [!] Query failed '{q}': {e}")

    print(f"[+] Total unique candidate repositories discovered: {len(all_repos)}")
    return list(all_repos.values())

def inspect_repo_for_subscriptions(repo_meta, matcher, known_urls):
    """
    Scans a repository's contents and README for raw subscription files and URLs.
    Validates candidates by downloading and decoding proxies.
    Returns list of valid source dicts.
    """
    repo_full = repo_meta["fullName"]
    default_branch = repo_meta.get("defaultBranch", "main") or "main"
    stars = repo_meta.get("stargazersCount", 0)
    owner = repo_full.split("/")[0]

    discovered = []
    candidate_urls = set()

    # 1. Inspect repository file contents
    try:
        cmd = ["gh", "api", f"repos/{repo_full}/contents"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            contents = json.loads(res.stdout)
            if isinstance(contents, list):
                for item in contents:
                    name = item.get("name", "").lower()
                    t = item.get("type", "")
                    d_url = item.get("download_url")

                    # Check files
                    if t == "file" and d_url:
                        if name.endswith((".txt", ".sub", ".yaml", ".json")) or any(
                            k in name for k in ["whitelist", "white", "bl", "bs", "vless", "final", "keys", "proxy", "config", "sub"]
                        ):
                            # Skip obvious non-subscription files
                            if not any(k in name for k in ["license", "requirement", "docker", "caddy", "package", "setup"]):
                                candidate_urls.add((item.get("name"), d_url))

                    # Check subdirectories of interest
                    elif t == "dir" and name in ["configs", "subs", "sub", "checked", "vpn", "whitelist", "keys"]:
                        sub_cmd = ["gh", "api", f"repos/{repo_full}/contents/{name}"]
                        sub_res = subprocess.run(sub_cmd, capture_output=True, text=True, timeout=10)
                        if sub_res.returncode == 0:
                            sub_contents = json.loads(sub_res.stdout)
                            if isinstance(sub_contents, list):
                                for s_item in sub_contents:
                                    s_name = s_item.get("name", "")
                                    s_url = s_item.get("download_url")
                                    if s_url and s_name.endswith((".txt", ".sub", ".yaml", ".json")):
                                        candidate_urls.add((f"{name}/{s_name}", s_url))
    except Exception:
        pass

    # 2. Inspect README.md for subscription links
    try:
        cmd = ["gh", "api", f"repos/{repo_full}/readme"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if res.returncode == 0:
            r_data = json.loads(res.stdout)
            content_b64 = r_data.get("content", "")
            readme_text = base64.b64decode(content_b64).decode("utf-8", errors="ignore")

            # Extract URLs
            found_urls = re.findall(
                r'https?://(?:raw\.githubusercontent\.com|gitverse\.ru|hub\.mos\.ru|gist\.githubusercontent\.com|[a-zA-Z0-9_\-\.]+\.workers\.dev)/[^\s\)\"\'>]+',
                readme_text
            )
            for u in found_urls:
                u_clean = u.rstrip(".,;")
                candidate_urls.add((f"README ({os.path.basename(u_clean) or 'sub'})", u_clean))
    except Exception:
        pass

    # 3. Validate each candidate URL
    for label, u in candidate_urls:
        if u in known_urls:
            continue

        raw = fetch_url(u, timeout=6)
        if not raw:
            continue

        keys = decode_subscription_payload(raw)
        if len(keys) >= 2:  # Valid subscription with multiple keys
            # Detect Whitelist (БС) features
            bs_count = 0
            for k in keys[:30]:
                try:
                    parsed = urllib.parse.urlparse(k)
                    q = urllib.parse.parse_qs(parsed.query)
                    sni = q.get("sni", [""])[0].lower()
                    host = parsed.hostname or ""
                    if matcher.is_whitelist_sni(sni) or matcher.is_whitelist_ip(host):
                        bs_count += 1
                except Exception:
                    pass

            is_bs = bs_count > 0 or "white" in label.lower() or "бс" in label.lower() or "wl" in label.lower()
            category = "GitHub БС" if is_bs else "GitHub Bypass"

            source_item = {
                "name": f"{repo_full} ({label})",
                "category": category,
                "url": u,
                "author": owner,
                "link": f"https://github.com/{repo_full}",
                "stars": stars,
                "keys_count": len(keys),
                "is_bs": is_bs,
                "discovered_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            discovered.append(source_item)
            known_urls.add(u)
            print(f"    [+] VALID SOURCE: {source_item['name']} ({len(keys)} keys, {category})")

    return discovered

def run_github_discovery(run_engine_after=True):
    print("=" * 65)
    print("  GITHUB TOPICS & REPOSITORY WHITELIST DISCOVERY ENGINE")
    print(f"  Started at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    matcher = WhitelistMatcher()
    matcher.load_from_web()

    existing_discovered = load_discovered_sources()
    known_urls = get_known_urls()

    # Determine next available ID
    current_ids = [s["id"] for s in SOURCES] + [d.get("id", 0) for d in existing_discovered]
    next_id = max(current_ids, default=47) + 1

    candidate_repos = search_github_repositories()
    newly_found = []
    seen_new_urls = set()

    print(f"\n[*] Inspecting {len(candidate_repos)} candidate repositories in parallel (10 workers)...")
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(inspect_repo_for_subscriptions, repo, matcher, set(known_urls)): repo for repo in candidate_repos}
        done_cnt = 0
        for fut in concurrent.futures.as_completed(futures):
            done_cnt += 1
            repo = futures[fut]
            try:
                found = fut.result()
                for item in found:
                    u = item["url"]
                    if u not in known_urls and u not in seen_new_urls:
                        seen_new_urls.add(u)
                        item["id"] = next_id
                        next_id += 1
                        newly_found.append(item)
            except Exception as e:
                pass
            if done_cnt % 25 == 0 or done_cnt == len(candidate_repos):
                print(f"  Processed {done_cnt}/{len(candidate_repos)} repositories... ({len(newly_found)} valid sources found so far)")

    print("\n" + "=" * 65)
    print(f"  DISCOVERY COMPLETE: {len(newly_found)} NEW SUBSCRIPTION SOURCES FOUND")
    print("=" * 65)

    if newly_found:
        total_discovered = existing_discovered + newly_found
        save_discovered_sources(total_discovered)

        # Print table of new sources
        print("\nNew Discovered Sources:")
        for s in newly_found:
            print(f"  #{s['id']} [{s['category']}] {s['name']} -> {s['keys_count']} keys | {s['link']}")

        if run_engine_after:
            print("\n[*] Triggering whitelist verification engine with all sources...")
            run_harvest_and_test()
    else:
        print("[*] No new unique subscription sources found this cycle.")
        if run_engine_after:
            # Still run scheduled verification of existing sources
            run_harvest_and_test()

if __name__ == "__main__":
    run_github_discovery(run_engine_after=True)
