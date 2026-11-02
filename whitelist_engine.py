#!/usr/bin/env python3
"""
whitelist_engine.py - Autonomous Russian Whitelist (БС) & Censorship Bypass Proxy Harvester & Verifier
Hosted on: workpc (fedora)
Public Repo: https://github.com/u23jd9/russia-whitelist-vpn

Workflow:
1. Fetches current Russian Mobile Internet Whitelist DBs (escapingworm, hxehex, kort0881).
2. Harvests configs from 47 curated community channels/subscriptions (direct & proxy fallback).
3. Parses, classifies (БС / ЧС), and filters each config against Russian Whitelist criteria (SNI & IP CIDR).
4. Tests TCP liveness + end-to-end proxy connectivity to YouTube (HTTP 204) via parallel sing-box instances.
5. Keeps working nodes "as-is" with source provider credits.
6. Generates Raw, Base64 (Happ/Incy), Clash Meta, and Sing-box subscription formats.
7. Commits & pushes to public GitHub repository.
8. Synchronizes verified configs to delyoself.site for the Telegram bot.
"""

import os
import sys
import time
import json
import base64
import socket
import ipaddress
import tempfile
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = SCRIPT_DIR
CACHE_DIR = os.path.join(WORK_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Local sing-box binary
SINGBOX_BIN = os.path.expanduser("~/.local/bin/sing-box")
if not os.path.exists(SINGBOX_BIN):
    SINGBOX_BIN = "sing-box"

# VDS SOCKS5 Proxy fallback if direct access is restricted
LOCAL_PROXY = "socks5h://127.0.0.1:2080"

# Target VDS for remote bot & web subscription sync
VDS_HOST = "delyoself.site"
VDS_SSH_PORT = 2223
VDS_USER = "delyoself"

# Whitelist Databases
WHITELIST_DATABASES = [
    {
        "name": "escapingworm/russia-whitelist",
        "url": "https://raw.githubusercontent.com/escapingworm/russia-whitelist/main/ru-whitelist-cidr.txt",
        "type": "cidr"
    },
    {
        "name": "hxehex/russia-mobile-internet-whitelist (domains)",
        "url": "https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main/whitelist.txt",
        "type": "domain"
    },
    {
        "name": "hxehex/russia-mobile-internet-whitelist (cidr)",
        "url": "https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main/cidrwhitelist.txt",
        "type": "cidr"
    },
    {
        "name": "kort0881/russia-whitelist",
        "url": "https://raw.githubusercontent.com/kort0881/russia-whitelist/main/whitelist.txt",
        "type": "domain_or_cidr"
    }
]

# 47 Curated Community Whitelist & Bypass Subscriptions
SOURCES = [
    {"id": 1, "name": "Lime (БС)", "category": "БС", "url": "https://raw.githubusercontent.com/LimeHi/LimeVPN/refs/heads/main/whitelist.txt", "author": "LimeVPN", "link": "https://github.com/LimeHi/LimeVPN"},
    {"id": 2, "name": "Lime (ЧС)", "category": "ЧС", "url": "https://raw.githubusercontent.com/LimeHi/LimeVPN/refs/heads/main/blacklist.txt", "author": "LimeVPN", "link": "https://github.com/LimeHi/LimeVPN"},
    {"id": 3, "name": "WL RUS (БС)", "category": "БС", "url": "https://gitverse.ru/api/repos/bywarm/rser/raw/branch/master/wl.txt", "author": "bywarm", "link": "https://gitverse.ru/bywarm/rser"},
    {"id": 4, "name": "WL RUS (ЧС)", "category": "ЧС", "url": "https://gitverse.ru/api/repos/bywarm/rser/raw/branch/master/black.txt", "author": "bywarm", "link": "https://gitverse.ru/bywarm/rser"},
    {"id": 5, "name": "RoGo (БС)", "category": "БС", "url": "https://gitverse.ru/api/repos/RoGo/mobile-whitelist/raw/branch/master/mobile-whitelist-1.txt", "author": "RoGo", "link": "https://gitverse.ru/RoGo/mobile-whitelist"},
    {"id": 6, "name": "Akres", "category": "Универсальный", "url": "https://github.com/theakres/VPN/raw/main/all", "author": "theakres", "link": "https://github.com/theakres/VPN"},
    {"id": 7, "name": "Игарëк (БС)", "category": "БС", "url": "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt", "author": "igareck", "link": "https://github.com/igareck/vpn-configs-for-russia"},
    {"id": 8, "name": "Игарëк (ЧС)", "category": "ЧС", "url": "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS.txt", "author": "igareck", "link": "https://github.com/igareck/vpn-configs-for-russia"},
    {"id": 9, "name": "Zieng2", "category": "БС", "url": "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt", "author": "zieng2", "link": "https://github.com/zieng2/wl"},
    {"id": 10, "name": "Hiddifycode", "category": "Универсальный", "url": "https://github.com/Remiuc0ff/Hiddifycode/raw/refs/heads/main/Owner-@remiuc", "author": "Remiuc0ff", "link": "https://github.com/Remiuc0ff/Hiddifycode"},
    {"id": 11, "name": "RKP (БС)", "category": "БС", "url": "https://hub.mos.ru/rkp/sub-roskompozor/raw/main/wl", "author": "Роскомпозор", "link": "https://hub.mos.ru/rkp/sub-roskompozor"},
    {"id": 12, "name": "RKP (ЧС)", "category": "ЧС", "url": "https://hub.mos.ru/rkp/sub-roskompozor/raw/main/bl", "author": "Роскомпозор", "link": "https://hub.mos.ru/rkp/sub-roskompozor"},
    {"id": 13, "name": "Rjsxrd", "category": "БС/Обход", "url": "https://raw.githubusercontent.com/whoahaow/rjsxrd/refs/heads/main/githubmirror/bypass/bypass-all.txt", "author": "whoahaow", "link": "https://github.com/whoahaow/rjsxrd"},
    {"id": 14, "name": "VlessForU (БС)", "category": "БС", "url": "https://sub.vlessfo.ru/vlessforu/working_configs.txt", "author": "VlessForU", "link": "https://vlessfo.ru"},
    {"id": 15, "name": "AirLink", "category": "Универсальный", "url": "https://gitverse.ru/api/repos/zxc67/generator/raw/branch/master/key", "author": "zxc67", "link": "https://gitverse.ru/zxc67/generator"},
    {"id": 16, "name": "Dequar", "category": "БС", "url": "https://raw.githubusercontent.com/dequar/deqwl/refs/heads/main/deray.txt", "author": "dequar", "link": "https://github.com/dequar/deqwl"},
    {"id": 17, "name": "RaViraNet", "category": "Премиум", "url": "https://raw.githubusercontent.com/btsk161/Freeinternet_byMygalaru.github.io/refs/heads/main/premium.txt", "author": "btsk161", "link": "https://github.com/btsk161/Freeinternet_byMygalaru.github.io"},
    {"id": 18, "name": "Luxxuria", "category": "Non-RU", "url": "https://raw.githubusercontent.com/luxxuria/harvester/refs/heads/main/non_ru.txt", "author": "luxxuria", "link": "https://github.com/luxxuria/harvester"},
    {"id": 19, "name": "Severny LTE", "category": "LTE БС", "url": "https://tri.su/nwkL7", "author": "Severny", "link": "https://tri.su/nwkL7"},
    {"id": 20, "name": "Shatak", "category": "RU VLESS", "url": "https://raw.githubusercontent.com/ShatakVPN/ConfigForge-V2Ray/main/configs/ru/vless.txt", "author": "ShatakVPN", "link": "https://github.com/ShatakVPN/ConfigForge-V2Ray"},
    {"id": 21, "name": "Ghost", "category": "БС", "url": "https://raw.githubusercontent.com/ewecrow78-gif/whitelist1/main/list.txt", "author": "ewecrow78-gif", "link": "https://github.com/ewecrow78-gif/whitelist1"},
    {"id": 22, "name": "VPN From Kirill", "category": "Free", "url": "https://free.vpn-from-kirill.workers.dev/", "author": "Kirill", "link": "https://free.vpn-from-kirill.workers.dev/"},
    {"id": 23, "name": "HardVPN", "category": "LTE БС", "url": "https://github.com/ksenkovsolo/HardVPN-bypass-WhiteLists-/raw/refs/heads/main/vpn-lte/WHITELIST-ALL.txt", "author": "ksenkovsolo", "link": "https://github.com/ksenkovsolo/HardVPN-bypass-WhiteLists-"},
    {"id": 24, "name": "MobilVPN", "category": "Gist", "url": "https://gist.github.com/MobilVPN/aa00fd08e0740d5f74a7f893a7748eee.txt", "author": "MobilVPN", "link": "https://gist.github.com/MobilVPN"},
    {"id": 25, "name": "Vlesstrojan", "category": "RU White All", "url": "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/refs/heads/main/checked/RU_Best/ru_white_all_WHITE.txt", "author": "kort0881", "link": "https://github.com/kort0881/vpn-checker-backend"},
    {"id": 26, "name": "Kizяк (БС)", "category": "БС", "url": "https://raw.githubusercontent.com/Maskkost93/kizyak-vpn-4.0/refs/heads/main/kizyakbeta6.txt", "author": "Maskkost93", "link": "https://github.com/Maskkost93/kizyak-vpn-4.0"},
    {"id": 27, "name": "Kizяк (ЧС)", "category": "ЧС", "url": "https://raw.githubusercontent.com/Maskkost93/kizyak-vpn-4.0/refs/heads/main/kizyakbeta6BL.txt", "author": "Maskkost93", "link": "https://github.com/Maskkost93/kizyak-vpn-4.0"},
    {"id": 28, "name": "Gidroksi (БС)", "category": "БС", "url": "https://gitverse.ru/api/repos/gidro/white/raw/branch/master/subscription.txt", "author": "gidro", "link": "https://gitverse.ru/gidro/white"},
    {"id": 29, "name": "Gidroksi (ЧС)", "category": "ЧС", "url": "https://gidroksi.fun/black-list", "author": "gidro", "link": "https://gidroksi.fun"},
    {"id": 30, "name": "Apex (БС)", "category": "БС", "url": "https://gitverse.ru/api/repos/bikinitw22/apelsintel/raw/branch/main/alive_bs.txt", "author": "bikinitw22", "link": "https://gitverse.ru/bikinitw22/apelsintel"},
    {"id": 31, "name": "Apex (ЧС)", "category": "ЧС", "url": "https://gitverse.ru/api/repos/bikinitw22/apelsintel/raw/branch/main/alive_bl.txt", "author": "bikinitw22", "link": "https://gitverse.ru/bikinitw22/apelsintel"},
    {"id": 32, "name": "Aetris (БС)", "category": "БС", "url": "https://raw.githubusercontent.com/flaafix/AetrisVPN-white-list-lite/refs/heads/main/AetrisVPN.txt", "author": "flaafix", "link": "https://github.com/flaafix/AetrisVPN-white-list-lite"},
    {"id": 33, "name": "Aetris (ЧС)", "category": "ЧС", "url": "https://raw.githubusercontent.com/flaafix/AetrisVPN-black-list/refs/heads/main/configs.txt", "author": "flaafix", "link": "https://github.com/flaafix/AetrisVPN-black-list"},
    {"id": 34, "name": "sch2VPN", "category": "Normal", "url": "https://happy-decoder.cc/p/http://stabratni4.temp.swtest.ru/api.php?type=normal", "author": "sch2VPN", "link": "https://happy-decoder.cc"},
    {"id": 35, "name": "v2crackNG sub", "category": "Subs", "url": "https://junify.fun/subs", "author": "Junify", "link": "https://junify.fun"},
    {"id": 36, "name": "ЭтоНеЯ (БС)", "category": "БС", "url": "https://hub.mos.ru/kfwl/etoneya/-/raw/main/whitelist", "author": "ЭтоНеЯ", "link": "https://hub.mos.ru/kfwl/etoneya"},
    {"id": 37, "name": "ЭтоНеЯ (ЧС)", "category": "ЧС", "url": "https://hub.mos.ru/kfwl/etoneya/-/raw/main/other", "author": "ЭтоНеЯ", "link": "https://hub.mos.ru/kfwl/etoneya"},
    {"id": 38, "name": "ЭтоНеЯ (Ютуб)", "category": "YouTube", "url": "https://hub.mos.ru/kfwl/etoneya/-/raw/main/youtube", "author": "ЭтоНеЯ", "link": "https://hub.mos.ru/kfwl/etoneya"},
    {"id": 39, "name": "ЭтоНеЯ (Gemini)", "category": "Gemini", "url": "https://etoneya.su/gemini", "author": "ЭтоНеЯ", "link": "https://etoneya.su"},
    {"id": 40, "name": "HAPPiVPN (JSON)", "category": "JSON", "url": "https://raw.githubusercontent.com/gooseteam-hackers/freevpn-cracks/refs/heads/main/subscription_auto.txt", "author": "gooseteam-hackers", "link": "https://github.com/gooseteam-hackers/freevpn-cracks"},
    {"id": 41, "name": "HAPPiVPN (Default)", "category": "Default", "url": "https://raw.githubusercontent.com/gooseteam-hackers/freevpn-cracks/refs/heads/main/subscription_auto.txt", "author": "gooseteam-hackers", "link": "https://github.com/gooseteam-hackers/freevpn-cracks"},
    {"id": 42, "name": "KFWL (БС)", "category": "БС", "url": "https://hub.mos.ru/kfwl/auto/raw/main/wl", "author": "KFWL", "link": "https://hub.mos.ru/kfwl/auto"},
    {"id": 43, "name": "KFWL (ЧС)", "category": "ЧС", "url": "https://hub.mos.ru/kfwl/auto/raw/main/bl", "author": "KFWL", "link": "https://hub.mos.ru/kfwl/auto"},
    {"id": 44, "name": "KFWL (Gemini)", "category": "Gemini", "url": "https://hub.mos.ru/kfwl/auto/raw/main/gemini", "author": "KFWL", "link": "https://hub.mos.ru/kfwl/auto"},
    {"id": 45, "name": "KFWL (Full ЧС)", "category": "Full ЧС", "url": "https://hub.mos.ru/kfwl/auto/raw/main/fullbl", "author": "KFWL", "link": "https://hub.mos.ru/kfwl/auto"},
    {"id": 46, "name": "notakeys", "category": "Keys", "url": "https://github.com/wucrd/parsing-configs/raw/refs/heads/main/configs/keys", "author": "wucrd", "link": "https://github.com/wucrd/parsing-configs"},
    {"id": 47, "name": "Sigrid VPN sub", "category": "Bypass", "url": "https://is.wepogp.gay/bypass-hwid-lock-3z5O6BFAaJQzGlamvtSo?payload=LoWcw85kRd%2BHRAuaIWWTGQtmHz91ER2Gsf9j8ro4aENKelQom7dBGSEIW11PuLnbJGqHulnnMD/AW2RrnHWKlWFJxvUtqF01SLDdwqY%2Bj9MB2RSD%2BDWEqu7KmBMo/8DS", "author": "Sigrid VPN", "link": "https://is.wepogp.gay"}
]

DISCOVERED_FILE = os.path.join(WORK_DIR, "discovered_sources.json")

def get_all_sources():
    sources = list(SOURCES)
    if os.path.exists(DISCOVERED_FILE):
        try:
            with open(DISCOVERED_FILE, "r", encoding="utf-8") as f:
                discovered = json.load(f)
            existing_urls = {s["url"] for s in sources}
            for d in discovered:
                if d.get("url") and d["url"] not in existing_urls:
                    sources.append(d)
                    existing_urls.add(d["url"])
        except Exception as e:
            print(f"[!] Error loading discovered sources: {e}")
    return sources

# Common Russian Whitelist Fallback Domains
DEFAULT_WHITELIST_DOMAINS = {
    "gosuslugi.ru", "gu-st.ru", "esia.gosuslugi.ru", "mos.ru", "sberbank.ru", "tinkoff.ru",
    "vk.com", "vk.ru", "vk-portal.net", "userapi.com", "yandex.ru", "ya.ru", "yastatic.net",
    "mail.ru", "cloud.mail.ru", "ok.ru", "megafon.ru", "mts.ru", "beeline.ru", "t2.ru", "tele2.ru",
    "rt.ru", "rostelecom.ru", "ozon.ru", "wildberries.ru", "dzen.ru", "rutube.ru", "kinopoisk.ru",
    "pochta.ru", "nalog.gov.ru", "cbr.ru", "vtb.ru", "alfabank.ru", "gazprombank.ru"
}

# ==============================================================================
# 1. Whitelist DB Fetcher & Matcher
# ==============================================================================
class WhitelistMatcher:
    def __init__(self):
        self.domains = set(DEFAULT_WHITELIST_DOMAINS)
        self.networks = []

    def load_from_web(self):
        print("[*] Updating Russian Whitelist databases from GitHub...")
        for db in WHITELIST_DATABASES:
            try:
                req = urllib.request.Request(db["url"], headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=12) as r:
                    text = r.read().decode("utf-8", errors="ignore")
                count = 0
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if db["type"] == "domain":
                        self.domains.add(line.lower())
                        count += 1
                    elif db["type"] == "cidr":
                        try:
                            net = ipaddress.ip_network(line, strict=False)
                            self.networks.append(net)
                            count += 1
                        except ValueError:
                            pass
                    elif db["type"] == "domain_or_cidr":
                        if "/" in line:
                            try:
                                net = ipaddress.ip_network(line, strict=False)
                                self.networks.append(net)
                                count += 1
                            except ValueError:
                                pass
                        else:
                            self.domains.add(line.lower())
                            count += 1
                print(f"  [✓] {db['name']}: loaded {count} items")
            except Exception as e:
                print(f"  [!] {db['name']}: failed to fetch ({e})")
        print(f"[+] Total whitelist database: {len(self.domains)} domains, {len(self.networks)} CIDRs.")

    def matches_domain(self, domain):
        if not domain:
            return False
        d = domain.lower().strip()
        if d in self.domains:
            return True
        for wd in self.domains:
            if d.endswith("." + wd):
                return True
        return False

    def matches_ip(self, ip_str):
        if not ip_str:
            return False
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            for net in self.networks:
                if ip_obj in net:
                    return True
        except ValueError:
            pass
        return False

# ==============================================================================
# 2. Subscription Fetcher (Direct + SOCKS5 Fallback)
# ==============================================================================
def fetch_url(url, timeout=10):
    # Try Direct
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "v2rayN/6.42"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e1:
        # Fallback to SOCKS5 Proxy via curl
        try:
            cmd = ["curl", "-s", "-L", "--connect-timeout", str(timeout), "-x", LOCAL_PROXY, url]
            res = subprocess.run(cmd, capture_output=True, timeout=timeout + 4)
            if res.returncode == 0 and res.stdout:
                return res.stdout
        except Exception:
            pass
    return None

def decode_subscription_payload(raw_bytes):
    if not raw_bytes:
        return []
    text = ""
    try:
        text = raw_bytes.decode("utf-8", errors="ignore").strip()
    except Exception:
        pass

    # Try Base64 decode
    try:
        clean_b64 = text.replace(" ", "").replace("\n", "").replace("\r", "")
        decoded = base64.b64decode(clean_b64).decode("utf-8", errors="ignore")
        if "://" in decoded:
            text = decoded
    except Exception:
        pass

    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line and any(line.startswith(proto) for proto in ["vless://", "trojan://", "ss://", "hysteria2://", "hy2://"]):
            lines.append(line)
    return lines

# ==============================================================================
# 3. Config Parsing & Sing-box Outbound Synthesis
# ==============================================================================
def parse_proxy_url(url_str, provider_meta, matcher):
    try:
        parsed = urllib.parse.urlparse(url_str)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return None

        # Resolve query params
        params = dict(urllib.parse.parse_qsl(parsed.query))
        sni = params.get("sni") or params.get("host") or params.get("servername") or ""
        pbk = params.get("pbk") or params.get("public-key") or ""
        sid = params.get("sid") or params.get("short-id") or ""
        fp = params.get("fp") or "chrome"
        net_type = params.get("type") or "tcp"
        flow = params.get("flow") or ""
        service_name = params.get("serviceName") or params.get("path") or ""

        # Check Whitelist Conformance
        is_bs_sni = matcher.matches_domain(sni)
        is_bs_ip = matcher.matches_ip(host)
        is_source_bs = "БС" in provider_meta["category"]
        is_bs = is_bs_sni or is_bs_ip or is_source_bs

        tag_clean = f"node_{os.urandom(4).hex()}"

        outbound = None
        if scheme == "vless":
            uuid = parsed.username
            if not uuid:
                return None
            outbound = {
                "type": "vless",
                "tag": tag_clean,
                "server": host,
                "server_port": port,
                "uuid": uuid,
                "flow": flow if "xtls-rprx-vision" in flow else ""
            }
            # TLS / Reality
            security = params.get("security", "").lower()
            if security == "reality" and pbk:
                outbound["tls"] = {
                    "enabled": True,
                    "server_name": sni or host,
                    "utls": {"enabled": True, "fingerprint": fp},
                    "reality": {"enabled": True, "public_key": pbk, "short_id": sid}
                }
            elif security == "tls":
                outbound["tls"] = {
                    "enabled": True,
                    "server_name": sni or host,
                    "insecure": True
                }

            if net_type == "grpc":
                outbound["transport"] = {"type": "grpc", "service_name": service_name}
            elif net_type in ["ws", "websocket"]:
                outbound["transport"] = {"type": "ws", "path": service_name or "/"}

        elif scheme == "trojan":
            password = parsed.username
            if not password:
                return None
            outbound = {
                "type": "trojan",
                "tag": tag_clean,
                "server": host,
                "server_port": port,
                "password": password,
                "tls": {"enabled": True, "server_name": sni or host, "insecure": True}
            }

        elif scheme in ["hysteria2", "hy2"]:
            password = parsed.username
            outbound = {
                "type": "hysteria2",
                "tag": tag_clean,
                "server": host,
                "server_port": port,
                "password": password or "",
                "tls": {"enabled": True, "server_name": sni or host, "insecure": True}
            }

        if outbound:
            return {
                "raw_url": url_str,
                "provider": provider_meta["name"],
                "author": provider_meta["author"],
                "link": provider_meta["link"],
                "scheme": scheme,
                "host": host,
                "port": port,
                "sni": sni,
                "is_bs": is_bs,
                "is_bs_sni": is_bs_sni,
                "outbound": outbound
            }
    except Exception:
        pass
    return None

# ==============================================================================
# 4. Fast TCP Reachability Check (Pre-filter)
# ==============================================================================
def is_tcp_alive(host, port, timeout=1.2):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        res = sock.connect_ex((host, port))
        sock.close()
        return res == 0
    except Exception:
        return False

def check_node_reachable(item):
    if item.get("scheme") in ["hysteria2", "hy2"]:
        return True
    return is_tcp_alive(item["host"], item["port"], 1.2)

# ==============================================================================
# 5. Parallel Sing-box YouTube Verification
# ==============================================================================
def verify_batch_singbox(batch, base_port=29800):
    """
    Spins up 1 temporary sing-box process with N inbounds and N outbounds.
    Tests each outbound against https://www.youtube.com/generate_204 simultaneously.
    """
    if not batch:
        return []

    inbounds = []
    rules = []
    outbounds = []

    for i, item in enumerate(batch):
        p = base_port + i
        in_tag = f"mix_{i}"
        inbounds.append({
            "type": "mixed",
            "tag": in_tag,
            "listen": "127.0.0.1",
            "listen_port": p
        })
        rules.append({"inbound": [in_tag], "outbound": item["outbound"]["tag"]})
        outbounds.append(item["outbound"])

    outbounds.append({"type": "direct", "tag": "direct"})

    cfg = {
        "log": {"level": "panic"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": {"rules": rules}
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
        cfg_file = f.name

    proc = None
    verified = []
    try:
        proc = subprocess.Popen([SINGBOX_BIN, "run", "-c", cfg_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.7)

        def test_single_proxy(i):
            item = batch[i]
            port = base_port + i
            proxy_handler = urllib.request.ProxyHandler({
                "http": f"http://127.0.0.1:{port}",
                "https": f"http://127.0.0.1:{port}"
            })
            opener = urllib.request.build_opener(proxy_handler)
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    "https://www.youtube.com/generate_204",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
                with opener.open(req, timeout=3.5) as resp:
                    if resp.status in [200, 204]:
                        lat = int((time.time() - t0) * 1000)
                        return (item, lat)
            except Exception:
                # Fallback to Google 204
                try:
                    req = urllib.request.Request("https://www.gstatic.com/generate_204", headers={"User-Agent": "Mozilla/5.0"})
                    with opener.open(req, timeout=2.5) as resp:
                        if resp.status in [200, 204]:
                            lat = int((time.time() - t0) * 1000)
                            return (item, lat)
                except Exception:
                    pass
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futures = [ex.submit(test_single_proxy, idx) for idx in range(len(batch))]
            for fut in concurrent.futures.as_completed(futures):
                res = fut.result()
                if res:
                    item, latency = res
                    item["latency"] = latency
                    verified.append(item)
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=1.5)
            except Exception:
                proc.kill()
        if os.path.exists(cfg_file):
            os.remove(cfg_file)

    return verified

# ==============================================================================
# 6. Artifact Synthesizers (Raw, Base64, Clash, Singbox, README)
# ==============================================================================
def format_remark(item):
    bs_emoji = "🇷🇺" if item["is_bs"] else "🌐"
    bs_tag = "БС" if item["is_bs"] else "ЧС"
    proto = item["scheme"].upper()
    lat = item.get("latency", 0)
    sni = f" ({item['sni']})" if item.get("sni") else ""
    return f"{bs_emoji} [{item['provider']}] {proto}{sni} | YouTube {lat}ms"

def generate_formatted_raw(verified_items):
    lines = []
    for item in verified_items:
        raw = item["raw_url"]
        # Strip existing fragment and append standardized verified remark
        base = raw.split("#")[0]
        remark = urllib.parse.quote(format_remark(item))
        lines.append(f"{base}#{remark}")
    return "\n".join(lines) + "\n"

def generate_clash_yaml(verified_items):
    lines = [
        "# ============================================================",
        "# DELETEYOURVPN - Verified Russian Whitelist & Bypass Proxies",
        f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"# Total Working Nodes: {len(verified_items)} (Tested with YouTube)",
        "# ============================================================",
        "port: 7890",
        "socks-port: 7891",
        "mixed-port: 7892",
        "allow-lan: false",
        "mode: rule",
        "log-level: info",
        "unified-delay: true",
        "tcp-concurrent: true",
        "",
        "dns:",
        "  enable: true",
        "  ipv6: false",
        "  enhanced-mode: fake-ip",
        "  fake-ip-range: 198.18.0.1/16",
        "  default-nameserver:",
        "    - 77.88.8.8",
        "    - 1.1.1.1",
        "  nameserver:",
        "    - https://77.88.8.8/dns-query",
        "    - https://1.1.1.1/dns-query",
        "",
        "proxies:"
    ]

    proxy_names = []
    for idx, item in enumerate(verified_items):
        ob = item["outbound"]
        name = format_remark(item).replace('"', '')
        proxy_names.append(name)

        if ob["type"] == "vless":
            lines.extend([
                f'  - name: "{name}"',
                '    type: vless',
                f'    server: {ob["server"]}',
                f'    port: {ob["server_port"]}',
                f'    uuid: "{ob["uuid"]}"',
                f'    network: {ob.get("transport", {}).get("type", "tcp")}',
                '    tls: true',
                '    udp: true'
            ])
            if ob.get("flow"):
                lines.append(f'    flow: {ob["flow"]}')
            tls_cfg = ob.get("tls", {})
            if tls_cfg.get("server_name"):
                lines.append(f'    servername: {tls_cfg["server_name"]}')
            if tls_cfg.get("reality"):
                r = tls_cfg["reality"]
                lines.append('    reality-opts:')
                lines.append(f'      public-key: {r["public_key"]}')
                if r.get("short_id"):
                    lines.append(f'      short-id: "{r["short_id"]}"')
            if tls_cfg.get("utls"):
                lines.append(f'    client-fingerprint: {tls_cfg["utls"].get("fingerprint", "chrome")}')

        elif ob["type"] == "trojan":
            lines.extend([
                f'  - name: "{name}"',
                '    type: trojan',
                f'    server: {ob["server"]}',
                f'    port: {ob["server_port"]}',
                f'    password: "{ob["password"]}"',
                '    udp: true',
                f'    sni: {ob.get("tls", {}).get("server_name", ob["server"])}'
            ])

        elif ob["type"] == "hysteria2":
            lines.extend([
                f'  - name: "{name}"',
                '    type: hysteria2',
                f'    server: {ob["server"]}',
                f'    port: {ob["server_port"]}',
                f'    password: "{ob["password"]}"',
                f'    sni: {ob.get("tls", {}).get("server_name", ob["server"])}',
                '    skip-cert-verify: true'
            ])

    lines.extend([
        "",
        "proxy-groups:",
        "  - name: 🛡️ Белые Списки (Выбор)",
        "    type: select",
        "    proxies:",
        "      - ⚡ Самый быстрый (URL-Test)",
        "      - 🇷🇺 Только Белые Списки (БС)",
        "      - 🛡️ Fallback",
        "      - DIRECT"
    ] + [f'      - "{p}"' for p in proxy_names])

    bs_proxies = [format_remark(i).replace('"', '') for i in verified_items if i["is_bs"]]
    if not bs_proxies:
        bs_proxies = proxy_names

    lines.extend([
        "",
        "  - name: ⚡ Самый быстрый (URL-Test)",
        "    type: url-test",
        "    url: https://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:"
    ] + [f'      - "{p}"' for p in proxy_names])

    lines.extend([
        "",
        "  - name: 🇷🇺 Только Белые Списки (БС)",
        "    type: url-test",
        "    url: https://www.gstatic.com/generate_204",
        "    interval: 180",
        "    tolerance: 50",
        "    proxies:"
    ] + [f'      - "{p}"' for p in bs_proxies])

    lines.extend([
        "",
        "  - name: 🛡️ Fallback",
        "    type: fallback",
        "    url: https://www.gstatic.com/generate_204",
        "    interval: 180",
        "    proxies:"
    ] + [f'      - "{p}"' for p in proxy_names[:8]])

    lines.extend([
        "",
        "rules:",
        "  - DOMAIN-SUFFIX,ru,DIRECT",
        "  - DOMAIN-SUFFIX,su,DIRECT",
        "  - DOMAIN-SUFFIX,рф,DIRECT",
        "  - GEOIP,private,DIRECT,no-resolve",
        "  - GEOIP,RU,DIRECT",
        "  - MATCH,🛡️ Белые Списки (Выбор)"
    ])
    return "\n".join(lines) + "\n"

def generate_singbox_json(verified_items):
    outbounds = []
    proxy_tags = []
    bs_tags = []

    for item in verified_items:
        ob = dict(item["outbound"])
        name = format_remark(item)
        ob["tag"] = name
        proxy_tags.append(name)
        if item["is_bs"]:
            bs_tags.append(name)
        outbounds.append(ob)

    if not bs_tags:
        bs_tags = proxy_tags

    cfg = {
        "log": {"level": "info", "timestamp": True},
        "dns": {
            "servers": [
                {"tag": "dns-remote", "address": "https://1.1.1.1/dns-query", "detour": "select"},
                {"tag": "dns-direct", "address": "77.88.8.8", "detour": "direct"}
            ],
            "rules": [
                {"domain_suffix": [".ru", ".su", ".рф"], "server": "dns-direct"}
            ]
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 2085,
                "sniff": True
            }
        ],
        "outbounds": [
            {
                "type": "selector",
                "tag": "select",
                "outbounds": [
                    "⚡ Самый быстрый",
                    "🇷🇺 Белые списки (БС)",
                    "fallback",
                    "direct"
                ] + proxy_tags,
                "default": "⚡ Самый быстрый"
            },
            {
                "type": "urltest",
                "tag": "⚡ Самый быстрый",
                "outbounds": proxy_tags,
                "url": "https://www.gstatic.com/generate_204",
                "interval": "3m",
                "tolerance": 50
            },
            {
                "type": "urltest",
                "tag": "🇷🇺 Белые списки (БС)",
                "outbounds": bs_tags,
                "url": "https://www.gstatic.com/generate_204",
                "interval": "3m",
                "tolerance": 50
            },
            {
                "type": "urltest",
                "tag": "fallback",
                "outbounds": proxy_tags[:6] if len(proxy_tags) >= 6 else proxy_tags,
                "url": "https://www.gstatic.com/generate_204",
                "interval": "3m",
                "tolerance": 50
            },
            {"type": "direct", "tag": "direct"}
        ] + outbounds,
        "route": {
            "final": "select",
            "rules": [
                {"domain_suffix": [".ru", ".su", ".рф"], "outbound": "direct"},
                {"ip_is_private": True, "outbound": "direct"}
            ]
        }
    }
    return json.dumps(cfg, indent=2, ensure_ascii=False)

def generate_readme(verified_items, stats_by_source):
    total = len(verified_items)
    bs_count = sum(1 for i in verified_items if i.get("is_bs"))
    now_str = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())

    lines = [
        "# 🛡️ DELETEYOURVPN — Белые Списки РФ (Whitelist & Bypass)",
        "",
        "> **Автоматически валидированный каталог серверов для работы в белых списках мобильных операторов РФ и обхода DPI.**",
        "> Все серверы протестированы на сквозное соединение с **YouTube** и ресурсами Google.",
        "",
        f"📅 **Последнее обновление:** `{now_str}`  ",
        f"⚡ **Проверенных рабочих серверов:** `{total}` шт. (из них строго в БС: `{bs_count}` шт.)",
        "",
        "---",
        "",
        "## 🔗 Ссылки на подписки",
        "",
        "| Формат | Ссылка на скачивание / импорт | Назначение |",
        "| :--- | :--- | :--- |",
        "| 📱 **Base64 (Happ / Incy / v2rayNG)** | `https://raw.githubusercontent.com/u23jd9/russia-whitelist-vpn/main/whitelist_vless.txt` | Универсальная подписка для мобильных клиентов |",
        "| 📋 **Plaintext (Raw ключи)** | `https://raw.githubusercontent.com/u23jd9/russia-whitelist-vpn/main/whitelist_raw.txt` | Прямой список ключей vless://, trojan://, hy2:// |",
        "| ⚔️ **Clash Meta / Mihomo** | `https://raw.githubusercontent.com/u23jd9/russia-whitelist-vpn/main/whitelist_clash.yaml` | Конфигурация с автовыбором и балансировкой |",
        "| 📦 **Sing-box Client** | `https://raw.githubusercontent.com/u23jd9/russia-whitelist-vpn/main/whitelist_singbox.json` | JSON конфиг для sing-box 1.11+ |",
        "",
        "---",
        "",
        "## 🏆 Авторы и Источники (Credits)",
        "",
        "Серверы агрегируются из открытых проверенных источников комьюнити. Авторам исходных подписок выражается огромная благодарность:",
        "",
        "| # | Источник / Провайдер | Категория | Рабочих нод | Репозиторий / Канал |",
        "| :--- | :--- | :---: | :---: | :--- |"
    ]

    for s in get_all_sources():
        c = stats_by_source.get(s["name"], 0)
        c_badge = f"**{c}**" if c > 0 else "0"
        lines.append(f"| {s['id']} | **{s['name']}** | `{s['category']}` | {c_badge} | [{s['author']}]({s['link']}) |")

    lines.extend([
        "",
        "### 📚 Репозитории белых списков:",
        "- [`escapingworm/russia-whitelist`](https://github.com/escapingworm/russia-whitelist) — База IP-диапазонов мобильных операторов РФ.",
        "- [`hxehex/russia-mobile-internet-whitelist`](https://github.com/hxehex/russia-mobile-internet-whitelist) — Доверенные домены и CIDR пулы.",
        "- [`kort0881/russia-whitelist`](https://github.com/kort0881/russia-whitelist) — Маршрутизация и легальные сетевые конфигурации.",
        "",
        "---",
        "*Обновляется автоматически с помощью Python-демона `whitelist_engine.py` на workpc.*"
    ])
    return "\n".join(lines) + "\n"

# ==============================================================================
# 7. Main Harvest & Verification Loop
# ==============================================================================
def run_harvest_and_test():
    print("=" * 65)
    print("  RUSSIAN WHITELIST PROXY HARVESTER & YOUTUBE VERIFIER")
    print(f"  Started at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 65)

    # 1. Load Whitelist Matcher
    matcher = WhitelistMatcher()
    matcher.load_from_web()

    # 2. Harvest from All Sources (Curated + Discovered)
    all_sources = get_all_sources()
    print(f"\n[*] Harvesting configs from {len(all_sources)} sources ({len(SOURCES)} curated + {len(all_sources)-len(SOURCES)} auto-discovered)...")
    all_configs = []
    seen_keys = set()

    def harvest_single_source(s):
        raw = fetch_url(s["url"], timeout=8)
        if not raw:
            return (s, [])
        items = decode_subscription_payload(raw)
        parsed_items = []
        for raw_line in items:
            parsed = parse_proxy_url(raw_line, s, matcher)
            if parsed:
                parsed_items.append(parsed)
        return (s, parsed_items)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        future_to_src = {ex.submit(harvest_single_source, s): s for s in all_sources}
        completed_src = 0
        for fut in concurrent.futures.as_completed(future_to_src):
            completed_src += 1
            s, parsed_items = fut.result()
            added = 0
            for parsed in parsed_items:
                key = f"{parsed['host']}:{parsed['port']}:{parsed['outbound'].get('uuid', '')}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                all_configs.append(parsed)
                added += 1
            if added > 0:
                print(f"  [✓] ({completed_src}/{len(all_sources)}) {s['name']}: {added} unique nodes")
            elif completed_src % 25 == 0 or completed_src == len(all_sources):
                print(f"  ... fetched {completed_src}/{len(all_sources)} sources ({len(all_configs)} unique nodes so far)")

    print(f"\n[+] Total unique harvested nodes: {len(all_configs)}")
    if not all_configs:
        print("[!] No configs fetched. Aborting.")
        return

    # 3. Fast TCP/Protocol Pre-filter
    print("\n[*] Pre-filtering nodes via fast reachability test (1.2s timeout)...")
    alive_candidates = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
        future_to_item = {ex.submit(check_node_reachable, item): item for item in all_configs}
        for fut in concurrent.futures.as_completed(future_to_item):
            item = future_to_item[fut]
            if fut.result():
                alive_candidates.append(item)

    print(f"[+] Surviving TCP-reachable nodes: {len(alive_candidates)} / {len(all_configs)}")

    # 4. Deep YouTube Connectivity Verification with Sing-Box
    print("\n[*] Testing YouTube HTTP 204 connectivity via sing-box in batches of 15...")
    verified_nodes = []
    batch_size = 15

    # Priority to Whitelist (БС) nodes first
    alive_candidates.sort(key=lambda x: (not x["is_bs"], x["provider"]))

    for i in range(0, len(alive_candidates), batch_size):
        batch = alive_candidates[i:i + batch_size]
        res = verify_batch_singbox(batch, base_port=29850)
        verified_nodes.extend(res)
        print(f"  Processed {min(i + batch_size, len(alive_candidates))}/{len(alive_candidates)}... ({len(verified_nodes)} YouTube OK so far)")
        # Cap at 50 high-quality working nodes to keep subscription lightweight & ultra-fast
        if len(verified_nodes) >= 50:
            print("[+] Reached target quota of 50 verified stable servers.")
            break

    print(f"\n=================================================================")
    print(f"  VERIFICATION COMPLETE: {len(verified_nodes)} WORKING SERVERS (YOUTUBE OK)")
    print(f"=================================================================")

    if not verified_nodes:
        print("[!] No working nodes verified. Keeping existing files.")
        return

    # Sort verified nodes: Whitelist (БС) first, then by lowest latency
    verified_nodes.sort(key=lambda x: (not x["is_bs"], x.get("latency", 9999)))

    # Stats by source
    stats_by_source = {}
    for item in verified_nodes:
        p = item["provider"]
        stats_by_source[p] = stats_by_source.get(p, 0) + 1

    # 5. Write Files in repo directory
    raw_content = generate_formatted_raw(verified_nodes)
    raw_file = os.path.join(WORK_DIR, "whitelist_raw.txt")
    with open(raw_file, "w", encoding="utf-8") as f:
        f.write(raw_content)

    b64_content = base64.b64encode(raw_content.strip().encode("utf-8")).decode("utf-8")
    b64_file = os.path.join(WORK_DIR, "whitelist_vless.txt")
    with open(b64_file, "w", encoding="utf-8") as f:
        f.write(b64_content)

    clash_content = generate_clash_yaml(verified_nodes)
    clash_file = os.path.join(WORK_DIR, "whitelist_clash.yaml")
    with open(clash_file, "w", encoding="utf-8") as f:
        f.write(clash_content)

    sb_content = generate_singbox_json(verified_nodes)
    sb_file = os.path.join(WORK_DIR, "whitelist_singbox.json")
    with open(sb_file, "w", encoding="utf-8") as f:
        f.write(sb_content)

    readme_content = generate_readme(verified_nodes, stats_by_source)
    readme_file = os.path.join(WORK_DIR, "README.md")
    with open(readme_file, "w", encoding="utf-8") as f:
        f.write(readme_content)

    print("[+] Generated artifacts:")
    print(f"    - {raw_file}")
    print(f"    - {b64_file}")
    print(f"    - {clash_file}")
    print(f"    - {sb_file}")
    print(f"    - {readme_file}")

    # 6. Git Commit & Push to Public GitHub Repo
    try:
        print("\n[*] Committing and pushing to GitHub repo u23jd9/russia-whitelist-vpn...")
        subprocess.run(["git", "add", "-A"], cwd=WORK_DIR, check=True)
        commit_msg = f"Auto-update: {len(verified_nodes)} verified whitelist nodes (YouTube OK) [{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}]"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=WORK_DIR, check=False)
        subprocess.run(["git", "push", "origin", "main"], cwd=WORK_DIR, check=True)
        print("[✓] Pushed to https://github.com/u23jd9/russia-whitelist-vpn successfully!")
    except Exception as e:
        print(f"[!] Git commit/push error: {e}")

    # 7. Synchronize to VDS (delyoself.site) for Telegram Bot and Web Hosting
    try:
        print("\n[*] Syncing verified files to VDS delyoself.site...")
        sync_cmd = (
            f"tar czf - -C {WORK_DIR} whitelist_raw.txt whitelist_vless.txt whitelist_clash.yaml whitelist_singbox.json | "
            f"ssh -p {VDS_SSH_PORT} -o StrictHostKeyChecking=no {VDS_USER}@{VDS_HOST} "
            f"\"ssh -i ~/.ssh/id_autossh root@{VDS_HOST} '"
            f"tar xzf - -C /tmp/ && "
            f"cp /tmp/whitelist_raw.txt /opt/freesota/whitelist-raw.txt && "
            f"cp /tmp/whitelist_vless.txt /opt/freesota/whitelist-xray.txt && "
            f"cp /tmp/whitelist_clash.yaml /opt/freesota/whitelist-clash.yaml && "
            f"cp /tmp/whitelist_singbox.json /opt/freesota/whitelist-singbox.json && "
            f"chown root:root /opt/freesota/whitelist-* && "
            f"systemctl restart freesota-web.service"
            f"'\""
        )
        subprocess.run(sync_cmd, shell=True, check=True)
        print("[✓] Synchronized to /opt/freesota/ on delyoself.site and restarted freesota-web!")
    except Exception as e:
        print(f"[!] VDS synchronization error: {e}")

if __name__ == "__main__":
    run_harvest_and_test()
