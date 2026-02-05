"""
Network Discovery Module for Potboy

Uses mDNS/Zeroconf to automatically discover devices on the local network.
- Server registers itself so clients can find it
- Server discovers Raspberry Pi clients
- No manual IP configuration needed!

Requirements:
    pip install zeroconf
"""

import socket
import time
import threading
from typing import Optional, Callable

# Try to import zeroconf, gracefully degrade if not available
try:
    from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf, ServiceStateChange
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False
    print("⚠️ zeroconf not installed. Auto-discovery disabled.")
    print("   Install with: pip install zeroconf")


# Service type for Potboy
SERVICE_TYPE = "_potboy._tcp.local."
SERVER_SERVICE_NAME = "potboy-server._potboy._tcp.local."
CLIENT_SERVICE_NAME = "potboy-client._potboy._tcp.local."


def get_local_ip() -> str:
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class PotboyServiceRegistration:
    """Register this device as a Potboy service on the network."""
    
    def __init__(self, service_name: str, port: int, properties: dict = None):
        self.service_name = service_name
        self.port = port
        self.properties = properties or {}
        self.zeroconf: Optional[Zeroconf] = None
        self.info: Optional[ServiceInfo] = None
    
    def start(self) -> bool:
        """Start advertising the service. Returns True if successful."""
        if not ZEROCONF_AVAILABLE:
            return False
        
        try:
            local_ip = get_local_ip()
            
            self.zeroconf = Zeroconf()
            self.info = ServiceInfo(
                SERVICE_TYPE,
                self.service_name,
                addresses=[socket.inet_aton(local_ip)],
                port=self.port,
                properties=self.properties,
                server=f"{socket.gethostname()}.local."
            )
            
            self.zeroconf.register_service(self.info)
            print(f"📡 Service registered: {self.service_name} at {local_ip}:{self.port}")
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to register service: {e}")
            return False
    
    def stop(self):
        """Stop advertising the service."""
        if self.zeroconf and self.info:
            self.zeroconf.unregister_service(self.info)
            self.zeroconf.close()
            print(f"📡 Service unregistered: {self.service_name}")


class PotboyServiceDiscovery:
    """Discover Potboy services on the network."""
    
    def __init__(self, target_service: str = None):
        """
        Args:
            target_service: The service name to look for (e.g., SERVER_SERVICE_NAME)
                           If None, discovers all Potboy services.
        """
        self.target_service = target_service
        self.discovered_services: dict = {}  # service_name -> (ip, port, properties)
        self.zeroconf: Optional[Zeroconf] = None
        self.browser: Optional[ServiceBrowser] = None
        self._on_found: Optional[Callable] = None
        self._lock = threading.Lock()
    
    def _on_service_state_change(self, zeroconf: Zeroconf, service_type: str, 
                                  name: str, state_change: ServiceStateChange):
        """Callback when a service is found or removed."""
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info:
                # Get IP address
                if info.addresses:
                    ip = socket.inet_ntoa(info.addresses[0])
                    port = info.port
                    properties = {k.decode(): v.decode() if isinstance(v, bytes) else v 
                                for k, v in info.properties.items()}
                    
                    with self._lock:
                        self.discovered_services[name] = (ip, port, properties)
                    
                    print(f"🔍 Discovered: {name} at {ip}:{port}")
                    
                    if self._on_found:
                        self._on_found(name, ip, port, properties)
        
        elif state_change == ServiceStateChange.Removed:
            with self._lock:
                if name in self.discovered_services:
                    del self.discovered_services[name]
                    print(f"🔍 Service removed: {name}")
    
    def start(self, on_found: Callable = None) -> bool:
        """
        Start discovering services.
        
        Args:
            on_found: Optional callback(name, ip, port, properties) when service found
        
        Returns:
            True if discovery started successfully
        """
        if not ZEROCONF_AVAILABLE:
            return False
        
        try:
            self._on_found = on_found
            self.zeroconf = Zeroconf()
            self.browser = ServiceBrowser(
                self.zeroconf, 
                SERVICE_TYPE, 
                handlers=[self._on_service_state_change]
            )
            print(f"🔍 Searching for Potboy services...")
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to start discovery: {e}")
            return False
    
    def find_service(self, timeout: float = 5.0) -> Optional[tuple]:
        """
        Find a specific service (blocking).
        
        Args:
            timeout: Maximum time to wait in seconds
        
        Returns:
            (ip, port, properties) tuple if found, None otherwise
        """
        if not ZEROCONF_AVAILABLE:
            return None
        
        if not self.zeroconf:
            self.start()
        
        # Wait for service to be discovered
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                if self.target_service and self.target_service in self.discovered_services:
                    return self.discovered_services[self.target_service]
                
                # If no specific target, return first found
                if not self.target_service and self.discovered_services:
                    return list(self.discovered_services.values())[0]
            
            time.sleep(0.1)
        
        return None
    
    def stop(self):
        """Stop discovering services."""
        if self.zeroconf:
            self.zeroconf.close()


def discover_server(timeout: float = 5.0) -> Optional[tuple]:
    """
    Convenience function to discover the Potboy server.
    
    Returns:
        (ip, port) tuple if found, None otherwise
    """
    discovery = PotboyServiceDiscovery(SERVER_SERVICE_NAME)
    result = discovery.find_service(timeout)
    discovery.stop()
    
    if result:
        ip, port, _ = result
        return (ip, port)
    return None


def discover_client(timeout: float = 5.0) -> Optional[tuple]:
    """
    Convenience function to discover a Potboy client (Raspberry Pi).
    
    Returns:
        (ip, port) tuple if found, None otherwise
    """
    discovery = PotboyServiceDiscovery(CLIENT_SERVICE_NAME)
    result = discovery.find_service(timeout)
    discovery.stop()
    
    if result:
        ip, port, _ = result
        return (ip, port)
    return None


# Simple test
if __name__ == "__main__":
    print("Testing Potboy Discovery...")
    print(f"Local IP: {get_local_ip()}")
    
    # Register as server
    reg = PotboyServiceRegistration(SERVER_SERVICE_NAME, 8765, {"type": "server"})
    reg.start()
    
    print("\nSearching for services for 10 seconds...")
    discovery = PotboyServiceDiscovery()
    discovery.start()
    time.sleep(10)
    
    print(f"\nDiscovered services: {discovery.discovered_services}")
    
    discovery.stop()
    reg.stop()
