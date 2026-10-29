import os
import json
import logging
from typing import List, Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)

KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".newsdata_keys")
CURRENT_INDEX_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".newsdata_index")

_MEMORY_INDEX = 0

def load_keys() -> List[str]:
    if not os.path.exists(KEY_FILE):
        return []
    with open(KEY_FILE, "r") as f:
        keys = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return keys

def get_next_key() -> Optional[str]:
    global _MEMORY_INDEX
    keys = load_keys()
    if not keys:
        return None
    key = keys[_MEMORY_INDEX % len(keys)]
    _MEMORY_INDEX = (_MEMORY_INDEX + 1) % len(keys)
    return key

async def fetch_ticker_news(ticker: str, company_name: Optional[str] = None, max_articles: int = 5) -> List[Dict[str, Any]]:
    """Mengambil berita terkini seputar emiten dengan rotasi kunci NewsData.io secara round-robin."""
    keys = load_keys()
    if not keys:
        return []

    # Buat query yang relevan
    # Misal: "ASII" OR "Astra International"
    terms = [ticker.upper()]
    if company_name:
        clean_name = company_name.replace("PT", "").replace("Tbk", "").strip()
        if clean_name and len(clean_name) > 3:
            terms.append(f'"{clean_name}"')
    
    query = " OR ".join(terms)

    # Coba iterasi kunci jika ada yang limit (HTTP 429 atau status != success)
    for _ in range(len(keys)):
        api_key = get_next_key()
        if not api_key:
            break
        
        url = "https://newsdata.io/api/1/latest"
        params = {
            "apikey": api_key,
            "q": query,
            "language": "id,en",
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        articles = []
                        for item in data.get("results", [])[:max_articles]:
                            articles.append({
                                "title": item.get("title", ""),
                                "link": item.get("link", ""),
                                "description": item.get("description", ""),
                                "pubDate": item.get("pubDate", ""),
                                "source": item.get("source_id", "News"),
                            })
                        if articles:
                            return articles
                elif resp.status_code in (429, 401, 403):
                    logger.warning(f"NewsData key {api_key[:10]}... rate-limited or error ({resp.status_code}), rotating to next key...")
                    continue
        except Exception as e:
            logger.error(f"Error fetching NewsData with key {api_key[:10]}...: {e}")
            continue

    return []
