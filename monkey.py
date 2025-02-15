from gevent import monkey
# Patch only what we need, thread=False to avoid conflicts
monkey.patch_all(thread=False, socket=True, dns=True, time=True, select=True, ssl=True)