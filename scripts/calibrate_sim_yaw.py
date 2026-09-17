"""Bounded single-trial calibration against a dedicated official simulator.

Start/reset the dedicated simulator between signs. No hardware socket accepted.
"""
import argparse
import json
import math
from pathlib import Path
import socket
import threading
import time

ROOT=Path('/home/juper007/projects/microduck-connectome-thor')
SOCKET=ROOT/'cal-state/duck-a.sock'

def yaw(frame):
    w,x,y,z=frame['imu']['quat']
    return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))

def delta(a,b): return math.atan2(math.sin(a-b),math.cos(a-b))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sign',type=int,choices=(-1,1),required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,choices=(3,8),default=3)
    args=parser.parse_args()
    latest={}; fault=[]; finish=threading.Event()
    sub=socket.socket(socket.AF_UNIX); sub.settimeout(.2); sub.connect(str(SOCKET))
    sub.sendall(b'{"jsonrpc":"2.0","id":1,"method":"robot.subscribe","params":{"hz":50}}\n')
    def observe():
        buffer=b''
        while not finish.is_set():
            try: chunk=sub.recv(65536)
            except socket.timeout: continue
            except OSError: break
            if not chunk: fault.append('subscription closed'); break
            buffer+=chunk
            while b'\n' in buffer:
                line,buffer=buffer.split(b'\n',1)
                msg=json.loads(line)
                if msg.get('method')=='robot.state':
                    latest['sample']=(time.monotonic_ns(),msg['params'])
    thread=threading.Thread(target=observe,daemon=True); thread.start()
    cmd=socket.socket(socket.AF_UNIX); cmd.settimeout(.1); cmd.connect(str(SOCKET))
    body=socket.create_connection(('127.0.0.1',18801),timeout=.1)
    bf=body.makefile('rwb')
    def sense():
        bf.write(b'{"op":"read"}\n'); bf.flush()
        return json.loads(bf.readline())
    def move(v):
        cmd.sendall((json.dumps({'jsonrpc':'2.0','method':'robot.move','params':{'vx':0.,'vy':0.,'vyaw':v}})+'\n').encode())
    def state():
        sample=latest.get('sample')
        if not sample or time.monotonic_ns()-sample[0]>=100_000_000 or time.monotonic_ns()-sample[1]['t_ns']>=100_000_000:
            raise RuntimeError('stale robot state')
        s=sample[1]
        if s['safety']['fallen'] or s['safety']['limp'] or fault:
            raise RuntimeError('simulator safety fault')
        return s
    trace=[]
    try:
        bf.write(b'{"op":"hello","protocol":1,"joints":15}\n'); bf.flush(); bf.readline()
        time.sleep(.15)
        state()
        baseline_start=sense()
        for _ in range(50): move(0); state(); time.sleep(.02)
        initial=sense()
        previous=time.monotonic(); v=0
        for i in range(args.seconds*50):
            begin=time.monotonic(); dt=begin-previous
            if dt>.1: raise RuntimeError('calibration scheduler stalled')
            previous=begin
            target=args.sign*.2
            v+=max(-1.5*min(dt,.02),min(1.5*min(dt,.02),target-v))
            s=state(); move(v)
            trace.append({'timestamp_ns':time.monotonic_ns(),'command_yaw':v,'applied':s['move']['applied'],'odom_yaw':s['odom']['yaw'],'policy':s['policy']})
            time.sleep(max(0,.02-(time.monotonic()-begin)))
        end=sense()
        stop_ns=time.monotonic_ns(); move(0)
        first_neutral=None; requested_zero=None; decay={}
        for _ in range(250):
            move(0); s=state()
            elapsed=(time.monotonic_ns()-stop_ns)/1e6
            if s['t_ns']>=stop_ns and all(abs(x)<1e-9 for x in s['move']['requested']) and requested_zero is None:
                requested_zero=elapsed
            for bound in (.01,.001,1e-9):
                if s['t_ns']>=stop_ns and all(abs(x)<=bound for x in s['move']['applied']) and str(bound) not in decay:
                    decay[str(bound)]=elapsed
            if s['t_ns']>=stop_ns and all(abs(x)<1e-9 for x in s['move']['applied']) and first_neutral is None:
                first_neutral=(time.monotonic_ns()-stop_ns)/1e6
            time.sleep(.02)
        stopped=sense()
        report={'sign':args.sign,'command_limit_radps':.2,'duration_ticks':args.seconds*50,
                'baseline_delta_rad':delta(yaw(initial),yaw(baseline_start)),
                'heading_delta_rad':delta(yaw(end),yaw(initial)),
                'post_stop_heading_delta_rad':delta(yaw(stopped),yaw(end)),
                'zero_twist_to_applied_zero_observed_ms':first_neutral,
                'zero_twist_to_requested_zero_observed_ms':requested_zero,
                'applied_decay_observed_ms_by_tolerance':decay,
                'initial_strict_stop_test_applied_1e9_within_1s':first_neutral is not None and first_neutral<=1000,
                'initial_trunk_z':initial['trunk_z'],'final_trunk_z':stopped['trunk_z'],
                'trace':trace,'stop_transport':'zero_twist','measurement':'MuJoCo trunk quaternion, wxyz, world yaw',
                'scope':'bounded calibration; no neural controller or crash-watchdog approval'}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k!='trace'}))
    finally:
        try: move(0)
        finally:
            finish.set(); cmd.close(); body.close(); sub.close(); thread.join(timeout=.5)

if __name__=='__main__': main()
