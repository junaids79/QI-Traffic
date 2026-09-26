import sqlite3, json, os
from werkzeug.security import generate_password_hash
DB_PATH=os.path.join(os.path.dirname(__file__),'qi_traffic.db')

def connect():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    c=connect(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS vehicles(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,type TEXT NOT NULL,owner_id INTEGER);
    CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,name TEXT,latitude REAL,longitude REAL);
    CREATE TABLE IF NOT EXISTS edges(id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT,destination TEXT,distance REAL,normal_time REAL,speed_limit REAL,traffic_level TEXT,current_speed REAL,emergency_access INTEGER,vehicle_restrictions TEXT);
    CREATE TABLE IF NOT EXISTS traffic_data(id INTEGER PRIMARY KEY AUTOINCREMENT,edge_id INTEGER,traffic_level TEXT,current_speed REAL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS route_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,source TEXT,destination TEXT,vehicle_type TEXT,emergency INTEGER,deadline TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS route_results(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER,algorithm TEXT,route_json TEXT,distance REAL,travel_time REAL,fitness REAL,execution_ms REAL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS benchmark_results(id INTEGER PRIMARY KEY AUTOINCREMENT,algorithm TEXT,nodes INTEGER,execution_ms REAL,distance REAL,travel_time REAL,fitness REAL,valid INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    ''')
    if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0:
        users=[('admin','admin123','ADMIN'),('user','user123','NORMAL_USER'),('emergency','emergency123','EMERGENCY_USER')]
        c.executemany('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',[(u,generate_password_hash(p),r) for u,p,r in users])
    if c.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0]==0:
        c.executemany('INSERT INTO vehicles(name,type) VALUES(?,?)',[('City Car','Car'),('Delivery Bike','Bike'),('Transit Bus','Bus'),('Freight Truck','Truck'),('Rapid Ambulance','Ambulance')])
    c.commit(); c.close()
