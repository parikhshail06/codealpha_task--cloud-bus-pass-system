import hmac
import hashlib
import json
import time
import base64

SECRET_KEY = b"cloud_bus_pass_sec_token_9847291837491"

def generate_ticket_hmac(ticket_id: str, user_phone: str, fare: float, route_id: str, timestamp: float) -> str:
    """
    Generate SHA-256 HMAC for tamper-proof pricing and anti-theft ticket verification.
    """
    message = f"{ticket_id}:{user_phone}:{fare:.2f}:{route_id}:{int(timestamp)}".encode('utf-8')
    return hmac.new(SECRET_KEY, message, hashlib.sha256).hexdigest()

def verify_ticket_hmac(ticket_id: str, user_phone: str, fare: float, route_id: str, timestamp: float, signature: str) -> bool:
    """
    Verify if ticket signature matches server calculations.
    """
    expected = generate_ticket_hmac(ticket_id, user_phone, fare, route_id, timestamp)
    return hmac.compare_digest(expected, signature)

def calculate_server_fare(distance_km: float, bus_type: str, pass_type: str, user_category: str) -> dict:
    """
    Calculate authoritative server-side fare matrix in Indian Rupees (INR) to prevent price tampering.
    """
    rate_map = {
        "Standard": 2.0,
        "AC Deluxe": 3.5,
        "Electric Eco": 2.8,
        "Express Sleeper": 4.5
    }
    base_rate = rate_map.get(bus_type, 2.0)
    raw_single_fare = max(20.0, distance_km * base_rate)
    
    pass_multipliers = {
        "Single": 1.0,
        "Daily": 3.5,
        "Weekly": 14.0,
        "Monthly": 40.0
    }
    multiplier = pass_multipliers.get(pass_type, 1.0)
    subtotal = raw_single_fare * multiplier

    discount_map = {
        "Regular": 0.0,
        "Student": 0.50,
        "Senior": 0.40,
        "Disabled": 0.60
    }
    discount_rate = discount_map.get(user_category, 0.0)
    discount_amount = subtotal * discount_rate
    final_fare = round(subtotal - discount_amount, 2)

    return {
        "distance_km": distance_km,
        "bus_type": bus_type,
        "pass_type": pass_type,
        "user_category": user_category,
        "subtotal": round(subtotal, 2),
        "discount_amount": round(discount_amount, 2),
        "final_fare": final_fare,
        "calculated_at": time.time()
    }

def build_qr_data(ticket_data: dict) -> str:
    """
    Construct signed payload string for QR code generation & scanning.
    """
    payload = {
        "id": ticket_data.get("ticket_id"),
        "phone": ticket_data.get("user_phone"),
        "name": ticket_data.get("passenger_name"),
        "fare": ticket_data.get("fare"),
        "route": ticket_data.get("route_name"),
        "type": ticket_data.get("pass_type"),
        "valid_until": ticket_data.get("expiry_date"),
        "sig": ticket_data.get("hmac_signature")
    }
    return json.dumps(payload)

def generate_svg_qr(data_str: str) -> str:
    """
    Fallback native SVG QR-like visual generator.
    Uses deterministically hashed matrix pattern for visual fidelity.
    """
    h = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
    grid_size = 21
    scale = 10
    svg_size = grid_size * scale
    
    rects = []
    def add_finder(x_off, y_off):
        for r in range(7):
            for c in range(7):
                if (r in (0, 6) or c in (0, 6)) or (2 <= r <= 4 and 2 <= c <= 4):
                    rects.append(f'<rect x="{(x_off+c)*scale}" y="{(y_off+r)*scale}" width="{scale}" height="{scale}" fill="#0f172a"/>')

    add_finder(0, 0)
    add_finder(14, 0)
    add_finder(0, 14)

    bit_index = 0
    for r in range(grid_size):
        for c in range(grid_size):
            if (r < 7 and c < 7) or (r < 7 and c >= 14) or (r >= 14 and c < 7):
                continue
            char = h[bit_index % len(h)]
            bit_index += 1
            if int(char, 16) % 2 == 0:
                rects.append(f'<rect x="{c*scale}" y="{r*scale}" width="{scale}" height="{scale}" fill="#0f172a"/>')

    svg = f'''<svg viewBox="0 0 {svg_size} {svg_size}" width="200" height="200" xmlns="http://www.w3.org/2000/svg" style="background:#ffffff; padding:12px; border-radius:12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
        {''.join(rects)}
    </svg>'''
    return svg
