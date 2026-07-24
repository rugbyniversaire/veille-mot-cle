import streamlit as st
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from supabase import create_client

# ------------------- CONNEXION SUPABASE -------------------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Veille mot-clé", page_icon="🔍")

if "session" not in st.session_state:
    st.session_state.session = None


# ------------------- ECRAN DE CONNEXION -------------------
def ecran_connexion():
    st.title("🔍 Outil de veille")
    onglet_connexion, onglet_inscription = st.tabs(["Connexion", "Inscription"])

    with onglet_connexion:
        email = st.text_input("Email", key="email_connexion")
        mot_de_passe = st.text_input("Mot de passe", type="password", key="mdp_connexion")
        if st.button("Se connecter"):
            try:
                resultat = supabase.auth.sign_in_with_password({"email": email, "password": mot_de_passe})
                st.session_state.session = resultat.session
                st.rerun()
            except Exception as e:
                st.error(f"Erreur de connexion : {e}")

    with onglet_inscription:
        email_i = st.text_input("Email", key="email_inscription")
        mdp_i = st.text_input("Mot de passe (6 caractères min.)", type="password", key="mdp_inscription")
        if st.button("Créer un compte"):
            try:
                supabase.auth.sign_up({"email": email_i, "password": mdp_i})
                st.success("Compte créé. Vérifie ta boîte mail pour confirmer, puis connecte-toi.")
            except Exception as e:
                st.error(f"Erreur d'inscription : {e}")


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
    seuil = maintenant - timedelta(hours=24)
    tous = (
        chercher_google_news(mot_cle, seuil)
        + chercher_reddit(mot_cle, seuil)
        + chercher_hackernews(mot_cle, seuil)
        + chercher_mastodon(mot_cle, seuil)
    )
    tous.sort(key=lambda r: r["date_pub"], reverse=True)
    return tous, maintenant


# ------------------- ECRAN PRINCIPAL (CONNECTE) -------------------
def ecran_principal():
    user_id = st.session_state.session.user.id

    col1, col2 = st.columns([4, 1])
    with col1:
        st.title("🔍 Outil de veille")
    with col2:
        if st.button("Déconnexion"):
            supabase.auth.sign_out()
            st.session_state.session = None
            st.rerun()

    st.subheader("Tes mots-clés suivis")

    nouveau_mot_cle = st.text_input("Ajouter un mot-clé")
    if st.button("Ajouter") and nouveau_mot_cle.strip():
        supabase.table("mots_cles").insert({"user_id": user_id, "mot_cle": nouveau_mot_cle.strip()}).execute()
        st.rerun()

    reponse = supabase.table("mots_cles").select("*").eq("user_id", user_id).order("cree_le", desc=True).execute()
    mots_cles = reponse.data

    if not mots_cles:
        st.info("Aucun mot-clé enregistré pour l'instant.")
    else:
        for mc in mots_cles:
            col_a, col_b, col_c = st.columns([3, 1, 1])
            col_a.write(mc["mot_cle"])
            if col_b.button("Rechercher", key=f"chercher_{mc['id']}"):
                st.session_state.mot_cle_actif = mc["mot_cle"]
            if col_c.button("🗑️", key=f"suppr_{mc['id']}"):
                supabase.table("mots_cles").delete().eq("id", mc["id"]).execute()
                st.rerun()

        if st.button("Tout vérifier"):
            st.session_state.tout_verifier = True

    st.divider()

    # Recherche sur un seul mot-clé
    if st.session_state.get("mot_cle_actif"):
        mot = st.session_state.mot_cle_actif
        st.subheader(f"Résultats pour « {mot} »")
        with st.spinner("Recherche en cours..."):
            resultats, maintenant = rechercher_tout(mot)
        afficher_resultats(resultats, maintenant)

    # Recherche sur tous les mots-clés
    if st.session_state.get("tout_verifier"):
        st.session_state.tout_verifier = False
        for mc in mots_cles:
            st.subheader(f"Résultats pour « {mc['mot_cle']} »")
            with st.spinner(f"Recherche pour {mc['mot_cle']}..."):
                resultats, maintenant = rechercher_tout(mc["mot_cle"])
            afficher_resultats(resultats, maintenant)


def afficher_resultats(resultats, maintenant):
    if not resultats:
        st.warning("Aucun résultat publié dans les dernières 24h.")
        return
    st.success(f"{len(resultats)} résultat(s) trouvé(s)")
    for r in resultats:
        age = maintenant - r["date_pub"]
        heures = int(age.total_seconds() // 3600)
        minutes = int((age.total_seconds() % 3600) // 60)
        st.markdown(f"**[{r['source']}]** {r['titre']}")
        st.markdown(f"[{r['lien']}]({r['lien']}) — il y a {heures}h{minutes:02d}min")
        st.divider()


# ------------------- ROUTAGE -------------------
if st.session_state.session is None:
    ecran_connexion()
else:
    ecran_principal()
