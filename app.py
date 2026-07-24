import streamlit as st
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

st.set_page_config(page_title="Veille mot-clé", page_icon="🔍")
st.title("🔍 Outil de veille")
st.caption("Résultats publiés dans les dernières 24h, toutes sources confondues")

if "mots_cles" not in st.session_state:
    st.session_state.mots_cles = []


# ------------------- GESTION DES MOTS-CLES -------------------
st.subheader("Tes mots-clés suivis")

col1, col2 = st.columns([4, 1])
with col1:
    nouveau_mot_cle = st.text_input("Ajouter un mot-clé", label_visibility="collapsed", placeholder="Ajouter un mot-clé")
with col2:
    if st.button("Ajouter") and nouveau_mot_cle.strip():
        if nouveau_mot_cle.strip() not in st.session_state.mots_cles:
            st.session_state.mots_cles.append(nouveau_mot_cle.strip())
        st.rerun()

if not st.session_state.mots_cles:
    st.info("Aucun mot-clé ajouté pour l'instant.")
else:
    for mc in st.session_state.mots_cles:
        col_a, col_b = st.columns([5, 1])
        col_a.write(f"• {mc}")
        if col_b.button("🗑️", key=f"suppr_{mc}"):
            st.session_state.mots_cles.remove(mc)
            st.rerun()

st.divider()

lancer = st.button("Lancer la veille sur tous les mots-clés", disabled=not st.session_state.mots_cles)

LIMITE_HEURES = 24


# ------------------- FONCTIONS DE RECHERCHE -------------------
def est_recent(date_publication, seuil):
    if date_publication is None:
        return False
    return date_publication >= seuil


def chercher_google_news(mot_cle, seuil):
    url = f"https://news.google.com/rss/search?q={quote(mot_cle)}&hl=fr&gl=FR&ceid=FR:fr"
    flux = feedparser.parse(url)
    resultats = []
    for entree in flux.entries:
        date_pub = None
        if entree.get("published_parsed"):
            date_pub = datetime(*entree.published_parsed[:6], tzinfo=timezone.utc)
        if est_recent(date_pub, seuil):
            resultats.append({"source": "Google News", "titre": entree.title, "lien": entree.link, "date_pub": date_pub})
    return resultats


def chercher_reddit(mot_cle, seuil):
    url = f"https://old.reddit.com/search.rss?q={quote(mot_cle)}&sort=new"
    try:
        flux = feedparser.parse(url)
        resultats = []
        for entree in flux.entries:
            date_pub = None
            if entree.get("published_parsed"):
                date_pub = datetime(*entree.published_parsed[:6], tzinfo=timezone.utc)
            if est_recent(date_pub, seuil):
                resultats.append({"source": "Reddit", "titre": entree.title, "lien": entree.link, "date_pub": date_pub})
        return resultats
    except Exception:
        return []


def chercher_hackernews(mot_cle, seuil):
    url = "https://hn.algolia.com/api/v1/search_by_date"
    params = {"query": mot_cle, "tags": "story", "numericFilters": f"created_at_i>{int(seuil.timestamp())}"}
    try:
        reponse = requests.get(url, params=params, timeout=10)
        data = reponse.json()
        resultats = []
        for hit in data.get("hits", []):
            date_pub = datetime.fromtimestamp(hit.get("created_at_i", 0), tz=timezone.utc)
            resultats.append({"source": "Hacker News", "titre": hit.get("title", ""), "lien": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}", "date_pub": date_pub})
        return resultats
    except Exception:
        return []


def chercher_mastodon(mot_cle, seuil):
    url = "https://mastodon.social/api/v2/search"
    params = {"q": mot_cle, "type": "statuses", "limit": 25}
    headers = {"User-Agent": "veille-outil/1.0"}
    try:
        reponse = requests.get(url, params=params, headers=headers, timeout=10)
        if reponse.status_code != 200:
            return []
        data = reponse.json()
        resultats = []
        for statut in data.get("statuses", []):
            date_pub = None
            if statut.get("created_at"):
                date_pub = datetime.fromisoformat(statut["created_at"].replace("Z", "+00:00"))
            if est_recent(date_pub, seuil):
                resultats.append({"source": "Mastodon - @" + statut.get("account", {}).get("acct", ""), "titre": statut.get("content", "")[:120], "lien": statut.get("url", ""), "date_pub": date_pub})
        return resultats
    except Exception:
        return []


def rechercher_tout(mot_cle):
    maintenant = datetime.now(timezone.utc)
    seuil = maintenant - timedelta(hours=LIMITE_HEURES)
    tous = (
        chercher_google_news(mot_cle, seuil)
        + chercher_reddit(mot_cle, seuil)
        + chercher_hackernews(mot_cle, seuil)
        + chercher_mastodon(mot_cle, seuil)
    )
    tous.sort(key=lambda r: r["date_pub"], reverse=True)
    return tous, maintenant


def afficher_resultats(resultats, maintenant):
    if not resultats:
        st.warning(f"Aucun résultat publié dans les dernières {LIMITE_HEURES}h.")
        return
    st.success(f"{len(resultats)} résultat(s) trouvé(s)")
    for r in resultats:
        age = maintenant - r["date_pub"]
        heures = int(age.total_seconds() // 3600)
        minutes = int((age.total_seconds() % 3600) // 60)
        st.markdown(f"**[{r['source']}]** {r['titre']}")
        st.markdown(f"[{r['lien']}]({r['lien']}) — il y a {heures}h{minutes:02d}min")
        st.divider()


# ------------------- LANCEMENT -------------------
if lancer:
    for mc in st.session_state.mots_cles:
        st.subheader(f"Résultats pour « {mc} »")
        with st.spinner(f"Recherche pour « {mc} »..."):
            resultats, maintenant = rechercher_tout(mc)
        afficher_resultats(resultats, maintenant)
