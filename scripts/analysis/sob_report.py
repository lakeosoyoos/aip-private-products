"""Throwaway: report loss ratios / net-per-producer-dollar from aggregated SOBTPU."""
import json, pandas as pd
D='/private/tmp/claude-501/-Users-rhondacolbert-Desktop/037977b4-c889-4791-ac77-6a028b7c901e/scratchpad/'
d=json.load(open(D+'sobtpu.json'))['agg']
rows=[]
for k,v in d.items():
    y,crop,plan,cov,unit=k.split('|')
    rows.append(dict(year=int(y),crop=crop,plan=plan,cov=float(cov),unit=unit,
                     acres=v[0],liab=v[1],prem=v[2],subs=v[3],ind=v[4]))
df=pd.DataFrame(rows); df['pprem']=df['prem']-df['subs']
def summ(g):
    prem=g['prem'].sum(); pp=g['pprem'].sum(); ind=g['ind'].sum(); liab=g['liab'].sum()
    return pd.Series({'liab_$B':round(liab/1e9,2),'acres_M':round(g['acres'].sum()/1e6,1),
        'gross_LR':round(ind/prem,3) if prem else None,
        'prod_LR':round(ind/pp,3) if pp else None,
        'subsidy%':round(g['subs'].sum()/prem,3) if prem else None,
        'net/prod$':round((ind-pp)/pp,3) if pp else None,
        'gross_rate':round(prem/liab,4) if liab else None,
        'prod_rate':round(pp/liab,4) if liab else None,
        'net$/acre':round((ind-pp)/g['acres'].sum(),2) if g['acres'].sum() else None})
pd.set_option('display.width',260)
main=df[df['crop'].isin(['Corn','Soybeans','Wheat'])&df['plan'].isin(['01','02','03'])]
if __name__=='__main__':
    print("years:",sorted(df['year'].unique()))
    print("\n### by UNIT STRUCTURE (Corn+Soy+Wheat, buy-up YP/RP/RPHPE, 2010-2024) ###")
    print(main.groupby('unit').apply(summ).sort_values('liab_$B',ascending=False).to_string())
    for u in ['OU','BU','EU']:
        print(f"\n### by COVERAGE LEVEL — {u} ###")
        print(main[main['unit']==u].groupby('cov').apply(summ).to_string())
    print("\n### by PLAN (all units) ###")
    print(main.groupby('plan').apply(summ).to_string())
    print("\n### EU vs OU at 80/85, per crop ###")
    print(main[main['cov'].isin([0.80,0.85])].groupby(['crop','cov','unit']).apply(summ).to_string())
