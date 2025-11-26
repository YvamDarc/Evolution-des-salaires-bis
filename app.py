import streamlit as st
import pandas as pd
import plotly.express as px
import io
from datetime import datetime

st.set_page_config(page_title="Analyse sous-groupe soins", layout="wide")

st.title("📊 Analyse du sous-groupe « soins » – avec logique d’entrées, sorties et arrêts")

st.markdown(
    """
Cette application permet d'analyser les **évolutions du coût global** par salarié
pour un sous-groupe (par exemple *soins*), à partir d'un fichier Excel au format :

- `Salarie`
- `Sous_groupe`
- Colonnes mensuelles : `janv-24`, `févr-24`, ..., `oct-25`

Elle ajoute une **logique métier** :

- détection des **entrées / sorties en cours d’année**,
- repérage des mois d’**activité très faible** (souvent des arrêts, congés longs, temps partiel très réduit),
- calcul du **plus long bloc consécutif** de ces mois “faibles”.

Toutes les visualisations sont faites avec **Plotly**.
"""
)

# --------------------------------------------------------
# 1. UPLOAD FICHIER
# --------------------------------------------------------
uploaded_file = st.file_uploader("📂 Importer le fichier Excel (tableau récap)", type=["xlsx"])

if uploaded_file is None:
    st.info("Dépose un fichier Excel pour commencer.")
    st.stop()

# Lecture du fichier (1ère feuille)
df_raw = pd.read_excel(uploaded_file)

st.subheader("👁‍🗨 Aperçu des données importées")
st.dataframe(df_raw.head(), use_container_width=True)

# Vérif colonnes
required_cols = {"Salarie", "Sous_groupe"}
if not required_cols.issubset(df_raw.columns):
    st.error(f"Le fichier doit contenir au minimum les colonnes : {required_cols}")
    st.stop()

# --------------------------------------------------------
# 2. PRÉPARATION DES DONNÉES
# --------------------------------------------------------

# Colonnes de périodes = toutes sauf identifiants
id_cols = ["Salarie", "Sous_groupe"]
period_cols = [c for c in df_raw.columns if c not in id_cols]

if len(period_cols) == 0:
    st.error("Aucune colonne de mois détectée (en dehors de Salarie / Sous_groupe).")
    st.stop()

# On crée une correspondance "nom de colonne" -> vraie date (en partant de janv-2024)
# On suppose que les colonnes sont déjà dans l'ordre chronologique.
dates = pd.date_range("2024-01-01", periods=len(period_cols), freq="MS")
col_to_date = dict(zip(period_cols, dates))

# Passage au format long
df_long = df_raw.melt(
    id_vars=id_cols,
    value_vars=period_cols,
    var_name="Periode_label",
    value_name="Cout_global",
)

# Ajout de la date réelle
df_long["Date"] = df_long["Periode_label"].map(col_to_date)
df_long = df_long.dropna(subset=["Date"])  # au cas où
df_long["Year"] = df_long["Date"].dt.year

# On garde uniquement les lignes avec un coût renseigné
df_long = df_long.dropna(subset=["Cout_global"])

# --------------------------------------------------------
# 2bis. CHOIX DU SOUS-GROUPE
# --------------------------------------------------------
st.subheader("🎯 Choix du sous-groupe à analyser")
group_options = sorted(df_long["Sous_groupe"].dropna().unique().tolist())
default_idx = group_options.index("soins") if "soins" in group_options else 0
selected_group = st.selectbox("Sous-groupe :", group_options, index=default_idx)

df_group = df_long[df_long["Sous_groupe"] == selected_group].copy()

if df_group.empty:
    st.warning(f"Aucune donnée pour le sous-groupe « {selected_group} ».")
    st.stop()

# --------------------------------------------------------
# 2ter. LOGIQUE ARRÊTS / ENTRÉES / SORTIES
# --------------------------------------------------------

st.subheader("🧩 Paramètres de détection des arrêts")

seuil_absence = st.slider(
    "Seuil de coût mensuel en-dessous duquel on considère un mois comme « activité très réduite / arrêt » :",
    min_value=0,
    max_value=3000,
    value=1500,
    step=100,
    help="En-dessous de ce montant, on considère que le salarié n'est que très peu présent (arrêt, congé long, temps partiel très réduit...).",
)

# Index temporel global
dates_sorted = sorted(df_group["Date"].unique())
date_to_idx = {d: i for i, d in enumerate(dates_sorted)}
df_group["idx"] = df_group["Date"].map(date_to_idx)

global_first_idx = 0
global_last_idx = len(dates_sorted) - 1

def longest_true_streak(bool_list):
    """Retourne la longueur max de 'True' consécutifs dans une liste booléenne."""
    max_streak = 0
    streak = 0
    for val in bool_list:
        if val:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak

def parcours_logic(sub):
    """Calcule la logique entrée/sortie/arrêts pour un salarié."""
    sub = sub.sort_values("idx")
    first_idx = int(sub["idx"].min())
    last_idx = int(sub["idx"].max())

    entree = first_idx > global_first_idx
    sortie = last_idx < global_last_idx

    faible = (sub["Cout_global"] <= seuil_absence) | sub["Cout_global"].isna()
    nb_faibles = int(faible.sum())
    longest = int(longest_true_streak(list(faible)))

    return pd.Series({
        "entree_en_cours": entree,
        "sortie_en_cours": sortie,
        "nb_mois_faibles": nb_faibles,
        "plus_long_arret": longest,
    })

parcours = (
    df_group.groupby("Salarie")
    .apply(parcours_logic)
    .reset_index()
)

# --------------------------------------------------------
# 3. INDICATEURS PAR SALARIÉ
# --------------------------------------------------------

# Moyenne annuelle par salarié
annual_mean = (
    df_group
    .groupby(["Salarie", "Sous_groupe", "Year"], as_index=False)["Cout_global"]
    .mean()
)

# Pivot pour avoir 2024 / 2025 côte à côte
resume = annual_mean.pivot_table(
    index=["Salarie", "Sous_groupe"],
    columns="Year",
    values="Cout_global"
).reset_index()

# Renommage plus lisible
col_2024 = 2024 if 2024 in resume.columns else None
col_2025 = 2025 if 2025 in resume.columns else None

if col_2024 is not None:
    resume["moy_2024"] = resume[col_2024]
else:
    resume["moy_2024"] = pd.NA

if col_2025 is not None:
    resume["moy_2025"] = resume[col_2025]
else:
    resume["moy_2025"] = pd.NA

# Variation absolue / relative
resume["var_abs"] = resume["moy_2025"] - resume["moy_2024"]
resume["var_rel_%"] = resume["var_abs"] / resume["moy_2024"] * 100

# Volatilité (écart-type)
volatility = (
    df_group
    .groupby("Salarie")["Cout_global"]
    .std()
    .rename("ecart_type")
    .reset_index()
)

resume = resume.merge(volatility, on="Salarie", how="left")

# Anomalies (valeurs très faibles ou négatives)
df_group["Anomalie"] = (df_group["Cout_global"] <= 0) | (df_group["Cout_global"] < 500)
anom_summary = (
    df_group.groupby("Salarie")["Anomalie"]
    .sum()
    .rename("nb_anomalies")
    .reset_index()
)

resume = resume.merge(anom_summary, on="Salarie", how="left")
resume["nb_anomalies"] = resume["nb_anomalies"].fillna(0).astype(int)

# Ajout de la logique de parcours (entrées, sorties, arrêts)
resume = resume.merge(parcours, on="Salarie", how="left")

# Tri par variation décroissante
resume_sorted = resume.sort_values("var_abs", ascending=False)

# --------------------------------------------------------
# 4. RÉSUMÉ GLOBAL
# --------------------------------------------------------

st.subheader("📌 Résumé global du sous-groupe")

sum_2024 = df_group[df_group["Year"] == 2024]["Cout_global"].sum()
sum_2025 = df_group[df_group["Year"] == 2025]["Cout_global"].sum()
delta_total = sum_2025 - sum_2024

col1, col2, col3 = st.columns(3)
col1.metric("Total 2024", f"{sum_2024:,.0f} €".replace(",", " "))
col2.metric("Total 2025", f"{sum_2025:,.0f} €".replace(",", " "),
            delta=f"{delta_total:,.0f} €".replace(",", " "))
if sum_2024 != 0:
    col3.metric("Évolution globale", f"{(delta_total / sum_2024 * 100):.1f} %")
else:
    col3.metric("Évolution globale", "n/a")

nb_entrees = int(resume["entree_en_cours"].sum())
nb_sorties = int(resume["sortie_en_cours"].sum())
nb_long_arrets = int((resume["plus_long_arret"] >= 2).sum())

st.markdown(
    f"""
- **{nb_entrees} salarié(s)** semblent **entrer en cours de période** (pas de coût sur les premiers mois).
- **{nb_sorties} salarié(s)** semblent **sortir en cours de période**.
- **{nb_long_arrets} salarié(s)** présentent au moins **2 mois consécutifs** en-dessous de {seuil_absence} €,  
  ce qui ressemble à des **arrêts / longues absences**.
"""
)

# Graphique global : évolution mensuelle totale du sous-groupe
st.markdown("### 📉 Évolution mensuelle globale du sous-groupe")
agg_month = (
    df_group.groupby("Date", as_index=False)["Cout_global"]
    .sum()
    .sort_values("Date")
)

fig_tot = px.line(
    agg_month,
    x="Date",
    y="Cout_global",
    markers=True,
    title=f"Coût global mensuel du sous-groupe « {selected_group} »",
)
fig_tot.update_layout(
    xaxis_title="Mois",
    yaxis_title="Coût global (€)",
    xaxis_tickformat="%m/%Y",
)
st.plotly_chart(fig_tot, use_container_width=True)

# --------------------------------------------------------
# 5. TOP HAUSSES / BAISSES
# --------------------------------------------------------

st.subheader("🏆 Salariés qui expliquent les principales évolutions")

top_n = st.slider("Nombre de salariés à afficher dans les classements :", 5, 20, 10)

# Top hausses
top_up = resume_sorted.head(top_n)
# Top baisses
top_down = resume_sorted.sort_values("var_abs", ascending=True).head(top_n)

col_up, col_down = st.columns(2)

with col_up:
    st.markdown("#### 📈 Plus fortes **hausses** (moyenne 2025 vs 2024)")
    fig_up = px.bar(
        top_up,
        x="Salarie",
        y="var_abs",
        hover_data=[
            "moy_2024",
            "moy_2025",
            "var_rel_%",
            "ecart_type",
            "nb_anomalies",
            "entree_en_cours",
            "sortie_en_cours",
            "plus_long_arret",
        ],
        title="Top hausses de coût moyen annuel",
    )
    fig_up.update_layout(xaxis_title="", yaxis_title="Variation absolue (€)")
    fig_up.update_xaxes(tickangle=45)
    st.plotly_chart(fig_up, use_container_width=True)

with col_down:
    st.markdown("#### 📉 Plus fortes **baisses**")
    fig_down = px.bar(
        top_down,
        x="Salarie",
        y="var_abs",
        hover_data=[
            "moy_2024",
            "moy_2025",
            "var_rel_%",
            "ecart_type",
            "nb_anomalies",
            "entree_en_cours",
            "sortie_en_cours",
            "plus_long_arret",
        ],
        title="Top baisses de coût moyen annuel",
    )
    fig_down.update_layout(xaxis_title="", yaxis_title="Variation absolue (€)")
    fig_down.update_xaxes(tickangle=45)
    st.plotly_chart(fig_down, use_container_width=True)

# --------------------------------------------------------
# 6. NIVEAU vs VOLATILITÉ (avec logique)
# --------------------------------------------------------

st.subheader("🌪 Stabilité vs niveau de coût (en tenant compte des arrêts)")

df_scatter = resume.dropna(subset=["moy_2024", "ecart_type", "var_abs"]).copy()

if df_scatter.empty:
    st.info("Pas assez de données complètes pour afficher le graphique de stabilité.")
else:
    df_scatter["size_var"] = df_scatter["var_abs"].abs()

    fig_scatter = px.scatter(
        df_scatter,
        x="moy_2024",
        y="ecart_type",
        size="size_var",
        color="var_abs",
        hover_data=[
            "Salarie",
            "moy_2025",
            "var_rel_%",
            "nb_anomalies",
            "entree_en_cours",
            "sortie_en_cours",
            "plus_long_arret",
            "nb_mois_faibles",
        ],
        title="Niveau moyen 2024 vs volatilité (variation en taille/couleur, arrêts en info-bulle)",
    )
    fig_scatter.update_layout(
        xaxis_title="Coût moyen 2024 (€)",
        yaxis_title="Écart-type du coût mensuel (€)",
    )
    st.plotly_chart(fig_scatter, use_container_width=True)

    st.markdown(
        f"""
**Lecture :**

- Les points en haut sont les salariés **instables** (forte variabilité).
- Les bulles grandes représentent les salariés avec une **grosse variation moyenne** entre 2024 et 2025.
- Les infos-bulles indiquent s'il s'agit plutôt d'un **effet structurel** (arrivée/départ),
  de **longs arrêts** (*plus_long_arret ≥ 2 mois sous {seuil_absence} €*),
  ou d'une vraie **augmentation de rythme / de quotité**.
"""
    )

# --------------------------------------------------------
# 7. ANOMALIES
# --------------------------------------------------------

st.subheader("⚠️ Anomalies possibles (très faible ou négatif)")

df_anom = df_group[df_group["Anomalie"]].copy()
if df_anom.empty:
    st.info("Aucune anomalie nette détectée (coût < 500 € ou ≤ 0).")
else:
    st.markdown(
        """
Les lignes ci-dessous correspondent à des **coûts mensuels très faibles ou négatifs**  
(qui peuvent être soit des **erreurs de données**, soit des cas particuliers à vérifier : régularisations, fins de contrat, etc.).
"""
    )
    st.dataframe(
        df_anom.sort_values(["Salarie", "Date"])[
            ["Salarie", "Date", "Cout_global", "Periode_label"]
        ],
        use_container_width=True,
    )

# --------------------------------------------------------
# 8. RÉCAPITULATIF & EXPORT
# --------------------------------------------------------

st.subheader("📋 Tableau récapitulatif par salarié")

affiche_cols = [
    "Salarie",
    "Sous_groupe",
    "moy_2024",
    "moy_2025",
    "var_abs",
    "var_rel_%",
    "ecart_type",
    "nb_anomalies",
    "entree_en_cours",
    "sortie_en_cours",
    "nb_mois_faibles",
    "plus_long_arret",
]

st.dataframe(
    resume_sorted[affiche_cols],
    use_container_width=True,
)

# Petite synthèse automatique plus "logique"
st.markdown("### 🧠 Synthèse automatique (version métier)")

top_contrib = resume_sorted.head(5)
if delta_total != 0:
    part_top = (top_contrib["var_abs"].sum() / delta_total * 100)
else:
    part_top = 0

sal_instable = resume_sorted.sort_values("ecart_type", ascending=False).iloc[0]

st.markdown(
    f"""
- Les **5 plus fortes hausses** expliquent environ **{part_top:.1f} %** de la variation totale du groupe.
- Parmi ces 5, **{int((top_contrib['entree_en_cours']).sum())}** sont des **entrées en cours de période**
  et **{int((top_contrib['plus_long_arret'] >= 2).sum())}** ont au moins **un arrêt long**,  
  ce qui indique que la hausse est souvent liée à un **changement de présence** plutôt qu'à une pure hausse de coût horaire.
- Le salarié le plus instable est **{sal_instable['Salarie']}**  
  (écart-type ≈ {sal_instable['ecart_type']:.0f} €, plus long arrêt : {int(sal_instable['plus_long_arret'])} mois).
"""
)

# Export Excel
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
    resume_sorted.to_excel(writer, index=False, sheet_name="Resume_sous_groupe")
    df_group.to_excel(writer, index=False, sheet_name="Detail_long")

st.download_button(
    "💾 Télécharger le fichier d'analyse (Excel)",
    data=buffer.getvalue(),
    file_name=f"analyse_{selected_group}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
