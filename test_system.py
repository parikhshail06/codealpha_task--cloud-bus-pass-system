import unittest
import time
import json
from app import app
from database import init_db, get_db_connection
from security import calculate_server_fare, generate_ticket_hmac, verify_ticket_hmac
from scaler import global_seat_locks, global_scaler

class TestCloudBusPassSystem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = app.test_client()

    def test_01_fare_calculation_matrix(self):
        """Verify dynamic server fare matrix in INR and concession discounts"""
        # Distance: 32.5km, Bus: AC Deluxe (3.5/km), Pass: Daily (3.5x), Category: Regular
        # Raw = 32.5 * 3.5 = 113.75. Subtotal = 113.75 * 3.5 = 398.12
        fare = calculate_server_fare(32.5, "AC Deluxe", "Daily", "Regular")
        self.assertEqual(fare["final_fare"], 398.12)

        # Student Discount (50% off)
        student_fare = calculate_server_fare(32.5, "AC Deluxe", "Daily", "Student")
        self.assertEqual(student_fare["final_fare"], 199.06)

    def test_02_hmac_tamper_proof_signature(self):
        """Verify HMAC signature generation and integrity verification"""
        ticket_id = "PASS-TEST-1234"
        phone = "9876543210"
        fare = 150.00
        route_id = "1"
        ts = time.time()

        sig = generate_ticket_hmac(ticket_id, phone, fare, route_id, ts)
        self.assertTrue(verify_ticket_hmac(ticket_id, phone, fare, route_id, ts, sig))

        # Tampered fare check should fail!
        self.assertFalse(verify_ticket_hmac(ticket_id, phone, 1.00, route_id, ts, sig))

    def test_03_price_tamper_prevention_api(self):
        """Verify backend blocks client price tampering attacks with HTTP 400"""
        payload = {
            "passenger_name": "Test Attacker",
            "user_phone": "9998887776",
            "user_email": "attacker@test.com",
            "user_category": "Regular",
            "pass_type": "Monthly",
            "route_id": 1,
            "client_claimed_fare": 1.00  # Attempted price modification!
        }
        res = self.client.post("/api/book-pass", json=payload)
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "TAMPERING_DETECTED")

    def test_04_seat_locking_and_concurrency(self):
        """Verify atomic seat locking prevents double booking"""
        bus_id = 1
        seat_no = 5
        date = "2026-08-15"
        
        # User 1 acquires lock
        acquired = global_seat_locks.acquire_lock(bus_id, seat_no, date, "user_1")
        self.assertTrue(acquired)

        # User 2 tries to acquire lock for same seat -> should be denied!
        acquired_user2 = global_seat_locks.acquire_lock(bus_id, seat_no, date, "user_2")
        self.assertFalse(acquired_user2)

        # Release lock
        global_seat_locks.release_lock(bus_id, seat_no, date)

    def test_05_conductor_verification_api(self):
        """Verify conductor verification endpoint with legitimate pass"""
        # Book a legitimate pass for Route 1 (18.5km)
        fare_info = calculate_server_fare(18.5, "AC Deluxe", "Daily", "Regular")
        pass_res = self.client.post("/api/book-pass", json={
            "passenger_name": "Alice Valid",
            "user_phone": "9123456789",
            "user_email": "alice@test.com",
            "user_category": "Regular",
            "pass_type": "Daily",
            "route_id": 1,
            "client_claimed_fare": fare_info["final_fare"]
        })
        self.assertEqual(pass_res.status_code, 200)
        pass_id = pass_res.get_json()["pass"]["pass_id"]

        # Conductor verifies pass
        verify_res = self.client.post("/api/verify-pass-or-ticket", json={"identifier": pass_id})
        self.assertEqual(verify_res.status_code, 200)
        v_data = verify_res.get_json()
        self.assertTrue(v_data["valid"])
        self.assertEqual(v_data["status"], "Active")

    def test_06_auto_scaler_node_provisioning(self):
        """Verify cloud cluster auto-scaling logic under high traffic"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM server_nodes WHERE status='ACTIVE';")
        initial_nodes = cursor.fetchone()[0]

        # Trigger traffic surge simulation
        global_scaler._update_cluster_state(current_rps=250.0)

        cursor.execute("SELECT COUNT(*) FROM server_nodes WHERE status='ACTIVE';")
        scaled_nodes = cursor.fetchone()[0]
        conn.close()

        self.assertGreater(scaled_nodes, initial_nodes)

if __name__ == "__main__":
    unittest.main()
