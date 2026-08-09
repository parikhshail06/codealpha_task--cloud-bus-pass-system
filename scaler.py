import time
import threading
import random
import uuid
from database import get_db_connection

class SeatLockManager:
    """
    In-memory seat lock manager with TTL to prevent concurrent double-booking.
    """
    def __init__(self, lock_ttl_seconds=300):
        self.locks = {} # key: "bus_id:seat_no:date" -> {"phone": str, "timestamp": float}
        self.lock_ttl = lock_ttl_seconds
        self.mutex = threading.Lock()

    def acquire_lock(self, bus_id: int, seat_number: int, travel_date: str, user_phone: str) -> bool:
        key = f"{bus_id}:{seat_number}:{travel_date}"
        now = time.time()
        with self.mutex:
            self._cleanup_expired(now)
            if key in self.locks:
                existing = self.locks[key]
                if existing["phone"] != user_phone and (now - existing["timestamp"]) < self.lock_ttl:
                    return False
            self.locks[key] = {"phone": user_phone, "timestamp": now}
            return True

    def release_lock(self, bus_id: int, seat_number: int, travel_date: str):
        key = f"{bus_id}:{seat_number}:{travel_date}"
        with self.mutex:
            if key in self.locks:
                del self.locks[key]

    def is_locked(self, bus_id: int, seat_number: int, travel_date: str, current_user_phone: str = "") -> bool:
        key = f"{bus_id}:{seat_number}:{travel_date}"
        now = time.time()
        with self.mutex:
            self._cleanup_expired(now)
            if key in self.locks:
                existing = self.locks[key]
                if existing["phone"] != current_user_phone and (now - existing["timestamp"]) < self.lock_ttl:
                    return True
            return False

    def _cleanup_expired(self, now: float):
        expired_keys = [k for k, v in self.locks.items() if (now - v["timestamp"]) >= self.lock_ttl]
        for k in expired_keys:
            del self.locks[k]


class AutoScalerDaemon:
    """
    Cloud Auto-Scaler Daemon: Monitors cluster traffic, dynamically provisions/terminates
    virtual server instances based on RPS and CPU load spikes.
    """
    def __init__(self):
        self.running = False
        self.surge_active = False
        self.surge_until = 0
        self.current_simulated_rps = 14.0
        self.lock = threading.Lock()
        self.scale_up_rps_threshold = 40.0
        self.scale_down_rps_threshold = 12.0

    def start(self):
        self.running = True
        t = threading.Thread(target=self._monitor_loop, daemon=True)
        t.start()

    def stop(self):
        self.running = False

    def trigger_traffic_surge(self, duration_seconds=30, target_rps=220.0):
        with self.lock:
            self.surge_active = True
            self.surge_until = time.time() + duration_seconds
            self.current_simulated_rps = target_rps

    def record_request(self):
        with self.lock:
            if not self.surge_active:
                self.current_simulated_rps += 1.2

    def _monitor_loop(self):
        while self.running:
            time.sleep(3.0)
            now = time.time()
            with self.lock:
                if self.surge_active and now > self.surge_until:
                    self.surge_active = False
                
                # Decay RPS towards baseline if not in active surge
                if not self.surge_active:
                    self.current_simulated_rps = max(10.0, self.current_simulated_rps * 0.75 + random.uniform(0.5, 3.0))
                
                current_rps = self.current_simulated_rps

            self._update_cluster_state(current_rps)

    def _update_cluster_state(self, current_rps: float):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT node_id, status, cpu_usage, rps FROM server_nodes WHERE status='ACTIVE';")
            active_nodes = cursor.fetchall()
            node_count = max(1, len(active_nodes))
            
            rps_per_node = current_rps / node_count

            # Update existing active node metrics
            for node in active_nodes:
                node_id = node["node_id"]
                # CPU load proportional to RPS per node
                base_cpu = min(98.5, max(15.0, (rps_per_node * 1.6) + random.uniform(-3.0, 5.0)))
                mem = min(92.0, max(25.0, 30.0 + (rps_per_node * 0.8) + random.uniform(-1.0, 2.0)))
                cursor.execute(
                    "UPDATE server_nodes SET cpu_usage=?, memory_usage=?, rps=? WHERE node_id=?;",
                    (round(base_cpu, 1), round(mem, 1), round(rps_per_node, 1), node_id)
                )

            # Auto-scaling logic
            if rps_per_node > self.scale_up_rps_threshold and node_count < 8:
                # Provision new server node!
                new_id = f"node-worker-{uuid.uuid4().hex[:6]}"
                node_num = node_count + 1
                new_name = f"Cloud Node Worker {node_num}"
                new_ip = f"10.0.4.{100 + node_num}"
                cursor.execute("""
                INSERT INTO server_nodes (node_id, name, ip_address, status, cpu_usage, memory_usage, rps, created_at)
                VALUES (?, ?, ?, 'ACTIVE', ?, ?, ?, ?);
                """, (new_id, new_name, new_ip, 35.0, 28.0, rps_per_node / 2, time.time()))
                print(f"[AUTO-SCALER] Scaled UP: Provisioned virtual server {new_name} ({new_id}) due to high load (RPS: {current_rps:.1f})")

            elif rps_per_node < self.scale_down_rps_threshold and node_count > 1:
                # Scale down: terminate latest worker node
                latest_worker = [n for n in active_nodes if "worker" in n["node_id"]]
                if latest_worker:
                    node_to_kill = latest_worker[-1]["node_id"]
                    cursor.execute("DELETE FROM server_nodes WHERE node_id=?;", (node_to_kill,))
                    print(f"[AUTO-SCALER] Scaled DOWN: De-provisioned virtual server ({node_to_kill}) as load decreased.")

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[AUTO-SCALER ERROR]: {e}")

global_seat_locks = SeatLockManager()
global_scaler = AutoScalerDaemon()
