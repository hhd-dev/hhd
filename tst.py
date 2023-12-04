from time import sleep
from hhd.controller.physical.imu import AccelImu, GyroImu
from hhd.controller.virtual.ds5 import DualSense5Edge

p = DualSense5Edge()
# p = PVC()

a = AccelImu()
a.register(p)
b = GyroImu()
b.register(p)

try:
    a.start()
    b.start()
    p.start()
    sleep(5000)
finally:
    a.stop()
    b.stop()
    p.stop()
