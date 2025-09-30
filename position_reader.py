#!/usr/bin/env python3
"""
UR10 Position Reader - Command Line Tool
A simple script to read and display real-time position data from UR10
for comparison with teach pendant values.

Author: jsecco ®
"""

import socket
import struct
import time
import sys
import argparse
from typing import List, Optional

class UR10PositionReader:
    """Simple UR10 position data reader for debugging and comparison."""
    
    def __init__(self, robot_ip: str, port: int = 30003):
        """
        Initialize the position reader.
        
        Args:
            robot_ip: IP address of the UR10 robot
            port: Communication port (30003 for real-time data)
        """
        self.robot_ip = robot_ip
        self.port = port
        self.socket = None
        self.connected = False
        
    def connect(self) -> bool:
        """Connect to the UR10 robot."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.robot_ip, self.port))
            self.connected = True
            print(f"✅ Connected to UR10 at {self.robot_ip}:{self.port}")
            return True
        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from the robot."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            finally:
                self.socket = None
                self.connected = False
        print("🔌 Disconnected from UR10")
    
    def read_message(self) -> Optional[bytes]:
        """Read a complete message from the robot."""
        if not self.connected or not self.socket:
            return None
        
        try:
            # Read message header (4 bytes = message length)
            header = self._recv_exact(4)
            if not header:
                return None
            
            # Unpack message length
            message_length = struct.unpack('>I', header)[0]
            
            if message_length > 10000:  # Sanity check
                print(f"⚠️  Unusually large message: {message_length} bytes")
                return None
            
            # Read the complete message
            message_data = self._recv_exact(message_length - 4)
            return message_data
            
        except Exception as e:
            print(f"❌ Error reading message: {e}")
            return None
    
    def _recv_exact(self, length: int) -> Optional[bytes]:
        """Receive exactly the specified number of bytes."""
        data = b''
        while len(data) < length:
            try:
                chunk = self.socket.recv(length - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                continue
            except Exception:
                return None
        return data
    
    def parse_position_data(self, data: bytes, verbose: bool = False) -> dict:
        """
        Parse position data from the robot message.
        Scans through the entire message looking for reasonable position values.
        """
        results = {
            'tcp_candidates': [],
            'joint_candidates': [],
            'raw_doubles': [],
            'target_values': None
        }
        
        # Target values from teach pendant (you mentioned: Rx: 1.707, Ry: 3.654, Rz: -0.579)
        target_rx, target_ry, target_rz = 1.707, 3.654, -0.579
        
        # Scan through the data looking for double values (8 bytes each)
        for offset in range(0, len(data) - 48, 8):  # Need at least 48 bytes for 6 doubles
            try:
                # Try to read 6 consecutive doubles
                doubles = list(struct.unpack('>6d', data[offset:offset + 48]))
                results['raw_doubles'].append((offset, doubles))
                
                # Check if this could be TCP position data
                # TCP positions: X, Y, Z (should be in meters, reasonable range)
                # TCP orientations: Rx, Ry, Rz (could be in radians)
                if self._looks_like_tcp_data(doubles):
                    results['tcp_candidates'].append({
                        'offset': offset,
                        'position': doubles[:3],
                        'orientation': doubles[3:6],
                        'full_data': doubles
                    })
                
                # Check if this could be joint angle data
                # Joint angles should be in radians, typically -2π to +2π range
                if self._looks_like_joint_data(doubles):
                    results['joint_candidates'].append({
                        'offset': offset,
                        'angles': doubles,
                        'degrees': [x * 180 / 3.14159 for x in doubles]
                    })
                
                # Check for specific target values
                self._check_for_target_values(doubles, offset, target_rx, target_ry, target_rz, results)
                    
            except struct.error:
                continue
        
        return results
    
    def _looks_like_tcp_data(self, doubles: List[float]) -> bool:
        """Check if the doubles look like TCP position/orientation data."""
        position = doubles[:3]
        orientation = doubles[3:6]
        
        # Position should be reasonable for a robot workspace (in meters)
        pos_reasonable = all(-3.0 < x < 3.0 for x in position)
        
        # Orientation values could be in various formats, so be more lenient
        orient_reasonable = all(-10.0 < x < 10.0 for x in orientation)
        
        return pos_reasonable and orient_reasonable
    
    def _looks_like_joint_data(self, doubles: List[float]) -> bool:
        """Check if the doubles look like joint angle data."""
        # Joint angles should be reasonable (typically -2π to +2π, but can be more)
        return all(-7.0 < x < 7.0 for x in doubles)
    
    def _check_for_target_values(self, doubles: List[float], offset: int, target_rx: float, target_ry: float, target_rz: float, results: dict):
        """Check if any consecutive 3 values match our target orientation values."""
        tolerance = 0.01  # Allow small differences
        
        # Check all possible 3-value combinations in the 6 doubles
        for i in range(4):  # Can check positions 0-2, 1-3, 2-4, 3-5
            values = doubles[i:i+3]
            
            # Check if these 3 values match our target RPY values
            if (abs(values[0] - target_rx) < tolerance and 
                abs(values[1] - target_ry) < tolerance and 
                abs(values[2] - target_rz) < tolerance):
                
                results['target_values'] = {
                    'offset': offset,
                    'position_in_array': i,
                    'found_values': values,
                    'target_values': [target_rx, target_ry, target_rz],
                    'full_array': doubles
                }
                return
    
    def display_position_data(self, data: dict, verbose: bool = False):
        """Display the parsed position data in a readable format."""
        print("\n" + "="*60)
        print(f"📊 POSITION DATA ANALYSIS - {time.strftime('%H:%M:%S')}")
        print("="*60)
        
        # Display target value matches first (most important)
        if data.get('target_values'):
            print(f"\n🎯 TARGET VALUES FOUND!")
            target = data['target_values']
            print(f"  Found at offset {target['offset']}, positions {target['position_in_array']}-{target['position_in_array']+2}:")
            print(f"  Expected: Rx={target['target_values'][0]:.3f}, Ry={target['target_values'][1]:.3f}, Rz={target['target_values'][2]:.3f}")
            print(f"  Found:    Rx={target['found_values'][0]:.3f}, Ry={target['found_values'][1]:.3f}, Rz={target['found_values'][2]:.3f}")
            print(f"  Full array: [{', '.join(f'{x:+7.3f}' for x in target['full_array'])}]")
            print(f"  ✅ THIS IS LIKELY THE CORRECT TCP ORIENTATION DATA!")
        else:
            print(f"\n❌ Target values (Rx=1.707, Ry=3.654, Rz=-0.579) not found")
        
        # Display TCP candidates
        if data['tcp_candidates']:
            print(f"\n🎯 TCP Position Candidates ({len(data['tcp_candidates'])} found):")
            for i, tcp in enumerate(data['tcp_candidates']):
                print(f"\n  Candidate #{i+1} (offset {tcp['offset']}):")
                print(f"    Position: X={tcp['position'][0]:+7.3f}m  Y={tcp['position'][1]:+7.3f}m  Z={tcp['position'][2]:+7.3f}m")
                print(f"    Orient:   Rx={tcp['orientation'][0]:+7.3f}   Ry={tcp['orientation'][1]:+7.3f}   Rz={tcp['orientation'][2]:+7.3f}")
                print(f"    Orient°:  Rx={tcp['orientation'][0]*180/3.14159:+7.1f}°  Ry={tcp['orientation'][1]*180/3.14159:+7.1f}°  Rz={tcp['orientation'][2]*180/3.14159:+7.1f}°")
        else:
            print("\n❌ No TCP position candidates found")
        
        # Display Joint candidates
        if data['joint_candidates']:
            print(f"\n🦾 Joint Angle Candidates ({len(data['joint_candidates'])} found):")
            for i, joint in enumerate(data['joint_candidates']):
                print(f"\n  Candidate #{i+1} (offset {joint['offset']}):")
                print(f"    Radians: J1={joint['angles'][0]:+7.3f}  J2={joint['angles'][1]:+7.3f}  J3={joint['angles'][2]:+7.3f}")
                print(f"             J4={joint['angles'][3]:+7.3f}  J5={joint['angles'][4]:+7.3f}  J6={joint['angles'][5]:+7.3f}")
                print(f"    Degrees: J1={joint['degrees'][0]:+7.1f}°  J2={joint['degrees'][1]:+7.1f}°  J3={joint['degrees'][2]:+7.1f}°")
                print(f"             J4={joint['degrees'][3]:+7.1f}°  J5={joint['degrees'][4]:+7.1f}°  J6={joint['degrees'][5]:+7.1f}°")
        else:
            print("\n❌ No joint angle candidates found")
        
        if verbose and data['raw_doubles']:
            print(f"\n🔍 All Double Values Found ({len(data['raw_doubles'])} sets):")
            for offset, doubles in data['raw_doubles'][:10]:  # Show first 10 sets
                print(f"  Offset {offset:3d}: [{', '.join(f'{x:+8.3f}' for x in doubles)}]")
            if len(data['raw_doubles']) > 10:
                print(f"  ... and {len(data['raw_doubles'])-10} more sets")
    
    def run_continuous(self, update_rate: float = 1.0, verbose: bool = False):
        """Run continuous position monitoring."""
        print(f"\n🚀 Starting continuous position monitoring (update every {update_rate:.1f}s)")
        print("📋 Compare these values with your UR10 teach pendant")
        print("   Press Ctrl+C to stop")
        
        message_count = 0
        last_display_time = 0
        
        try:
            while True:
                message = self.read_message()
                if message:
                    message_count += 1
                    current_time = time.time()
                    
                    # Display at specified rate
                    if current_time - last_display_time >= update_rate:
                        position_data = self.parse_position_data(message, verbose)
                        
                        # Clear screen for better readability
                        print("\033[2J\033[H")  # Clear screen and move cursor to top
                        
                        print(f"📡 Messages received: {message_count}")
                        self.display_position_data(position_data, verbose)
                        
                        last_display_time = current_time
                
                time.sleep(0.01)  # Small delay to prevent overwhelming the system
                
        except KeyboardInterrupt:
            print(f"\n\n⏹️  Stopped by user. Total messages received: {message_count}")


def main():
    """Main function to run the position reader."""
    parser = argparse.ArgumentParser(
        description='Read and display UR10 robot position data for comparison with teach pendant',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python position_reader.py 192.168.10.24
  python position_reader.py 192.168.10.24 --rate 2.0 --verbose
  python position_reader.py 192.168.10.24 --single
        """
    )
    
    parser.add_argument('robot_ip', help='IP address of the UR10 robot')
    parser.add_argument('--port', type=int, default=30003, 
                       help='Communication port (default: 30003)')
    parser.add_argument('--rate', type=float, default=1.0,
                       help='Update rate in seconds (default: 1.0)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show verbose output including all raw data')
    parser.add_argument('--single', '-s', action='store_true',
                       help='Read single message and exit')
    
    args = parser.parse_args()
    
    print("🤖 UR10 Position Reader")
    print("="*40)
    
    reader = UR10PositionReader(args.robot_ip, args.port)
    
    try:
        if not reader.connect():
            sys.exit(1)
        
        if args.single:
            print("\n📖 Reading single message...")
            message = reader.read_message()
            if message:
                position_data = reader.parse_position_data(message, args.verbose)
                reader.display_position_data(position_data, args.verbose)
            else:
                print("❌ No message received")
        else:
            reader.run_continuous(args.rate, args.verbose)
            
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)
    finally:
        reader.disconnect()


if __name__ == "__main__":
    main()
