## sqlite and pyodbc
- http://www.ch-werner.de/sqliteodbc/
- http://www.ch-werner.de/sqliteodbc/html/index.html

```
$ sudo apt install unixodbc
OR:
$ wget ftp://ftp.unixodbc.org/pub/unixODBC/unixODBC-2.3.12.tar.gz
# then normal 
./configure && make
sudo make install
```
```
sudo apt --fix-broken install
sudo apt install unixodbc-dev  # needed to build sqliteodbc

$ wget http://www.ch-werner.de/sqliteodbc/sqliteodbc-0.99991.tar.gz
sudo apt install sqlite3
sudo apt install libsqlite3-dev
./configure && make
sudo make install
```
Add the following volume mount to docker-compose.yml:
```
  - /usr/local/lib/libsqlite3odbc.so:/usr/local/lib/libsqlite3odbc.so
```