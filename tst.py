import select
from hhd.controller.physical.imu import AccelImu, GyroImu
from hhd.controller.virtual.ds5 import DualSense5Edge

p = DualSense5Edge()
# p = PVC()

a = AccelImu()
b = GyroImu()

fds = []
devs = []
fd_to_dev = {}
def prepare(m):
    fs = m.open()
    devs.append(m)
    fds.extend(fs)
    for f in fs:
        fd_to_dev[f] = m

try:
    prepare(a)
    prepare(b)
    prepare(p)
    
    while True:
        r, _, _ = select.select(fds, [], [])
        evs = []
        to_run = set()
        for f in r:
            to_run.add(id(fd_to_dev[f]))

        for d in devs:
            if id(d) in to_run:
                evs.extend(d.produce(r))

        if evs:
            p.consume(evs)
finally:
    a.close(True)
    b.close(True)
    p.close(True)