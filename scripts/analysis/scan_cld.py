"""Throwaway: stream A01040 CoverageLevelDifferential; aggregate RDF/URF by crop x coverage
level nationally, and keep full detail for benchmark counties."""
import csv, json, collections, statistics, sys
P='data/cache/adm/2026_A01040_CoverageLevelDifferential_YTD.txt'
ROW={"0011":"Wheat","0016":"Oats","0018":"Rice","0021":"Cotton","0041":"Corn",
     "0051":"Grain Sorghum","0075":"Peanuts","0081":"Soybeans","0091":"Barley"}
BENCH={('17','019'),('19','153'),('31','043'),('20','155'),('38','017'),('48','189'),
       ('17','113'),('27','037'),('46','035'),('06','047')}
agg=collections.defaultdict(list)      # (crop, plan, cov) -> [rdf]
urf=collections.defaultdict(list)      # (crop, cov, which) -> [factor]
bench=[]
n=0
with open(P, newline='', encoding='utf8', errors='replace') as fh:
    r=csv.DictReader(fh, delimiter='|')
    for row in r:
        if row.get('Deleted Date'): continue
        c=row['Commodity Code']
        if c not in ROW: continue
        plan=row['Insurance Plan Code']
        if plan not in ('01','02','03'): continue
        if row.get('Coverage Type Code')!='A': continue
        if row.get('Insurance Option Code'): continue     # base offer only
        if row.get('Sub County Code'): continue           # exclude high-risk sub-county
        if row.get('WA Number'): continue
        n+=1
        crop=ROW[c]; cov=row['Coverage Level Percent']
        try: rdf=float(row['Rate Differential Factor'])
        except (TypeError,ValueError): continue
        agg[(crop,plan,cov)].append(rdf)
        for lab,col in (('U','Unit Residual Factor'),('EU','Enterprise Unit Residual Factor'),
                        ('WU','Whole Farm Unit Residual Factor')):
            v=row.get(col)
            if v:
                try: urf[(crop,cov,lab)].append(float(v))
                except ValueError: pass
        if (row['State Code'],row['County Code']) in BENCH:
            bench.append({k:row[k] for k in ('Commodity Code','Insurance Plan Code','State Code',
                'County Code','Type Code','Practice Code','Coverage Level Percent',
                'Irrigation Practice Code','Rate Differential Factor','Unit Residual Factor',
                'Enterprise Unit Residual Factor','Whole Farm Unit Residual Factor','CAT Residual Factor')})
def summ(v): 
    v=sorted(v); return {'n':len(v),'mean':round(statistics.fmean(v),5),
        'median':round(statistics.median(v),5),'min':round(v[0],5),'max':round(v[-1],5)}
out={'n_rows':n,
     'rdf':{f"{k[0]}|{k[1]}|{k[2]}":summ(v) for k,v in agg.items()},
     'urf':{f"{k[0]}|{k[1]}|{k[2]}":summ(v) for k,v in urf.items()},
     'bench':bench}
D='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/'
json.dump(out, open(D+'cld.json','w'))
print("rows kept:",n,"bench rows:",len(bench))
