"""Throwaway: stream A00810 Price -> projected/harvest price + volatility for row crops."""
import csv, json, collections, statistics
P='data/cache/adm/2026_A00810_Price_YTD.txt'
ROW={"0011":"Wheat","0016":"Oats","0018":"Rice","0021":"Cotton","0041":"Corn",
     "0051":"Grain Sorghum","0075":"Peanuts","0081":"Soybeans","0091":"Barley","0015":"Canola",
     "0047":"Dry Beans","0067":"Dry Peas","0078":"Sunflowers","0094":"Rye"}
pp=collections.defaultdict(list); hp=collections.defaultdict(list); vol=collections.defaultdict(list)
bench=[]
BENCH={('17','019'),('19','153'),('20','155'),('38','017'),('48','189')}
n=0
with open(P,newline='',encoding='utf8',errors='replace') as fh:
    for row in csv.DictReader(fh,delimiter='|'):
        if row.get('Deleted Date'): continue
        c=row['Commodity Code']
        if c not in ROW: continue
        plan=row['Insurance Plan Code']
        if plan not in ('01','02','03'): continue
        n+=1; k=(ROW[c],plan)
        for col,d in (('Projected Price',pp),('Harvest Price',hp),('Price Volatility Factor',vol)):
            v=row.get(col)
            if v:
                try: d[k].append(float(v))
                except ValueError: pass
        if (row['State Code'],row['County Code']) in BENCH and row.get('Projected Price'):
            bench.append({x:row[x] for x in ('Commodity Code','Insurance Plan Code','State Code','County Code',
                'Type Code','Practice Code','Projected Price','Harvest Price','Price Volatility Factor',
                'Irrigation Practice Code')})
def s(v):
    v=sorted(v); return {'n':len(v),'mean':round(statistics.fmean(v),5),'median':round(statistics.median(v),5),
                         'min':v[0],'max':v[-1],'distinct':len(set(v))}
D='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/'
json.dump({'n':n,'pp':{'|'.join(k):s(v) for k,v in pp.items() if v},
           'hp':{'|'.join(k):s(v) for k,v in hp.items() if v},
           'vol':{'|'.join(k):s(v) for k,v in vol.items() if v},
           'bench':bench[:4000]}, open(D+'price.json','w'))
print("price rows:",n)
