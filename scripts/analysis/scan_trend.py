"""Throwaway: map Historical Yield Trend ID -> crop from A00030, then measure the
county yield trend RMA publishes in A01115 (Yield vs Trended Yield)."""
import csv, json, collections, statistics
ROW={"0011":"Wheat","0016":"Oats","0018":"Rice","0021":"Cotton","0041":"Corn",
     "0051":"Grain Sorghum","0075":"Peanuts","0081":"Soybeans","0091":"Barley"}
tid=collections.defaultdict(set)
with open('data/cache/adm/2026_A00030_InsuranceOffer_YTD.txt',newline='',encoding='utf8',errors='replace') as fh:
    for r in csv.DictReader(fh,delimiter='|'):
        if r.get('Deleted Date'): continue
        c=r['Commodity Code']
        if c not in ROW or r['Insurance Plan Code'] not in ('01','02','03'): continue
        h=(r.get('Historical Yield Trend ID') or '').strip()
        if h: tid[h].add(ROW[c])
print("trend ids mapped:",len(tid))
slope=collections.defaultdict(list)
byid=collections.defaultdict(list)
with open('data/cache/adm/2026_A01115_HistoricalYieldTrend_YTD.txt',newline='',encoding='utf8',errors='replace') as fh:
    for r in csv.DictReader(fh,delimiter='|'):
        if r.get('Deleted Date'): continue
        h=r['Historical Yield Trend ID']
        if h not in tid: continue
        try:
            y=int(r['Yield Year']); a=float(r['Yield Amount']); t=float(r['Trended Yield Amount'])
        except (TypeError,ValueError): continue
        byid[h].append((y,a,t))
out={}
for h,v in byid.items():
    v.sort()
    yrs=[x[0] for x in v]
    # RMA trends every historical yield to the current commodity year; implied bu/ac/yr
    # slope = (trended - actual) / (target_year - yield_year), target = max year + 1
    tgt=max(yrs)+1
    s=[(t-a)/(tgt-y) for y,a,t in v if tgt>y and a>0]
    if not s: continue
    for crop in tid[h]:
        slope[crop].append(statistics.fmean(s))
    out[h]={'crops':sorted(tid[h]),'nyears':len(v),'span':[min(yrs),max(yrs)],
            'slope_mean':round(statistics.fmean(s),4),
            'base_yield_mean':round(statistics.fmean([a for _,a,_ in v]),2)}
D='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/'
json.dump(out,open(D+'trend.json','w'))
print("\n=== implied trend slope (units/ac/yr) by crop, over trend IDs ===")
for c,v in sorted(slope.items()):
    v=sorted(v)
    print(f"{c:15s} n={len(v):5d} mean={statistics.fmean(v):8.4f} median={statistics.median(v):8.4f} p10={v[len(v)//10]:8.4f} p90={v[9*len(v)//10]:8.4f}")
