from __future__ import annotations

import ipaddress
import json
import re
import socket
import ssl
from datetime import date, timedelta
from html import unescape
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager


LABEL_PATTERN = re.compile(
    r"(?:Benchmark|比較基準|參考指標|指標指數|基準指數|追蹤指數)\s*[:：]?\s*"
    r"([^\n\r|｜<>]{2,80}?(?:指數|Index))",
    flags=re.IGNORECASE,
)
INDEX_PATTERN = re.compile(
    r"([A-Za-z0-9&／/・\.\-\s\u4e00-\u9fff]{2,60}(?:指數|Index))",
    flags=re.IGNORECASE,
)
FUND_PATTERN = re.compile(
    r"([A-Za-z0-9Ａ-Ｚａ-ｚ０-９&（）()／/・\.\-\s\u4e00-\u9fff]{2,80}基金)"
)


class _MoneyDJTLSAdapter(HTTPAdapter):
    """Keep certificate verification while tolerating MoneyDJ's legacy chain."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        pool_kwargs["ssl_context"] = context
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )


def _get_public_page(url: str, **kwargs) -> requests.Response:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.endswith(".moneydj.com"):
        session = requests.Session()
        session.mount("https://", _MoneyDJTLSAdapter())
        return session.get(url, **kwargs)
    return requests.get(url, **kwargs)


def _resolve_moneydj_wrapper_url(url: str) -> str:
    """Convert MoneyDJ bank wrapper URLs into their iframe data URLs."""
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.hostname.lower().endswith(".moneydj.com"):
        return url
    if parsed.path.rstrip("/").lower() != "/main.html":
        return url

    route = parse_qs(parsed.query).get("sUrl", [""])[0]
    route = unquote(route)
    page_match = re.search(r"\$WR(\d{2})\]DJHTM", route, flags=re.IGNORECASE)
    fund_match = re.search(r"\{A\}([A-Z0-9]+(?:-[A-Z0-9]+)?)", route, flags=re.IGNORECASE)
    if not page_match or not fund_match:
        return url

    page = f"wr{page_match.group(1)}.djhtm"
    fund_id = fund_match.group(1).upper()
    return urlunparse(
        (parsed.scheme, parsed.netloc, f"/w/wr/{page}", "", urlencode({"a": fund_id}), "")
    )


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("請貼上完整的 http 或 https 基金網址。")
    if parsed.username or parsed.password:
        raise ValueError("網址不可包含帳號或密碼。")
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise ValueError("無法解析網址主機。") from exc
    if any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("基於安全考量，不接受內網或本機網址。")
    return parsed.geturl()


def _download_html(url: str, max_bytes: int = 8_000_000) -> tuple[str, str]:
    safe_url = _validate_public_url(url)
    for _ in range(4):
        response = _get_public_page(
            safe_url,
            timeout=(15, 35),
            headers={"User-Agent": "Mozilla/5.0 IntegratedFundWeeklyReport/1.0"},
            allow_redirects=False,
            stream=True,
        )
        if response.is_redirect or response.is_permanent_redirect:
            destination = response.headers.get("location")
            response.close()
            if not destination:
                raise ValueError("網站重新導向缺少目的網址。")
            safe_url = _validate_public_url(urljoin(safe_url, destination))
            continue
        response.raise_for_status()
        _validate_public_url(response.url)
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("基金網頁超過 8 MB，請改用手動填寫。")
            chunks.append(chunk)
        raw = b"".join(chunks)
        encoding = response.encoding or response.apparent_encoding or "utf-8"
        return raw.decode(encoding, errors="replace"), response.url
    raise ValueError("網站重新導向次數過多。")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip(" -–—|｜：:")


def extract_fund_metadata(html: str, source_url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    text = _clean(soup.get_text("\n", strip=True))
    script_text = "\n".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))

    title_candidates: list[str] = []
    for selector in ("h1", "h2", "h3", "h4"):
        title_candidates.extend(_clean(node.get_text(" ", strip=True)) for node in soup.select(selector))
    for attr in (("property", "og:title"), ("name", "twitter:title")):
        node = soup.find("meta", attrs={attr[0]: attr[1]})
        if node and node.get("content"):
            title_candidates.append(_clean(node["content"]))
    if soup.title and soup.title.string:
        title_candidates.append(_clean(soup.title.string))
    title_candidates.append(text[:500])

    fund_matches: list[str] = []
    for candidate in title_candidates:
        for match in FUND_PATTERN.finditer(candidate):
            value = _clean(match.group(1))
            value = re.sub(r"基金(?:\s+基金)+$", "基金", value)
            if value not in fund_matches:
                fund_matches.append(value)

    generic_names = {"基金", "國內基金", "境外基金", "海外基金", "單一基金", "基金資訊"}
    usable_names = [name for name in fund_matches if name not in generic_names]
    fund_name = max(
        usable_names,
        key=lambda name: (bool(re.match(r"^\d", name)), len(name)),
        default="",
    )

    benchmark = ""
    for heading in soup.select("h1, h2, h3, h4, h5"):
        heading_text = _clean(heading.get_text(" ", strip=True))
        heading_match = re.search(
            r"基準指數\s*[-–—:：]\s*(.{2,80})$", heading_text, flags=re.IGNORECASE
        )
        if heading_match:
            benchmark = _clean(heading_match.group(1))
            break
    combined = "\n".join((text, script_text, html))
    labelled = LABEL_PATTERN.search(combined) if not benchmark else None
    if labelled:
        benchmark = _clean(labelled.group(1))
    elif not benchmark:
        candidates = []
        for match in INDEX_PATTERN.finditer(combined):
            value = _clean(match.group(1))
            if any(noise in value for noise in ("基金績效", "指數型基金", "指數基金")):
                continue
            if value not in candidates:
                candidates.append(value)
        if len(candidates) == 1:
            benchmark = candidates[0]

    return {
        "fund_name": fund_name,
        "benchmark": benchmark,
        "source_url": source_url,
    }


def fetch_fund_metadata(url: str) -> dict[str, str]:
    resolved_url = _resolve_moneydj_wrapper_url(unquote(url))
    html, final_url = _download_html(resolved_url)
    result = extract_fund_metadata(html, final_url)
    if not result["fund_name"] and not result["benchmark"]:
        raise ValueError("這個頁面沒有可辨識的基金名稱或 Benchmark，請手動填寫。")
    return result


def fetch_fund_top_industries(url: str, limit: int = 3) -> list[dict]:
    """Read and aggregate MoneyDJ's public fund industry allocation."""
    decoded = unquote(url.strip())
    parsed = urlparse(decoded)
    if not parsed.hostname or not parsed.hostname.lower().endswith(".moneydj.com"):
        return []
    candidates = [parse_qs(parsed.query).get("a", [""])[0]]
    candidates.append(parse_qs(parsed.query).get("sUrl", [""])[0])
    joined = " ".join(candidates)
    match = re.search(r"(AC[A-Z0-9]+)(?:-[A-Z0-9]+)?", joined, flags=re.IGNORECASE)
    if not match:
        return []
    code = match.group(1).upper()
    endpoint = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "/jsondata/djjson/fundjsondata.xdjjson",
            "",
            urlencode({"x": "wr04p3", "a": code}),
            "",
        )
    )
    payload, _ = _download_html(endpoint)
    records = json.loads(payload).get("ResultSet", {}).get("Result", [])
    aggregated: dict[str, float] = {}
    data_date = ""
    for record in records:
        name = re.sub(r"^(?:上市|上櫃)", "", str(record.get("V2", "")).strip())
        if not name or name == "合計":
            continue
        try:
            weight = float(record.get("V3"))
        except (TypeError, ValueError):
            continue
        aggregated[name] = aggregated.get(name, 0.0) + weight
        data_date = data_date or str(record.get("V1", ""))
    ranked = sorted(aggregated.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [
        {"產業": name, "持股權重%": round(weight, 2), "持股資料日期": data_date}
        for name, weight in ranked
    ]


def fetch_fund_top_holdings(url: str, limit: int = 10) -> list[dict]:
    """Read MoneyDJ's published top holdings table when the page provides it."""
    resolved = _resolve_moneydj_wrapper_url(unquote(url.strip()))
    parsed = urlparse(resolved)
    if not parsed.hostname or not parsed.hostname.lower().endswith(".moneydj.com"):
        return []
    query = parse_qs(parsed.query)
    fund_id = query.get("a", [""])[0]
    if not fund_id:
        return []
    holdings_url = urlunparse(
        (parsed.scheme, parsed.netloc, "/w/wr/wr04.djhtm", "", urlencode({"a": fund_id}), "")
    )
    html, _ = _download_html(holdings_url)
    soup = BeautifulSoup(html, "html.parser")
    holdings = []
    seen = set()
    for row in soup.select("table tr"):
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        for start in (0, 4):
            if len(cells) < start + 3:
                continue
            name = cells[start]
            try:
                weight = float(cells[start + 2].replace("%", "").replace(",", ""))
            except (TypeError, ValueError):
                continue
            if not name or name in seen:
                continue
            seen.add(name)
            holdings.append({"公司／持股": name, "基金持股權重%": weight})
            if len(holdings) >= limit:
                return holdings
    return holdings


def fetch_fund_metrics(url: str) -> dict:
    """Fetch public MoneyDJ data and calculate current fund metrics.

    Weekly/monthly returns use the latest NAV and the latest observation on or
    before 7/30 calendar days earlier. Maximum drawdown uses the downloaded
    trailing-year NAV series. Sharpe and Beta are read from MoneyDJ's published
    performance table.
    """
    resolved = _resolve_moneydj_wrapper_url(unquote(url.strip()))
    parsed = urlparse(resolved)
    if not parsed.hostname or not parsed.hostname.lower().endswith(".moneydj.com"):
        return {}
    fund_id = parse_qs(parsed.query).get("a", [""])[0]
    code_match = re.match(r"(AC[A-Z0-9]+)", fund_id, flags=re.IGNORECASE)
    if not fund_id or not code_match:
        return {}
    code = code_match.group(1).upper()

    end = date.today()
    start = end - timedelta(days=400)
    nav_url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "/w/bcd/tBCDNavList.djbcd",
            "",
            urlencode(
                {
                    "a": code,
                    "b": "1",
                    "c": f"{start.year}-{start.month}-{start.day}",
                    "d": f"{end.year}-{end.month}-{end.day}",
                }
            ),
            "",
        )
    )
    payload, _ = _download_html(nav_url)
    payload = re.sub(r"<!--.*?-->", "", payload).strip()
    parts = payload.split()
    nav_rows: list[tuple[date, float]] = []
    if len(parts) >= 2:
        raw_dates = parts[0].split(",")
        raw_values = parts[1].split(",")
        for raw_date, raw_value in zip(raw_dates, raw_values):
            try:
                nav_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
                nav_rows.append((nav_date, float(raw_value)))
            except (TypeError, ValueError):
                continue
    nav_rows.sort(key=lambda item: item[0])
    if len(nav_rows) < 2:
        raise ValueError("MoneyDJ 未回傳足夠的歷史淨值，基金指標未更新。")

    latest_date, latest_nav = nav_rows[-1]

    def return_to(days: int) -> float | None:
        eligible = [item for item in nav_rows if item[0] <= latest_date - timedelta(days=days)]
        if not eligible or eligible[-1][1] == 0:
            return None
        return (latest_nav / eligible[-1][1] - 1) * 100

    peak = nav_rows[0][1]
    max_drawdown = 0.0
    for _, nav in nav_rows:
        peak = max(peak, nav)
        if peak:
            max_drawdown = min(max_drawdown, (nav / peak - 1) * 100)

    performance_url = urlunparse(
        (parsed.scheme, parsed.netloc, "/w/wr/wr03.djhtm", "", urlencode({"a": fund_id}), "")
    )
    html, _ = _download_html(performance_url)
    soup = BeautifulSoup(html, "html.parser")
    sharpe = beta = None
    for table in soup.select("table"):
        headers = [_clean(th.get_text(" ", strip=True)).lower() for th in table.select("thead th")]
        if "sharpe" not in headers or "beta" not in headers:
            continue
        row = table.select_one("tbody tr")
        cells = [_clean(td.get_text(" ", strip=True)) for td in row.find_all("td")] if row else []
        if len(cells) >= 7:
            try:
                sharpe = float(cells[-2])
                beta = float(cells[-1])
            except ValueError:
                pass
        break

    benchmark_week = None
    comparison_match = re.search(
        r"['\"]BCDUrl['\"]\s*:\s*['\"]([^'\"]*BCDROIList5Applet[^'\"]*)",
        html,
        flags=re.IGNORECASE,
    )
    if comparison_match:
        comparison_url = urljoin(performance_url, unescape(comparison_match.group(1)))
        comparison_payload, _ = _download_html(comparison_url)
        comparison_payload = re.sub(r"<!--.*?-->", "", comparison_payload).strip()
        comparison_parts = comparison_payload.split()
        if len(comparison_parts) >= 3:
            dates = comparison_parts[0].split(",")
            benchmark_returns = comparison_parts[2].split(",")
            benchmark_rows: list[tuple[date, float]] = []
            for raw_date, raw_return in zip(dates, benchmark_returns):
                try:
                    item_date = date(
                        int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8])
                    )
                    benchmark_rows.append((item_date, float(raw_return)))
                except (TypeError, ValueError):
                    continue
            if benchmark_rows:
                benchmark_latest_date, benchmark_latest = benchmark_rows[-1]
                bases = [
                    item
                    for item in benchmark_rows
                    if item[0] <= benchmark_latest_date - timedelta(days=7)
                ]
                if bases and 100 + bases[-1][1] != 0:
                    benchmark_week = (
                        (100 + benchmark_latest) / (100 + bases[-1][1]) - 1
                    ) * 100

    return {
        "fund_week": return_to(7),
        "fund_month": return_to(30),
        "sharpe": sharpe,
        "beta": beta,
        "max_drawdown": max_drawdown,
        "benchmark_week": benchmark_week,
        "nav_date": latest_date.isoformat(),
        "nav": latest_nav,
        "drawdown_period": f"{nav_rows[0][0].isoformat()}～{latest_date.isoformat()}",
    }
