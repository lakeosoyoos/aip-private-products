"""Throwaway: aggregate RMA SOBTPU (crop insurance experience) by crop x plan x coverage
level x unit structure. Fields are positional per SOBTPU_External_All_Years.pdf."""
import zipfile, csv, io, json, collections, glob, os, sys
DIR='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/sobtpu/'
# 0-based positions
YEAR,COMM,COMMNAME,PLAN,PLANAB,COVTYPE,COVLVL,DELIV,UNIT,UNITNAME = 0,6,7,8,9,10,11,12,17,18
NETQTY,RPTTYPE,LIAB,PREM,SUBS,IND = 19,20,21,22,23,24
ROW={"0011":"Wheat","0016":"Oats","0018":"Rice","0021":"Cotton","0041":"Corn",
     "0051":"Grain Sorghum","0075":"Peanuts","0081":"Soybeans","0091":"Barley","0015":"Canola",
     "0047":"Dry Beans","0067":"Dry Peas","0078":"Sunflowers","0094":"Rye"}
agg=collections.defaultdict(lambda:[0.0]*5)   # -> [acres, liab, prem, subs, ind]
unitnames={}
def f(x):
    x=x.strip()
    return float(x) if x else 0.0
for z in sorted(glob.glob(DIR+'sobtpu_*.zip')):
    with zipfile.ZipFile(z) as zf:
        nm=zf.namelist()[0]
        with zf.open(nm) as fh:
            for line in io.TextIOWrapper(fh,encoding='utf8',errors='replace'):
                p=line.rstrip('\n').split('|')
                if len(p)<25: continue
                c=p[COMM].strip()
                if c not in ROW: continue
                plan=p[PLAN].strip()
                if plan not in ('01','02','03','25','44','42','90'): continue
                if p[COVTYPE].strip()!='A': continue      # buy-up only, exclude CAT
                k=(int(p[YEAR]),ROW[c],plan,p[COVLVL].strip(),p[UNIT].strip())
                unitnames[p[UNIT].strip()]=p[UNITNAME].strip()
                a=agg[k]
                for i,col in enumerate((NETQTY,LIAB,PREM,SUBS,IND)): a[i]+=f(p[col])
    print("done",os.path.basename(z),len(agg)); sys.stdout.flush()
D='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/'
json.dump({'unitnames':unitnames,
           'agg':{'|'.join(map(str,k)):[round(x,2) for x in v] for k,v in agg.items()}},
          open(D+'sobtpu.json','w'))
print("keys",len(agg)); print(unitnames)
