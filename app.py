import streamlit as st
import requests
import feedparser
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

st.set_page_config(page_title="Veille mot-clé", page_icon="🔍")
st.title("🔍 Outil de veille")
st.caption("Résultats publiés dans les dernières 24h, toutes sources confondues")

YOUTUBE_API_KEY = st.secrets.get("YOUTUBE_API_KEY", "")

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

col_lancer, col_filtre = st.columns([2, 2])
with col_lancer:
    lancer = st.button("Lancer la veille sur tous les mots-clés", disabled=not st.session_state.mots_cles)
with col_filtre:
    ne_garder_que_regroupes = st.checkbox("N'afficher que les sujets avec plusieurs sources", value=False)

LIMITE_HEURES = 24
SEUIL_SIMILARITE = 0.42

MOTS_VIDES = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "en", "au", "aux",
    "pour", "avec", "sur", "dans", "par", "est", "sont", "qui", "que", "son",
    "sa", "ses", "ce", "cette", "ces", "il", "elle", "ils", "elles", "vers",
    "ne", "pas", "plus", "leur", "leurs", "après", "avant", "the", "and", "of",
    "to", "in", "a", "an", "is", "for", "on", "with", "at", "by"
}


# ------------------- REGROUPEMENT PAR SIMILARITE -------------------
def normaliser_titre(titre):
    mots = re.findall(r"[a-zàâäéèêëïîôöùûüç0-9]+", titre.lower())
    return {m for m in mots if m not in MOTS_VIDES and len(m) > 2}


def similarite(mots_a, mots_b):
    if not mots_a or not mots_b:
        return 0
    intersection = len(mots_a & mots_b)
    union = len(mots_a | mots_b)
    jaccard = intersection / union if union else 0
    chevauchement = intersection / min(len(mots_a), len(mots_b))
    return max(jaccard, chevauchement)


def regrouper_resultats(resultats):
    groupes = []
    for r in resultats:
        mots_titre = normaliser_titre(r["titre"])
        meilleur_groupe = None
        meilleur_score = 0
        for groupe in groupes:
            score = similarite(mots_titre, groupe["mots"])
            if score > SEUIL_SIMILARITE and score > meilleur_score:
                meilleur_groupe = groupe
                meilleur_score = score
        if meilleur_groupe:
            meilleur_groupe["elements"].append(r)
            meilleur_groupe["mots"] |= mots_titre
        else:
            groupes.append({"mots": mots_titre, "elements": [r]})
    return groupes


def synthetiser_titre_heuristique(elements):
    if len(elements) == 1:
        return elements[0]["titre"]

    compte = {}
    casse_originale = {}
    ordre_apparition = []

    for e in elements:
        mots_bruts = re.findall(r"[A-Za-zÀ-ÿ0-9]+", e["titre"])
        vus_dans_ce_titre = set()
        for m in mots_bruts:
            m_norm = m.lower()
            if m_norm in MOTS_VIDES or len(m_norm) <= 2:
                continue
            if m_norm not in vus_dans_ce_titre:
                compte[m_norm] = compte.get(m_norm, 0) + 1
                vus_dans_ce_titre.add(m_norm)
            if m_norm not in casse_originale:
                casse_originale[m_norm] = m
                ordre_apparition.append(m_norm)

    seuil_frequence = max(2, (len(elements) + 1) // 2)
    mots_choisis = [m for m in ordre_apparition if compte.get(m, 0) >= seuil_frequence]

    if not mots_choisis:
        mots_choisis = sorted(ordre_apparition, key=lambda m: -compte.get(m, 0))[:6]

    mots_choisis = mots_choisis[:6]
    titre = " ".join(casse_originale[m] for m in mots_choisis)
    return titre if titre else elements[0]["titre"]


def synthetiser_titre_ia(elements):
    titres = [e["titre"] for e in elements[:8]]
    prompt = (
        "Voici plusieurs titres d'articles ou de posts qui parlent du même sujet d'actualité. "
        "Propose un titre de synthèse court (8 mots maximum), neutre et informatif, en français. "
        "Réponds uniquement avec le titre, sans guillemets ni ponctuation finale, sans préambule.\n\n"
        + "\n".join(f"- {t}" for t in titres)
    )
    try:
        reponse = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 60,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=10,
        )
        if reponse.status_code != 200:
            return None
        data = reponse.json()
        texte = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        return texte.strip('"« »') or None
    except Exception:
        return None


def synthetiser_titre(elements):
    if len(elements) == 1:
        return elements[0]["titre"]
    if ANTHROPIC_API_KEY:
        titre_ia = synthetiser_titre_ia(elements)
        if titre_ia:
            return titre_ia
    return synthetiser_titre_heuristique(elements)


# ------------------- FONCTIONS DE RECHERCHE -------------------
def est_recent(date_publication, seuil):
    if date_publication is None:
        return False
    return date_publication >= seuil


def parser_date_iso(chaine):
    """Parse une date ISO 8601 de façon tolérante (gère les fractions de secondes non standard)."""
    if not chaine:
        return None
    chaine = chaine.replace("Z", "+00:00")
    match = re.match(r"^(.*?\.\d{1,6})\d*(\+.*)$", chaine)
    if match:
        chaine = match.group(1) + match.group(2)
    try:
        return datetime.fromisoformat(chaine)
    except ValueError:
        return None


def est_pertinent(mot_cle, texte):
    """Vérifie que la majorité des mots significatifs du mot-clé apparaissent dans le texte."""
    mots_cle = [m for m in re.findall(r"[a-zàâäéèêëïîôöùûüç0-9]+", mot_cle.lower()) if len(m) > 2]
    if not mots_cle:
        return True
    texte_norm = texte.lower()
    trouves = sum(1 for m in mots_cle if m in texte_norm)
    seuil_requis = max(1, round(len(mots_cle) * 0.6))
    return trouves >= seuil_requis


def dedupliquer(resultats):
    """Supprime les doublons stricts (même lien ou même titre)."""
    vus = set()
    uniques = []
    for r in resultats:
        cle = (r["lien"] or "") + "|" + r["titre"].strip().lower()
        if cle in vus:
            continue
        vus.add(cle)
        uniques.append(r)
    return uniques


def extraire_image_html(html):
    if not html:
        return None
    match = re.search(r'<img[^>]+src="([^"]+)"', html)
    return match.group(1) if match else None


def chercher_google_news(mot_cle, seuil):
    url = f"https://news.google.com/rss/search?q={quote(mot_cle)}&hl=fr&gl=FR&ceid=FR:fr"
    flux = feedparser.parse(url)
    resultats = []
    for entree in flux.entries:
        date_pub = None
        if entree.get("published_parsed"):
            date_pub = datetime(*entree.published_parsed[:6], tzinfo=timezone.utc)
        if not est_recent(date_pub, seuil):
            continue
        titre_brut = entree.title
        media = None
        if " - " in titre_brut:
            titre_sans_media, _, media = titre_brut.rpartition(" - ")
            if titre_sans_media.strip():
                titre_brut = titre_sans_media.strip()
        source_label = "Google News" + (f" - {media.strip()}" if media else "")
        image = extraire_image_html(entree.get("summary", ""))
        resultats.append({"source": source_label, "titre": titre_brut, "lien": entree.link, "date_pub": date_pub, "image": image})
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
                image = extraire_image_html(entree.get("summary", ""))
                resultats.append({"source": "Reddit", "titre": entree.title, "lien": entree.link, "date_pub": date_pub, "image": image})
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
            resultats.append({"source": "Hacker News", "titre": hit.get("title", ""), "lien": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}", "date_pub": date_pub, "image": None})
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
            date_pub = parser_date_iso(statut.get("created_at"))
            if est_recent(date_pub, seuil):
                pieces_jointes = statut.get("media_attachments", [])
                image = pieces_jointes[0].get("preview_url") if pieces_jointes else None
                resultats.append({"source": "Mastodon - @" + statut.get("account", {}).get("acct", ""), "titre": statut.get("content", "")[:120], "lien": statut.get("url", ""), "date_pub": date_pub, "image": image})
        return resultats
    except Exception:
        return []


def chercher_bluesky(mot_cle, seuil):
    url = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
    params = {"q": mot_cle, "sort": "latest", "limit": 25}
    headers = {"User-Agent": "veille-outil/1.0"}
    try:
        reponse = requests.get(url, params=params, headers=headers, timeout=10)
        if reponse.status_code != 200:
            return []
        data = reponse.json()
    except Exception:
        return []

    resultats = []
    for post in data.get("posts", []):
        try:
            record = post.get("record", {})
            date_pub = parser_date_iso(record.get("createdAt"))
            if not est_recent(date_pub, seuil):
                continue
            auteur = post.get("author", {})
            handle = auteur.get("handle", "")
            uri = post.get("uri", "")
            rkey = uri.split("/")[-1] if uri else ""
            lien = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else ""
            texte = record.get("text", "")[:120]
            embed = post.get("embed", {})
            image = None
            if embed.get("images"):
                image = embed["images"][0].get("thumb")
            elif embed.get("external", {}).get("thumb"):
                image = embed["external"]["thumb"]
            resultats.append({
                "source": "Bluesky - @" + handle,
                "titre": texte,
                "lien": lien,
                "date_pub": date_pub,
                "image": image
            })
        except Exception:
            continue
    return resultats


def chercher_youtube(mot_cle, seuil):
    if not YOUTUBE_API_KEY:
        return []
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "q": mot_cle,
        "part": "snippet",
        "type": "video",
        "order": "date",
        "maxResults": 25,
        "publishedAfter": seuil.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "relevanceLanguage": "fr",
    }
    try:
        reponse = requests.get(url, params=params, timeout=10)
        if reponse.status_code != 200:
            return []
        data = reponse.json()
        resultats = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            date_pub = parser_date_iso(snippet.get("publishedAt"))
            video_id = item.get("id", {}).get("videoId")
            titre_video = snippet.get("title", "")
            description = snippet.get("description", "")
            if est_recent(date_pub, seuil) and video_id and est_pertinent(mot_cle, titre_video + " " + description):
                miniatures = snippet.get("thumbnails", {})
                image = (miniatures.get("medium") or miniatures.get("default") or {}).get("url")
                resultats.append({
                    "source": "YouTube - " + snippet.get("channelTitle", ""),
                    "titre": titre_video,
                    "lien": f"https://www.youtube.com/watch?v={video_id}",
                    "date_pub": date_pub,
                    "image": image
                })
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
        + chercher_bluesky(mot_cle, seuil)
        + chercher_youtube(mot_cle, seuil)
    )
    tous = [r for r in tous if est_pertinent(mot_cle, r["titre"])]
    tous = dedupliquer(tous)
    tous.sort(key=lambda r: r["date_pub"], reverse=True)
    return tous, maintenant


def afficher_resultats(resultats, maintenant, ne_garder_que_regroupes=False):
    if not resultats:
        st.warning(f"Aucun résultat publié dans les dernières {LIMITE_HEURES}h.")
        return

    groupes = regrouper_resultats(resultats)
    groupes.sort(key=lambda g: max(e["date_pub"] for e in g["elements"]), reverse=True)

    if ne_garder_que_regroupes:
        groupes = [g for g in groupes if len(g["elements"]) > 1]
        if not groupes:
            st.warning("Aucun sujet couvert par plusieurs sources pour l'instant. Décoche le filtre pour tout voir.")
            return

    st.success(f"{len(resultats)} résultat(s) trouvé(s), regroupés en {len(groupes)} sujet(s)")

    for groupe in groupes:
        elements = groupe["elements"]
        titre_groupe = synthetiser_titre(elements)
        plus_recent = max(e["date_pub"] for e in elements)
        age = maintenant - plus_recent
        heures = int(age.total_seconds() // 3600)
        minutes = int((age.total_seconds() % 3600) // 60)

        if len(elements) == 1:
            e = elements[0]
            col_img, col_texte = st.columns([1, 4]) if e.get("image") else (None, st)
            if col_img:
                with col_img:
                    st.image(e["image"], use_container_width=True)
                with col_texte:
                    st.markdown(f"**[{e['source']}]** {e['titre']}")
                    st.markdown(f"[{e['lien']}]({e['lien']}) — il y a {heures}h{minutes:02d}min")
            else:
                st.markdown(f"**[{e['source']}]** {e['titre']}")
                st.markdown(f"[{e['lien']}]({e['lien']}) — il y a {heures}h{minutes:02d}min")
        else:
            label = f"{titre_groupe}  —  🗞️ {len(elements)} articles (dernier il y a {heures}h{minutes:02d}min)"
            with st.expander(label):
                image_groupe = next((e.get("image") for e in elements if e.get("image")), None)
                if image_groupe:
                    st.image(image_groupe, width=320)
                for e in elements:
                    age_e = maintenant - e["date_pub"]
                    h_e = int(age_e.total_seconds() // 3600)
                    m_e = int((age_e.total_seconds() % 3600) // 60)
                    st.markdown(f"**[{e['source']}]** {e['titre']}")
                    st.markdown(f"[{e['lien']}]({e['lien']}) — il y a {h_e}h{m_e:02d}min")
                    st.markdown("")
        st.divider()


# ------------------- LANCEMENT -------------------
if lancer:
    if not YOUTUBE_API_KEY:
        st.info("Astuce : ajoute YOUTUBE_API_KEY dans les Secrets Streamlit pour inclure les vidéos YouTube.")
    if not ANTHROPIC_API_KEY:
        st.info("Astuce : ajoute ANTHROPIC_API_KEY dans les Secrets Streamlit pour des titres de synthèse plus naturels.")
    for mc in st.session_state.mots_cles:
        st.subheader(f"Résultats pour « {mc} »")
        with st.spinner(f"Recherche pour « {mc} »..."):
            resultats, maintenant = rechercher_tout(mc)
        afficher_resultats(resultats, maintenant, ne_garder_que_regroupes)
