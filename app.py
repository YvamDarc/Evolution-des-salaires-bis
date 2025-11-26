import streamlit as st
import pandas as pd
import plotly.express as px
import io
from datetime import datetime

st.set_page_config(page_title="Analyse sous-groupe soins", layout="wide")

st.title("📊 Analyse du sous-groupe « soins »")

st.markdown(
    """
Cette application permet d'analyser les **évolutions du coût global** par salarié
pour un sous-groupe (par exemple *soins*), à partir d'un fichier Excel au format :

- `Salarie`
- `Sous_groupe`
- Colonnes mensuelles : `janv-24`, `févr-24`, ..., `oct-25`

Les graphiques utilisent **Plotly** pour être interactifs.
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

# Restriction à un sous-groupe (par défaut "soins" si présent)
st.subheader("🎯 Choix du sous-groupe à analyser")
group_options = sorted(df_long["Sous_groupe"].dropna().unique().tolist())
default_idx = group_options.index("soins") if "soins" in group_options else 0
selected_group = st.selectbox("Sous-groupe :", group_options, index=default_idx)

df_group = df_long[df_long["Sous_groupe"] == selected_group].copy()

if df_group.empty:
    st.warning(f"Aucune donnée pour le sous-groupe « {selected_group} ».")
    st.stop()

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
        hover_data=["moy_2024", "moy_2025", "var_rel_%", "ecart_type", "nb_anomalies"],
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
        hover_data=["moy_2024", "moy_2025", "var_rel_%", "ecart_type", "nb_anomalies"],
        title="Top baisses de coût moyen annuel",
    )
    fig_down.update_layout(xaxis_title="", yaxis_title="Variation absolue (€)")
    fig_down.update_xaxes(tickangle=45)
    st.plotly_chart(fig_down, use_container_width=True)

# --------------------------------------------------------
# 6. NIVEAU vs VOLATILITÉ (CORRIGÉ)
# --------------------------------------------------------

st.subheader("🌪 Stabilité vs niveau de coût")

# On enlève les NaN et on impose une taille positive
df_scatter = resume.dropna(subset=["moy_2024", "ecart_type", "var_abs"]).copy()

if df_scatter.empty:
    st.info("Pas assez de données complètes pour afficher le graphique de stabilité.")
else:
    df_scatter["size_var"] = df_scatter["var_abs"].abs()
    # Si tout est à 0, Plotly peut ne rien afficher, mais ce n'est pas bloquant

    fig_scatter = px.scatter(
        df_scatter,
        x="moy_2024",
        y="ecart_type",
        size="size_var",         # taille = valeur absolue
        color="var_abs",         # couleur = hausse ou baisse
        hover_data=["Salarie", "moy_2025", "var_rel_%", "nb_anomalies"],
        title="Niveau moyen 2024 vs volatilité (avec variation comme taille/couleur)",
    )
    fig_scatter.update_layout(
        xaxis_title="Coût moyen 2024 (€)",
        yaxis_title="Écart-type du coût mensuel (€)",
    )
    st.plotly_chart(fig_scatter, use_container_width=True)

    st.markdown(
        """
**Lecture :**
- Les points en haut sont les salariés **instables** (forte variabilité).
- Les bulles grandes et colorées représentent les salariés qui **pèsent le plus** dans l'évolution globale.
"""
    )

# --------------------------------------------------------
# 7. ANOMALIES
# --------------------------------------------------------

st.subheader("⚠️ Anomalies possibles")

df_anom = df_group[df_group["Anomalie"]].copy()
if df_anom.empty:
    st.info("Aucune anomalie détectée selon la règle simple (coût < 500 € ou ≤ 0).")
else:
    st.markdown(
        "Les lignes ci-dessous correspondent à des **coûts mensuels très faibles ou négatifs**."
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

st.dataframe(
    resume_sorted[["Salarie", "Sous_groupe", "moy_2024", "moy_2025", "var_abs", "var_rel_%", "ecart_type", "nb_anomalies"]],
    use_container_width=True,
)

# Petite synthèse automatique
st.markdown("### 🧠 Synthèse automatique")

top_contrib = resume_sorted.head(5)
if delta_total != 0:
    part_top = (top_contrib["var_abs"].sum() / delta_total * 100)
else:
    part_top = 0

st.markdown(
    f"""
- Les **5 plus fortes hausses** expliquent environ **{part_top:.1f} %** de la variation totale du groupe.
- Le salarié avec la plus forte hausse est **{top_contrib.iloc[0]['Salarie']}**  
  (variation moyenne ≈ {top_contrib.iloc[0]['var_abs']:.0f} €).
- Le salarié le plus instable est **{resume.sort_values('ecart_type', ascending=False).iloc[0]['Salarie']}**  
  (écart-type ≈ {resume['ecart_type'].max():.0f} €).
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
