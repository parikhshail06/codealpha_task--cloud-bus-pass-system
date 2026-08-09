import sqlite3
import json
import time
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "bus_pass_system.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Routes Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        route_code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        origin TEXT NOT NULL,
        destination TEXT NOT NULL,
        distance_km REAL NOT NULL,
        stops TEXT NOT NULL,
        fare_base REAL NOT NULL
    );
    """)

    # Buses Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS buses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bus_number TEXT UNIQUE NOT NULL,
        route_id INTEGER NOT NULL,
        bus_type TEXT NOT NULL,
        total_seats INTEGER NOT NULL,
        departure_time TEXT NOT NULL,
        FOREIGN KEY(route_id) REFERENCES routes(id)
    );
    """)

    # Passes Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS passes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pass_id TEXT UNIQUE NOT NULL,
        passenger_name TEXT NOT NULL,
        user_phone TEXT NOT NULL,
        user_email TEXT NOT NULL,
        user_category TEXT NOT NULL,
        pass_type TEXT NOT NULL,
        route_id INTEGER NOT NULL,
        fare REAL NOT NULL,
        issued_at REAL NOT NULL,
        expiry_date TEXT NOT NULL,
        hmac_signature TEXT NOT NULL,
        qr_data TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Active',
        FOREIGN KEY(route_id) REFERENCES routes(id)
    );
    """)

    # Tickets Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id TEXT UNIQUE NOT NULL,
        passenger_name TEXT NOT NULL,
        user_phone TEXT NOT NULL,
        user_email TEXT NOT NULL,
        user_category TEXT NOT NULL,
        bus_id INTEGER NOT NULL,
        seat_number INTEGER NOT NULL,
        travel_date TEXT NOT NULL,
        pass_type TEXT NOT NULL,
        fare REAL NOT NULL,
        issued_at REAL NOT NULL,
        hmac_signature TEXT NOT NULL,
        qr_data TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Valid',
        FOREIGN KEY(bus_id) REFERENCES buses(id)
    );
    """)

    # Virtual Server Nodes Table (Auto-Scaling Cluster)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS server_nodes (
        node_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        status TEXT NOT NULL,
        cpu_usage REAL NOT NULL,
        memory_usage REAL NOT NULL,
        rps REAL NOT NULL,
        created_at REAL NOT NULL
    );
    """)

    # Fraud Prevention Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fraud_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_or_pass_id TEXT NOT NULL,
        user_phone TEXT NOT NULL,
        reason TEXT NOT NULL,
        tampered_fare REAL NOT NULL,
        expected_fare REAL NOT NULL,
        client_ip TEXT NOT NULL,
        logged_at REAL NOT NULL
    );
    """)

    # Seed initial routes if empty
    cursor.execute("SELECT COUNT(*) FROM routes;")
    if cursor.fetchone()[0] == 0:
        seed_routes = [
            ("R-101", "Mumbai Metro Corridor", "Mumbai Central", "CST (Chhatrapati Shivaji Terminus)", 18.5, json.dumps(["Mumbai Central", "Dadar West", "Worli Sea Link", "CST Terminus"]), 40.0),
            ("R-102", "NCR Cyber Highway", "Delhi ISBT Kashmiri Gate", "Gurgaon Cyber Hub", 38.0, json.dumps(["Delhi ISBT Kashmiri Gate", "Connaught Place", "Dhaula Kuan", "Gurgaon Cyber Hub"]), 75.0),
            ("R-103", "Bengaluru Tech Express", "Majestic Bus Station (KBS)", "Electronic City Phase 1", 24.5, json.dumps(["Majestic Bus Station (KBS)", "Shantinagar", "Silk Board", "Electronic City Phase 1"]), 50.0),
            ("R-104", "Hyderabad IT Corridor", "MGBS Terminal", "HITEC City (Cyber Towers)", 22.0, json.dumps(["MGBS Terminal", "Ameerpet", "Jubilee Hills", "HITEC City"]), 45.0),
            ("R-105", "Chennai OMR Express", "Koyambedu CMBT", "Navalur IT Hub (OMR)", 28.0, json.dumps(["Koyambedu CMBT", "Guindy", "Perungudi", "Navalur IT Hub"]), 55.0),
            ("R-106", "Pune IT Park Shuttle", "Swargate Bus Stand", "Hinjawadi IT Park Phase 3", 21.0, json.dumps(["Swargate", "Deccan Gymkhana", "Baner", "Hinjawadi IT Park"]), 45.0)
        ]
        cursor.executemany("INSERT INTO routes (route_code, name, origin, destination, distance_km, stops, fare_base) VALUES (?,?,?,?,?,?,?);", seed_routes)

    # Seed initial buses if empty
    cursor.execute("SELECT COUNT(*) FROM buses;")
    if cursor.fetchone()[0] == 0:
        seed_buses = [
            ("BUS-101", 1, "AC Deluxe", 40, "07:30 AM"),
            ("BUS-102", 1, "Electric Eco", 40, "09:15 AM"),
            ("BUS-201", 2, "Standard", 45, "08:00 AM"),
            ("BUS-202", 2, "Express Sleeper", 30, "10:30 PM"),
            ("BUS-301", 3, "Electric Eco", 40, "08:15 AM"),
            ("BUS-302", 3, "AC Deluxe", 40, "05:45 PM"),
            ("BUS-401", 4, "Standard", 45, "07:45 AM"),
            ("BUS-501", 5, "Electric Eco", 40, "08:30 AM"),
            ("BUS-601", 6, "AC Deluxe", 40, "08:00 AM")
        ]
        cursor.executemany("INSERT INTO buses (bus_number, route_id, bus_type, total_seats, departure_time) VALUES (?,?,?,?,?);", seed_buses)

    # Seed initial master server node
    cursor.execute("SELECT COUNT(*) FROM server_nodes;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO server_nodes (node_id, name, ip_address, status, cpu_usage, memory_usage, rps, created_at)
        VALUES ('node-primary-01', 'Cloud Node Primary 1', '10.0.4.101', 'ACTIVE', 24.5, 38.2, 12.0, ?);
        """, (time.time(),))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
