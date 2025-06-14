#!/usr/bin/python3.11
import aiohttp, asyncio, fcntl, socket, struct

def get_ip_address(ifname: str):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8915,  # SIOCGIFADDR
        struct.pack('256s', bytes(ifname[:15], 'utf-8'))
    )[20:24])

# Get the IP address of eth0
ip_addr = get_ip_address('eth0')
API_URL = f'http://{ip_addr}:8000/single_query'
API_URL = f'http://{ip_addr}:8000/multiple_queries'

async def fetch(session, url):
    async with session.get(url) as response:
        return await response.json()

async def main():
    async with aiohttp.ClientSession() as session:
        tasks = [fetch(session, API_URL) for _ in range(5)]
        results = await asyncio.gather(*tasks)
        for result in results:
            print(result)

# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
