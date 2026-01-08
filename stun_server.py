from flask import Flask, request, jsonify
import redis
import json
import socket
from datetime import datetime, timedelta
import threading

app = Flask(__name__)

# Redis connection configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

class STUNServer:
    def __init__(self):
        """Initialize Redis connection and peer management"""
        try:
            self.redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True
            )
            print("Connected to Redis successfully")
            
            # Test connection
            self.redis_client.ping()
        except redis.ConnectionError:
            print("Redis not available, using in-memory storage")
            self.redis_client = None
            self.peers = {}
        
        # Clean up old peers periodically
        self.cleanup_thread = threading.Thread(target=self.cleanup_old_peers, daemon=True)
        self.cleanup_thread.start()
    
    def register_peer(self, username, ip_address, port):
        """Register a new peer in the system"""
        peer_info = {
            'username': username,
            'ip_address': ip_address,
            'port': port,
            'status': 'online',
            'last_seen': datetime.now().isoformat(),
            'registered_at': datetime.now().isoformat()
        }
        
        if self.redis_client:
            # Store in Redis with 1-hour expiry
            key = f"peer:{username}"
            self.redis_client.hset(key, mapping=peer_info)
            self.redis_client.expire(key, 3600)  # 1 hour TTL
            self.redis_client.sadd("online_peers", username)
        else:
            # Store in memory
            self.peers[username] = peer_info
        
        return peer_info
    
    def get_all_peers(self):
        """Get list of all registered peers"""
        if self.redis_client:
            # Get all peer usernames from set
            peer_usernames = self.redis_client.smembers("online_peers")
            peers = []
            for username in peer_usernames:
                peer_data = self.redis_client.hgetall(f"peer:{username}")
                if peer_data:
                    peers.append(peer_data)
            return peers
        else:
            return list(self.peers.values())
    
    def get_peer_info(self, username):
        """Get information for a specific peer"""
        if self.redis_client:
            key = f"peer:{username}"
            peer_info = self.redis_client.hgetall(key)
            if not peer_info:
                return None
            return peer_info
        else:
            return self.peers.get(username)
    
    def update_peer_status(self, username, status='online'):
        """Update peer's online status and timestamp"""
        if self.redis_client:
            key = f"peer:{username}"
            if self.redis_client.exists(key):
                self.redis_client.hset(key, 'status', status)
                self.redis_client.hset(key, 'last_seen', datetime.now().isoformat())
                
                if status == 'online':
                    self.redis_client.sadd("online_peers", username)
                else:
                    self.redis_client.srem("online_peers", username)
    
    def cleanup_old_peers(self):
        """Periodically clean up peers that haven't been seen for a while"""
        while True:
            threading.Event().wait(300)  # Every 5 minutes
            
            if self.redis_client:
                # Redis handles TTL automatically
                pass
            else:
                # Clean in-memory peers older than 30 minutes
                current_time = datetime.now()
                to_remove = []
                for username, peer in self.peers.items():
                    last_seen = datetime.fromisoformat(peer['last_seen'])
                    if (current_time - last_seen) > timedelta(minutes=30):
                        to_remove.append(username)
                
                for username in to_remove:
                    del self.peers[username]

# Initialize STUN server
stun_server = STUNServer()

# API Endpoints
@app.route('/register', methods=['POST'])
def register():
    """
    Endpoint: /register
    Method: POST
    Description: Register a new peer
    Request Body: JSON with username, ip_address, port
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['username', 'ip_address', 'port']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'error': f'Missing required field: {field}'
                }), 400
        
        username = data['username']
        ip_address = data['ip_address']
        port = data['port']
        
        # Check if username already exists
        existing_peer = stun_server.get_peer_info(username)
        if existing_peer:
            # Update existing peer
            stun_server.update_peer_status(username, 'online')
            return jsonify({
                'message': 'Peer updated successfully',
                'peer': existing_peer
            }), 200
        
        # Register new peer
        peer_info = stun_server.register_peer(username, ip_address, port)
        
        return jsonify({
            'message': 'Peer registered successfully',
            'peer': peer_info
        }), 201
        
    except Exception as e:
        return jsonify({
            'error': f'Registration failed: {str(e)}'
        }), 500

@app.route('/peers', methods=['GET'])
def get_peers():
    """
    Endpoint: /peers
    Method: GET
    Description: Get list of all online peers
    """
    try:
        peers = stun_server.get_all_peers()
        
        # Filter only online peers
        online_peers = [peer for peer in peers if peer.get('status') == 'online']
        
        return jsonify({
            'count': len(online_peers),
            'peers': online_peers
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': f'Failed to fetch peers: {str(e)}'
        }), 500

@app.route('/peerinfo', methods=['GET'])
def get_peer_info():
    """
    Endpoint: /peerinfo
    Method: GET
    Description: Get information for a specific peer
    Query Parameter: username
    """
    try:
        username = request.args.get('username')
        
        if not username:
            return jsonify({
                'error': 'Username parameter is required'
            }), 400
        
        peer_info = stun_server.get_peer_info(username)
        
        if not peer_info:
            return jsonify({
                'error': f'Peer {username} not found'
            }), 404
        
        return jsonify({
            'peer': peer_info
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': f'Failed to fetch peer info: {str(e)}'
        }), 500

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    """
    Endpoint: /heartbeat
    Method: POST
    Description: Update peer's last seen timestamp
    """
    try:
        data = request.get_json()
        username = data.get('username')
        
        if not username:
            return jsonify({'error': 'Username is required'}), 400
        
        stun_server.update_peer_status(username)
        
        return jsonify({
            'message': 'Heartbeat received'
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': f'Heartbeat failed: {str(e)}'
        }), 500

@app.route('/unregister', methods=['POST'])
def unregister():
    """
    Endpoint: /unregister
    Method: POST
    Description: Unregister a peer (set to offline)
    """
    try:
        data = request.get_json()
        username = data.get('username')
        
        if not username:
            return jsonify({'error': 'Username is required'}), 400
        
        stun_server.update_peer_status(username, 'offline')
        
        return jsonify({
            'message': f'Peer {username} unregistered successfully'
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': f'Unregistration failed: {str(e)}'
        }), 500

if __name__ == '__main__':
    print("Starting STUN Server on port 5000...")
    print("Available endpoints:")
    print("  POST   /register    - Register a new peer")
    print("  GET    /peers       - Get all online peers")
    print("  GET    /peerinfo    - Get specific peer info")
    print("  POST   /heartbeat   - Update peer status")
    print("  POST   /unregister  - Unregister peer")
    
    app.run(host='0.0.0.0', port=5000, debug=True)