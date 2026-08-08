"""Throwaway: irrigated vs non-irrigated, same county+type: county reference yield and
the rate a producer at that reference yield pays (ReferenceRate + FixedRate)."""
import pandas as pd
br=pd.read_csv('data/cache/adm/2026_A01010_BaseRate_YTD.txt',sep='|',dtype=str,
    usecols=['Deleted Date','Commodity Code','Insurance Plan Code','State Code','County Code',
             'Sub County Code','Type Code','Practice Code','Irrigation Practice Code',
             'Coverage Level Percent','Reference Amount','Reference Rate','Fixed Rate','Exponent Value'])
ROW={"0011":"Wheat","0021":"Cotton","0041":"Corn","0051":"Grain Sorghum","0081":"Soybeans"}
br=br[(br['Deleted Date'].isna())&(br['Insurance Plan Code']=='02')&(br['Sub County Code'].isna())
      &(br['Coverage Level Percent']=='0.65')&(br['Commodity Code'].isin(ROW))]
br=br[br['Irrigation Practice Code'].isin(['002','003'])].copy()
for c in ['Reference Amount','Reference Rate','Fixed Rate']: br[c]=br[c].astype(float)
br['rate65']=br['Reference Rate']+br['Fixed Rate']      # rate for a producer at county reference yield
br['crop']=br['Commodity Code'].map(ROW)
g=br.groupby(['crop','State Code','County Code','Type Code','Irrigation Practice Code']).agg(
    ref=('Reference Amount','mean'), rate=('rate65','mean')).reset_index()
p=g.pivot_table(index=['crop','State Code','County Code','Type Code'],
                columns='Irrigation Practice Code', values=['ref','rate'])
p=p.dropna()
p['ref_lift']=p[('ref','002')]/p[('ref','003')]
p['rate_ratio']=p[('rate','002')]/p[('rate','003')]
pd.set_option('display.width',200)
print("counties with BOTH irrigated and non-irrigated offers (same crop/type):",len(p))
print("\n=== irrigated vs non-irrigated, RY2026, RP, at the county reference yield ===")
q=pd.DataFrame({'ref_lift':p['ref_lift'],'rate_ratio':p['rate_ratio'],
                'prem_ratio':p['ref_lift']*p['rate_ratio']})
q.index=p.index
print(q.groupby(level='crop').agg(['size','median','mean']).round(4).to_string())
print("\n=== liability lift x rate change => gross premium per acre ratio (irr / non-irr) ===")

