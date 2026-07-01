import streamlit as st
import requests
import anthropic
from datetime import datetime, timedelta, timezone
import urllib.parse

# --- Config ---
NEWS_API_KEY = st.secrets["NEWS_API_KEY"]
ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

# Single batched query — 1 API call per run instead of 17
KEYWORDS = [
    "cybersecurity acquisition",
    "cybersecurity merger",
    "cybersecurity funding",
    "cybersecurity IPO",
    "CISO appointment",
    "cybersecurity CEO",
    "cybersecurity layoffs",
    "SEC cybersecurity",
    "security vendor",
]

MA_KEYWORDS = {"acquisition", "merger", "IPO", "funding", "bankruptcy", "buyout", "deal", "investment"}

# --- Helpers ---

def fetch_news(keywords, hours_back=24):
    from_time = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    articles = []
    errors = []

    query = " OR ".join(f'"{kw}"' for kw in keywords)

    url = (
        f"https://newsapi.org/v2/everything"
        f"?q={urllib.parse.quote(query)}"
        f"&from={from_time}"
        f"&sortBy=publishedAt"
        f"&language=en"
        f"&pageSize=50"
        f"&apiKey={NEWS_API_KEY}"
    )

    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("status") != "ok":
            errors.append(data.get("message", "Unknown NewsAPI error"))
        else:
            for art in data.get("articles", []):
                if art.get("title") and "[Removed]" not in art.get("title", ""):
                    articles.append(art)
    except Exception as e:
        errors.append(str(e))

    articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    return articles, errors


def is_relevant(article):
    title = article.get("title", "")
    description = article.get("description") or ""

    prompt = f"""You are a filter for a cybersecurity business intelligence newsletter for CISOs and enterprise security architects.

Is this article relevant to cybersecurity BUSINESS and MARKET news?

YES if it covers: vendor acquisitions, mergers, funding rounds, IPOs, executive appointments or departures, product strategy, market consolidation, regulatory actions against vendors, SEC enforcement, company layoffs, bankruptcies, or significant partnership deals.

NO if it is primarily about: specific cyberattacks, data breaches, malware, threat actors, vulnerabilities, incident response, security operations, or unrelated topics.

Answer only YES or NO.

Title: {title}
Description: {description}"""

    try:
        response = ANTHROPIC_CLIENT.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip().upper().startswith("YES")
    except Exception:
        return True


def is_ma(article):
    text = (article.get("title", "") + " " + (article.get("description") or "")).lower()
    return any(kw in text for kw in MA_KEYWORDS)


def summarize(article):
    title = article.get("title", "")
    description = article.get("description") or ""
    source = article.get("source", {}).get("name", "")

    prompt = f"""You are a briefing assistant for The Fallout, a cybersecurity business intelligence newsletter written for CISOs and enterprise security architects.

Summarize this news item in 2-3 sentences. Focus on what it means for enterprise security practitioners making vendor, budget, and platform decisions. No em dashes. No vague language. Be specific and direct. Write in complete sentences. Do not editorialize.

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
st.caption("Cybersecurity business and market intelligence")

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    filter_mode = st.radio(
        "Show",
        ["All business news", "M&A only"],
        horizontal=True
    )
with col2:
    hours_back = st.slider("Hours back", min_value=6, max_value=72, value=24, step=6)
with col3:
    run = st.button("Fetch Briefing", type="primary", use_container_width=True)

st.divider()

if run:
    with st.spinner("Fetching news..."):
        articles, errors = fetch_news(KEYWORDS, hours_back=hours_back)

    if errors:
        with st.expander(f"API errors ({len(errors)})"):
            for e in errors:
                st.text(e)

    if not articles:
        st.warning("NewsAPI returned 0 articles. Check API errors above or try a wider time window.")
        st.stop()

    st.caption(f"Raw fetch: {len(articles)} articles from NewsAPI.")

    status = st.empty()
    status.markdown(f"**{len(articles)} items fetched** — running relevance filter...")
    progress = st.progress(0)

    relevant = []
    for i, article in enumerate(articles):
        progress.progress((i + 1) / len(articles))
        if is_relevant(article):
            relevant.append(article)

    progress.empty()
    st.caption(f"After relevance filter: {len(relevant)} items passed.")

    if filter_mode == "M&A only":
        relevant = [a for a in relevant if is_ma(a)]
        st.caption(f"After M&A filter: {len(relevant)} items.")

    if not relevant:
        st.info("No relevant business news found. Try expanding the time window.")
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
        ma = is_ma(article)

        tag = '<span class="tag-ma">M&A</span>' if ma else '<span class="tag-general">Market</span>'

        st.markdown(f"""
        <div class="article-card">
            <div class="article-title"><a href="{url}" target="_blank">{title}</a></div>
            <div class="article-meta">{tag} {source} &nbsp;·&nbsp; {published}</div>
            <div class="article-summary">{summary}</div>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("Copy for X"):
            st.text_area("Tweet", value=tweet, height=100, key=f"tweet_{i}", label_visibility="collapsed")

    progress.empty()
    status.markdown(f"**Briefing complete** — {len(relevant)} items.")