import datetime, pyodbc, random

conn = pyodbc.connect(
    'DRIVER=/usr/lib/x86_64-linux-gnu/odbc/libmaodbc.so;'
    'UID=root;'
    'PWD=root'
)
cursor = conn.cursor()
cursor.execute("CREATE DATABASE IF NOT EXISTS network_traffic")
cursor.execute("USE network_traffic")
cursor.execute('''CREATE TABLE IF NOT EXISTS tcp_hourly (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    date_hour DATETIME,
                    port INT,
                    flows INT,
                    pkts INT,
                    bytes INT
                )''')
ports = [80, 443, 8080, 21, 22]  # common port numbers
def generate_random_data():
    flows  = random.randint(1, 1000)
    pkts   = random.randint(100, 10000)
    bytes_ = random.randint(1000, 1000000)
    port   = random.choice(ports)
    return port, flows, pkts, bytes_

now = datetime.datetime.now()
# populate the table with data for the past 6 weeks (7 days * 6 weeks * 24 hours = 1008 entries)
data = []
for i in range(1008):
    date_hour = now - datetime.timedelta(hours=i)
    port, flows, pkts, bytes_ = generate_random_data()
    data.append((date_hour, port, flows, pkts, bytes_))
insert_query = '''INSERT INTO tcp_hourly (date_hour, port, flows, pkts, bytes)
VALUES (?, ?, ?, ?, ?)'''
cursor.executemany(insert_query, data)
conn.commit()
cursor.close()
conn.close()
print('data populated successfully')
