import sqlite3, datetime, random

conn   = sqlite3.connect('/opt/db/test.db')  # connects or creates the database
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS tcp_hourly (
                    date_hour INTEGER,
                    port INTEGER,
                    flows INTEGER,
                    pkts INTEGER,
                    bytes INTEGER
                )''')

ports  = [80, 443, 8080, 21, 22]  # common port numbers
def generate_random_data():
    flows  = random.randint(1, 1000)
    pkts   = random.randint(100, 10000)
    bytes_ = random.randint(1000, 1000000)
    port   = random.choice(ports)
    return port, flows, pkts, bytes_

now = datetime.datetime.now()
# populate the table with data for the past 6 weeks (7 days * 6 weeks * 24 hours = 1008 entries)
for i in range(1008):
    date_hour = now - datetime.timedelta(hours=i)
    date_hour = date_hour.replace(minute=0, second=0, microsecond=0)
    unix_time = int(date_hour.timestamp())
    port, flows, pkts, bytes_ = generate_random_data()
    cursor.execute('INSERT INTO tcp_hourly (date_hour, port, flows, pkts, bytes) VALUES (?, ?, ?, ?, ?)',
                   (unix_time, port, flows, pkts, bytes_))
conn.commit()
conn.close()
print('data populated successfully')
