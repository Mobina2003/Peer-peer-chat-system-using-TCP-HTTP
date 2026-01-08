import socket
import threading
import json
import requests
import time
from datetime import datetime
import sys

class Peer:
    def __init__(self, username, stun_server_url='http://localhost:5000'):
        """
        Initialize a new peer
        
        Args:
            username (str): Unique username for the peer
            stun_server_url (str): URL of the STUN server
        """
        self.username = username
        self.stun_server_url = stun_server_url
        
        # Network information
        self.local_ip = self.get_local_ip()
        self.peer_port = None  # Will be assigned when TCP server starts
        
        # Connection management
        self.connections = {}  # username -> socket
        self.is_running = False
        self.tcp_server = None
        self.tcp_server_thread = None
        
        # Heartbeat thread
        self.heartbeat_thread = None
        
    def get_local_ip(self):
        """Get local IP address"""
        try:
            # Create a socket to get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def start_tcp_server(self, port=0):
        """
        Start TCP server to listen for incoming connections
        
        Args:
            port (int): Port to listen on (0 for random)
        """
        try:
            # Create TCP socket
            self.tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Bind to any available port
            self.tcp_server.bind((self.local_ip, port))
            self.tcp_server.listen(5)
            
            # Get assigned port
            self.peer_port = self.tcp_server.getsockname()[1]
            
            print(f"TCP Server started on {self.local_ip}:{self.peer_port}")
            
            # Start listening thread
            self.is_running = True
            self.tcp_server_thread = threading.Thread(target=self.accept_connections, daemon=True)
            self.tcp_server_thread.start()
            
            return True
        except Exception as e:
            print(f"Failed to start TCP server: {e}")
            return False
    
    def accept_connections(self):
        """Accept incoming TCP connections"""
        while self.is_running:
            try:
                client_socket, client_address = self.tcp_server.accept()
                print(f"Connection from {client_address}")
                
                # Start new thread to handle this connection
                thread = threading.Thread(
                    target=self.handle_incoming_connection,
                    args=(client_socket, client_address),
                    daemon=True
                )
                thread.start()
            except:
                break
    
    def handle_incoming_connection(self, client_socket, client_address):
        """Handle incoming connection request"""
        try:
            # Receive connection request
            data = client_socket.recv(1024).decode('utf-8')
            if data:
                connection_request = json.loads(data)
                
                if connection_request.get('type') == 'connect_request':
                    from_username = connection_request.get('username')
                    
                    print(f"\n🔔 Connection request from {from_username}")
                    response = input("Accept connection? (y/n): ").lower()
                    
                    if response == 'y':
                        # Accept connection
                        accept_msg = json.dumps({
                            'type': 'connection_accepted',
                            'from': self.username
                        })
                        client_socket.send(accept_msg.encode('utf-8'))
                        
                        # Add to connections
                        self.connections[from_username] = client_socket
                        
                        print(f"✅ Connected to {from_username}")
                        
                        # Start chat with this peer
                        self.chat_with_peer(from_username, client_socket)
                    else:
                        # Reject connection
                        reject_msg = json.dumps({
                            'type': 'connection_rejected',
                            'from': self.username
                        })
                        client_socket.send(reject_msg.encode('utf-8'))
                        client_socket.close()
        except Exception as e:
            print(f"Error handling connection: {e}")
            client_socket.close()
    
    def register_with_stun(self):
        """Register this peer with the STUN server"""
        try:
            if not self.peer_port:
                print("TCP server not started. Starting TCP server...")
                if not self.start_tcp_server():
                    return False
            
            # Prepare registration data
            registration_data = {
                'username': self.username,
                'ip_address': self.local_ip,
                'port': self.peer_port
            }
            
            # Send POST request to STUN server
            response = requests.post(
                f"{self.stun_server_url}/register",
                json=registration_data,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code in [200, 201]:
                print(f"✅ Successfully registered as {self.username}")
                print(f"   IP: {self.local_ip}, Port: {self.peer_port}")
                
                # Start heartbeat
                self.start_heartbeat()
                
                return True
            else:
                print(f"❌ Registration failed: {response.json().get('error')}")
                return False
                
        except requests.exceptions.ConnectionError:
            print(f"❌ Cannot connect to STUN server at {self.stun_server_url}")
            return False
        except Exception as e:
            print(f"❌ Registration error: {e}")
            return False
    
    def start_heartbeat(self):
        """Start sending heartbeat to STUN server"""
        def heartbeat_loop():
            while self.is_running:
                try:
                    requests.post(
                        f"{self.stun_server_url}/heartbeat",
                        json={'username': self.username},
                        timeout=5
                    )
                except:
                    pass  # Silently fail for heartbeat
                
                time.sleep(60)  # Send heartbeat every minute
        
        self.heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
    
    def get_online_peers(self):
        """Get list of online peers from STUN server"""
        try:
            response = requests.get(f"{self.stun_server_url}/peers")
            
            if response.status_code == 200:
                data = response.json()
                peers = data.get('peers', [])
                
                # Filter out self
                other_peers = [p for p in peers if p['username'] != self.username]
                
                return other_peers
            else:
                print(f"Failed to get peers: {response.json().get('error')}")
                return []
                
        except Exception as e:
            print(f"Error getting peers: {e}")
            return []
    
    def get_peer_info(self, username):
        """Get connection info for a specific peer"""
        try:
            response = requests.get(
                f"{self.stun_server_url}/peerinfo",
                params={'username': username}
            )
            
            if response.status_code == 200:
                return response.json().get('peer')
            else:
                print(f"Peer {username} not found")
                return None
                
        except Exception as e:
            print(f"Error getting peer info: {e}")
            return None
    
    def connect_to_peer(self, target_username):
        """Connect to another peer using TCP"""
        try:
            # Get peer information from STUN server
            peer_info = self.get_peer_info(target_username)
            
            if not peer_info:
                print(f"❌ Peer {target_username} not found or offline")
                return False
            
            if target_username in self.connections:
                print(f"⚠️  Already connected to {target_username}")
                return True
            
            # Extract connection info
            target_ip = peer_info['ip_address']
            target_port = int(peer_info['port'])
            
            # Create TCP socket
            peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            peer_socket.settimeout(10)  # 10 second timeout
            
            print(f"Connecting to {target_username} at {target_ip}:{target_port}...")
            
            try:
                peer_socket.connect((target_ip, target_port))
                
                # Send connection request
                connect_request = json.dumps({
                    'type': 'connect_request',
                    'username': self.username,
                    'timestamp': datetime.now().isoformat()
                })
                peer_socket.send(connect_request.encode('utf-8'))
                
                # Wait for response
                response = peer_socket.recv(1024).decode('utf-8')
                response_data = json.loads(response)
                
                if response_data.get('type') == 'connection_accepted':
                    print(f"✅ Connection accepted by {target_username}")
                    
                    # Store connection
                    self.connections[target_username] = peer_socket
                    
                    # Start chat
                    self.chat_with_peer(target_username, peer_socket)
                    return True
                else:
                    print(f"❌ Connection rejected by {target_username}")
                    peer_socket.close()
                    return False
                    
            except socket.timeout:
                print(f"❌ Connection timeout for {target_username}")
                peer_socket.close()
                return False
            except ConnectionRefusedError:
                print(f"❌ Connection refused by {target_username}")
                return False
                
        except Exception as e:
            print(f"❌ Error connecting to peer: {e}")
            return False
    
    def chat_with_peer(self, peer_username, peer_socket):
        """Handle chat session with a peer"""
        def receive_messages():
            """Thread to receive messages"""
            while self.is_running and peer_username in self.connections:
                try:
                    data = peer_socket.recv(1024).decode('utf-8')
                    if not data:
                        break
                    
                    message_data = json.loads(data)
                    
                    if message_data.get('type') == 'message':
                        timestamp = message_data.get('timestamp', '')
                        sender = message_data.get('from', 'Unknown')
                        content = message_data.get('content', '')
                        
                        print(f"\n[{timestamp}] {sender}: {content}")
                        print("You: ", end="", flush=True)
                        
                    elif message_data.get('type') == 'disconnect':
                        print(f"\n🔴 {peer_username} disconnected")
                        break
                        
                except (ConnectionResetError, ConnectionAbortedError):
                    print(f"\n🔴 Connection lost with {peer_username}")
                    break
                except Exception as e:
                    if self.is_running:
                        print(f"\n⚠️  Error receiving message: {e}")
                    break
            
            # Clean up
            if peer_username in self.connections:
                del self.connections[peer_username]
            peer_socket.close()
        
        def send_messages():
            """Thread to send messages"""
            print(f"\n💬 Chatting with {peer_username} (type '/exit' to end)")
            print("You: ", end="", flush=True)
            
            while self.is_running and peer_username in self.connections:
                try:
                    message = input()
                    
                    if message.lower() == '/exit':
                        # Send disconnect message
                        disconnect_msg = json.dumps({
                            'type': 'disconnect',
                            'from': self.username,
                            'timestamp': datetime.now().isoformat()
                        })
                        peer_socket.send(disconnect_msg.encode('utf-8'))
                        
                        if peer_username in self.connections:
                            del self.connections[peer_username]
                        peer_socket.close()
                        print(f"Disconnected from {peer_username}")
                        break
                    
                    # Send message
                    message_data = json.dumps({
                        'type': 'message',
                        'from': self.username,
                        'content': message,
                        'timestamp': datetime.now().isoformat()
                    })
                    peer_socket.send(message_data.encode('utf-8'))
                    
                    print("You: ", end="", flush=True)
                    
                except Exception as e:
                    print(f"Error sending message: {e}")
                    break
        
        # Start receive thread
        receive_thread = threading.Thread(target=receive_messages, daemon=True)
        receive_thread.start()
        
        # Start send thread in main thread or separate
        send_thread = threading.Thread(target=send_messages, daemon=True)
        send_thread.start()
        
        # Wait for threads to complete
        send_thread.join()
    
    def unregister(self):
        """Unregister from STUN server and clean up"""
        self.is_running = False
        
        # Close all connections
        for username, sock in self.connections.items():
            try:
                sock.close()
            except:
                pass
        self.connections.clear()
        
        # Close TCP server
        if self.tcp_server:
            self.tcp_server.close()
        
        # Unregister from STUN
        try:
            requests.post(
                f"{self.stun_server_url}/unregister",
                json={'username': self.username},
                timeout=5
            )
            print("Unregistered from STUN server")
        except:
            pass

def main():
    """Main function to run the peer"""
    print("=" * 50)
    print("P2P Chat System - Peer Client")
    print("=" * 50)
    
    # Get username
    username = input("Enter your username: ").strip()
    if not username:
        print("Username cannot be empty!")
        return
    
    # Create peer instance
    peer = Peer(username)
    
    # Register with STUN server
    if not peer.register_with_stun():
        print("Failed to register. Exiting...")
        return
    
    try:
        while True:
            print("\n" + "=" * 50)
            print("Menu:")
            print("1. List online peers")
            print("2. Connect to a peer")
            print("3. My connection info")
            print("4. Exit")
            print("=" * 50)
            
            choice = input("Select option: ").strip()
            
            if choice == '1':
                # List online peers
                peers = peer.get_online_peers()
                
                if not peers:
                    print("\nNo other peers online")
                else:
                    print(f"\n📱 Online Peers ({len(peers)}):")
                    for i, p in enumerate(peers, 1):
                        print(f"{i}. {p['username']} - {p['ip_address']}:{p['port']}")
                
            elif choice == '2':
                # Connect to a peer
                target_username = input("Enter username to connect to: ").strip()
                
                if target_username == peer.username:
                    print("Cannot connect to yourself!")
                    continue
                
                # Check if already connected
                if target_username in peer.connections:
                    print(f"Already connected to {target_username}")
                    continue
                
                # Connect
                peer.connect_to_peer(target_username)
                
            elif choice == '3':
                # Show connection info
                print(f"\nMy Information:")
                print(f"Username: {peer.username}")
                print(f"IP Address: {peer.local_ip}")
                print(f"Port: {peer.peer_port}")
                print(f"STUN Server: {peer.stun_server_url}")
                print(f"Active connections: {len(peer.connections)}")
                
            elif choice == '4':
                # Exit
                print("Goodbye!")
                break
                
            else:
                print("Invalid option!")
                
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        peer.unregister()

if __name__ == "__main__":
    main()