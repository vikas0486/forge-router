import asyncio
import logging
from forge.router.engine import router

# Configure logging to see details
logging.basicConfig(level=logging.INFO)

async def main():
    print("Checking provider status...")
    status = await router.get_status()
    for name, info in status.items():
        ok_str = "✅" if info["ok"] else "❌"
        reason = f" ({info.get('reason')})" if not info["ok"] else ""
        print(f"{ok_str} {name:10}: {info['ok']}{reason}")

if __name__ == "__main__":
    asyncio.run(main())
