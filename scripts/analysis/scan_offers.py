"""Throwaway: single streaming pass over ADM A00030 InsuranceOffer."""
import csv, json, sys, collections
P='data/cache/adm/2026_A00030_InsuranceOffer_YTD.txt'
ROW={"0011":"Wheat","0015":"Canola","0016":"Oats","0017":"Millet","0018":"Rice","0021":"Cotton",
     "0031":"Flax","0041":"Corn","0047":"Dry Beans","0051":"Grain Sorghum","0067":"Dry Peas",
     "0075":"Peanuts","0078":"Sunflowers","0081":"Soybeans","0091":"Barley","0094":"Rye"}
PLANS={'01','02','03'}
flags=collections.defaultdict(lambda: collections.Counter())
ud=collections.defaultdict(set)     # unit discount id -> commodities
hyt=collections.defaultdict(lambda: collections.Counter())   # commodity -> has trend id
counties=collections.defaultdict(lambda: collections.defaultdict(set))  # comm -> flag -> {(st,co)}
n=0
with open(P, newline='', encoding='utf8', errors='replace') as fh:
    r=csv.DictReader(fh, delimiter='|')
    for row in r:
        if row.get('Deleted Date'): continue
        c=row['Commodity Code']
        if c not in ROW: continue
        if row['Insurance Plan Code'] not in PLANS: continue
        n+=1
        name=ROW[c]
        k=(row['State Code'],row['County Code'])
        for f,lab in (('Optional Unit Allowed Flag','OU'),('Basic Unit Allowed Flag','BU'),
                      ('Enterprise Unit Allowed Flag','EU'),('Whole Farm Unit Allowed Flag','WU')):
            v=(row.get(f) or '').strip()
            flags[name][f"{lab}={v or 'blank'}"]+=1
            if v=='Y': counties[name][lab].add(k)
        counties[name]['ANY'].add(k)
        if row.get('Unit Discount ID'): ud[row['Unit Discount ID']].add(name)
        hyt[name]['trend' if (row.get('Historical Yield Trend ID') or '').strip() else 'notrend']+=1
        hyt[name]['beta' if (row.get('Beta ID') or '').strip() else 'nobeta']+=1
        hyt[name]['pace' if (row.get('Pace Rate ID') or '').strip() else 'nopace']+=1
out={'n_offers':n,
     'flags':{k:dict(v) for k,v in flags.items()},
     'county_counts':{k:{f:len(s) for f,s in v.items()} for k,v in counties.items()},
     'hyt':{k:dict(v) for k,v in hyt.items()},
     'unit_discount_ids':{k:sorted(v) for k,v in ud.items()}}
json.dump(out, open('/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/offers.json','w'), indent=1)
print("offers scanned:",n)
