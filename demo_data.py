import json
from decimal import Decimal


def seed_demo(connect, reconcile):
    with connect() as connection:
        if connection.execute('SELECT count(*) FROM imports').fetchone()[0]:
            return
        companies = ['Luma Iberia', 'Luma France', 'Luma UK', 'Luma US']
        for index, name in enumerate(companies):
            connection.execute('INSERT INTO companies VALUES (?,?)', ('demo-company-' + str(index), name))
        settings = dict(mode='Multi Currency', base='EUR', currencies=['EUR', 'GBP', 'USD'], tolerance='0.01', methods={'Balance': 'Closing', 'P&L': 'Average', 'Patrimonio': 'Historical'})
        connection.execute('UPDATE settings SET data=? WHERE id=1', (json.dumps(settings),))
        for month in ['09', '10']:
            period = '2026-' + month
            rates = {currency + '|' + (period + '-01' if method == 'Historical' else period) + '|' + method: rate for currency, rate in [('USD', '0.92'), ('GBP', '1.18')] for method in ['Closing', 'Average', 'Historical']}
            all_rows = []
            for index in range(24):
                other = companies[1 + index % 3]
                currency = {'Luma France': 'EUR', 'Luma UK': 'GBP', 'Luma US': 'USD'}[other]
                rate = Decimal({'EUR': '1', 'GBP': '1.18', 'USD': '0.92'}[currency])
                category = ['Balance', 'P&L', 'Patrimonio'][index % 3]
                statement = 'P&L' if category == 'P&L' else 'Balance'
                value = Decimal(5000 + index * 1250)
                difference = Decimal(0)
                if index in ([3, 10, 17, 22] if month == '10' else [2, 7, 11, 16, 20, 23]):
                    difference = Decimal(150 + index * 25)
                base = dict(account=str(130000 + index), period=period, date=period+'-01', reference='IC-'+month+'-'+str(index+1).zfill(3), statement=statement, category=category)
                all_rows.append(dict(base, entity=companies[0], counterparty=other, currency='EUR', amount=str(value * rate)))
                all_rows.append(dict(base, entity=other, counterparty=companies[0], currency=currency, amount=str(-value + difference)))
                if month == '10' and index == 3:
                    for reference, debit, credit in [('IC-10-025', '1200', '-1150'), ('IC-10-026', '800', '-775')]:
                        all_rows.append(dict(base, reference=reference, entity=companies[0], counterparty=other, currency='EUR', amount=debit))
                        all_rows.append(dict(base, reference=reference, entity=other, counterparty=companies[0], currency='EUR', amount=credit))
            for company_index, company in enumerate(companies):
                for statement in ['Balance', 'P&L']:
                    rows = [row for row in all_rows if row['entity'] == company and row['statement'] == statement]
                    if rows:
                        connection.execute('INSERT INTO imports (id,name,created,data,company_id) VALUES (?,?,?,?,?)', ('demo-'+month+'-'+str(company_index)+'-'+statement, company+' · '+statement+' · '+period+'.csv', period+'-28T09:00:00', json.dumps(rows), 'demo-company-'+str(company_index)))
            result = reconcile(all_rows, dict(settings, rates=rates, matching='Balances'))
            connection.execute('INSERT INTO history VALUES (?,?,?)', ('demo-run-'+month, period+'-28T10:30:00', json.dumps(result)))
