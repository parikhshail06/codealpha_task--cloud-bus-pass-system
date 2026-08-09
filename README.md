# 🚌 CloudBus Pass - Scalable Cloud-Based Bus Pass & Ticket Booking System
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-Flask-green.svg)](https://flask.palletsprojects.com/)
[![Security](https://img.shields.io/badge/security-HMAC--SHA256-red.svg)](#-anti-theft--price-tamper-prevention)
[![License](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
A production-grade, cloud-native **Bus Pass & Online Ticket Booking System** built in Python. Designed for high scalability, reliability, and security, **CloudBus Pass** addresses critical transit challenges including **ticket theft prevention**, **price tampering elimination**, **dynamic auto-scaling under high traffic**, **atomic seat locking**, and **live conductor QR code pass validation**.
---
## 🌟 Key Features
### 1. 🎫 Pass & Ticket Booking Engine
- **Flexible Pass Options**: Issue Daily (24h), Weekly (7 days), and Monthly (30 days) unlimited travel passes.
- **Single Journey Booking**: Interactive 2D seat map selection with real-time availability states.
- **Concession Discounts**: Automatic concession matrix for Students (50% off), Senior Citizens (40% off), and Differently Abled passengers (60% off).
- **Indian Rupee (₹) & Metro Routes**: Built-in support for major Indian transit corridors across Mumbai, Delhi NCR, Bengaluru, Hyderabad, Chennai, and Pune.
### 2. 🛡️ Anti-Theft & Price Tamper Prevention
- **SHA-256 HMAC Signatures**: Every ticket and pass is cryptographically signed using a server-side secret key `(ID + Phone + Fare + Route + Timestamp)`.
- **Anti-Price Tampering Guard**: Client-claimed fares are validated against the authoritative server fare matrix. Any DOM or API payload tampering is blocked instantly with HTTP 400 (`TAMPERING_DETECTED`) and recorded in security incident logs.
- **Digital Anti-Theft Passes**: Dynamic SVG QR code matrix generator with dynamic expiry timestamps, eliminating physical ticket loss.
### 3. ⚡ Cloud Auto-Scaling & High-Traffic Resilience
- **Server Cluster Auto-Scaler Daemon**: Background load manager monitoring Requests Per Second (RPS) and CPU utilization.
- **Dynamic Provisioning**: Automatically provisions new virtual server worker nodes (`Cloud Node Worker 2`, `Worker 3`...) when RPS per node exceeds 40 RPS, and gracefully de-provisions nodes when traffic cools down.
- **Traffic Surge Test Trigger**: Built-in simulator button to launch 220+ RPS spikes and observe cluster auto-scaling live.
### 4. 🔒 Concurrency Seat Lock Manager
- **Atomic Seat Lock (5-Minute TTL)**: In-memory lock mechanism preventing double-booking when multiple users reserve the same seat simultaneously during flash sales.
