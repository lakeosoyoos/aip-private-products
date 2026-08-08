"""Throwaway: stream A01060 OptionRate -> per-crop option rate summary for row crops."""
import csv, json, collections, statistics
P='data/cache/adm/2026_A01060_OptionRate_YTD.txt'
ROW={"0011":"Wheat","0016":"Oats","0018":"Rice","0021":"Cotton","0041":"Corn",
     "0051":"Grain Sorghum","0075":"Peanuts","0081":"Soybeans","0091":"Barley","0015":"Canola",
     "0047":"Dry Beans","0067":"Dry Peas","0078":"Sunflowers","0094":"Rye","0017":"Millet","0031":"Flax"}
agg=collections.defaultdict(list); meth=collections.defaultdict(collections.Counter)
conv=collections.defaultdict(list)
n=0
with open(P,newline='',encoding='utf8',errors='replace') as fh:
    for row in csv.DictReader(fh,delimiter='|'):
        if row.get('Deleted Date'): continue
        c=row['Commodity Code']
        if c not in ROW: continue
        if row['Insurance Plan Code'] not in ('01','02','03'): continue
        opt=row['Insurance Option Code']
        if not opt: continue
        n+=1
        k=(ROW[c],opt,row.get('Coverage Level Percent') or 'ALL')
        meth[(ROW[c],opt)][row.get('Rate Method Code') or '-']+=1
        try: agg[k].append(float(row['Option Rate']))
        except (TypeError,ValueError): pass
        v=row.get('Option Conversion Factor')
        if v:
            try: conv[(ROW[c],opt)].append(float(v))
            except ValueError: pass
def s(v):
    v=sorted(v); return {'n':len(v),'mean':round(statistics.fmean(v),5),'median':round(statistics.median(v),5),
                         'min':round(v[0],5),'max':round(v[-1],5)}
out={'n':n,'rates':{'|'.join(k):s(v) for k,v in agg.items() if v},
     'methods':{'|'.join(k):dict(v) for k,v in meth.items()},
     'conv':{'|'.join(k):s(v) for k,v in conv.items() if v}}
D='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/'
json.dump(out,open(D+'optrate.json','w'))
print("option rows:",n)
