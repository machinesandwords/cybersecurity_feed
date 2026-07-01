import streamlit as st
import requests
import anthropic
from datetime import datetime, timedelta, timezone
import urllib.parse

# --- Config ---
NEWS_API_KEY = st.secrets["NEWS_API_KEY"]
ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

CYBERSECURITY_DOMAINS = (
    "darkreading.com,bleepingcomputer.com,securityweek.com,theregister.com,"
    "wired.com,zdnet.com,scmagazine.com,cybersecuritydive.com,threatpost.com,"
    "krebsonsecurity.com,helpnetsecurity.com,infosecurity-magazine.com,"
    "securityboulevard.com,csoonline.com,axios.com,reuters.com,wsj.com"
)

KEYWORDS = [
    "cybersecurity acquisition",
    "cybersecurity merger",
    "security vendor funding",
    "cybersecurity IPO",
    "cybersecurity partnership",
    "CISO appointment",
    "security platform launch",
    "cybersecurity layoffs",
    "security vendor bankruptcy",
    "ransomware attack",
    "data breach",
    "cybersecurity regulation",
    "security market share",
    "threat intelligence",
    "zero trust",
    "cybersecurity CEO",
    "SEC fines cybersecurity",
    "SEC penalties cybersecurity",
]

MA_KEYWORDS = {"acquisition", "merger", "IPO", "funding", "bankruptcy", "buyout", "deal"}

# --- Helpers ---

def fetch_news(keywords, hours_back=24):
    from_time = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen_urls = set()
    articles = []

    for kw in keywords:
        url = (
            f"https://newsapi.org/v2/everything"
            f"?q={urllib.parse.quote(kw)}"
            f"&from={from_time}"
            f"&sortBy=publishedAt"
            f"&language=en"
            f"&pageSize=5"
            f"&domains={CYBERSECURITY_DOMAINS}"
            f"&apiKey={NEWS_API_KEY}"
        )
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            for art in data.get("articles", []):
                if art["url"] not in seen_urls and art.get("title") and "[Removed]" not in art.get("title", ""):
                    seen_urls.add(art["url"])
                    art["matched_keyword"] = kw
                    articles.append(art)
        except Exception:
            continue

    articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    return articles


def is_relevant(article):
    """Claude relevance filter — drops anything not about enterprise cybersecurity market news."""
    title = article.get("title", "")
    description = article.get("description") or ""

    prompt = f"""You are a filter for a cybersecurity market intelligence newsletter for CISOs and enterprise security architects.

Is this article relevant to enterprise cybersecurity market news? This includes: vendor acquisitions, mergers, funding, executive moves, product launches, regulatory actions, data breaches at enterprises, ransomware, SEC enforcement, or significant market shifts in the cybersecurity industry.

Answer only YES or NO.

Title: {title}
Description: {description}"""

    try:
        response = ANTHROPIC_CLIENT.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        answer = response.content[0].text.strip().upper()
        return answer.startswith("YES")
    except Exception:
        return True  # Default to keeping if filter fails


def is_ma(article):
    text = (article.get("title", "") + " " + (article.get("description") or "")).lower()
    return any(kw in text for kw in MA_KEYWORDS)


def summarize(article):
    title = article.get("title", "")
    description = article.get("description") or ""
    source = article.get("source", {}).get("name", "")

    prompt = f"""You are a briefing assistant for a cybersecurity market intelligence newsletter called The Fallout, written for CISOs and enterprise security architects.

Summarize this news item in 2-3 sentences. Focus on what it means for enterprise security practitioners, not investors. No em dashes. No vague language. Be specific and direct. Write in complete sentences.

Title: {title}
Source: {source}
Description: {description}

Return only the summary, nothing else."""

    try:
        response = ANTHROPIC_CLIENT.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Summary unavailable: {e}"


def format_tweet(article, summary):
    url = article.get("url", "")
    base = f"{summary}\n\n{url}"
    if len(base) > 280:
        max_summary = 280 - len(url) - 4
        summary = summary[:max_summary].rsplit(" ", 1)[0] + "..."
        base = f"{summary}\n\n{url}"
    return base


# --- UI ---

st.set_page_config(page_title="The Fallout — Daily Briefing", layout="wide")

st.markdown("""
    <style>
    .article-card {
        border: 1px solid #e0e0e0;
        border-left: 4px solid #0D7377;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        border-radius: 2px;
        background: #fff;
    }
    .article-title { font-size: 1rem; font-weight: 600; margin-bottom: 0.25rem; }
    .article-meta { font-size: 0.75rem; color: #888; margin-bottom: 0.5rem; }
    .article-summary { font-size: 0.9rem; line-height: 1.5; margin-bottom: 0.75rem; }
    .tag-ma {
        background: #0D7377; color: white;
        font-size: 0.7rem; padding: 2px 8px;
        border-radius: 2px; margin-right: 6px;
    }
    .tag-general {
        background: #e0e0e0; color: #444;
        font-size: 0.7rem; padding: 2px 8px;
        border-radius: 2px; margin-right: 6px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("The Fallout — Daily Briefing")
st.caption("Cybersecurity market intelligence for security practitioners")

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    filter_mode = st.radio(
        "Show",
        ["All cybersecurity news", "M&A only"],
        horizontal=True
    )
with col2:
    hours_back = st.slider("Hours back", min_value=6, max_value=72, value=24, step=6)
with col3:
    run = st.button("Fetch Briefing", type="primary", use_container_width=True)

st.divider()

if run:
    with st.spinner("Fetching news from cybersecurity sources..."):
        articles = fetch_news(KEYWORDS, hours_back=hours_back)

    if not articles:
        st.info("No articles found. Try expanding the time window.")
        st.stop()

    # Relevance filter
    status = st.empty()
    status.markdown(f"**{len(articles)} items fetched** — running relevance filter...")
    progress = st.progress(0)

    relevant = []
    for i, article in enumerate(articles):
        progress.progress((i + 1) / len(articles))
        if is_relevant(article):
            relevant.append(article)

    if filter_mode == "M&A only":
        relevant = [a for a in relevant if is_ma(a)]

    progress.empty()

    if not relevant:
        st.info("No relevant articles found after filtering. Try expanding the time window.")
        st.stop()

    status.markdown(f"**{len(relevant)} relevant items** — summarizing...")
    progress = st.progress(0)

    for i, article in enumerate(relevant):
        progress.progress((i + 1) / len(relevant))

        summary = summarize(article)
        tweet = format_tweet(article, summary)

        title = article.get("title", "No title")
        url = article.get("url", "#")
        source = article.get("source", {}).get("name", "Unknown")
        published = article.get("publishedAt", "")[:10]
        keyword = article.get("matched_keyword", "")
        ma = is_ma(article)

        tag = '<span class="tag-ma">M&A</span>' if ma else '<span class="tag-general">Market</span>'

        st.markdown(f"""
        <div class="article-card">
            <div class="article-title"><a href="{url}" target="_blank">{title}</a></div>
            <div class="article-meta">{tag} {source} &nbsp;·&nbsp; {published} &nbsp;·&nbsp; via: {keyword}</div>
            <div class="article-summary">{summary}</div>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("Copy for X"):
            st.text_area("Tweet", value=tweet, height=100, key=f"tweet_{i}", label_visibility="collapsed")

    progress.empty()
    status.markdown(f"**Briefing complete** — {len(relevant)} items.")