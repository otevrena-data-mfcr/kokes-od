import csv
import sys
from datetime import datetime
from urllib.request import urlopen

import psycopg2
import psycopg2.sql as pql
import lxml.etree
from tqdm import tqdm

from parse_or import parse_listing

def ares_url(rejstrik, ico):
    if rejstrik == 'or':
        return 'http://wwwinfo.mfcr.cz/cgi-bin/ares/darv_{}.cgi?ico={}&rozsah=1'.format(rejstrik, ico)

    return 'http://wwwinfo.mfcr.cz/cgi-bin/ares/darv_{}.cgi?ico={}'.format(rejstrik, ico)

if __name__ == '__main__':
    rejstrik = sys.argv[1]
    assert rejstrik in ['res', 'or']

    conn = psycopg2.connect(host='localhost')
    while True:
        with conn, conn.cursor() as cursor:
            cursor.execute('select ico from ares.raw where rejstrik = %s and xml is null limit 25',
                       (rejstrik,))
            icos = [j[0] for j in cursor.fetchall()]
            if len(icos) == 0: break

            for ico in tqdm(icos):
                assert isinstance(ico, int) and ico > 0 and len(str(ico)) <= 8, 'invalid format, {}'.format(ico)
                r = urlopen(ares_url(rejstrik, ico))
                dt = r.read()
                if b'Chyba 23 - chybn' in dt:
                    raise ValueError('nespravny format ico: {}'.format(ico))

                if (b'<dtt:faultcode>' in dt) or (b'nastala SQL chyba' in dt) or (b'Chyba 900' in dt) or (b'MAX. DOBA DOTAZU' in dt):
                    raise ValueError(f'chyba v API ({ico})')

                found = b'Chyba 71 - nenalezeno' not in dt
                if not found:
                    print(ico, 'nenalezeno')

                # TODO: upsert? (kdybychom meli ICO odjinud)
                cursor.execute('update ares.raw set modified_on=%s, xml=%s, found=%s where rejstrik = %s and ico = %s',
                    (datetime.utcnow(), dt, found, rejstrik, ico))

                if rejstrik == 'or':
                    et = lxml.etree.fromstring(dt)
                    data = parse_listing(et, ico)
                    if data is None:
                        print('nenaparsovano', ico) # TODO: eh?
                        continue

                    cursor.execute('delete from ares.or_udaje where ico = %s', (ico, ))
                    for table, rows in data.items():
                        for row in rows:
                            columns = list(row.keys())
                            pvalues = [f'%({j})s' for j in columns]
                            # updates = [f'"{j}" = EXCLUDED."{j}"' for j in columns if j != 'ico'] # nebude treba asi
                            query = f'''
                                INSERT INTO ares."or_{table}"({', '.join(columns)}) VALUES({', '.join(pvalues)})
                            '''
                            cursor.execute(query, row)

                conn.commit()
