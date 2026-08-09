"""Throwaway: $/acre worked example + irrigated-vs-non-irrigated rate split, from ADM RY2026."""
import json, csv, collections, statistics, math
import pandas as pd
D='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/'
COVS=[0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85]
SUB26={'OU':{.50:.67,.55:.69,.60:.69,.65:.64,.70:.64,.75:.60,.80:.51,.85:.41},
       'EU':{.50:.80,.55:.80,.60:.80,.65:.80,.70:.80,.75:.80,.80:.71,.85:.56}}
SUB25={'OU':{.50:.67,.55:.64,.60:.64,.65:.59,.70:.59,.75:.55,.80:.48,.85:.38},
       'EU':{.50:.80,.55:.80,.60:.80,.65:.80,.70:.80,.75:.77,.80:.68,.85:.53}}
SUB25['BU']=SUB25['OU']; SUB26['BU']=SUB26['OU']

# --- A01010 base-rate parameters for Champaign IL (17/019) corn, non-irrigated grain ---
br=pd.read_csv('data/cache/adm/2026_A01010_BaseRate_YTD.txt',sep='|',dtype=str)
br=br[(br['Deleted Date'].isna())&(br['Commodity Code']=='0041')&(br['State Code']=='17')
      &(br['County Code']=='019')&(br['Insurance Plan Code']=='02')&(br['Sub County Code'].isna())]
print("Champaign IL corn RP base-rate rows:",len(br))
print(br[['Type Code','Practice Code','Irrigation Practice Code','Coverage Level Percent',
          'Reference Amount','Reference Rate','Exponent Value','Fixed Rate']].drop_duplicates().to_string())

# --- benchmark county RDF/URF from the A01040 scan ---
cld=json.load(open(D+'cld.json'))
b=pd.DataFrame(cld['bench'])
b=b[(b['Commodity Code']=='0041')&(b['State Code']=='17')&(b['County Code']=='019')
    &(b['Insurance Plan Code']=='02')]
print("\nChampaign corn RP A01040 rows:",len(b), "practices:",sorted(b['Practice Code'].unique()))

# --- practice / type comparison within Champaign ---
b2=b[b['Type Code']=='016'].copy()
for c in ['Coverage Level Percent','Rate Differential Factor','Unit Residual Factor',
          'Enterprise Unit Residual Factor']: b2[c]=b2[c].astype(float)
print("\n=== Champaign corn type 016: RDF / URF by practice x coverage ===")
print(b2.pivot_table(index='Coverage Level Percent',columns='Practice Code',
                     values='Rate Differential Factor',aggfunc='mean').round(4).to_string())

# --- price for this county/type ---
pj=json.load(open(D+'price.json'))
px=[r for r in pj['bench'] if r['State Code']=='17' and r['County Code']=='019'
    and r['Commodity Code']=='0041']
print("\nChampaign corn price rows:", {(r['Type Code'],r['Practice Code']):r['Projected Price'] for r in px})

# --- the ladder in $/acre ---
REF_AMT, REF_RATE, EXPO, FIXED = 212.0, 0.0078, -1.593, 0.0051   # type 016, practice 003
APH = 212.0        # producer sits at the county reference yield
PRICE = 4.62
prelim = REF_RATE*(APH/REF_AMT)**EXPO + FIXED
print(f"\npreliminary yield rate at APH={APH} = {prelim:.5f}")
sub=b2[b2['Practice Code']=='003']
rdf=dict(zip(sub['Coverage Level Percent'],sub['Rate Differential Factor']))
urf=dict(zip(sub['Coverage Level Percent'],sub['Unit Residual Factor']))
eurf=dict(zip(sub['Coverage Level Percent'],sub['Enterprise Unit Residual Factor']))
ud=pd.read_csv('data/cache/adm/2026_A01090_UnitDiscount_YTD.txt',sep='|',dtype=str)
ud=ud[(ud['Deleted Date'].isna())&(ud['Record Category Code']=='04')
      &(ud['Unit Discount ID'].isin(['410001','410201','410501','411001','412001','413001','414001','415001']))
      &(ud['Area Low Quantity']=='400.00')]
ud['cl']=ud['Coverage Level Percent'].astype(float)
euf=ud.groupby('cl')['Enterprise Unit Discount Factor'].apply(lambda s:s.astype(float).mean()).to_dict()
buf=ud.groupby('cl')['Basic Unit Discount Factor'].apply(lambda s:s.astype(float).mean()).to_dict()

print("\n=== Champaign IL corn RP, 212-bu APH, $4.62 projected, 400-799 ac unit, $/ACRE ===")
print(f"{'unit':4s} {'cov':>5s} {'liab':>9s} {'rate':>8s} {'gross':>8s} {'sub%':>5s} {'producer':>9s} "
      f"{'RY2025 prod':>12s} {'OBBBA save':>11s} {'marg$/added$liab':>17s}")
for unit in ['OU','BU','EU']:
    prev=None
    for cov in COVS:
        r=prelim*rdf[cov]*(eurf[cov] if unit=='EU' else urf[cov])
        if unit=='BU': r*=buf[cov]
        if unit=='EU': r*=euf[cov]
        liab=APH*PRICE*cov
        gross=liab*r
        prod=gross*(1-SUB26[unit][cov]); prod25=gross*(1-SUB25[unit][cov])
        m=''
        if prev:
            m=f"{(prod-prev[1])/(liab-prev[0]):.4f}"
        print(f"{unit:4s} {cov:5.2f} {liab:9.2f} {r:8.5f} {gross:8.2f} {SUB26[unit][cov]*100:5.0f} "
              f"{prod:9.2f} {prod25:12.2f} {prod25-prod:11.2f} {m:>17s}")
        prev=(liab,prod)
