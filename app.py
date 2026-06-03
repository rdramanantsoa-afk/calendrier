import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
import io
import re

st.set_page_config(page_title="Générateur de Calendrier de Paiement", layout="wide")
st.title("Abattement & Calendrier de Paiement Automatique")

def extraire_annee_mois(row):
    months_fr = ['janvier', 'février', 'fevrier', 'mars', 'avril', 'mai', 'juin', 
                 'juillet', 'août', 'aout', 'septembre', 'octobre', 'novembre', 'décembre', 'decembre']
    texte_complet = f"{str(row.get('ANNEE', ''))} {str(row.get('MOIS', ''))}".lower()
    
    annee_trouvee = re.search(r'\b(20\d{2})\b', texte_complet)
    annee_final = int(annee_trouvee.group(1)) if annee_trouvee else None
    
    if annee_final is None and pd.notna(row.get('Date échéance')):
        try:
            annee_final = pd.to_datetime(row['Date échéance']).year
        except:
            annee_final = 2025

    mois_final = ""
    for m in months_fr:
        if m in texte_complet:
            mois_final = m.capitalize()
            break
            
    if not mois_final and pd.notna(row.get('Date échéance')):
        try:
            dt = pd.to_datetime(row['Date échéance'])
            mois_list_fr = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 
                            'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
            mois_final = mois_list_fr[dt.month - 1]
        except:
            mois_final = "Décembre"
            
    if mois_final == "Fevrier": mois_final = "Février"
    if mois_final == "Aout": mois_final = "Août"
    if mois_final == "Decembre": mois_final = "Décembre"
    if not mois_final: mois_final = "Décembre"
        
    return annee_final, mois_final

def calculer_penalites(principal, date_echeance_legale, date_calendrier):
    if pd.isna(principal) or principal <= 0 or pd.isna(date_echeance_legale) or date_calendrier <= date_echeance_legale:
        return 0, 0
    
    diff = relativedelta(date_calendrier, date_echeance_legale)
    nb_mois = diff.years * 12 + diff.months
    if diff.days > 0:
        nb_mois += 1
    if nb_mois <= 0:
        return 0, 0
    taux = 0.03 + (nb_mois - 1) * 0.01
    return principal * taux, taux

def generer_calendrier(df_input, nb_echeances, date_debut):
    df = df_input.copy()
    df.columns = df.columns.str.strip()
    
    # Gestion de la date légale d'échéance
    if 'Date échéance' in df.columns:
        df['Date_Echeance_Legale'] = pd.to_datetime(df['Date échéance'], dayfirst=True, errors='coerce')
    else:
        # Si pas de colonne "Date échéance", on va la générer via l'Année / Mois
        df['Date_Echeance_Legale'] = None

    annees_propres = []
    mois_propres = []
    for idx, row in df.iterrows():
        a, m = extraire_annee_mois(row)
        annees_propres.append(a)
        mois_propres.append(m)
        
    df['ANNEE'] = annees_propres
    df['MOIS'] = mois_propres
    
    # Recréer proprement la date légale si elle manquait
    for idx, row in df.iterrows():
        if pd.isna(row['Date_Echeance_Legale']):
            months_map = {
                'Janvier': 1, 'Février': 2, 'Mars': 3, 'Avril': 4, 'Mai': 5, 'Juin': 6,
                'Juillet': 7, 'Août': 8, 'Septembre': 9, 'Octobre': 10, 'Novembre': 11, 'Décembre': 12
            }
            num_m = months_map.get(row['MOIS'], 12)
            df.at[idx, 'Date_Echeance_Legale'] = datetime(int(row['ANNEE']), num_m, 17)

    df['Principal'] = pd.to_numeric(df['Principal'], errors='coerce').fillna(0)
    df['Amende'] = pd.to_numeric(df['Amende'], errors='coerce').fillna(0)
    
    # RECHERCHE FLEXIBLE : Détecte 'Pénalité de retard' ou 'Pénalités de retard'
    col_penalite_source = None
    for c in df.columns:
        if 'pénalité' in c.lower() and 'retard' in c.lower():
            col_penalite_source = c
            break
            
    if col_penalite_source:
        df['Pénalités_Initiales'] = pd.to_numeric(df[col_penalite_source], errors='coerce').fillna(0)
    else:
        df['Pénalités_Initiales'] = 0
    
    df = df.sort_values(by='Date_Echeance_Legale').reset_index(drop=True)
    
    # Le montant moyen inclut TOUT (Principal + Amende + Pénalités existantes de l'input)
    total_base = df['Principal'].sum() + df['Amende'].sum() + df['Pénalités_Initiales'].sum()
    montant_moyen_cible = total_base / nb_echeances
    seuil_max = montant_moyen_cible * 1.10
    
    dates_calendrier = [date_debut + relativedelta(months=i) for i in range(nb_echeances + 24)]
    lignes_sortie = []
    idx_echeance_actuelle = 0
    cumul_echeance_courante = 0
    piles_dettes = df.to_dict('records')
    
    while len(piles_dettes) > 0:
        dette = piles_dettes.pop(0)
        p_dispo = dette['Principal']
        a_dispo = dette['Amende']
        pen_dispo = dette['Pénalités_Initiales']
        
        total_dette_ligne = p_dispo + a_dispo + pen_dispo
        
        if total_dette_ligne == 0:
            continue
            
        reste_place_cible = montant_moyen_cible - cumul_echeance_courante
        
        if cumul_echeance_courante + total_dette_ligne <= seuil_max:
            dette['Échéance'] = dates_calendrier[idx_echeance_actuelle].strftime('%Y-%m-%d')
            cumul_echeance_courante += total_dette_ligne
            lignes_sortie.append(dette)
            if cumul_echeance_courante >= montant_moyen_cible:
                idx_echeance_actuelle += 1
                cumul_echeance_courante = 0
        else:
            part_a_prendre = max(0, reste_place_cible)
            if part_a_prendre == 0 and cumul_echeance_courante > 0:
                idx_echeance_actuelle += 1
                cumul_echeance_courante = 0
                piles_dettes.insert(0, dette)
                continue
                
            ratio = part_a_prendre / total_dette_ligne if total_dette_ligne > 0 else 0
            
            dette_actuelle = dette.copy()
            dette_actuelle['Principal'] = p_dispo * ratio
            dette_actuelle['Amende'] = a_dispo * ratio
            dette_actuelle['Pénalités_Initiales'] = pen_dispo * ratio
            dette_actuelle['Échéance'] = dates_calendrier[idx_echeance_actuelle].strftime('%Y-%m-%d')
            lignes_sortie.append(dette_actuelle)
            
            dette_restante = dette.copy()
            dette_restante['Principal'] = p_dispo - (p_dispo * ratio)
            dette_restante['Amende'] = a_dispo - (a_dispo * ratio)
            dette_restante['Pénalités_Initiales'] = pen_dispo - (pen_dispo * ratio)
            piles_dettes.insert(0, dette_restante)
            
            idx_echeance_actuelle += 1
            cumul_echeance_courante = 0

    df_result = pd.DataFrame(lignes_sortie)
    
    penalites_finales = []
    taux_totaux = []
    
    for _, r in df_result.iterrows():
        if r['Principal'] > 0:
            dt_cal = datetime.strptime(r['Échéance'], '%Y-%m-%d')
            p, t = calculer_penalites(r['Principal'], r['Date_Echeance_Legale'], dt_cal)
            penalites_finales.append(p)
            taux_totaux.append(t)
        else:
            # S'il n'y a pas de principal, on récupère le montant de la pénalité isolée de l'input
            penalites_finales.append(r['Pénalités_Initiales'])
            taux_totaux.append(0)
        
    df_result['Pénalités de retard'] = penalites_finales
    df_result['Taux'] = taux_totaux
    df_result['Total'] = df_result['Principal'] + df_result['Amende'] + df_result['Pénalités de retard']
    return df_result, montant_moyen_cible

uploaded_file = st.file_uploader("Étape 1 : Chargez votre fichier (INPUT)", type=["csv", "xlsx"])
if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_in = pd.read_csv(uploaded_file)
        else:
            df_in = pd.read_excel(uploaded_file)
            
        st.success("Fichier INPUT chargé avec succès !")
        st.sidebar.header("Paramètres")
        nb_echeances = st.sidebar.number_input("Nombre d'échéances :", min_value=1, max_value=24, value=4)
        date_initiale = st.sidebar.date_input("Date de la première échéance :", datetime(2026, 6, 22))
        
        if st.button("Calculer et Générer le Calendrier"):
            date_initiale_dt = datetime(date_initiale.year, date_initiale.month, date_initiale.day)
            df_out, moy_cible = generer_calendrier(df_in, nb_echeances, date_initiale_dt)
            
            st.subheader("📊 Synthèse Globale")
            col1, col2, col3 = st.columns(3)
            col1.metric("Montant Moyen / Échéance", f"{moy_cible:,.2f} MGA")
            col2.metric("Total Pénalités", f"{df_out['Pénalités de retard'].sum():,.2f} MGA")
            col3.metric("Total Global", f"{df_out['Total'].sum():,.2f} MGA")
            
            cols_to_show = ['Échéance', 'NATURE', 'ANNEE', 'MOIS', 'Principal', 'Amende', 'Pénalités de retard', 'Taux', 'Total']
            df_clean = df_out[[c for c in cols_to_show if c in df_out.columns]].copy()
            
            final_rows = []
            for echeance_date, group in df_clean.groupby('Échéance', sort=True):
                for _, row in group.iterrows():
                    final_rows.append(row.to_dict())
                
                subtotal_row = {
                    'Échéance': f"SOUS-TOTAL {echeance_date}",
                    'NATURE': '', 'ANNEE': '', 'MOIS': '',
                    'Principal': group['Principal'].sum(),
                    'Amende': group['Amende'].sum(),
                    'Pénalités de retard': group['Pénalités de retard'].sum(),
                    'Taux': np.nan,
                    'Total': group['Total'].sum()
                }
                final_rows.append(subtotal_row)
                
            df_final_with_subtotals = pd.DataFrame(final_rows)
            
            st.subheader("📋 Calendrier Format OUTPUT")
            st.dataframe(df_final_with_subtotals.style.format({
                'Principal': '{:,.2f}',
                'Amende': '{:,.2f}',
                'Pénalités de retard': '{:,.2f}',
                'Taux': lambda x: f"{x:.0%}" if pd.notna(x) else "",
                'Total': '{:,.2f}'
            }))
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_final_with_subtotals.to_excel(writer, index=False, sheet_name='OUTPUT')
            st.download_button(label="📥 Télécharger OUTPUT (Excel)", data=output.getvalue(), file_name="calendrier_paiement_output.xlsx")
    except Exception as e:
        st.error(f"Erreur : {e}")
