from flask import Flask, render_template, request, jsonify
import time
import uuid
import json
import os

from database import init_db, get_db_connection
from security import (
    calculate_server_fare,
    generate_ticket_hmac,
    verify_ticket_hmac,
    build_qr_data,
    generate_svg_qr
)
from scaler import global_seat_locks, global_scaler

app = Flask(__name__, template_folder="templates", static_folder="static")

# Initialize database schema and start auto-scaler daemon on boot
init_db()
global_scaler.start()

@app.before_request
def track_request_metrics():
    global_scaler.record_request()

# ---------------------------------------------------------
# Web Routes
# ---------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.route("/api/routes", methods=["GET"])
def get_routes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM routes;")
    rows = [dict(r) for r in cursor.fetchall()]
    for r in rows:
        r["stops"] = json.loads(r["stops"])
    conn.close()
    return jsonify({"status": "success", "routes": rows})

@app.route("/api/buses", methods=["GET"])
def get_buses():
    route_id = request.args.get("route_id")
    conn = get_db_connection()
    cursor = conn.cursor()
    if route_id:
        cursor.execute("""
            SELECT b.*, r.name as route_name, r.origin, r.destination, r.distance_km 
            FROM buses b 
            JOIN routes r ON b.route_id = r.id 
            WHERE b.route_id = ?;
        """, (route_id,))
    else:
        cursor.execute("""
            SELECT b.*, r.name as route_name, r.origin, r.destination, r.distance_km 
            FROM buses b 
            JOIN routes r ON b.route_id = r.id;
        """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({"status": "success", "buses": rows})

@app.route("/api/bus/<int:bus_id>/seats", methods=["GET"])
def get_bus_seats(bus_id):
    travel_date = request.args.get("date", time.strftime("%Y-%m-%d"))
    user_phone = request.args.get("phone", "")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get total bus seats
    cursor.execute("SELECT total_seats FROM buses WHERE id = ?;", (bus_id,))
    bus_row = cursor.fetchone()
    if not bus_row:
        conn.close()
        return jsonify({"status": "error", "message": "Bus not found"}), 404
    total_seats = bus_row["total_seats"]

    # Get booked seats
    cursor.execute("""
        SELECT seat_number FROM tickets 
        WHERE bus_id = ? AND travel_date = ? AND status != 'Cancelled';
    """, (bus_id, travel_date))
    booked_seats = set(row["seat_number"] for row in cursor.fetchall())
    conn.close()

    seats_layout = []
    for s in range(1, total_seats + 1):
        if s in booked_seats:
            status = "booked"
        elif global_seat_locks.is_locked(bus_id, s, travel_date, user_phone):
            status = "locked"
        else:
            status = "available"
        seats_layout.append({"seat_number": s, "status": status})

    return jsonify({
        "status": "success",
        "bus_id": bus_id,
        "travel_date": travel_date,
        "total_seats": total_seats,
        "seats": seats_layout
    })

@app.route("/api/seat/lock", methods=["POST"])
def lock_seat():
    data = request.get_json() or {}
    bus_id = data.get("bus_id")
    seat_number = data.get("seat_number")
    travel_date = data.get("travel_date")
    user_phone = data.get("user_phone", "guest")

    if not (bus_id and seat_number and travel_date):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    # Check database if already booked
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM tickets WHERE bus_id = ? AND seat_number = ? AND travel_date = ? AND status != 'Cancelled';
    """, (bus_id, seat_number, travel_date))
    if cursor.fetchone():
        conn.close()
        return jsonify({"status": "error", "message": "Seat already booked"}), 409
    conn.close()

    acquired = global_seat_locks.acquire_lock(bus_id, seat_number, travel_date, user_phone)
    if acquired:
        return jsonify({"status": "success", "message": "Seat locked for 5 minutes", "expires_in": 300})
    else:
        return jsonify({"status": "error", "message": "Seat is currently locked by another user"}), 409

@app.route("/api/calculate-fare", methods=["POST"])
def calculate_fare_endpoint():
    data = request.get_json() or {}
    distance_km = float(data.get("distance_km", 20.0))
    bus_type = data.get("bus_type", "Standard")
    pass_type = data.get("pass_type", "Single")
    user_category = data.get("user_category", "Regular")

    fare_details = calculate_server_fare(distance_km, bus_type, pass_type, user_category)
    return jsonify({"status": "success", "fare_details": fare_details})

@app.route("/api/book-pass", methods=["POST"])
def book_pass():
    data = request.get_json() or {}
    passenger_name = data.get("passenger_name", "").strip()
    user_phone = data.get("user_phone", "").strip()
    user_email = data.get("user_email", "").strip()
    user_category = data.get("user_category", "Regular")
    pass_type = data.get("pass_type", "Daily")
    route_id = data.get("route_id")
    client_claimed_fare = float(data.get("client_claimed_fare", 0.0))

    if not (passenger_name and user_phone and route_id):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM routes WHERE id = ?;", (route_id,))
    route = cursor.fetchone()
    if not route:
        conn.close()
        return jsonify({"status": "error", "message": "Route not found"}), 404

    # 1. ANTI-TAMPER CHECK: Calculate authoritative server fare
    server_fare_calc = calculate_server_fare(route["distance_km"], "AC Deluxe", pass_type, user_category)
    expected_fare = server_fare_calc["final_fare"]

    # If client claimed fare differs by > $0.05, block as TAMPERING ATTACK!
    if abs(client_claimed_fare - expected_fare) > 0.05:
        client_ip = request.remote_addr or "127.0.0.1"
        cursor.execute("""
            INSERT INTO fraud_logs (ticket_or_pass_id, user_phone, reason, tampered_fare, expected_fare, client_ip, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, ("NEW_PASS_REQ", user_phone, "Price tampering detected (Client claimed lower fare)", client_claimed_fare, expected_fare, client_ip, time.time()))
        conn.commit()
        conn.close()
        return jsonify({
            "status": "error",
            "code": "TAMPERING_DETECTED",
            "message": f"Security Alert: Claimed fare (₹{client_claimed_fare:.2f}) does not match server fare matrix (₹{expected_fare:.2f}). Transaction logged."
        }), 400

    # 2. Issue Pass
    pass_id = f"PASS-{uuid.uuid4().hex[:8].upper()}"
    issued_at = time.time()
    
    # Expiry date calculation
    if pass_type == "Daily":
        expiry_timestamp = issued_at + 86400
        expiry_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expiry_timestamp))
    elif pass_type == "Weekly":
        expiry_timestamp = issued_at + (86400 * 7)
        expiry_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expiry_timestamp))
    else: # Monthly
        expiry_timestamp = issued_at + (86400 * 30)
        expiry_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expiry_timestamp))

    # 3. Generate SHA-256 HMAC Signature
    hmac_sig = generate_ticket_hmac(pass_id, user_phone, expected_fare, str(route_id), issued_at)

    pass_record = {
        "pass_id": pass_id,
        "passenger_name": passenger_name,
        "user_phone": user_phone,
        "user_email": user_email,
        "user_category": user_category,
        "pass_type": pass_type,
        "route_name": route["name"],
        "route_id": route_id,
        "fare": expected_fare,
        "issued_at": issued_at,
        "expiry_date": expiry_date,
        "hmac_signature": hmac_sig
    }

    qr_payload_str = build_qr_data(pass_record)
    qr_svg = generate_svg_qr(qr_payload_str)

    cursor.execute("""
        INSERT INTO passes (pass_id, passenger_name, user_phone, user_email, user_category, pass_type, route_id, fare, issued_at, expiry_date, hmac_signature, qr_data, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active');
    """, (pass_id, passenger_name, user_phone, user_email, user_category, pass_type, route_id, expected_fare, issued_at, expiry_date, hmac_sig, qr_payload_str))
    
    conn.commit()
    conn.close()

    pass_record["qr_svg"] = qr_svg
    pass_record["qr_payload"] = qr_payload_str

    return jsonify({"status": "success", "message": "Bus Pass issued successfully!", "pass": pass_record})


@app.route("/api/book-ticket", methods=["POST"])
def book_ticket():
    data = request.get_json() or {}
    passenger_name = data.get("passenger_name", "").strip()
    user_phone = data.get("user_phone", "").strip()
    user_email = data.get("user_email", "").strip()
    user_category = data.get("user_category", "Regular")
    bus_id = data.get("bus_id")
    seat_number = data.get("seat_number")
    travel_date = data.get("travel_date")
    client_claimed_fare = float(data.get("client_claimed_fare", 0.0))

    if not (passenger_name and user_phone and bus_id and seat_number and travel_date):
        return jsonify({"status": "error", "message": "Missing required booking details"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if seat is already booked
    cursor.execute("""
        SELECT id FROM tickets WHERE bus_id = ? AND seat_number = ? AND travel_date = ? AND status != 'Cancelled';
    """, (bus_id, seat_number, travel_date))
    if cursor.fetchone():
        conn.close()
        return jsonify({"status": "error", "message": f"Seat #{seat_number} is already booked for this travel date"}), 409

    # Get bus & route info
    cursor.execute("""
        SELECT b.*, r.name as route_name, r.distance_km 
        FROM buses b JOIN routes r ON b.route_id = r.id 
        WHERE b.id = ?;
    """, (bus_id,))
    bus = cursor.fetchone()
    if not bus:
        conn.close()
        return jsonify({"status": "error", "message": "Bus not found"}), 404

    # 1. ANTI-TAMPER CHECK: Calculate authoritative server fare
    server_fare_calc = calculate_server_fare(bus["distance_km"], bus["bus_type"], "Single", user_category)
    expected_fare = server_fare_calc["final_fare"]

    if abs(client_claimed_fare - expected_fare) > 0.05:
        client_ip = request.remote_addr or "127.0.0.1"
        cursor.execute("""
            INSERT INTO fraud_logs (ticket_or_pass_id, user_phone, reason, tampered_fare, expected_fare, client_ip, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, ("NEW_TKT_REQ", user_phone, "Ticket price tampering detected", client_claimed_fare, expected_fare, client_ip, time.time()))
        conn.commit()
        conn.close()
        return jsonify({
            "status": "error",
            "code": "TAMPERING_DETECTED",
            "message": f"Security Alert: Claimed fare (₹{client_claimed_fare:.2f}) does not match server calculation (₹{expected_fare:.2f}). Transaction rejected."
        }), 400

    # 2. Issue Ticket
    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    issued_at = time.time()
    hmac_sig = generate_ticket_hmac(ticket_id, user_phone, expected_fare, str(bus["route_id"]), issued_at)

    ticket_record = {
        "ticket_id": ticket_id,
        "passenger_name": passenger_name,
        "user_phone": user_phone,
        "user_email": user_email,
        "user_category": user_category,
        "bus_number": bus["bus_number"],
        "bus_type": bus["bus_type"],
        "route_name": bus["route_name"],
        "seat_number": seat_number,
        "travel_date": travel_date,
        "departure_time": bus["departure_time"],
        "pass_type": "Single",
        "fare": expected_fare,
        "issued_at": issued_at,
        "hmac_signature": hmac_sig
    }

    qr_payload_str = build_qr_data(ticket_record)
    qr_svg = generate_svg_qr(qr_payload_str)

    cursor.execute("""
        INSERT INTO tickets (ticket_id, passenger_name, user_phone, user_email, user_category, bus_id, seat_number, travel_date, pass_type, fare, issued_at, hmac_signature, qr_data, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Single', ?, ?, ?, ?, 'Valid');
    """, (ticket_id, passenger_name, user_phone, user_email, user_category, bus_id, seat_number, travel_date, expected_fare, issued_at, hmac_sig, qr_payload_str))

    conn.commit()
    conn.close()

    # Release seat lock
    global_seat_locks.release_lock(bus_id, seat_number, travel_date)

    ticket_record["qr_svg"] = qr_svg
    ticket_record["qr_payload"] = qr_payload_str

    return jsonify({"status": "success", "message": "Bus Ticket booked successfully!", "ticket": ticket_record})


@app.route("/api/my-passes-and-tickets", methods=["GET"])
def get_user_records():
    phone = request.args.get("phone", "").strip()
    if not phone:
        return jsonify({"status": "error", "message": "Phone number required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch passes
    cursor.execute("""
        SELECT p.*, r.name as route_name 
        FROM passes p JOIN routes r ON p.route_id = r.id 
        WHERE p.user_phone = ? ORDER BY p.issued_at DESC;
    """, (phone,))
    passes = [dict(r) for r in cursor.fetchall()]
    for p in passes:
        p["qr_svg"] = generate_svg_qr(p["qr_data"])

    # Fetch tickets
    cursor.execute("""
        SELECT t.*, b.bus_number, b.bus_type, b.departure_time, r.name as route_name 
        FROM tickets t 
        JOIN buses b ON t.bus_id = b.id 
        JOIN routes r ON b.route_id = r.id 
        WHERE t.user_phone = ? ORDER BY t.issued_at DESC;
    """, (phone,))
    tickets = [dict(r) for r in cursor.fetchall()]
    for t in tickets:
        t["qr_svg"] = generate_svg_qr(t["qr_data"])

    conn.close()
    return jsonify({"status": "success", "passes": passes, "tickets": tickets})


@app.route("/api/verify-pass-or-ticket", methods=["POST"])
def verify_pass_or_ticket():
    """
    Conductor Live Verification Endpoint:
    Checks cryptographic signature, anti-theft HMAC, and validity status.
    """
    data = request.get_json() or {}
    identifier = data.get("identifier", "").strip()

    if not identifier:
        return jsonify({"status": "error", "message": "No pass/ticket ID or QR string provided"}), 400

    # If identifier is a JSON QR string, parse it
    try:
        if identifier.startswith("{") and identifier.endswith("}"):
            parsed = json.loads(identifier)
            identifier = parsed.get("id", identifier)
    except Exception:
        pass

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Check in passes
    cursor.execute("""
        SELECT p.*, r.name as route_name, r.origin, r.destination 
        FROM passes p JOIN routes r ON p.route_id = r.id 
        WHERE p.pass_id = ?;
    """, (identifier,))
    pass_row = cursor.fetchone()

    if pass_row:
        p = dict(pass_row)
        # Verify HMAC
        is_valid_hmac = verify_ticket_hmac(p["pass_id"], p["user_phone"], p["fare"], str(p["route_id"]), p["issued_at"], p["hmac_signature"])
        
        # Check expiry
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        is_expired = p["expiry_date"] < now_str

        conn.close()
        if not is_valid_hmac:
            return jsonify({
                "valid": False,
                "type": "PASS",
                "reason": "INVALID_HMAC_SIGNATURE",
                "message": "SECURITY WARNING: Pass signature has been tampered with!",
                "record": p
            }), 400
        
        if is_expired:
            return jsonify({
                "valid": False,
                "type": "PASS",
                "reason": "PASS_EXPIRED",
                "message": f"Pass expired on {p['expiry_date']}",
                "record": p
            })

        return jsonify({
            "valid": True,
            "type": "PASS",
            "status": p["status"],
            "message": "PASS VERIFIED & VALID",
            "record": p
        })

    # 2. Check in tickets
    cursor.execute("""
        SELECT t.*, b.bus_number, b.bus_type, b.departure_time, r.name as route_name 
        FROM tickets t 
        JOIN buses b ON t.bus_id = b.id 
        JOIN routes r ON b.route_id = r.id 
        WHERE t.ticket_id = ?;
    """, (identifier,))
    ticket_row = cursor.fetchone()

    if ticket_row:
        t = dict(ticket_row)
        is_valid_hmac = verify_ticket_hmac(t["ticket_id"], t["user_phone"], t["fare"], str(t["bus_id"]), t["issued_at"], t["hmac_signature"])
        conn.close()

        if not is_valid_hmac:
            return jsonify({
                "valid": False,
                "type": "TICKET",
                "reason": "INVALID_HMAC_SIGNATURE",
                "message": "SECURITY WARNING: Ticket signature is invalid or tampered!",
                "record": t
            }), 400

        return jsonify({
            "valid": True,
            "type": "TICKET",
            "status": t["status"],
            "message": "TICKET VERIFIED & VALID",
            "record": t
        })

    conn.close()
    return jsonify({"valid": False, "reason": "NOT_FOUND", "message": "Invalid Pass/Ticket ID. Record not found in database."}), 404


@app.route("/api/cluster/metrics", methods=["GET"])
def get_cluster_metrics():
    """
    Cloud Auto-Scaler & System Health Metrics Endpoint.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM server_nodes;")
    nodes = [dict(n) for n in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) FROM tickets;")
    total_tickets = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM passes;")
    total_passes = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(fare), 0) FROM tickets;")
    ticket_revenue = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(fare), 0) FROM passes;")
    pass_revenue = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM fraud_logs;")
    fraud_count = cursor.fetchone()[0]

    conn.close()

    total_rps = sum(n["rps"] for n in nodes if n["status"] == "ACTIVE")
    avg_cpu = sum(n["cpu_usage"] for n in nodes if n["status"] == "ACTIVE") / max(1, len(nodes))

    return jsonify({
        "status": "success",
        "nodes": nodes,
        "node_count": len(nodes),
        "total_rps": round(total_rps, 1),
        "avg_cpu": round(avg_cpu, 1),
        "total_tickets": total_tickets,
        "total_passes": total_passes,
        "total_revenue": round(ticket_revenue + pass_revenue, 2),
        "fraud_attempts_blocked": fraud_count,
        "active_seat_locks": len(global_seat_locks.locks),
        "surge_active": global_scaler.surge_active
    })


@app.route("/api/cluster/surge", methods=["POST"])
def trigger_surge():
    data = request.get_json() or {}
    duration = int(data.get("duration", 30))
    target_rps = float(data.get("target_rps", 220.0))
    
    global_scaler.trigger_traffic_surge(duration, target_rps)
    return jsonify({
        "status": "success",
        "message": f"Simulated traffic surge triggered! ({target_rps} RPS for {duration} seconds). Auto-scaler actively monitoring..."
    })


@app.route("/api/fraud-logs", methods=["GET"])
def get_fraud_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM fraud_logs ORDER BY logged_at DESC LIMIT 20;")
    logs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({"status": "success", "fraud_logs": logs})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
