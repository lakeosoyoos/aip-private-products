"""Throwaway: coverage-level x unit-structure ladder, per $1 of full-value liability.
All inputs are ADM RY2026 primitives; the preliminary yield rate R0 cancels."""
import json, pandas as pd
D='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/'
COVS=[0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85]
SUB={'OU':{.50:.67,.55:.69,.60:.69,.65:.64,.70:.64,.75:.60,.80:.51,.85:.41},
     'BU':{.50:.67,.55:.69,.60:.69,.65:.64,.70:.64,.75:.60,.80:.51,.85:.41},
     'EU':{.50:.80,.55:.80,.60:.80,.65:.80,.70:.80,.75:.80,.80:.71,.85:.56},
     'WU':{.50:.80,.55:.80,.60:.80,.65:.80,.70:.80,.75:.80,.80:.71,.85:.56}}

cld=json.load(open(D+'cld.json'))
off=json.load(open(D+'offers.json'))
crop_ids={}
for uid,cs in off['unit_discount_ids'].items():
    for c in cs: crop_ids.setdefault(c,set()).add(uid)
u=pd.read_csv('data/cache/adm/2026_A01090_UnitDiscount_YTD.txt',sep='|',dtype=str)
u=u[u['Deleted Date'].isna()].copy()
for c in ['Coverage Level Percent','Area Low Quantity','Basic Unit Discount Factor','Enterprise Unit Discount Factor']:
    u[c]=pd.to_numeric(u[c],errors='coerce')

def factors(crop, acres_band):
    s=u[u['Unit Discount ID'].isin(crop_ids[crop])]
    s=s[s['Area Low Quantity']==acres_band]
    bu=s.groupby('Coverage Level Percent')['Basic Unit Discount Factor'].mean()
    eu=s.groupby('Coverage Level Percent')['Enterprise Unit Discount Factor'].mean()
    return bu,eu

def rel_rate(crop, cov, unit, bu_f, eu_f):
    rdf=cld['rdf'][f"{crop}|02|{cov:.2f}"]['mean']
    if unit in ('OU','BU'):
        urf=cld['urf'][f"{crop}|{cov:.2f}|U"]['mean']
        udf=1.0 if unit=='OU' else bu_f[cov]
    elif unit=='EU':
        urf=cld['urf'][f"{crop}|{cov:.2f}|EU"]['mean']; udf=eu_f[cov]
    else:
        urf=cld['urf'][f"{crop}|{cov:.2f}|WU"]['mean']; udf=1.0
    return rdf*urf*udf

def table(crop, acres_band=400.0):
    bu_f,eu_f=factors(crop,acres_band)
    rows=[]
    for unit in ['OU','BU','EU']:
        prev=None
        for cov in COVS:
            r=rel_rate(crop,cov,unit,bu_f,eu_f)
            gross=cov*r                      # per $1 of full value
            prod=gross*(1-SUB[unit][cov])
            marg='' 
            if prev:
                dl=cov-prev[0]; marg=f"{(prod-prev[1])/dl:.4f}"
            rows.append({'unit':unit,'cov':cov,'rel_rate':round(r,4),
                         'gross/$liab':round(r,4),
                         'prod/$liab':round(r*(1-SUB[unit][cov]),5),
                         'gross/$fullval':round(gross,5),
                         'prod/$fullval':round(prod,5),
                         'subsidy':SUB[unit][cov],
                         'marg_prod/$added_liab':marg,
                         'net/prod$_if_LR1':round(1/(1-SUB[unit][cov])-1,3)})
            prev=(cov,prod)
    return pd.DataFrame(rows)

if __name__=='__main__':
    pd.set_option('display.width',250)
    for crop in ['Corn','Soybeans','Wheat']:
        print(f"\n############ {crop} — RY2026 ADM, 400-799 acre unit band, RP ############")
        print(table(crop).to_string(index=False))
