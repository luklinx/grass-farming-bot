import asyncio
import aiohttp
import random
import time
from datetime import datetime, timedelta
import logging
import json
import os
import pandas as pd
import matplotlib.pyplot as plt
from tabulate import tabulate
from fake_useragent import UserAgent
from typing import List, Dict, Optional, Any

# ==================== Core Farming Classes ====================

class GrassIOBot:
    """Base class for Grass.io API interactions"""
    def __init__(self, api_key: str):
        self.base_url = "https://api.getgrass.io/v1"
        self.api_key = api_key
        self.session = aiohttp.ClientSession()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": UserAgent().random
        }
        
    async def _make_request(self, endpoint: str, method: str = 'GET', data: Optional[Dict] = None):
        """Generic API request handler"""
        url = f"{self.base_url}/{endpoint}"
        try:
            async with self.session.request(method, url, json=data, headers=self.headers) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            logging.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    async def get_user_info(self):
        return await self._make_request("user")
    
    async def submit_bandwidth_proof(self, proof_data: Dict):
        return await self._make_request("proofs/bandwidth", "POST", proof_data)
    
    async def check_rewards(self):
        return await self._make_request("rewards/balance")
    
    async def claim_rewards(self, amount: float):
        return await self._make_request("rewards/claim", "POST", {"amount": amount})
    
    async def close(self):
        await self.session.close()

class GrassPointsTracker:
    """Tracks and displays points across multiple accounts"""
    def __init__(self, accounts: List[Dict]):
        self.accounts = accounts
        self.points_history = []
        self.report_dir = "grass_reports"
        os.makedirs(self.report_dir, exist_ok=True)
        
    async def get_account_points(self, session: aiohttp.ClientSession, account: Dict):
        """Get current points for a single account"""
        bot = GrassIOBot(account['api_key'])
        try:
            points_data = await bot.check_rewards()
            return {
                "account": account["name"],
                "points": points_data.get("amount", 0),
                "timestamp": datetime.now().isoformat(),
                "status": "active" if "error" not in points_data else "inactive"
            }
        finally:
            await bot.close()
    
    async def update_all_points(self):
        """Update points for all accounts"""
        async with aiohttp.ClientSession() as session:
            tasks = [self.get_account_points(session, account) for account in self.accounts]
            results = await asyncio.gather(*tasks)
            self.points_history.extend(results)
            return results
    
    def display_points(self, points_data: List[Dict]):
        """Display points in formatted table"""
        sorted_data = sorted(points_data, key=lambda x: x["points"], reverse=True)
        table_data = [[
            acc["account"],
            f"{acc['points']:.4f}",
            acc["status"],
            "↑" if self._get_trend(acc["account"]) > 0 else "↓"
        ] for acc in sorted_data]
        
        print(f"\n{' Grass Account Points ':=^60}")
        print(tabulate(table_data, headers=["Account", "Points", "Status", "Trend"], tablefmt="grid"))
        print(f"Total points: {sum(acc['points'] for acc in sorted_data):.4f}")
        print("=" * 60)
    
    def _get_trend(self, account_name: str) -> float:
        """Calculate points trend for an account"""
        account_history = [p for p in self.points_history if p["account"] == account_name]
        return account_history[-1]["points"] - account_history[-2]["points"] if len(account_history) > 1 else 0
    
    def generate_report(self, points_data: List[Dict]):
        """Generate CSV report and chart"""
        # CSV Report
        df = pd.DataFrame(points_data)
        report_path = os.path.join(self.report_dir, f"points_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        df.to_csv(report_path, index=False)
        
        # Chart
        plt.figure(figsize=(12, 6))
        df = df.sort_values("points", ascending=False)
        colors = ['green' if s == 'active' else 'red' for s in df['status']]
        plt.bar(df['account'], df['points'], color=colors)
        plt.title(f"Grass Points Distribution (Total: {df['points'].sum():.2f})")
        plt.xticks(rotation=90)
        plt.tight_layout()
        plt.savefig(os.path.join(self.report_dir, f"chart_{datetime.now().strftime('%Y%m%d_%H%M')}.png"))
        plt.close()

class GrassMultiFarmer:
    """Main farming bot with multi-account support"""
    def __init__(self, config_file: str = 'config.json'):
        self.config = self._load_config(config_file)
        self.accounts = self.config['accounts']
        self.global_config = self.config['global_config']
        self.points_tracker = GrassPointsTracker(self.accounts)
        self.semaphore = asyncio.Semaphore(self.global_config.get('concurrent_limit', 5))
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('grass_farmer.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('GrassFarmer')
    
    def _load_config(self, config_file: str) -> Dict:
        """Load configuration file"""
        with open(config_file) as f:
            return json.load(f)
    
    async def farm_account(self, account: Dict):
        """Farming routine for single account"""
        async with self.semaphore:
            bot = GrassIOBot(account['api_key'])
            try:
                # Connect and farm
                await asyncio.sleep(random.uniform(1, 5))
                proof = {
                    "duration": random.randint(300, 600),
                    "bandwidth": random.uniform(1, account.get('max_bandwidth', 10)),
                    "timestamp": int(time.time())
                }
                await bot.submit_bandwidth_proof(proof)
                
                # Check rewards
                rewards = await bot.check_rewards()
                if rewards.get('amount', 0) >= account.get('claim_threshold', 5):
                    await bot.claim_rewards(rewards['amount'])
                
                return rewards.get('amount', 0)
            finally:
                await bot.close()
    
    async def run_batch(self, batch: List[Dict]):
        """Process a batch of accounts"""
        tasks = [self.farm_account(account) for account in batch]
        return await asyncio.gather(*tasks)
    
    async def rotate_accounts(self):
        """Rotate through all accounts in batches"""
        batch_size = self.global_config.get('batch_size', 5)
        total_accounts = len(self.accounts)
        
        while True:
            for i in range(0, total_accounts, batch_size):
                batch = self.accounts[i:i + batch_size]
                results = await self.run_batch(batch)
                self.logger.info(f"Processed batch: {len(batch)} accounts, total rewards: {sum(results):.4f}")
                
                # Update and display points
                points_data = await self.points_tracker.update_all_points()
                self.points_tracker.display_points(points_data)
                self.points_tracker.generate_report(points_data)
                
                # Random delay between batches
                await asyncio.sleep(random.uniform(
                    self.global_config.get('min_delay', 30),
                    self.global_config.get('max_delay', 120)
                ))
    
    async def run(self):
        """Main entry point"""
        self.logger.info(f"Starting farming with {len(self.accounts)} accounts")
        try:
            await self.rotate_accounts()
        except asyncio.CancelledError:
            self.logger.info("Farming stopped by user")
        except Exception as e:
            self.logger.error(f"Fatal error: {e}")

# ==================== Main Execution ====================

async def main():
    # Initialize with your config file
    farmer = GrassMultiFarmer('config.json')
    
    try:
        await farmer.run()
    except KeyboardInterrupt:
        pass
    finally:
        # Cleanup
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())
