"""Linux host metrics collector, independent of HTTP and presentation."""
import glob
import os
import re
import time
from pathlib import Path
from energy_store import counter_delta
from config import Settings

settings = Settings.from_env()
PROC, SYS, ROOT = settings.proc, settings.sys, settings.root
previous = {}

def read(path, default=''):
    try:
        return Path(path).read_text().strip()
    except (OSError, ValueError):
        return default

def resolved(pattern):
    # sysfs class links are absolute: resolve them inside the host sysfs mount.
    for p in glob.glob(str(SYS / pattern)):
        path = Path(p)
        if path.is_symlink():
            target = os.readlink(path)
            if target.startswith('/sys/'):
                path = SYS / target[5:]
        yield path

def counters():
    cpu = {}
    for line in read(PROC / 'stat').splitlines():
        parts = line.split()
        if re.fullmatch(r'cpu\d*', parts[0]):
            values = list(map(int, parts[1:9]))
            cpu[parts[0]] = (sum(values), values[3] + values[4])
    net = {}
    for line in read(PROC / '1/net/dev').splitlines()[2:]:
        name, data = line.split(':', 1)
        v = list(map(int, data.split()))
        if name.strip() != 'lo':
            net[name.strip()] = (v[0], v[8])
    disks = {}
    for line in read(PROC / 'diskstats').splitlines():
        v = line.split()
        name = v[2]
        if (SYS / 'block' / name).exists() and not name.startswith(('loop', 'ram', 'dm-')):
            disks[name] = (int(v[5]) * 512, int(v[9]) * 512, int(v[12]))
    return cpu, net, disks

def sample(energy_store=None):
    global previous
    now = time.monotonic()
    wall_now = time.time()
    dt = now - previous.get('time', now)
    cpu, net, disks = counters()
    def rates(current, key):
        old = previous.get(key, {})
        return {name: [max(0, (v[i] - old[name][i]) / dt) if name in old and dt > 0 else 0 for i in range(len(v))] for name, v in current.items()}
    usage = {}
    for name, (total, idle) in cpu.items():
        ot, oi = previous.get('cpu', {}).get(name, (total, idle))
        usage[name] = round(100 * (1 - (idle - oi) / (total - ot)), 1) if total > ot else 0
    mem = {}
    for line in read(PROC / 'meminfo').splitlines():
        k, v = line.split(':', 1)
        mem[k] = int(v.split()[0]) * 1024
    total = mem.get('MemTotal', 0)
    available = mem.get('MemAvailable', mem.get('MemFree', 0))
    mounts = []
    seen = set()
    for line in read(PROC / '1/mounts').splitlines():
        dev, mount, fs, *_ = line.split()
        mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), mount)
        if not dev.startswith('/dev/') or dev in seen or fs in ('squashfs', 'tmpfs', 'devtmpfs'):
            continue
        try:
            stat = os.statvfs(ROOT / mount.lstrip('/'))
            capacity = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
            mounts.append(dict(device=dev, mount=mount, filesystem=fs, total=capacity, used=used, available=free, percent=round(100 * used / (used + free), 1) if used + free else 0))
            seen.add(dev)
        except OSError:
            continue
    temperatures, power = [], []
    for hw in resolved('class/hwmon/hwmon*'):
        driver = read(hw / 'name', hw.name)
        for f in hw.glob('temp*_input'):
            try:
                temperatures.append(dict(name=driver + ' / ' + read(f.with_name(f.name.replace('_input', '_label')), f.stem), celsius=int(read(f)) / 1000))
            except ValueError:
                pass
        for f in hw.glob('power*_input'):
            try:
                power.append(dict(name=driver + ' / ' + read(f.with_name(f.name.replace('_input', '_label')), f.stem), watts=int(read(f)) / 1000000, scope='Sensore hardware'))
            except ValueError:
                pass
    energies = {}
    deltas = {}
    expected_zones = 0
    for zone in resolved('class/powercap/*'):
        # Only package zones: subdomains would double-count CPU energy.
        if not re.fullmatch(r'(intel|amd)-rapl:\d+', zone.name):
            continue
        expected_zones += 1
        try:
            energy = int(read(zone / 'energy_uj'))
            maximum = int(read(zone / 'max_energy_range_uj'))
            energies[zone.name] = energy
            old = previous.get('energy', {}).get(zone.name)
            delta = counter_delta(energy, old, maximum, dt)
            if delta is not None:
                deltas[zone.name] = delta
                power.append(dict(name=read(zone / 'name', zone.name), watts=round(delta / dt / 1000000, 2), scope='Package CPU (non intero server)'))
        except ValueError:
            pass
    nr, dr = rates(net, 'net'), rates(disks, 'disks')
    data = dict(timestamp=wall_now, hostname=read(ROOT / 'etc/hostname', 'Server'), uptime=float(read(PROC / 'uptime', '0').split()[0]), cpu=dict(percent=usage.get('cpu', 0), cores=[v for k, v in usage.items() if k != 'cpu'], load=list(map(float, read(PROC / 'loadavg', '0 0 0').split()[:3]))), memory=dict(total=total, used=total-available, available=available, percent=round(100*(total-available)/total, 1) if total else 0, swap_total=mem.get('SwapTotal', 0), swap_used=mem.get('SwapTotal', 0)-mem.get('SwapFree', 0)), network=[dict(name=k, physical=(SYS / 'class/net' / k / 'device').exists(), received=net[k][0], sent=net[k][1], rx=v[0], tx=v[1]) for k,v in nr.items()], disks=[dict(name=k, read=v[0], write=v[1], busy=min(100, v[2]/10)) for k,v in dr.items()], filesystems=mounts, temperatures=temperatures, power=power)
    if energy_store is not None:
        measured = sum(deltas.values()) if expected_zones and len(deltas) == expected_zones else None
        energy_store.record(min(previous.get('wall', wall_now), wall_now), wall_now, measured)
        data['energy'] = dict(**energy_store.snapshot(data['timestamp']), measurement_available=measured is not None)
    previous = dict(time=now, wall=wall_now, cpu=cpu, net=net, disks=disks, energy=energies)
    return data

